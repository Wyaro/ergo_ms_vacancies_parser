"""
Базовый класс конфигурации Celery для модуля vacancies_parser.

Предоставляет общие настройки для всех источников парсинга:
- Общие таймауты и лимиты
- Шаблоны аннотаций задач
- Единые настройки очередей
"""

from typing import Dict, Any
from kombu import Queue, Exchange
from src.core.utils.celery import CeleryModuleConfig


class VacanciesParserCeleryConfigBase(CeleryModuleConfig):
    """
    Базовый класс конфигурации Celery для модуля vacancies_parser.
    
    Предоставляет общие настройки для всех источников парсинга.
    Подклассы должны переопределять специфичные настройки.
    """
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_task_routes(self) -> Dict[str, Dict[str, Any]]:
        """
        Базовые маршруты задач.
        
        Переопределите в подклассах для специфичных маршрутов.
        """
        return {}
    
    def get_task_queues(self) -> Dict[str, Dict[str, Any]]:
        """
        Базовые настройки очередей.
        
        Переопределите в подклассах для специфичных очередей.
        """
        return {}
    
    def get_task_annotations(self) -> Dict[str, Dict[str, Any]]:
        """
        Базовые аннотации задач.
        
        Предоставляет общие таймауты и лимиты для типичных задач.
        Переопределите в подклассах для специфичных аннотаций.
        """
        return {
            # Общие настройки для всех задач парсинга
            'vacancies_parser.tasks.*': {
                'time_limit': 3600,  # 1 час по умолчанию
                'soft_time_limit': 3300,  # 55 минут
            },
        }
    
    def get_default_time_limits(self) -> Dict[str, int]:
        """
        Получение таймаутов по умолчанию для разных типов задач.
        
        Returns:
            dict: Таймауты по типам задач
        """
        return {
            'orchestration': {
                'time_limit': 7200,  # 2 часа
                'soft_time_limit': 6900,  # 1 час 55 минут
            },
            'worker': {
                'time_limit': 3600,  # 1 час
                'soft_time_limit': 3300,  # 55 минут
            },
            'periodic': {
                'time_limit': 300,  # 5 минут
                'soft_time_limit': 270,  # 4.5 минуты
            },
            'batch': {
                'time_limit': 5400,  # 1.5 часа
                'soft_time_limit': 5100,  # 1 час 25 минут
            },
        }
    
    def get_default_rate_limits(self) -> Dict[str, str]:
        """
        Получение rate limits по умолчанию для разных типов задач.
        
        Returns:
            dict: Rate limits по типам задач
        """
        return {
            'orchestration': '10/h',  # 10 задач в час
            'worker': None,  # Без лимита для workers
            'periodic': '1/m',  # 1 задача в минуту
            'batch': '60/h',  # 60 задач в час
        }
