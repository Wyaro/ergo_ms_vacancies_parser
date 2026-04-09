# vacancies_parser: подробный гайд разработчика

## 1) Что это за модуль и зачем он нужен

`modules/vacancies_parser` — модуль массового парсинга вакансий из внешних источников (`HeadHunter`, `Habr Career`, `SuperJob`) с асинхронной обработкой через Celery.

Ключевая цель модуля:
- запускать парсинг задачами;
- параллельно обрабатывать найденные вакансии;
- хранить результаты по источникам в отдельных таблицах;
- предоставлять API и UI для контроля задач, прогресса и результата.

---

## 2) Технологический стек и зачем он используется

- `Django` — ORM, модели, API-слой, валидация, миграции.
- `DRF` — ViewSet/Router API для управления задачами и просмотра данных.
- `Celery` — фоновые и периодические задачи (оркестрация, workers, crash recovery).
- `PostgreSQL` (через ORM) — хранение задач/элементов/вакансий.
- `requests + BeautifulSoup` — HTTP и HTML-парсинг.
- `Vue.js` (client модуля) — интерфейс управления парсингом и просмотра результатов.

Почему так:
- парсинг I/O-bound и долгий -> выносится в Celery;
- много конкурентных единиц работы -> `TaskItem` + lease + `SKIP LOCKED`;
- разные источники имеют разные схемы -> source-specific таблицы и парсеры.

---

## 3) Структура модуля (от общего к частному)

```text
modules/vacancies_parser/
  README.md
  MODELS_DOCUMENTATION.md
  DEVELOPER_GUIDE.md
  api/
    apps.py
    urls.py
    tasks.py
    celery_config.py
    celery_beat_config.py
    core/
      models.py
      normalized_models.py
      views.py
      scheduler.py
      celery_tasks.py
      celery_config_base.py
      parsers/
        base.py
        api_parsers.py
        html_parsers.py
      tasks/
        base.py
        orchestration.py
        worker.py
      utils/
        task_runner.py
        celery_broker.py
    headhunter/
      apps.py
      models.py
      views.py
      urls.py
      parsers/
        api_parser.py
        html_parser.py
      celery_config.py
      celery_beat_config.py
      config/
        background_parsing.json
        professional_roles_config.json
    habr_career/
      apps.py
      models.py
      views.py
      urls.py
      parsers.py
      celery_config.py
      celery_beat_config.py
      .env
      management/commands/config.json
    superjob/
      apps.py
      models.py
      views.py
      urls.py
      parsers/html_parser.py
      celery_config.py
      management/commands/config.json
      README.md
  client/
    js/
      routes.js
      endpoints.js
      menu-config.json
```

---

## 4) Главный runtime-поток (как работает парсинг)

1. Клиент/пользователь создаёт задачу через `core` API (`ParsingTaskViewSet`).
2. Celery task `create_parsing_task`:
   - создаёт `ParsingTask`;
   - создаёт парсер через `ParserFactory.create_parser(source, mode)`;
   - делает discovery (`discover_items`);
   - массово создаёт `TaskItem`.
3. Запускается `coordinate_parsing_task`:
   - поднимает группу workers (`parse_items_worker`, 10 штук);
   - собирает их через `chord(...)` и callback `finalize_parsing_task`.
4. Каждый worker циклом:
   - claim батч элементов через `TaskScheduler` -> `TaskItem.claim_items_for_worker(..., select_for_update(skip_locked=True))`;
   - парсит item через `parser.parse_item`;
   - сохраняет в source-specific модель;
   - помечает item `completed/failed/blocked`.
5. Финализация:
   - `TaskScheduler.finalize_task()` чистит незавершённые item-ы (`_cleanup_stuck_items`);
   - обновляет статус задачи;
   - создаёт `ParsingStatistics`.

---

## 5) Наследование и ключевые абстракции

## 5.1 Парсеры

Базовый контракт:
- `ParserInterface` (`api/core/parsers/base.py`)
  - `discover_items(config)`
  - `parse_item(item_id, url)`
  - `validate_config(config)`

