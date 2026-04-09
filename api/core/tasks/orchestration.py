"""
Утилиты для координирующих задач парсинга.

Используется для:
- Создания ParsingTask
- Координации выполнения парсинга
- Финализации задач
"""

import logging
from typing import Dict, Any, Optional

from .base import BaseParsingTaskMixin

logger = logging.getLogger('celery.module.vacancies_parser.tasks.orchestration')


def validate_orchestration_params(**kwargs) -> bool:
    """
    Валидация параметров координирующей задачи.
    
    Args:
        **kwargs: Параметры задачи
    
    Returns:
        bool: True если параметры валидны
    
    Raises:
        ValueError: При невалидных параметрах
    """
    # Проверка обязательных параметров
    required_params = ['source', 'parsing_mode', 'config']
    for param in required_params:
        if param not in kwargs:
            raise ValueError(f"Отсутствует обязательный параметр: {param}")
    
    # Валидация source
    valid_sources = ['headhunter', 'habr_career', 'superjob']
    if kwargs.get('source') not in valid_sources:
        raise ValueError(f"Неверный source: {kwargs.get('source')}. Допустимые: {valid_sources}")
    
    # Валидация parsing_mode
    valid_modes = ['api', 'html']
    if kwargs.get('parsing_mode') not in valid_modes:
        raise ValueError(f"Неверный parsing_mode: {kwargs.get('parsing_mode')}. Допустимые: {valid_modes}")
    
    return True


class OrchestrationTaskMixin(BaseParsingTaskMixin):
    """
    Mixin для координирующих задач парсинга.
    
    Предоставляет общую логику для:
    - Создания ParsingTask
    - Координации worker задач
    - Мониторинга прогресса
    - Финализации задач
    """
    
    def validate_params(self, **kwargs) -> bool:
        """Валидация параметров координирующей задачи"""
        return validate_orchestration_params(**kwargs)
