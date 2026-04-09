"""
Сбор метрик выполнения задач парсинга.

Интегрируется с существующим ParsingMetrics и предоставляет
дополнительные метрики для мониторинга задач Celery.
"""

import hashlib
import json
import logging
import time
from typing import Dict, Any, Optional
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger('celery.module.vacancies_parser.metrics')


class TaskMetrics:
    """
    Сбор метрик выполнения задач парсинга.
    
    Предоставляет:
    - Метрики времени выполнения
    - Метрики успешности/ошибок
    - Метрики обработки items
    - Интеграция с ParsingMetrics
    """
    
    def __init__(self, source: Optional[str] = None):
        """
        Args:
            source: Источник парсинга (опционально)
        """
        self.source = source
        self.logger = logging.getLogger(f'celery.module.vacancies_parser.metrics.{source or "default"}')
        
        # Метрики задач
        self._task_start_times: Dict[str, float] = {}
        self._task_metrics: Dict[str, Dict[str, Any]] = defaultdict(dict)
        
        # Метрики items
        self._items_processed: Dict[str, int] = defaultdict(int)
        self._items_failed: Dict[str, int] = defaultdict(int)
        self._items_success: Dict[str, int] = defaultdict(int)

    def _safe_kwargs_digest(self, kwargs: Dict[str, Any]) -> Optional[str]:
        if not kwargs:
            return None
        try:
            payload = json.dumps(kwargs, sort_keys=True, default=str, ensure_ascii=False)
            return hashlib.sha256(payload.encode('utf-8')).hexdigest()
        except Exception:
            return None

    def _db_enabled(self) -> bool:
        """
        DB-режим может быть недоступен во время миграций/инициализации.
        В этом случае метрики остаются in-memory и в логах.
        """
        try:
            from django.db import connection
            return connection is not None
        except Exception:
            return False

    def _db_upsert_taskrun_start(self, task_id: str, task_name: Optional[str], kwargs: Dict[str, Any]):
        try:
            if not self._db_enabled():
                return
            from django.utils import timezone
            from .monitoring_models import TaskRun

            TaskRun.objects.update_or_create(
                celery_task_id=task_id,
                defaults={
                    'task_name': task_name or '',
                    'source': self.source,
                    'status': 'running',
                    'started_at': timezone.now(),
                    'kwargs_digest': self._safe_kwargs_digest(kwargs),
                },
            )
        except Exception as e:
            self.logger.debug("TaskRun start write failed: %s", e)

    def _db_update_taskrun_finish(
        self,
        task_id: str,
        status: str,
        duration: Optional[float],
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        try:
            if not self._db_enabled():
                return
            from django.utils import timezone
            from django.db.models import F
            from .monitoring_models import TaskRun

            update = {
                'status': status,
                'finished_at': timezone.now(),
                'duration_sec': duration,
                'error_type': error_type,
                'error_message': error_message,
            }
            TaskRun.objects.filter(celery_task_id=task_id).update(**update)
            # Дополнительно синхронизируем processed/errors из in-memory счётчиков
            TaskRun.objects.filter(celery_task_id=task_id).update(
                processed=F('processed') + self._items_processed.get(task_id, 0),
                errors=F('errors') + self._items_failed.get(task_id, 0),
            )
        except Exception as e:
            self.logger.debug("TaskRun finish write failed: %s", e)

    def increment_counter(self, task_id: str, field: str, inc: int = 1):
        """
        Унифицированный инкремент счётчика в TaskRun (если доступно).
        """
        if inc <= 0:
            return
        try:
            if not self._db_enabled():
                return
            from django.db.models import F
            from .monitoring_models import TaskRun

            allowed = {'processed', 'saved', 'updated', 'errors', 'timeouts', 'http_429', 'retries'}
            if field not in allowed:
                return
            TaskRun.objects.filter(celery_task_id=task_id).update(**{field: F(field) + inc})
        except Exception as e:
            self.logger.debug("TaskRun counter increment failed: %s", e)
    
    def record_task_start(self, task_id: str, task_name: Optional[str] = None, **kwargs):
        """
        Запись начала выполнения задачи.
        
        Args:
            task_id: ID задачи (Celery task ID или ParsingTask ID)
            task_name: Название задачи
            **kwargs: Дополнительные параметры (source, parsing_mode и т.д.)
        """
        self._task_start_times[task_id] = time.time()
        self._task_metrics[task_id] = {
            'task_name': task_name,
            'start_time': datetime.now().isoformat(),
            **kwargs
        }
        
        self.logger.debug(f"Задача {task_id} начата: {task_name}")
        self._db_upsert_taskrun_start(task_id, task_name, kwargs)
    
    def record_task_success(self, task_id: str, result: Optional[Any] = None, **kwargs):
        """
        Запись успешного завершения задачи.
        
        Args:
            task_id: ID задачи
            result: Результат выполнения задачи
            **kwargs: Дополнительные метрики
        """
        if task_id not in self._task_start_times:
            self.logger.warning(f"Задача {task_id} не была зарегистрирована")
            return
        
        duration = time.time() - self._task_start_times[task_id]
        
        self._task_metrics[task_id].update({
            'status': 'success',
            'duration': duration,
            'end_time': datetime.now().isoformat(),
            'result': str(result) if result else None,
            **kwargs
        })
        
        self.logger.info(f"Задача {task_id} завершена успешно за {duration:.2f} сек")
        self._db_update_taskrun_finish(task_id, status='success', duration=duration)
        
        # Очистка
        del self._task_start_times[task_id]
    
    def record_task_failure(self, task_id: str, exception: Exception, **kwargs):
        """
        Запись ошибки выполнения задачи.
        
        Args:
            task_id: ID задачи
            exception: Исключение
            **kwargs: Дополнительные метрики
        """
        if task_id not in self._task_start_times:
            self.logger.warning(f"Задача {task_id} не была зарегистрирована")
            return
        
        duration = time.time() - self._task_start_times[task_id]
        
        self._task_metrics[task_id].update({
            'status': 'failure',
            'duration': duration,
            'end_time': datetime.now().isoformat(),
            'error': str(exception),
            'error_type': type(exception).__name__,
            **kwargs
        })
        
        self.logger.error(f"Задача {task_id} завершена с ошибкой за {duration:.2f} сек: {exception}")
        self._db_update_taskrun_finish(
            task_id,
            status='failure',
            duration=duration,
            error_type=type(exception).__name__,
            error_message=str(exception),
        )
        
        # Очистка
        del self._task_start_times[task_id]
    
    def record_item_processed(self, task_id: str, success: bool = True, **kwargs):
        """
        Запись обработки одного item.
        
        Args:
            task_id: ID задачи
            success: Успешность обработки
            **kwargs: Дополнительные метрики
        """
        if success:
            self._items_success[task_id] += 1
        else:
            self._items_failed[task_id] += 1
        
        self._items_processed[task_id] += 1
        # В DB фиксируем только агрегаты — processed/errors
        if success:
            self.increment_counter(task_id, 'processed', 1)
        else:
            self.increment_counter(task_id, 'processed', 1)
            self.increment_counter(task_id, 'errors', 1)
    
    def get_metrics(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Получение метрик задачи или всех задач.
        
        Args:
            task_id: ID задачи (если None, возвращаются метрики всех задач)
        
        Returns:
            dict: Метрики задачи(й)
        """
        if task_id:
            metrics = self._task_metrics.get(task_id, {})
            metrics.update({
                'items_processed': self._items_processed.get(task_id, 0),
                'items_success': self._items_success.get(task_id, 0),
                'items_failed': self._items_failed.get(task_id, 0),
            })
            return metrics
        
        # Метрики всех задач
        all_metrics = {}
        for tid in self._task_metrics.keys():
            all_metrics[tid] = self.get_metrics(tid)
        
        return all_metrics
    
    def clear_metrics(self, task_id: Optional[str] = None):
        """
        Очистка метрик задачи или всех задач.
        
        Args:
            task_id: ID задачи (если None, очищаются все метрики)
        """
        if task_id:
            self._task_metrics.pop(task_id, None)
            self._items_processed.pop(task_id, None)
            self._items_success.pop(task_id, None)
            self._items_failed.pop(task_id, None)
            self._task_start_times.pop(task_id, None)
        else:
            self._task_metrics.clear()
            self._items_processed.clear()
            self._items_success.clear()
            self._items_failed.clear()
            self._task_start_times.clear()


# Глобальный экземпляр метрик
_default_metrics = TaskMetrics()


def get_task_metrics(source: Optional[str] = None) -> TaskMetrics:
    """
    Получение экземпляра метрик для источника.
    
    Args:
        source: Источник парсинга
    
    Returns:
        TaskMetrics: Экземпляр метрик
    """
    if source:
        return TaskMetrics(source)
    return _default_metrics
