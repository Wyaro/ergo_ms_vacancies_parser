"""
Базовые классы и утилиты для задач парсинга вакансий.

Содержит:
- BaseParsingTaskMixin: mixin для добавления функциональности к задачам
- OrchestrationTaskMixin: для координирующих задач
- WorkerTaskMixin: для worker задач
- PeriodicTaskMixin: для периодических задач
- Утилиты для работы с ошибками и метриками
"""

from .base import (
    BaseParsingTaskMixin,
    get_source_from_task_name,
    get_error_handler_for_task,
    get_metrics_for_task,
    create_task_with_error_handling,
)
from .orchestration import OrchestrationTaskMixin, validate_orchestration_params
from .worker import (
    WorkerTaskMixin,
    validate_worker_params,
    claim_items_for_worker,
    process_item,
    handle_item_error,
)
from .periodic import PeriodicTaskMixin

__all__ = [
    'BaseParsingTaskMixin',
    'OrchestrationTaskMixin',
    'WorkerTaskMixin',
    'PeriodicTaskMixin',
    'get_source_from_task_name',
    'get_error_handler_for_task',
    'get_metrics_for_task',
    'create_task_with_error_handling',
    'validate_orchestration_params',
    'validate_worker_params',
    'claim_items_for_worker',
    'process_item',
    'handle_item_error',
]
