"""
Конфигурация Celery Beat для модуля HeadHunter.
Настройка периодических задач парсинга вакансий.

Версия 0.3: Оптимизированное расписание без конфликтов по времени.
"""

from typing import Dict, Any
from celery.schedules import crontab

from src.core.utils.celery_beat.base import CeleryBeatModuleConfig


class HeadhunterCeleryBeatConfig(CeleryBeatModuleConfig):
    """
    Конфигурация периодических задач для парсинга HeadHunter.
    
    Принципы расписания:
    - Разнесение задач по времени (разные минуты) для избежания конфликтов
    - Разные расписания для рабочих и выходных дней
    - Интенсивный парсинг ночью, когда нагрузка на API минимальна
    - Приоритизация по важности категорий
    """
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_beat_schedule(self) -> Dict[str, Dict[str, Any]]:
        """
        Расписание периодических задач для парсинга вакансий.
        
        Returns:
            Dict[str, Dict[str, Any]]: Расписание задач
        """
        return {
            # ============================================================
            # ЕЖЕДНЕВНЫЙ ПАРСИНГ (высший приоритет) — новый pipeline
            # ============================================================
            'hh-daily-yesterday-today': {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': crontab(minute=0, hour=2),
                'args': [
                    'headhunter',
                    'api',
                    {'area': 113, 'pages': 20, 'per_page': 100, 'delay': 1.5},
                ],
                'kwargs': {
                    'name': 'HH: ежедневный парсинг IT-вакансий',
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
            'hh-monthly-recursive': {
                'task': 'vacancies_parser.tasks.create_parsing_task',
                'schedule': crontab(minute=0, hour=1, day_of_month='1'),
                'args': [
                    'headhunter',
                    'api',
                    {'area': 113, 'pages': 20, 'per_page': 100, 'delay': 1.5, 'text': 'программист'},
                ],
                'kwargs': {
                    'name': 'HH: ежемесячный глубокий прогон',
                },
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 9,
                    'expires': 12 * 60 * 60,
                }
            },
            
            # ============================================================
            # ЯЗЫКИ ПРОГРАММИРОВАНИЯ - РАБОЧИЕ ДНИ (3 раза в день)
            # ============================================================
            'hh-languages-workdays-morning': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=15, hour=6, day_of_week='1-5'),
                'kwargs': {
                    'category': 'LANG',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                }
            },
            'hh-languages-workdays-noon': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=15, hour=12, day_of_week='1-5'),
                'kwargs': {
                    'category': 'LANG',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                }
            },
            'hh-languages-workdays-evening': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=15, hour=18, day_of_week='1-5'),
                'kwargs': {
                    'category': 'LANG',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 8,
                    'expires': 4 * 60 * 60,
                }
            },
            
            # ============================================================
            # ЯЗЫКИ ПРОГРАММИРОВАНИЯ - ВЫХОДНЫЕ (2 раза в день)
            # ============================================================
            'hh-languages-weekend-morning': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=15, hour=10, day_of_week='0,6'),
                'kwargs': {
                    'category': 'LANG',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 6,
                    'expires': 6 * 60 * 60,
                }
            },
            'hh-languages-weekend-evening': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=15, hour=18, day_of_week='0,6'),
                'kwargs': {
                    'category': 'LANG',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 6,
                    'expires': 6 * 60 * 60,
                }
            },
            
            # ============================================================
            # ФРЕЙМВОРКИ - РАБОЧИЕ ДНИ (3 раза, сдвиг от языков)
            # ============================================================
            'hh-frameworks-workdays-morning': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=7, day_of_week='1-5'),
                'kwargs': {
                    'category': 'FRAMEWORK',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 25
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                }
            },
            'hh-frameworks-workdays-noon': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=13, day_of_week='1-5'),
                'kwargs': {
                    'category': 'FRAMEWORK',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 25
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                }
            },
            'hh-frameworks-workdays-evening': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=19, day_of_week='1-5'),
                'kwargs': {
                    'category': 'FRAMEWORK',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 25
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 7,
                    'expires': 4 * 60 * 60,
                }
            },
            
            # ============================================================
            # ФРЕЙМВОРКИ - ВЫХОДНЫЕ (2 раза)
            # ============================================================
            'hh-frameworks-weekend-morning': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=11, day_of_week='0,6'),
                'kwargs': {
                    'category': 'FRAMEWORK',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 25
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 5,
                    'expires': 6 * 60 * 60,
                }
            },
            'hh-frameworks-weekend-evening': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=19, day_of_week='0,6'),
                'kwargs': {
                    'category': 'FRAMEWORK',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 25
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 5,
                    'expires': 6 * 60 * 60,
                }
            },
            
            # ============================================================
            # БАЗЫ ДАННЫХ (2 раза в день)
            # ============================================================
            'hh-databases-morning': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=45, hour=8),
                'kwargs': {
                    'category': 'DB',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 15
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 5,
                    'expires': 8 * 60 * 60,
                }
            },
            'hh-databases-evening': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=45, hour=20),
                'kwargs': {
                    'category': 'DB',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 15
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 5,
                    'expires': 8 * 60 * 60,
                }
            },
            
            # ============================================================
            # ИНСТРУМЕНТЫ (1 раз в день)
            # ============================================================
            'hh-tools-daily': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=0, hour=14),
                'kwargs': {
                    'category': 'TOOL',
                    'use_aliases': False,
                    'area': 113,
                    'pages': 2,
                    'delay': 1.5,
                    'get_details': True,
                    'max_queries': 15
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 4,
                    'expires': 12 * 60 * 60,
                }
            },
            
            # ============================================================
            # ОБЛАЧНЫЕ ПЛАТФОРМЫ (ночью)
            # ============================================================
            'hh-platforms-nightly': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
                'schedule': crontab(minute=30, hour=23),
                'kwargs': {
                    'category': 'PLATFORM',
                    'use_aliases': True,
                    'area': 113,
                    'pages': 2,
                    'delay': 2.0,
                    'get_details': True,
                    'max_queries': 15
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 3,
                    'expires': 20 * 60 * 60,
                }
            },
            
            # ============================================================
            # ПУЛЬС ТОП-20 (рабочие дни, каждые 3 часа в рабочее время)
            # ============================================================
            'hh-top20-pulse-09': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=9, day_of_week='1-5'),
                'kwargs': {
                    'categories': None,
                    'top_n': 20,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 1,
                    'delay': 1.0,
                    'get_details': False,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 2 * 60 * 60,
                }
            },
            'hh-top20-pulse-12': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=12, day_of_week='1-5'),
                'kwargs': {
                    'categories': None,
                    'top_n': 20,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 1,
                    'delay': 1.0,
                    'get_details': False,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 2 * 60 * 60,
                }
            },
            'hh-top20-pulse-15': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=15, day_of_week='1-5'),
                'kwargs': {
                    'categories': None,
                    'top_n': 20,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 1,
                    'delay': 1.0,
                    'get_details': False,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 2 * 60 * 60,
                }
            },
            'hh-top20-pulse-18': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=18, day_of_week='1-5'),
                'kwargs': {
                    'categories': None,
                    'top_n': 20,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 1,
                    'delay': 1.0,
                    'get_details': False,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 2 * 60 * 60,
                }
            },
            'hh-top20-pulse-21': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=21, day_of_week='1-5'),
                'kwargs': {
                    'categories': None,
                    'top_n': 20,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 1,
                    'delay': 1.0,
                    'get_details': False,
                    'max_queries': 20
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 2 * 60 * 60,
                }
            },
            
            # ============================================================
            # ГЛУБОКОЕ СКАНИРОВАНИЕ ТОП-40 (ночью)
            # ============================================================
            'hh-top40-deep-scan': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=3),
                'kwargs': {
                    'categories': ['LANG', 'FRAMEWORK'],
                    'top_n': 40,
                    'use_aliases': False,
                    'area': 113,
                    'pages': 3,
                    'delay': 2.0,
                    'get_details': True,
                    'max_queries': 40
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 6,
                    'expires': 4 * 60 * 60,
                }
            },
            
            # ============================================================
            # ЕЖЕНЕДЕЛЬНЫЙ ПОЛНЫЙ ПАРСИНГ (воскресенье ночью)
            # ============================================================
            'hh-weekly-comprehensive': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies',
                'schedule': crontab(minute=0, hour=4, day_of_week='sunday'),
                'kwargs': {
                    'categories': ['LANG', 'FRAMEWORK', 'DB', 'TOOL'],
                    'top_n': 60,
                    'use_aliases': True,
                    'area': 113,
                    'pages': 3,
                    'delay': 2.5,
                    'get_details': True,
                    'max_queries': 120
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 7,
                    'expires': 6 * 60 * 60,
                }
            },
            
            # ============================================================
            # ПРОВЕРКА СТАТУСА ВАКАНСИЙ (рано утром)
            # ============================================================
            'hh-check-vacancies-status': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.check_vacancies_status_task',
                'schedule': crontab(minute=0, hour=5),
                'kwargs': {
                    'batch_size': 150,
                    'delay': 0.2,
                    'max_vacancies': 800
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 2,
                    'expires': 6 * 60 * 60,
                }
            },

            # ============================================================
            # АКТУАЛИЗАЦИЯ СПРАВОЧНИКА ПРОФЕССИОНАЛЬНЫХ РОЛЕЙ (еженедельно)
            # ============================================================
            'hh-update-professional-roles': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.get_professional_roles_task',
                'schedule': crontab(minute=30, hour=6, day_of_week='sunday'),
                'kwargs': {},
                'options': {
                    'queue': 'headhunter',
                    'priority': 1,
                    'expires': 24 * 60 * 60,
                }
            },

            # ============================================================
            # ПАРСИНГ ПО ПРОФЕССИОНАЛЬНЫМ РОЛЯМ IT
            # ============================================================
            'hh-professional-roles-comprehensive': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_professional_roles',
                'schedule': crontab(minute=0, hour=3, day_of_week='monday'),
                'kwargs': {
                    'area': 113,
                    'pages': 5,
                    'delay': 3.0,
                    'get_details': True,
                    'max_concurrent_roles': 3,
                    'batch_size': 5,
                    'force_refresh_roles': False
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 9,
                    'expires': 48 * 60 * 60,
                }
            },
            'hh-professional-roles-daily': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_professional_roles',
                'schedule': crontab(minute=0, hour=9, day_of_week='tuesday,wednesday,thursday,friday'),
                'kwargs': {
                    'area': 113,
                    'pages': 2,
                    'delay': 2.0,
                    'get_details': True,
                    'max_concurrent_roles': 5,
                    'batch_size': 8,
                    'force_refresh_roles': False
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 8,
                    'expires': 24 * 60 * 60,
                }
            },
            'hh-professional-roles-quick-scan': {
                'task': 'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_professional_roles',
                'schedule': crontab(minute=30, hour=14, day_of_week='saturday'),
                'kwargs': {
                    'area': 113,
                    'pages': 1,
                    'delay': 1.5,
                    'get_details': False,
                    'max_concurrent_roles': 8,
                    'batch_size': 10,
                    'force_refresh_roles': False
                },
                'options': {
                    'queue': 'headhunter',
                    'priority': 6,
                    'expires': 12 * 60 * 60,
                }
            },
        }
    
    def get_additional_beat_config(self) -> Dict[str, Any]:
        """
        Дополнительные настройки для Beat планировщика.
        
        Returns:
            Dict[str, Any]: Дополнительные настройки
        """
        return {
            'headhunter_beat_enabled': True,
            'headhunter_beat_max_interval': 300,
            'headhunter_beat_sync_every': 60,
        }
