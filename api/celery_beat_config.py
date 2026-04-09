"""
Celery Beat конфигурация для модуля vacancies_parser.

Определяет периодические задачи:
- Crash recovery (release expired leases)
- Мониторинг прогресса задач
"""

from celery.schedules import crontab
from src.core.utils.celery_beat import CeleryBeatModuleConfig


class VacanciesParserBeatConfig(CeleryBeatModuleConfig):
    """Конфигурация Celery Beat для модуля vacancies_parser"""
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_beat_schedule(self):
        """
        Расписание периодических задач.
        
        Включает:
        - Освобождение expired leases каждые 5 минут (crash recovery)
        - Мониторинг прогресса задач каждые 10 минут
        """
        return {
            # Crash recovery - каждые 5 минут
            'vacancies_parser-release-expired-leases': {
                'task': 'vacancies_parser.tasks.release_expired_leases',
                'schedule': crontab(minute='*/5'),  # Каждые 5 минут
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 10,  # Высокий приоритет для crash recovery
                }
            },
            
            # Мониторинг - каждые 10 минут
            'vacancies_parser-monitor-tasks-progress': {
                'task': 'vacancies_parser.tasks.monitor_tasks_progress',
                'schedule': crontab(minute='*/10'),  # Каждые 10 минут
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 5,
                }
            },

            # Retention очистка мониторинга - раз в сутки ночью
            'vacancies-parser-cleanup-monitoring-retention': {
                'task': 'vacancies_parser.tasks.cleanup_monitoring_retention',
                'schedule': crontab(minute=30, hour=2),
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 1,
                }
            },

            # Дедупликация нормализованных вакансий - каждую ночь в 3:00
            'vacancies-parser-run-deduplication': {
                'task': 'vacancies_parser.tasks.run_deduplication_task',
                'schedule': crontab(minute=0, hour=3),
                'options': {
                    'queue': 'vacancies_parser',
                    'priority': 1,
                }
            },
        }


# Экземпляр конфигурации (автоматически обнаруживается системой)
# Примечание: менеджер создает экземпляр с module_name, поэтому не создаем здесь
