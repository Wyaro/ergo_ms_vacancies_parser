"""
Утилиты для периодических задач парсинга.

Используется для:
- Crash recovery (освобождение expired leases)
- Мониторинга прогресса задач
- Очистки данных
"""

import logging
from typing import Dict, Any

from .base import BaseParsingTaskMixin

logger = logging.getLogger('celery.module.vacancies_parser.tasks.periodic')


class PeriodicTaskMixin(BaseParsingTaskMixin):
    """
    Mixin для периодических задач парсинга.
    
    Предоставляет общую логику для:
    - Crash recovery
    - Мониторинга
    - Очистки данных
    """
    pass