Базовая реализация:
- `BaseParser(ParserInterface)`
  - общие поля: `source`, `parsing_mode`, `timeout`, `max_retries`
  - инфраструктура под нормализацию/извлечение полей

HTML-ветка:
- `BaseHTMLParser(BaseParser)`
- `HeadHunterHTMLParser(BaseHTMLParser)`
- `HabrCareerHTMLParser(BaseHTMLParser)`
- `SuperJobHTMLParser(BaseHTMLParser)`

API-ветка:
- `HeadHunterAPIParser(BaseParser)`
- `HabrCareerAPIParser(BaseParser)` (класс есть, но сейчас не зарегистрирован в `ParserFactory`)
- `SuperJobAPIParser(BaseParser)`

Фабрика:
- `ParserFactory` хранит реестр `(source, mode) -> class`.
- Базовые регистрации делаются в `core/parsers/api_parsers.py` и `core/parsers/html_parsers.py`.
- Source-level overrides регистрируются в `apps.py` конкретного источника.

## 5.2 Celery-конфиги

- `VacanciesParserCeleryConfigBase(CeleryModuleConfig)` в `api/core/celery_config_base.py`
  - общие дефолты time/rate limits
- Наследники:
  - `VacanciesParserCeleryConfig` (`api/celery_config.py`) — core задачи модуля
  - `HeadhunterCeleryConfig` (`api/headhunter/celery_config.py`)
  - `HabrCareerCeleryConfig` (`api/habr_career/celery_config.py`)
  - `SuperjobCeleryConfig` (`api/superjob/celery_config.py`)

Beat:
- Core beat: `api/celery_beat_config.py`
- HH beat: `api/headhunter/celery_beat_config.py`

---

## 6) Модели данных и фактическое хранение

## 6.1 Core orchestration-модели

`api/core/models.py`:
- `ParsingTask` (`vpm_parsing_task`) — задача парсинга (source, mode, config, status, counters).
- `TaskItem` (`vpm_task_item`) — единица работы (status, lease, attempts, ошибки, extracted_data).

Ключевой момент:
- claim конкурентный и атомарный: `SELECT ... FOR UPDATE SKIP LOCKED`.
- lease/recovery: истёкшие `in_progress` можно вернуть в оборот.

## 6.2 Normalized-модели

`api/core/normalized_models.py`:
- `NormalizedVacancy` (`vpm_vacancy`)
- `VacancyChangeHistory`
- `ParsingStatistics`

Важно: текущий worker-пайплайн (`api/core/tasks/worker.py`) сохраняет результат в **source-specific** таблицы, а не в `NormalizedVacancy`.

## 6.3 Source-specific модели

- `api/headhunter/models.py` -> `vpm_hh_vacancy`, `vpm_hh_vacancy_version`, `vpm_hh_vacancy_change_history`
- `api/habr_career/models.py` -> `vpm_hc_vacancy`, `vpm_hc_vacancy_version`, `vpm_hc_vacancy_change_history`
- `api/superjob/models.py` -> `vpm_sj_vacancy`, `vpm_sj_vacancy_version`, `vpm_sj_vacancy_change_history`

---

## 7) Где настраиваются конфиги парсинга

## 7.1 В рантайме задачи (главное место)

`ParsingTask.config` (JSON):
- передаётся из API/UI;
- используется в discovery/worker логике;
- может содержать: `area`, `pages`, `delay`, `text`, `max_pages`, `max_consecutive_blocks` и др.

## 7.2 Базовые Celery-настройки модуля

- `api/celery_config.py` — маршруты/очередь/аннотации core задач.
- `api/celery_beat_config.py` — периодика:
  - `release_expired_leases` (каждые 5 минут),
  - `monitor_tasks_progress` (каждые 10 минут).

## 7.3 Source-specific Celery-конфиги

- HH: `api/headhunter/celery_config.py`, `api/headhunter/celery_beat_config.py`
- Habr: `api/habr_career/celery_config.py`, `api/habr_career/celery_beat_config.py`
- SuperJob: `api/superjob/celery_config.py`, `api/superjob/celery_beat_config.py`

## 7.4 JSON-конфиги источников

- HH:
  - `api/headhunter/config/background_parsing.json`
  - `api/headhunter/config/professional_roles_config.json`
