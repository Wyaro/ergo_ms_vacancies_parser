"""
Базовые классы и утилиты для задач парсинга вакансий.

Предоставляет:
- Базовые классы задач с общей логикой retry и error handling
- Вспомогательные функции для работы с задачами
"""

import logging
from typing import Dict, Any, Optional, Callable

from ..error_handling import ErrorHandler, get_error_handler
from ..metrics import TaskMetrics, get_task_metrics

logger = logging.getLogger('celery.module.vacancies_parser.tasks.base')


def get_source_from_task_name(task_name: str) -> str:
    """
    Определение источника из имени задачи.
    
    Args:
        task_name: Имя задачи
    
    Returns:
        str: Источник парсинга
    """
    task_name_lower = task_name.lower()
    
    if 'headhunter' in task_name_lower or 'hh' in task_name_lower:
        return 'headhunter'
    elif 'habr' in task_name_lower:
        return 'habr_career'
    elif 'superjob' in task_name_lower or 'sj' in task_name_lower:
        return 'superjob'
    
    return 'unknown'


def get_error_handler_for_task(task_name: str) -> ErrorHandler:
    """
    Получение обработчика ошибок для задачи по имени.
    
    Args:
        task_name: Имя задачи
    
    Returns:
        ErrorHandler: Обработчик ошибок
    """
    source = get_source_from_task_name(task_name)
    return get_error_handler(source)


def get_metrics_for_task(task_name: str) -> TaskMetrics:
    """
    Получение метрик для задачи по имени.
    
    Args:
        task_name: Имя задачи
    
    Returns:
        TaskMetrics: Метрики задачи
    """
    source = get_source_from_task_name(task_name)
    return get_task_metrics(source)


def create_task_with_error_handling(
    task_func: Callable,
    task_name: str,
    max_retries: int = 3,
    default_retry_delay: int = 60,
    bind: bool = True
):
    """
    Создание задачи Celery с обработкой ошибок и метрик.
    
    Args:
        task_func: Функция задачи
        task_name: Имя задачи
        max_retries: Максимальное количество попыток
        default_retry_delay: Задержка по умолчанию
        bind: Использовать bind=True для доступа к self
    
    Returns:
        Декорированная функция задачи
    """
    from celery import shared_task
    
    error_handler = get_error_handler_for_task(task_name)
    metrics = get_metrics_for_task(task_name)
    
    @shared_task(
        name=task_name,
        bind=bind,
        max_retries=max_retries,
        default_retry_delay=default_retry_delay
    )
    def wrapped_task(self, *args, **kwargs):
        """Обертка задачи с обработкой ошибок и метрик"""
        task_id = self.request.id
        
        try:
            # Запись начала задачи
            metrics.record_task_start(task_id, task_name=task_name, **kwargs)
            logger.debug(f"Задача {task_id} начата: {task_name}")
            
            # Выполнение задачи
            if bind:
                result = task_func(self, *args, **kwargs)
            else:
                result = task_func(*args, **kwargs)
            
            # Запись успешного завершения
            metrics.record_task_success(task_id, result, **kwargs)
            logger.info(f"Задача {task_id} завершена успешно")
            
            return result
            
        except Exception as exc:
            # Проверка необходимости retry
            retries = self.request.retries if bind else 0
            
            if error_handler.should_retry(exc, retries, max_retries):
                # Вычисление задержки
                delay = error_handler.get_retry_delay(
                    exc,
                    retries,
                    base_delay=default_retry_delay
                )
                
                logger.info(
                    f"Повторная попытка задачи {task_id} через {delay} сек "
                    f"(попытка {retries + 1}/{max_retries}): {exc}"
                )
                
                # Retry
                if bind:
                    raise self.retry(exc=exc, countdown=delay)
                else:
                    # Для задач без bind нужно использовать другой подход
                    raise exc
            
            # Запись ошибки
            metrics.record_task_failure(task_id, exc, **kwargs)
            
            # Обработка ошибки
            error_info = error_handler.handle_error(exc, {
                'task_id': task_id,
                'task_name': task_name,
                'args': str(args),
                'kwargs': str(kwargs),
            })
            
            logger.error(
                f"Задача {task_id} завершена с ошибкой: {exc}",
                exc_info=True,
                extra=error_info
            )
            
            raise
    
    # Копируем атрибуты оригинальной функции
    wrapped_task.__name__ = task_func.__name__
    wrapped_task.__doc__ = task_func.__doc__
    wrapped_task.__module__ = task_func.__module__
    
    return wrapped_task


class BaseParsingTaskMixin:
    """
    Mixin класс для добавления функциональности обработки ошибок и метрик к задачам.
    
    Используйте этот mixin в задачах для получения единой логики обработки ошибок.
    """
    
    def get_error_handler(self) -> ErrorHandler:
        """Получение обработчика ошибок для задачи"""
        task_name = getattr(self, 'name', '') or ''
        return get_error_handler_for_task(task_name)
    
    def get_metrics(self) -> TaskMetrics:
        """Получение метрик для задачи"""
        task_name = getattr(self, 'name', '') or ''
        return get_metrics_for_task(task_name)
    
    def handle_task_error(self, exception: Exception, context: Optional[Dict[str, Any]] = None):
        """
        Обработка ошибки задачи.
        
        Args:
            exception: Исключение
            context: Дополнительный контекст
        """
        task_id = getattr(self.request, 'id', 'unknown')
        error_handler = self.get_error_handler()
        
        error_info = error_handler.handle_error(exception, {
            'task_id': task_id,
            'task_name': getattr(self, 'name', ''),
            **(context or {})
        })
        
        return error_info
