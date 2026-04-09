# Документация моделей модуля vacancies_parser

## Общее описание

Модуль `vacancies_parser` предназначен для парсинга вакансий из различных источников (HeadHunter, Habr Career, SuperJob). Система имеет модульную архитектуру с разделением на:

- **Core models** - общие модели для управления задачами парсинга
- **Normalized models** - унифицированная схема для агрегации данных из всех источников
- **Source-specific models** - сырые данные от конкретных площадок

---

## Структура таблиц

### 1. Core Models (modules/vacancies_parser/api/core/models.py)

| Модель | Старое имя таблицы | Новое имя таблицы | Описание |
|-------|------------------|------------------|----------|
| **ParsingTask** | parsing_task | **vpm_parsing_task** | Модель для управления задачами парсинга с state machine (created/running/paused/stopped/completed/failed) |
| **TaskItem** | task_item | **vpm_task_item** | Атомарная единица работы с lease механизмом для конкурентной обработки |

#### Правки:
- ✅ Добавлен префикс `vpm` ко всем таблицам
- ✅ Добавлено уникальность для config_hash (UniqueConstraint на source + config_hash)
- ✅ Добавлены индексы для производительности и конкурентной обработки
- ✅ Добавлен индекс для быстрого поиска по task и source_item_id

---

### 2. Normalized Models (modules/vacancies_parser/api/core/normalized_models.py)

| Модель | Старое имя таблицы | Новое имя таблицы | Описание |
|-------|------------------|------------------|----------|
| **NormalizedVacancy** | vacancy | **vpm_vacancy** | Унифицированная модель для агрегации данных из всех источников |
| **VacancyChangeHistory** | vacancy_change_history | **vpm_vacancy_change_history** | История изменений нормализованной вакансии |
| **ParsingStatistics** | parsing_statistics | **vpm_parsing_statistics** | Статистика парсинга для мониторинга и аналитики |

#### Правки:
- ✅ Исправлен FK на `'vacancies_parser.TaskItem'` (правильная ссылка на модель в том же модуле)
- ✅ Добавлен префикс `vpm` ко всем таблицам
- ✅ Добавлены индексы для производительности и дедупликации
- ✅ Добавлены поля для дедупликации (deduplication_hash, original_vacancy_id, deduplication_status)
- ✅ Добавлены методы для генерации хэша дедупликации (generate_deduplication_hash, update_deduplication_hash)
- ✅ Добавлен метод clean() для валидации JSON поля contacts
- ✅ Добавлен индекс для deduplication_hash в Meta
- ✅ Добавлено дефолтное значение для deduplication_hash (автоматическая генерация в save())

#### Поля дедупликации:
- `deduplication_hash` - SHA256 хэш агрегированный критерий для поиска дубликатов (default='', blank=True, автоматически генерируется в save() если пустой)
- `original_vacancy_id` - FK на NormalizedVacancy, если это дубликат
- `deduplication_status` - статус дедупликации (pending/original/duplicate)
- DEDUPLICATION_STATUS_CHOICES:
  - `pending` - ожидает проверки
  - `original` - оригинал (уникальная)
  - `duplicate` - дубликат

---

### 3. Source-Specific Models (modules/vacancies_parser/api/headhunter/models.py)

| Модель | Старое имя таблицы | Новое имя таблицы | Описание |
|-------|------------------|------------------|----------|
| **Vacancy** | vacancies_vacancy | **vpm_hh_vacancy** | Сырые данные вакансий с HeadHunter |
| **VacancyVersion** | vacancies_vacancyversion | **vpm_hh_vacancy_version** | Метаданные версий вакансий (без хранения полных данных) |
| **VacancyChangeHistory** | vacancies_vacancychangehistory | **vpm_hh_vacancy_change_history** | История изменений полей вакансий |

#### Правки:
- ✅ Добавлен префикс `vpm` ко всем таблицам
- ✅ Добавлены индексы для быстрого поиска по критериям
- ✅ Сохранена версия работы с отдельными версиями (VacancyVersion + VacancyChangeHistory)

#### Особенности:
- Версионность реализована отдельно:
  - `VacancyVersion` - хранит только метаданные (версия, описание изменений)
  - `VacancyChangeHistory` - хранит diff каждого поля
- Подход позволяет отслеживать изменения на уровне полей для каждой версии

---

## Связи между моделями

```
NormalizedVacancy (vpm_vacancy)
    ├── task_item → vacancies_parser.TaskItem (vpm_task_item)
    └── change_history → VacancyChangeHistory (vpm_vacancy_change_history)

Vacancy (vpm_hh_vacancy) - Сырые данные HeadHunter
    ├── versions → VacancyVersion (vpm_hh_vacancy_version)
    │   └── changes → VacancyChangeHistory (vpm_hh_vacancy_change_history)
    └── (через task_item при парсинге) → NormalizedVacancy

VacancyChangeHistory (vpm_vacancy_change_history)
    ├── vacancy → NormalizedVacancy (vpm_vacancy)
    ├── task_item → vacancies_parser.TaskItem (vpm_task_item)
    └── version → VacancyVersion (vpm_hh_vacancy_version)
```