- Habr:
  - `api/habr_career/management/commands/config.json`
- SuperJob:
  - `api/superjob/management/commands/config.json`

Важно по HeadHunter:
- `background_parsing.json` в текущем runtime **не является источником live-расписания Celery Beat**.
- Фактическое beat-расписание и параметры запуска по времени берутся из кода:
  - `api/headhunter/celery_beat_config.py` -> `HeadhunterCeleryBeatConfig.get_beat_schedule()`
  - именно там задаются `schedule`, `kwargs`, `options` для фоновых задач.
- `professional_roles_config.json` используется внутри задач для логики ролей/категории (через:
  - `api/headhunter/tasks/base.py` -> `_load_target_category_id()`
  - `api/headhunter/utils/professional_roles_config.py` -> `ProfessionalRolesManager`).

## 7.5 Переменные окружения

- SuperJob: `api/superjob/.env` загружается в `api/superjob/apps.py` (`_load_env()`).
- Habr: есть `api/habr_career/.env` (исторически под OAuth-часть).

---

## 8) Core API и source API (что видит клиент)

Core API (`api/urls.py`, `api/core/views.py`):
- `tasks/` — создать/пауза/резюм/стоп/прогресс/статистика.
- `items/` — список item-ов.
- `vacancies/` — normalized вакансии (read-only).
- `statistics/` — статистика парсинга.

Source API (у каждого источника свой router):
- `.../<source>/vacancies/` (просмотр source данных, версии, changes, stats, task_status)
- `.../<source>/parsing/...` (запуск source-специфичных сценариев)

Frontend:
- маршруты: `client/js/routes.js`
- endpoint-фабрика: `client/js/endpoints.js` (`getSourceEndpoints(source)`).

---

## 9) Детализация по источникам

## 9.1 Habr Career (`api/habr_career`)

Назначение:
- хранение и API для данных Habr Career;
- override HTML-парсера для корректной обработки блокировок/captcha-переадресаций.

Ключевые файлы:
- `apps.py`: регистрирует override-парсер через импорт `parsers`.
- `parsers.py`: `HabrCareerModuleHTMLParser(HabrCareerHTMLParser)`
  - переопределён `_make_request` (точнее ловит блокировки, retry + backoff);
  - `parse_item` передаёт оригинальный URL в `fetch_item`.
- `models.py`: `Vacancy` + version/change-history.
- `views.py`/`urls.py`: read-only vacancies + control actions (`parse_active`, `parse_archived`, `parse_all`).

Практический смысл override:
- избежать ложных срабатываний CAPTCHA на страницах с встроенными скриптами;
- снизить долю `blocked`/`network` ошибок на HTML-режиме.

## 9.2 HeadHunter (`api/headhunter`)

Назначение:
- самый развитый источник: API+HTML, расширенный anti-detection, сложный beat.

Ключевые файлы:
- `apps.py`: в `ready()` регистрирует оба override:
  - `HeadHunterAPIParserOverride`
  - `HeadHunterHTMLParserOverride`
- `parsers/api_parser.py`:
  - ротация UA, request spacing, throttle-паузы;
  - backoff на 429/403;
  - пересоздание сессии при блокировках.
- `parsers/html_parser.py`:
  - браузерные заголовки, прогрев сессии, cookies/referer;
  - CAPTCHA/block detection;
  - retry/backoff + session rotation.
- `celery_beat_config.py`:
  - детализированное расписание (ежедневные/еженедельные/ночные/импульсные задачи).
- `config/*.json`:
  - `professional_roles_config.json` — рабочий конфиг ролей для task-логики;
  - `background_parsing.json` — вспомогательный/документирующий конфиг профилей (не источник live beat schedule).

Как beat получает конфиг:
- глобально `core/api/src/config/settings/celery_beat.py` собирает расписания модулей через `CeleryBeatModuleManager`;
- менеджер подгружает `modules/.../api/<module>/celery_beat_config.py`;
- для HH итоговые cron-задачи берутся из `HeadhunterCeleryBeatConfig.get_beat_schedule()`.

