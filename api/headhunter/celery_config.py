"""
Конфигурация Celery для модуля headhunter.
Настройки задач парсинга вакансий с HeadHunter.
"""

from typing import Dict, Any

from src.core.utils.celery.base import CeleryModuleConfig

class HeadhunterCeleryConfig(CeleryModuleConfig):
    """
    Конфигурация Celery для модуля парсинга HeadHunter.
    """
    
    def get_task_routes(self) -> Dict[str, Dict[str, Any]]:
        """Маршруты задач для парсинга HeadHunter"""
        return {
            'modules.vacancies_parser.api.headhunter.tasks.*': {'queue': 'headhunter'},
        }
    
    def get_task_queues(self) -> Dict[str, Dict[str, Any]]:
        """Очереди задач для парсинга HeadHunter"""
        return {
            'headhunter': {
                'exchange': 'headhunter',
                'routing_key': 'headhunter',
            }
        }
    
    def get_task_annotations(self) -> Dict[str, Dict[str, Any]]:
        """Аннотации задач для парсинга HeadHunter"""
        return {
            'modules.vacancies_parser.api.headhunter.tasks.parse_hh_vacancies_task': {
                'time_limit': 7200,   # Таймаут 2 часа
                'soft_time_limit': 6900,  # Мягкий таймаут 1 час 55 минут
                'rate_limit': '100/h',   # Максимум 100 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_single_vacancy_task': {
                'time_limit': 1800,   # Таймаут 30 минут
                'soft_time_limit': 1500,  # Мягкий таймаут 25 минут
                'rate_limit': '100/h',  # Максимум 100 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies': {
                'time_limit': 5400,   # Таймаут 1.5 часа
                'soft_time_limit': 5100,  # Мягкий таймаут 1 час 25 минут
                'rate_limit': '60/h',  # Максимум 60 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category': {
                'time_limit': 3600,   # Таймаут 1 час
                'soft_time_limit': 3300,  # Мягкий таймаут 55 минут
                'rate_limit': '60/h',  # Максимум 60 задач в час
            },
        }
    
    def get_module_loggers(self) -> Dict[str, Any]:
        """Специализированные логгеры для модуля парсинга HeadHunter"""
        loggers = super().get_module_loggers()
        
        # Добавляем специализированные логгеры
        loggers.update({
            'parsing': self._get_logger('parsing'),
            'api': self._get_logger('api'),
        })
        
        return loggers
    
    def _get_logger(self, logger_name: str):
        """Создает специализированный логгер для модуля"""
        import logging
        return logging.getLogger(f'celery.module.{self.module_name}.{logger_name}')

    def get_max_concurrent_tasks(self) -> int:
        return 3  # Максимум 3 одновременных задачи