---

## Общие улучшения

### 1. Оптимизация индексов
Все модели имеют оптимизированные индексы для часто выполняемых запросов:
- Поиск по источнику и статусу
- Поиск по компании и городу
- Поиск по дате публикации
- Составные индексы для дедупликации (title + company_name, title + area_name, salary_from + salary_to)

### 2. Дедупликация
Добавлена инфраструктура для дедупликации:
- Автоматическая генерация хэша на основе ключевых полей (title, company_name, salary_from, salary_to, area_name)
- Хэш генерируется автоматически в методе `save()` если поле пустое (default='', blank=True)
- Возможность связи дубликатов через `original_vacancy_id`
- Статус дедупликации (pending/original/duplicate)

### 3. Валидация
Добавлен метод `clean()` в NormalizedVacancy для валидации JSON поля `contacts`:
- Проверка, что contacts является JSON объектом или null
- Проверка наличия обязательных полей (name, email)
- Генерация ValidationError при нарушении

### 4. Уникальность
ParsingTask имеет уникальность на сочетание (source, config_hash) для предотвращения дубликатов задач с одинаковой конфигурацией.

---

## Краткое описание моделей

### Core Models

#### ParsingTask
Модель для управления задачами парсинга. Поддерживает:
- State machine для управления статусом (created/running/paused/stopped/completed/failed)
- Персистентное отслеживание прогресса
- Связь с Celery через celery_task_id
- Конфигурация парсинга в JSON формате
- Хэш конфигурации для дедупликации

#### TaskItem
Атомарная единица работы с lease механизмом. Поддерживает:
- Конкурентно-безопасное claiming через SELECT FOR UPDATE SKIP LOCKED
- Автоматическое освобождение застрявших items (crash recovery)
- Retry логику с типизацией ошибок
- Состояния (pending/in_progress/completed/failed/retrying/blocked)

---

### Normalized Models

#### NormalizedVacancy
Унифицированная модель для агрегации данных из всех источников. Содержит:
- Общие поля (title, company, salary, location, experience, etc.)
- Связь с TaskItem для отслеживания источника парсинга
- Состояния (is_active, archived, version)
- Поля для дедупликации (deduplication_hash, original_vacancy_id, deduplication_status)
- Специфичные данные источника (source_specific_data, raw_data)

#### VacancyChangeHistory
История изменений нормализованной вакансии. Отслеживает:
- Diff между версиями (changed_fields - JSON с old/new значениями)
- Связь с TaskItem (vacancies_parser.TaskItem) для отслеживания источника изменений
- Связь с вакансией и версией

#### ParsingStatistics
Агрегированная статистика для мониторинга и аналитики. Содержит:
- Временные метрики (started_at, finished_at, duration_seconds)
- Счетчики (total_processed, successful_items, failed_items, blocked_items)
- Производительность (avg_item_duration_ms, items_per_second)
- Качество данных (complete_records, incomplete_records, error_breakdown)

---

### Source-Specific Models

#### Vacancy (HeadHunter)
Сырые данные вакансий с HeadHunter. Содержит:
- Основную информацию (title, company, salary, location, etc.)
- Специфичные для HH поля (hh_id, employer_id, alternate_url, etc.)
- Ссылки и идентификаторы
- Информацию о работодателе
- Дополнительные поля (premium, has_test, response_letter_required)
- Версионность (current_version)

#### VacancyVersion (HeadHunter)
Метаданные версий вакансий HeadHunter. Хранит:
- Номер версии
- Дата создания
- Описание изменений

#### VacancyChangeHistory (HeadHunter)
История изменений полей вакансий HeadHunter. Хранит:
- Diff каждого поля
- Связь с версией

---

## Примечания по миграциям

При применении этих правок необходимо выполнить миграции:

```bash
# Создание миграций для новых полей
ergoms makemigrations

# Применение миграций
ergoms migrate
```

Важно: Перед миграцией рекомендуется сделать бэкап существующих данных!

---

## Сводка изменений

1. **Префиксы таблиц (vpm)** - все таблицы теперь имеют краткие имена с префиксом
2. **FK связи** - исправлены на строковый формат `'vacancies_parser.TaskItem'` для правильной ссылки на модель в том же модуле
3. **Индексы** - оптимизированы для производительности и дедупликации
4. **Уникальность config_hash** - добавлено для предотвращения дубликатов задач
5. **Дедупликация** - добавлена полная инфраструктура (hash с дефолтным значением, original_id, status)
6. **Валидация** - добавлена проверка структуры JSON поля contacts
7. **Методы хэширования** - автоматическая генерация хэша дедупликации в save() если поле пустое

---

## Дополнительные рекомендации

1. **Производительность:** Добавленные индексы позволят ускорить запросы по source, company, area, salary
2. **Дедупликация:** Подготовленная инфраструктура для реализации алгоритмов дедупликации
3. **Архитектура:** Сохранено разделение между сырыми данными (Vacancy) и нормализованными (NormalizedVacancy)
4. **Версионность:** Реализован гибкий механизм версионирования с историей изменений на уровне полей

---

**Дата создания:** 19.01.2026
**Версия документации:** 1.0
