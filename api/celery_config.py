"""
Celery конфигурация для модуля vacancies_parser.

Определяет:
- Маршруты задач (task routes)
- Настройки очередей (task queues)
- Таймауты и лимиты (task annotations)
"""

from kombu import Queue, Exchange
from .core.celery_config_base import VacanciesParserCeleryConfigBase


class VacanciesParserCeleryConfig(VacanciesParserCeleryConfigBase):
    """Конфигурация Celery для модуля vacancies_parser"""
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_task_routes(self):
        """
        Маршруты задач модуля.
        
        Все задачи парсинга направляются в очередь 'vacancies_parser'.
        """
        return {
            'vacancies_parser.tasks.*': {'queue': 'vacancies_parser'},
        }
    
    def get_task_queues(self):
        """
        Настройки очереди модуля.
        
        Использует отдельную очередь 'vacancies_parser' для изоляции от других модулей.
        """
        return {
            'vacancies_parser': {
                'exchange': 'vacancies_parser',
                'routing_key': 'vacancies_parser',
                'queue_arguments': {'x-max-priority': 10}  # Поддержка приоритетов
            }
        }
    
    def get_task_annotations(self):
        """
        Таймауты и лимиты для задач модуля.
        
        Настройки оптимизированы для парсинга ~40k items/hour с параллелизмом ~10.
        """
        # Получаем базовые аннотации
        annotations = super().get_task_annotations()
        
        # Получаем таймауты по умолчанию
        default_limits = self.get_default_time_limits()
        default_rates = self.get_default_rate_limits()
        
        # Добавляем специфичные аннотации
        annotations.update({
            # Координирующие задачи
            'vacancies_parser.tasks.create_parsing_task': {
                'time_limit': 600,  # 10 минут (discovery может быть долгим)
                'soft_time_limit': 540,
                'rate_limit': '10/m',  # Лимит создания задач
            },
            'vacancies_parser.tasks.coordinate_parsing_task': {
                **default_limits['orchestration'],
                'rate_limit': None,  # Без лимита для координаторов
            },
            'vacancies_parser.tasks.finalize_parsing_task': {
                **default_limits['periodic'],
                'rate_limit': None,
            },
            
            # Worker задачи
            'vacancies_parser.tasks.parse_items_worker': {
                **default_limits['worker'],
                'rate_limit': None,  # Без лимита для workers
                'max_retries': 0,  # Workers не делают retry
            },
            
            # Периодические задачи
            'vacancies_parser.tasks.release_expired_leases': {
                **default_limits['periodic'],
                'rate_limit': default_rates['periodic'],
            },
            'vacancies_parser.tasks.monitor_tasks_progress': {
                **default_limits['periodic'],
                'rate_limit': default_rates['periodic'],
            },
            'vacancies_parser.tasks.cleanup_monitoring_retention': {
                **default_limits['periodic'],
                'rate_limit': None,
            },
            
            # Управляющие задачи
            'vacancies_parser.tasks.pause_task': {
                'time_limit': 60,
                'soft_time_limit': 50,
            },
            'vacancies_parser.tasks.resume_task': {
                'time_limit': 60,
                'soft_time_limit': 50,
            },
            'vacancies_parser.tasks.stop_task': {
                'time_limit': 120,
                'soft_time_limit': 110,
            },

            # Задачи нормализации
            'vacancies_parser.tasks.rebuild_normalized_vacancies_for_task': {
                **default_limits['batch'],
                'rate_limit': '10/h',
            },
            'vacancies_parser.tasks.run_deduplication_task': {
                **default_limits['periodic'],
                'rate_limit': default_rates['periodic'],
            },
        })
        
        return annotations


# Экземпляр конфигурации (автоматически обнаруживается системой)
# Примечание: менеджер создает экземпляр с module_name, поэтому не создаем здесь
