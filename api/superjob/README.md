# SuperJob - Парсер вакансий

Модуль парсинга вакансий с SuperJob API v2.0.

Полная справка по всем командам: `ergoms api superjob_help`

## Команды

### parse_superjob_vacancies - Парсинг вакансий

**По текстовому запросу:**
```bash
ergoms api parse_superjob_vacancies --text "Python"                        # Поиск по ключевому слову
ergoms api parse_superjob_vacancies --text "Python" --town "Москва"        # С фильтром по городу
ergoms api parse_superjob_vacancies --text "Django" --max-pages 20         # С увеличенным количеством страниц
ergoms api parse_superjob_vacancies --text "React" --delay 0.5             # С изменённой задержкой между запросами
```

**По каталогам (отраслям) - самый эффективный режим, без дубликатов:**
```bash
ergoms api parse_superjob_vacancies --list-catalogues                      # Вывести список всех каталогов и выйти
ergoms api parse_superjob_vacancies --catalogues                           # Парсинг по всем каталогам
ergoms api parse_superjob_vacancies --catalogues --catalogue-ids 33,381    # Только IT (33) и банки (381)
ergoms api parse_superjob_vacancies --catalogues --max-pages-per-catalogue 20  # С настройкой глубины на каталог
```

**Универсальный парсинг (по набору популярных запросов):**
```bash
ergoms api parse_superjob_vacancies --all                                  # Парсинг по ~35 популярным запросам
ergoms api parse_superjob_vacancies --all --max-pages 10                   # С увеличенной глубиной на запрос
```

**Максимальный режим (500 страниц = до 50 000 вакансий на запрос/каталог):**
```bash
ergoms api parse_superjob_vacancies --text "Python" --max                  # Максимум вакансий по запросу
ergoms api parse_superjob_vacancies --catalogues --max                     # Максимум по всем каталогам
ergoms api parse_superjob_vacancies --all --max                            # Максимум по всем запросам
```

**Детали одной вакансии:**
```bash
ergoms api parse_superjob_vacancies --vacancy-id 12345678                  # Получить детали вакансии по ID на SuperJob
```

**Из конфиг-файла:**
```bash
ergoms api parse_superjob_vacancies --config my_config.json                # Парсинг по параметрам из JSON-файла
```

**Общие флаги (комбинируются с любым режимом):**
```bash
--api-key "v3.r.XXX..."   # API-ключ вручную (вместо .env)
--celery                   # Запуск через Celery (асинхронно)
--celery --wait            # Celery + дождаться результата
--delay 0.5                # Задержка между запросами (сек)
```

### parse_superjob_vacancy - Одна вакансия с SuperJob

```bash
ergoms api parse_superjob_vacancy 12345678                                 # Получить и показать данные вакансии
ergoms api parse_superjob_vacancy 12345678 --save                          # Получить и сохранить в БД
ergoms api parse_superjob_vacancy 12345678 --api-key "v3.r.XXX..."         # С указанием API-ключа вручную
```

### show_superjob_vacancies - Просмотр вакансий из БД

```bash
ergoms api show_superjob_vacancies                                         # Последние 20 вакансий
ergoms api show_superjob_vacancies --id 42                                 # Вакансия по ID записи в БД
ergoms api show_superjob_vacancies --superjob-id 12345678                  # Вакансия по ID на SuperJob
ergoms api show_superjob_vacancies --search "Python" --city "Москва"       # Поиск по тексту + город
ergoms api show_superjob_vacancies --salary-min 150000 --active            # Фильтр по зарплате и активности
ergoms api show_superjob_vacancies --count                                 # Только количество вакансий
ergoms api show_superjob_vacancies --full --limit 5                        # Полный вывод с описанием
ergoms api show_superjob_vacancies --limit 20 --offset 40                  # Пагинация
```

### superjob_help - Справка

```bash
ergoms api superjob_help                                                   # Все команды, параметры, примеры
```

## API эндпоинты

Все эндпоинты требуют авторизации (`IsAuthenticated`).

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/api/vacancies_parser/superjob/vacancies/` | Список вакансий |
| GET | `/api/vacancies_parser/superjob/vacancies/{id}/` | Одна вакансия |
| GET | `/api/vacancies_parser/superjob/vacancies/stats/` | Статистика |
| GET | `/api/vacancies_parser/superjob/vacancies/{id}/versions/` | Версии вакансии |
| GET | `/api/vacancies_parser/superjob/vacancies/{id}/changes/` | История изменений |
| GET | `/api/vacancies_parser/superjob/vacancies/task_status/?task_id=...` | Статус Celery-задачи |
| POST | `/api/vacancies_parser/superjob/parsing/parse_by_text/` | Парсинг по тексту |
| POST | `/api/vacancies_parser/superjob/parsing/parse_all/` | Универсальный парсинг |
| POST | `/api/vacancies_parser/superjob/parsing/parse_by_catalogues/` | Парсинг по каталогам |
| POST | `/api/vacancies_parser/superjob/parsing/parse_by_config/` | Парсинг по конфигу |
| GET | `/api/vacancies_parser/superjob/parsing/catalogues/` | Список каталогов |
| POST | `/api/vacancies_parser/superjob/parsing/get_details/` | Детали вакансии |

## Ограничения SuperJob API

- 120 запросов/минуту на API-ключ
- Максимум 100 вакансий в одном ответе
- Максимум 500  страниц на один поисковый запрос
- API-ключ передается через заголовок `X-Api-App-Id`
