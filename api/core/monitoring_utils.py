"""
Утилиты мониторинга для vacancies_parser.

Используются в парсерах/задачах для фиксации деградаций внешних API и счётчиков TaskRun.
Все операции должны быть best-effort: отсутствие БД/таблиц не должно ломать парсинг.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger('celery.module.vacancies_parser.monitoring')


def _get_current_celery_task_id() -> Optional[str]:
    try:
        from celery import current_task
        if current_task and getattr(current_task, 'request', None):
            return current_task.request.id
    except Exception:
        return None
    return None


def increment_taskrun_counter(field: str, inc: int = 1, celery_task_id: Optional[str] = None) -> None:
    if inc <= 0:
        return
    task_id = celery_task_id or _get_current_celery_task_id()
    if not task_id:
        return
    try:
        from django.db.models import F
        from .monitoring_models import TaskRun

        allowed = {'processed', 'saved', 'updated', 'errors', 'timeouts', 'http_429', 'retries'}
        if field not in allowed:
            return
        TaskRun.objects.filter(celery_task_id=task_id).update(**{field: F(field) + inc})
    except Exception as e:
        logger.debug("increment_taskrun_counter failed: %s", e)


def record_external_api_event(
    source: str,
    event_type: str,
    endpoint: Optional[str] = None,
    count: int = 1,
    celery_task_id: Optional[str] = None,
) -> None:
    if count <= 0:
        return
    task_id = celery_task_id or _get_current_celery_task_id()
    try:
        from .monitoring_models import ExternalApiEvent

        ExternalApiEvent.objects.create(
            source=source,
            endpoint=endpoint,
            event_type=event_type,
            count=count,
            celery_task_id=task_id,
        )
    except Exception as e:
        logger.debug("record_external_api_event failed: %s", e)

