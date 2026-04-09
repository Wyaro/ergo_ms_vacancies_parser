"""
Конфигурация Celery Beat для модуля SuperJob.
Настройка периодических задач парсинга вакансий.

Принципы расписания:
- Разнесение задач по времени для избежания конфликтов
- Интенсивный парсинг ночью, когда нагрузка на API минимальна
- Разные расписания для рабочих и выходных дней
- Приоритизация по типу задачи
- Учёт лимита SuperJob API: 120 запросов/минуту
"""

from typing import Dict, Any
from celery.schedules import crontab

from src.core.utils.celery_beat.base import CeleryBeatModuleConfig


IT_CATALOGUE_ID = 33


class SuperjobCeleryBeatConfig(CeleryBeatModuleConfig):
    """
    Конфигурация периодических задач для парсинга SuperJob.

    Доступные каталоги SuperJob (IT-сфера):
    - 33: Информационные технологии, интернет, телеком (основной)

    Ключевые задачи:
    - parse_superjob_by_catalogues_task: парсинг по каталогам (IT)
    - parse_superjob_vacancies_task: парсинг по текстовым запросам
    - parse_all_superjob_vacancies_task: универсальный парсинг по config.json
    """

    def __init__(self, module_name: str):
        super().__init__(module_name)

    def get_beat_schedule(self) -> Dict[str, Dict[str, Any]]:
        def _pipeline_task(
            *,
            schedule,
            name: str,
            keyword: str,
            pages: int,
            delay: float,
            catalogues: str = None,
            priority: int,
            expires_sec: int,
        ) -> Dict[str, Any]:
            """
            Плановый запуск через новый pipeline vacancies_parser (NormalizedVacancy + ParsingTask).

            Важно: это не legacy superjob.tasks.*, которые сохраняют в source-specific модели.
            """
            return {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': schedule,
                'args': [
                    'superjob',
                    'api',
                    {
                        'keyword': keyword,
                        **({'catalogues': catalogues} if catalogues else {}),
                        'pages': pages,
                        'count': 100,
                        'delay': delay,
                    },
                ],
                'kwargs': {'name': name},
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': priority,
                    'expires': expires_sec,
                },
            }

        return {
            # ============================================================
            # ЕЖЕДНЕВНЫЙ ПАРСИНГ IT-КАТАЛОГА (высший приоритет) — новый pipeline
            # ============================================================
            'sj-daily-it-catalogue': {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': crontab(minute=0, hour=2),
                'args': [
                    'superjob',
                    'api',
                    {'catalogues': str(IT_CATALOGUE_ID), 'pages': 100, 'count': 100, 'delay': 1.0},
                ],
                'kwargs': {
                    'name': 'SJ: ежедневный парсинг IT-каталога',
                },
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 10,
                    'expires': 6 * 60 * 60,
                }
            },

            # ============================================================
            # МЕСЯЧНЫЙ ГЛУБОКИЙ ПРОГОН — новый pipeline
            # ============================================================
            'sj-monthly-deep-scan': {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': crontab(minute=0, hour=1, day_of_month='1'),
                'args': [
                    'superjob',
                    'api',
                    {'catalogues': str(IT_CATALOGUE_ID), 'pages': 100, 'count': 100, 'delay': 1.2, 'keyword': 'IT'},
                ],
                'kwargs': {
                    'name': 'SJ: ежемесячный глубокий прогон',
                },
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 9,
                    'expires': 12 * 60 * 60,
                }
            },

            # ============================================================
            # ЯЗЫКИ ПРОГРАММИРОВАНИЯ - РАБОЧИЕ ДНИ (3 раза/день)
            # ============================================================
            'sj-languages-workdays-morning': {
                **_pipeline_task(
                    schedule=crontab(minute=30, hour=6, day_of_week='1-5'),
                    name='SJ: Python (утро, будни)',
                    keyword='Python',
                    pages=20,
                    delay=1.5,
                    priority=8,
                    expires_sec=4 * 60 * 60,
                )
            },
            'sj-languages-workdays-noon': {
                **_pipeline_task(
                    schedule=crontab(minute=30, hour=12, day_of_week='1-5'),
                    name='SJ: JavaScript (день, будни)',
                    keyword='JavaScript',
                    pages=20,
                    delay=1.5,
                    priority=8,
                    expires_sec=4 * 60 * 60,
                )
            },
            'sj-languages-workdays-evening': {
                **_pipeline_task(
                    schedule=crontab(minute=30, hour=18, day_of_week='1-5'),
                    name='SJ: Java (вечер, будни)',
                    keyword='Java',
                    pages=20,
                    delay=1.5,
                    priority=8,
                    expires_sec=4 * 60 * 60,
                )
            },

            # ============================================================
            # ЯЗЫКИ ПРОГРАММИРОВАНИЯ - ВЫХОДНЫЕ (2 раза/день)
            # ============================================================
            'sj-languages-weekend-morning': {
                **_pipeline_task(
                    schedule=crontab(minute=30, hour=10, day_of_week='0,6'),
                    name='SJ: Python (утро, выходные)',
                    keyword='Python',
                    pages=20,
                    delay=1.5,
                    priority=6,
                    expires_sec=6 * 60 * 60,
                )
            },
            'sj-languages-weekend-evening': {
                **_pipeline_task(
                    schedule=crontab(minute=30, hour=18, day_of_week='0,6'),
                    name='SJ: JavaScript (вечер, выходные)',
                    keyword='JavaScript',
                    pages=20,
                    delay=1.5,
                    priority=6,
                    expires_sec=6 * 60 * 60,
                )
            },

            # ============================================================
            # ФРЕЙМВОРКИ - РАБОЧИЕ ДНИ (3 раза/день)
            # ============================================================
            'sj-frameworks-workdays-morning': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=7, day_of_week='1-5'),
                    name='SJ: React (утро, будни)',
                    keyword='React',
                    pages=25,
                    delay=1.5,
                    priority=7,
                    expires_sec=4 * 60 * 60,
                )
            },
            'sj-frameworks-workdays-noon': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=13, day_of_week='1-5'),
                    name='SJ: Django (день, будни)',
                    keyword='Django',
                    pages=25,
                    delay=1.5,
                    priority=7,
                    expires_sec=4 * 60 * 60,
                )
            },
            'sj-frameworks-workdays-evening': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=19, day_of_week='1-5'),
                    name='SJ: Spring (вечер, будни)',
                    keyword='Spring',
                    pages=25,
                    delay=1.5,
                    priority=7,
                    expires_sec=4 * 60 * 60,
                )
            },

            # ============================================================
            # ФРЕЙМВОРКИ - ВЫХОДНЫЕ (2 раза/день)
            # ============================================================
            'sj-frameworks-weekend-morning': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=11, day_of_week='0,6'),
                    name='SJ: React (утро, выходные)',
                    keyword='React',
                    pages=25,
                    delay=1.5,
                    priority=5,
                    expires_sec=6 * 60 * 60,
                )
            },
            'sj-frameworks-weekend-evening': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=19, day_of_week='0,6'),
                    name='SJ: Django (вечер, выходные)',
                    keyword='Django',
                    pages=25,
                    delay=1.5,
                    priority=5,
                    expires_sec=6 * 60 * 60,
                )
            },

            # ============================================================
            # РАННИЙ УТРЕННИЙ ЗАПУСК (чтобы данные были в течение дня после старта воркера)
            # ============================================================
            'sj-early-morning-pulse': {
                **_pipeline_task(
                    schedule=crontab(minute=0, hour=8),
                    name='SJ: Python (ранний пульс)',
                    keyword='Python',
                    pages=10,
                    delay=1.2,
                    priority=8,
                    expires_sec=2 * 60 * 60,
                )
            },

            # ============================================================
            # БАЗЫ ДАННЫХ (2 раза/день)
            # ============================================================
            'sj-databases-morning': {
                **_pipeline_task(
                    schedule=crontab(minute=0, hour=9),
                    name='SJ: PostgreSQL (утро)',
                    keyword='PostgreSQL',
                    pages=15,
                    delay=1.5,
                    priority=5,
                    expires_sec=8 * 60 * 60,
                )
            },
            'sj-databases-evening': {
                **_pipeline_task(
                    schedule=crontab(minute=0, hour=21),
                    name='SJ: SQL (вечер)',
                    keyword='SQL',
                    pages=15,
                    delay=1.5,
                    priority=5,
                    expires_sec=8 * 60 * 60,
                )
            },

            # ============================================================
            # ИНСТРУМЕНТЫ (1 раз/день)
            # ============================================================
            'sj-tools-daily': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=14),
                    name='SJ: Git (день)',
                    keyword='Git',
                    pages=15,
                    delay=1.5,
                    priority=4,
                    expires_sec=12 * 60 * 60,
                )
            },

            # ============================================================
            # ПЛАТФОРМЫ (ночью)
            # ============================================================
            'sj-platforms-nightly': {
                **_pipeline_task(
                    schedule=crontab(minute=45, hour=23),
                    name='SJ: Kubernetes (ночь)',
                    keyword='Kubernetes',
                    pages=15,
                    delay=2.0,
                    priority=3,
                    expires_sec=20 * 60 * 60,
                )
            },

            # ============================================================
            # ПУЛЬС ТОП-20 (рабочие дни каждые 3 часа)
            # ============================================================
            'sj-top20-pulse-09': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=9, day_of_week='1-5'),
                    name='SJ: IT-каталог (пульс 09, будни)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=1,
                    delay=1.0,
                    priority=9,
                    expires_sec=2 * 60 * 60,
                )
            },
            'sj-top20-pulse-12': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=12, day_of_week='1-5'),
                    name='SJ: IT-каталог (пульс 12, будни)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=1,
                    delay=1.0,
                    priority=9,
                    expires_sec=2 * 60 * 60,
                )
            },
            'sj-top20-pulse-15': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=15, day_of_week='1-5'),
                    name='SJ: IT-каталог (пульс 15, будни)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=1,
                    delay=1.0,
                    priority=9,
                    expires_sec=2 * 60 * 60,
                )
            },
            'sj-top20-pulse-18': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=18, day_of_week='1-5'),
                    name='SJ: IT-каталог (пульс 18, будни)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=1,
                    delay=1.0,
                    priority=9,
                    expires_sec=2 * 60 * 60,
                )
            },
            'sj-top20-pulse-21': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=21, day_of_week='1-5'),
                    name='SJ: IT-каталог (пульс 21, будни)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=1,
                    delay=1.0,
                    priority=9,
                    expires_sec=2 * 60 * 60,
                )
            },

            # ============================================================
            # ГЛУБОКОЕ СКАНИРОВАНИЕ ТОП-40 (nightly deep)
            # ============================================================
            'sj-top40-deep-scan': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=3),
                    name='SJ: IT-каталог (deep scan)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=3,
                    delay=2.0,
                    priority=6,
                    expires_sec=4 * 60 * 60,
                )
            },

            # ============================================================
            # ЕЖЕНЕДЕЛЬНЫЙ ПОЛНЫЙ ПАРСИНГ (weekly comprehensive)
            # ============================================================
            'sj-weekly-comprehensive': {
                **_pipeline_task(
                    schedule=crontab(minute=15, hour=4, day_of_week='sunday'),
                    name='SJ: IT-каталог (weekly comprehensive)',
                    keyword='IT',
                    catalogues=str(IT_CATALOGUE_ID),
                    pages=8,
                    delay=2.5,
                    priority=7,
                    expires_sec=6 * 60 * 60,
                )
            },

            # ============================================================
            # ПРОВЕРКА СТАТУСА ВАКАНСИЙ (рано утром)
            # Деактивация закрытых/архивных вакансий в БД
            # ============================================================
            'sj-check-vacancies-status': {
                'task': 'modules.vacancies_parser.api.superjob.tasks.check_superjob_vacancies_status_task',
                'schedule': crontab(minute=15, hour=5),
                'kwargs': {
                    'batch_size': 50,
                    'max_vacancies': 800,
                },
                'options': {
                    'queue': 'superjob',
                    'priority': 2,
                    'expires': 6 * 60 * 60,
                }
            },
        }

    def get_additional_beat_config(self) -> Dict[str, Any]:
        return {
            'superjob_beat_enabled': True,
            'superjob_beat_max_interval': 300,
            'superjob_beat_sync_every': 60,
        }
