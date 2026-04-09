"""
Утилиты для Celery задач SuperJob.

Общий паттерн обработки ошибок и retry для всех задач модуля.
"""

import logging
from typing import Callable, Dict, Any

from ...core.error_handling import SuperJobErrorHandler
from ...core.metrics import get_task_metrics

logger = logging.getLogger('modules.vacancies_parser.superjob')

_error_handler = SuperJobErrorHandler()


def get_superjob_error_handler() -> SuperJobErrorHandler:
    return _error_handler


def get_superjob_metrics():
    return get_task_metrics('superjob')


def run_task_with_error_handling(
    task,
    task_body: Callable[[], Dict[str, Any]],
    task_logger: logging.Logger = logger,
    error_context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Выполняет тело задачи с единым паттерном обработки ошибок и retry.

    Args:
        task: Celery task instance (self из bind=True).
        task_body: Callable без аргументов, возвращающий результат задачи.
        task_logger: Логгер для записи ошибок.
        error_context: Дополнительный контекст для обработчика ошибок.
    """
    task_id = task.request.id
    error_handler = get_superjob_error_handler()
    metrics = get_superjob_metrics()
    metrics.record_task_start(task_id, task_name=task.name)

    try:
        result = task_body()
        metrics.record_task_success(task_id, result)
        return result

    except Exception as exc:
        task_logger.error("Ошибка задачи %s: %s", task.name, exc, exc_info=True)
        metrics.record_task_failure(task_id, exc)

        context = {'task_id': task_id}
        if error_context:
            context.update(error_context)
        error_handler.handle_error(exc, context)

        retries = task.request.retries
        if error_handler.should_retry(exc, retries, task.max_retries):
            retry_delay = error_handler.get_retry_delay(
                exc, retries, base_delay=task.default_retry_delay
            )
            raise task.retry(exc=exc, countdown=retry_delay)

        return {'status': 'FAILURE', 'error': str(exc), 'message': f'Ошибка: {exc}'}
