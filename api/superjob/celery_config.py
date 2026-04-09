"""
Конфигурация Celery для модуля superjob.
Настройки задач парсинга вакансий с SuperJob.
"""

from typing import Dict, Any
from ..core.celery_config_base import VacanciesParserCeleryConfigBase


class SuperjobCeleryConfig(VacanciesParserCeleryConfigBase):
    """
    Конфигурация Celery для модуля парсинга SuperJob.
    """
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_task_routes(self) -> Dict[str, Dict[str, Any]]:
        """Маршруты задач для парсинга SuperJob"""
        return {
            'modules.vacancies_parser.api.superjob.tasks.*': {'queue': 'superjob'},
        }
    
    def get_task_queues(self) -> Dict[str, Dict[str, Any]]:
        """Очереди задач для парсинга SuperJob"""
        return {
            'superjob': {
                'exchange': 'superjob',
                'routing_key': 'superjob',
            }
        }
    
    def get_task_annotations(self) -> Dict[str, Dict[str, Any]]:
        """Аннотации задач для парсинга SuperJob"""
        prefix = 'modules.vacancies_parser.api.superjob.tasks'
        return {
            f'{prefix}.parse_superjob_vacancies_task': {
                'time_limit': 3600,
                'soft_time_limit': 3300,
                'rate_limit': '3/h',
            },
            f'{prefix}.parse_all_superjob_vacancies_task': {
                'time_limit': 180,
                'soft_time_limit': 120,
                'rate_limit': '1/h',
            },
            f'{prefix}.parse_superjob_vacancies_chunk_task': {
                'time_limit': 1800,
                'soft_time_limit': 1500,
                'rate_limit': None,
            },
            f'{prefix}.get_superjob_vacancy_details_task': {
                'time_limit': 1800,
                'soft_time_limit': 1500,
                'rate_limit': '30/h',
            },
            f'{prefix}.parse_superjob_vacancies_by_config_task': {
                'time_limit': 5400,
                'soft_time_limit': 5100,
                'rate_limit': '2/h',
            },
            f'{prefix}.parse_superjob_by_catalogues_task': {
                'time_limit': 14400,
                'soft_time_limit': 14100,
                'rate_limit': '1/h',
            },
            f'{prefix}.parse_superjob_single_catalogue_task': {
                'time_limit': 3900,
                'soft_time_limit': 3600,
                'rate_limit': '6/h',
            },
            f'{prefix}.parse_superjob_catalogues_chord_task': {
                'time_limit': 14400,
                'soft_time_limit': 14100,
                'rate_limit': '1/h',
            },
            f'{prefix}.parse_superjob_batch_task': {
                'time_limit': 3900,
                'soft_time_limit': 3600,
                'rate_limit': '6/h',
            },
            f'{prefix}.check_superjob_vacancies_status_task': {
                'time_limit': 7500,
                'soft_time_limit': 7200,
                'rate_limit': '2/h',
            },
        }
    
    def get_module_loggers(self) -> Dict[str, Any]:
        """Специализированные логгеры для модуля парсинга SuperJob"""
        loggers = super().get_module_loggers()
        
        # Добавляем специализированные логгеры
        loggers.update({
            'parsing': self._get_logger('parsing'),
            'api': self._get_logger('api'),
            'details': self._get_logger('details'),
        })
        
        return loggers
    
    def _get_logger(self, logger_name: str):
        """Создает специализированный логгер для модуля"""
        import logging
        return logging.getLogger(f'celery.module.{self.module_name}.{logger_name}')
    
    def get_max_concurrent_tasks(self) -> int:
        return 2

    def get_additional_config(self) -> Dict[str, Any]:
        """Дополнительные настройки для модуля парсинга SuperJob"""
        return {
            'superjob_max_concurrent_tasks': 2,
            'superjob_rate_limit': '8/m',
            'superjob_retry_delay': 120,
        }