Особенность:
- HH использует как API, так и HTML-потоки, при этом override-слой минимизирует бан/капчу.

## 9.3 SuperJob (`api/superjob`)

Назначение:
- API/HTML парсинг SuperJob;
- source-специфичный HTML override + удобные команды/эндпоинты.

Ключевые файлы:
- `apps.py`:
  - загрузка `api/superjob/.env` в окружение;
  - регистрация `SuperJobHTMLParserOverride`.
- `parsers/html_parser.py`:
  - браузерная эмуляция;
  - прогрев сессии;
  - извлечение ссылок/ID из разных HTML-форматов;
  - `parse_item -> fetch_item` с приоритетом оригинального URL.
- `models.py`: `SuperJobVacancy` + version/change-history.
- `README.md`: подробные команды управления и API usage.
- `management/commands/config.json`: дефолтный набор поисковых параметров.

---

## 10) Как устроено сохранение данных в worker

Файл: `api/core/tasks/worker.py`

Механика:
- `_SOURCE_CONFIGS`: привязка `source -> model/id_field/remap`.
- `_map_to_source_fields`: маппинг выхода парсера в поля source-модели.
- `_ensure_not_null_defaults`: подстановка дефолтов для NOT NULL полей.
- `_truncate_char_fields`: защита от превышения `max_length`.
- `_get_source_model`: динамическое получение Django-модели через `apps.get_model`.
- `process_item`: `update_or_create` в source-модель, затем `item.mark_completed(...)`.

Это ключевой слой защиты от:
- `NOT NULL` ошибок;
- `StringDataRightTruncation`;
- расхождений между полями парсера и БД-схемой.

---

## 11) Важные места для доработок

- Добавить новый источник:
  1) модель источника (`api/<source>/models.py`);
  2) парсер(ы) (`core` и/или source override);
  3) `apps.py` регистрация в `ParserFactory`;
  4) запись в `_SOURCE_CONFIGS` (`worker.py`);
  5) source `views.py` + `urls.py` + client endpoints.

- Изменить поведение ретраев/блокировок:
  - source override parser (`api/<source>/parsers/...`)
  - worker block-policy в `api/core/celery_tasks.py` (`consecutive_blocks`).

- Изменить параллелизм:
  - `worker_count` в `coordinate_parsing_task` (`api/core/celery_tasks.py`).

- Изменить правила финализации:
  - `TaskScheduler.finalize_task` и `_cleanup_stuck_items` (`api/core/scheduler.py`).

---

## 12) Быстрая карта чтения кода для нового разработчика

Рекомендуемый порядок:
1. `api/core/models.py` — понять `ParsingTask` и `TaskItem`.
2. `api/core/parsers/base.py` — интерфейс + фабрика.
3. `api/core/celery_tasks.py` — orchestration/workers/finalization.
4. `api/core/scheduler.py` — claiming/lease/finalize.
5. `api/core/tasks/worker.py` — финальная запись в БД.
6. Затем source-папка интересующей площадки:
   - `apps.py` -> `parsers` -> `views` -> `models` -> `celery_config`.

---

## 13) Ключевые нюансы текущего состояния

- API `core/vacancies` работает с `NormalizedVacancy`, но worker-пайплайн сейчас пишет в source-specific таблицы.
- Для Habr API-парсер в `ParserFactory` сейчас не зарегистрирован (доступны практические сценарии через HTML/source control flow).
- В source-level конфигах есть много legacy/служебных задач: перед рефакторингом проверять фактические точки запуска в `views.py` и celery tasks.

---

## 14) Файлы, которые стоит держать открытыми при разработке

- `modules/vacancies_parser/api/core/celery_tasks.py`
- `modules/vacancies_parser/api/core/tasks/worker.py`
- `modules/vacancies_parser/api/core/scheduler.py`
- `modules/vacancies_parser/api/core/parsers/base.py`
- `modules/vacancies_parser/api/core/parsers/html_parsers.py`
- `modules/vacancies_parser/api/headhunter/parsers/html_parser.py`
- `modules/vacancies_parser/api/habr_career/parsers.py`
- `modules/vacancies_parser/api/superjob/parsers/html_parser.py`

