"""
Конфигурация Celery Beat для модуля Habr Career.
Плановое HTML-расписание.

Доступные задачи:
- parse_habr_vacancies_task            (активные вакансии)
- parse_habr_archived_vacancies_task   (архивные вакансии)
- parse_habr_all_vacancies_task        (активные + архивные)
"""

from typing import Dict, Any
from celery.schedules import crontab

from src.core.utils.celery_beat.base import CeleryBeatModuleConfig


class HabrCareerCeleryBeatConfig(CeleryBeatModuleConfig):
    """
    Конфигурация периодических задач для парсинга Habr Career (HTML).

    Логика:
    - регулярный "пульс" активных вакансий днём;
    - ночные более глубокие прогоны;
    - отдельный weekly-прогон архивных для актуализации истории.
    """

    def __init__(self, module_name: str):
        super().__init__(module_name)

    def get_beat_schedule(self) -> Dict[str, Dict[str, Any]]:
        return {
            # ============================================================
            # ЕЖЕДНЕВНЫЙ НОЧНОЙ ПОЛНЫЙ ПРОГОН — новый pipeline
            # ============================================================
            'hc-daily-full-scan': {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': crontab(minute=30, hour=2),
                'args': [
                    'habr_career',
                    'html',
                    {'max_pages': 15, 'delay': 1.5},
                ],
                'kwargs': {
                    'name': 'HC: ежедневный полный прогон',
                },
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 9,
                    'expires': 6 * 60 * 60,
                },
            },

            # ============================================================
            # РАННИЙ УТРЕННИЙ ЗАПУСК (данные в течение дня после старта воркера)
            # ============================================================
            'hc-early-morning-pulse': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=10, hour=8),
                'kwargs': {
                    'pages': 4,
                    'delay': 1.2,
                    'get_details': True,
                    'search_text': 'Python',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 8,
                    'expires': 2 * 60 * 60,
                },
            },
            # ============================================================
            # ПО ТЕХНОЛОГИЯМ ИЗ COMPETENCE_CORE (рабочие дни)
            # ============================================================
            'hc-by-technologies-workdays': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_by_technologies_task',
                'schedule': crontab(minute=40, hour=9, day_of_week='1-5'),
                'kwargs': {
                    'pages_per_query': 2,
                    'delay': 1.2,
                    'get_details': False,
                    'max_queries': 80,
                    'use_aliases': True,
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                },
            },
            # ============================================================
            # ПО ТЕХНОЛОГИЯМ ИЗ COMPETENCE_CORE (ежедневно вечером)
            # ============================================================
            'hc-by-technologies-daily': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_by_technologies_task',
                'schedule': crontab(minute=40, hour=20),
                'kwargs': {
                    'pages_per_query': 3,
                    'delay': 1.3,
                    'get_details': True,
                    'max_queries': 200,
                    'use_aliases': True,
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 6,
                    'expires': 6 * 60 * 60,
                },
            },

            # ============================================================
            # ЯЗЫКИ - РАБОЧИЕ ДНИ (3 раза в день)
            # ============================================================
            'hc-languages-workdays-morning': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=6, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'Python',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                },
            },
            'hc-languages-workdays-noon': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=12, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'JavaScript',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                },
            },
            'hc-languages-workdays-evening': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=18, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'Java',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                },
            },

            # ============================================================
            # ЯЗЫКИ - ВЫХОДНЫЕ (2 раза в день)
            # ============================================================
            'hc-languages-weekend-morning': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=10, day_of_week='0,6'),
                'kwargs': {
                    'pages': 5,
                    'delay': 1.7,
                    'get_details': True,
                    'search_text': 'Python',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 6,
                    'expires': 6 * 60 * 60,
                },
            },
            'hc-languages-weekend-evening': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=18, day_of_week='0,6'),
                'kwargs': {
                    'pages': 5,
                    'delay': 1.7,
                    'get_details': True,
                    'search_text': 'JavaScript',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 6,
                    'expires': 6 * 60 * 60,
                },
            },

            # ============================================================
            # ФРЕЙМВОРКИ - РАБОЧИЕ ДНИ (3 раза/день)
            # ============================================================
            'hc-frameworks-workdays-morning': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=35, hour=7, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'React',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                },
            },
            'hc-frameworks-workdays-noon': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=35, hour=13, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'Django',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                },
            },
            'hc-frameworks-workdays-evening': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=35, hour=19, day_of_week='1-5'),
                'kwargs': {
                    'pages': 6,
                    'delay': 1.5,
                    'get_details': True,
                    'search_text': 'Vue',
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                },
            },

            # ============================================================
            # ПУЛЬС ТОПОВЫХ ЗАПРОСОВ - РАБОЧИЕ ДНИ (каждые 3 часа)
            # ============================================================
            'hc-top-pulse-09': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=9, day_of_week='1-5'),
                'kwargs': {'pages': 2, 'delay': 1.0, 'get_details': False, 'search_text': 'Python'},
                'options': {'queue': 'habr_career', 'priority': 9, 'expires': 2 * 60 * 60},
            },
            'hc-top-pulse-12': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=12, day_of_week='1-5'),
                'kwargs': {'pages': 2, 'delay': 1.0, 'get_details': False, 'search_text': 'JavaScript'},
                'options': {'queue': 'habr_career', 'priority': 9, 'expires': 2 * 60 * 60},
            },
            'hc-top-pulse-15': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=15, day_of_week='1-5'),
                'kwargs': {'pages': 2, 'delay': 1.0, 'get_details': False, 'search_text': 'DevOps'},
                'options': {'queue': 'habr_career', 'priority': 9, 'expires': 2 * 60 * 60},
            },
            'hc-top-pulse-18': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=18, day_of_week='1-5'),
                'kwargs': {'pages': 2, 'delay': 1.0, 'get_details': False, 'search_text': 'React'},
                'options': {'queue': 'habr_career', 'priority': 9, 'expires': 2 * 60 * 60},
            },
            'hc-top-pulse-21': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task',
                'schedule': crontab(minute=20, hour=21, day_of_week='1-5'),
                'kwargs': {'pages': 2, 'delay': 1.0, 'get_details': False, 'search_text': 'Django'},
                'options': {'queue': 'habr_career', 'priority': 9, 'expires': 2 * 60 * 60},
            },

            # ============================================================
            # НОЧНОЙ DEEP SCAN (после SuperJob 03:15)
            # ============================================================
            'hc-nightly-deep-scan': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_all_vacancies_task',
                'schedule': crontab(minute=35, hour=3),
                'kwargs': {
                    'pages': 10,
                    'delay': 2.0,
                    'get_details': True,
                    'search_text': None,
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 6,
                    'expires': 4 * 60 * 60,
                },
            },

            # ============================================================
            # WEEKLY COMPREHENSIVE (воскресенье ночью)
            # ============================================================
            'hc-weekly-comprehensive': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_all_vacancies_task',
                'schedule': crontab(minute=20, hour=4, day_of_week='sunday'),
                'kwargs': {
                    'pages': 12,
                    'delay': 2.2,
                    'get_details': True,
                    'search_text': None,
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 7,
                    'expires': 6 * 60 * 60,
                },
            },

            # ============================================================
            # WEEKLY ARCHIVE REFRESH (понедельник рано утром)
            # ============================================================
            'hc-weekly-archived-refresh': {
                'task': 'modules.vacancies_parser.api.habr_career.tasks.parse_habr_archived_vacancies_task',
                'schedule': crontab(minute=50, hour=5, day_of_week='monday'),
                'kwargs': {
                    'pages': 8,
                    'delay': 1.8,
                    'search_text': None,
                },
                'options': {
                    'queue': 'habr_career',
                    'priority': 5,
                    'expires': 6 * 60 * 60,
                },
            },
        }

    def get_additional_beat_config(self) -> Dict[str, Any]:
        return {
            'habr_career_beat_enabled': True,
            'habr_career_beat_max_interval': 300,
            'habr_career_beat_sync_every': 60,
        }

