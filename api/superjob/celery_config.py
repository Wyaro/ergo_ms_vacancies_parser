"""
Конфигурация Celery для модуля superjob.
Настройки задач парсинга вакансий с SuperJob.
"""

from typing import Dict, Any
from src.core.utils.celery.base import CeleryModuleConfig


class SuperjobCeleryConfig(CeleryModuleConfig):
    """
    Конфигурация Celery для модуля парсинга SuperJob.
    """
    
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
        return {
            'modules.vacancies_parser.api.superjob.tasks.parse_superjob_vacancies_task': {
                'time_limit': 3600,   # Таймаут 1 час
                'soft_time_limit': 3300,  # Мягкий таймаут 55 минут
                'rate_limit': '3/h',   # Максимум 3 задачи в час
            },
            'modules.vacancies_parser.api.superjob.tasks.parse_all_superjob_vacancies_task': {
                'time_limit': 7200,   # Таймаут 2 часа
                'soft_time_limit': 6900,  # Мягкий таймаут 1 час 55 минут
                'rate_limit': '1/h',   # Максимум 1 задача в час
            },
            'modules.vacancies_parser.api.superjob.tasks.get_superjob_vacancy_details_task': {
                'time_limit': 1800,   # Таймаут 30 минут
                'soft_time_limit': 1500,  # Мягкий таймаут 25 минут
                'rate_limit': '30/h',  # Максимум 30 задач в час
            },
            'modules.vacancies_parser.api.superjob.tasks.parse_superjob_vacancies_by_config_task': {
                'time_limit': 5400,   # Таймаут 1.5 часа
                'soft_time_limit': 5100,  # Мягкий таймаут 1 час 25 минут
                'rate_limit': '2/h',   # Максимум 2 задачи в час
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
    
    def get_additional_config(self) -> Dict[str, Any]:
        """Дополнительные настройки для модуля парсинга SuperJob"""
        return {
            'superjob_max_concurrent_tasks': 2,
            'superjob_rate_limit': '8/m',  # 8 запросов в минуту
            'superjob_retry_delay': 120,  # Задержка между повторами 2 минуты
        } 