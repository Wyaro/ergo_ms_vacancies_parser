"""
Конфигурация Celery для модуля habr_career.
Настройки задач парсинга вакансий с Habr Career.
"""

from typing import Dict, Any
from ..core.celery_config_base import VacanciesParserCeleryConfigBase


class HabrCareerCeleryConfig(VacanciesParserCeleryConfigBase):
    """
    Конфигурация Celery для модуля парсинга Habr Career.
    """
    
    def get_task_routes(self) -> Dict[str, Dict[str, Any]]:
        """Маршруты задач для парсинга Habr Career"""
        return {
            'modules.vacancies_parser.api.habr_career.tasks.*': {'queue': 'habr_career'},
        }
    
    def get_task_queues(self) -> Dict[str, Dict[str, Any]]:
        """Очереди задач для парсинга Habr Career"""
        return {
            'habr_career': {
                'exchange': 'habr_career',
                'routing_key': 'habr_career',
            }
        }
    
    def get_task_annotations(self) -> Dict[str, Dict[str, Any]]:
        """Аннотации задач для парсинга Habr Career"""
        return {
            'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_task': {
                'time_limit': 3600,   # Таймаут 1 час
                'soft_time_limit': 3300,  # Мягкий таймаут 55 минут
                'rate_limit': '4/h',   # Максимум 4 задачи в час
            },
            'modules.vacancies_parser.api.habr_career.tasks.parse_habr_archived_vacancies_task': {
                'time_limit': 3600,   # Таймаут 1 час
                'soft_time_limit': 3300,  # Мягкий таймаут 55 минут
                'rate_limit': '2/h',   # Максимум 2 задачи в час
            },
            'modules.vacancies_parser.api.habr_career.tasks.parse_habr_all_vacancies_task': {
                'time_limit': 7200,
                'soft_time_limit': 6900,
                'rate_limit': '1/h',
            },
            'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_by_technologies_task': {
                'time_limit': 180,
                'soft_time_limit': 120,
                'rate_limit': '2/h',
            },
            'modules.vacancies_parser.api.habr_career.tasks.parse_habr_vacancies_chunk_task': {
                'time_limit': 1800,
                'soft_time_limit': 1500,
                'rate_limit': None,
            },
        }
    
    def get_module_loggers(self) -> Dict[str, Any]:
        """Специализированные логгеры для модуля парсинга Habr Career"""
        loggers = super().get_module_loggers()
        
        # Добавляем специализированные логгеры
        loggers.update({
            'parsing': self._get_logger('parsing'),
            'api': self._get_logger('api'),
            'archived': self._get_logger('archived'),
        })
        
        return loggers
    
    def _get_logger(self, logger_name: str):
        """Создает специализированный логгер для модуля"""
        import logging
        return logging.getLogger(f'celery.module.{self.module_name}.{logger_name}')
    
    def get_additional_config(self) -> Dict[str, Any]:
        """Дополнительные настройки для модуля парсинга Habr Career"""
        return {
            'habr_career_max_concurrent_tasks': 2,
            'habr_career_rate_limit': '6/m',  # 6 запросов в минуту
            'habr_career_retry_delay': 90,  # Задержка между повторами 1.5 минуты
        } 