"""
Утилита для безопасного запуска Celery задач с fallback на синхронное выполнение.

Содержит:
- safe_task_run: безопасный запуск задач с автоматическим fallback
- Обработка ошибок подключения к брокеру
"""

import logging
from typing import Any, Callable, Dict, Optional
from kombu.exceptions import OperationalError

from .celery_broker import is_broker_error, BrokerUnavailableError

logger = logging.getLogger('celery.module.vacancies_parser.task_runner')


def safe_task_run(
    task_func: Callable,
    params: Dict[str, Any],
    prefer_async: bool = True,
    fallback_to_sync: bool = True
) -> Any:
    """
    Безопасный запуск задачи с fallback на синхронное выполнение при недоступности брокера.
    
    Args:
        task_func: Функция задачи Celery (с декоратором @shared_task)
        params: Параметры для передачи в задачу
        prefer_async: Предпочитать асинхронное выполнение
        fallback_to_sync: Разрешить fallback на синхронное выполнение при ошибке брокера
    
    Returns:
        Any: Результат выполнения задачи (AsyncResult для async, результат для sync)
    
    Raises:
        BrokerUnavailableError: Если брокер недоступен и fallback_to_sync=False
    """
    if not prefer_async:
        logger.debug("Синхронный запуск задачи (prefer_async=False)")
        return task_func(**params)

    try:
        logger.debug("Постановка задачи в очередь Celery")
        return task_func(**params)
    except (ConnectionRefusedError, OperationalError, ConnectionError, OSError) as e:
        if is_broker_error(e):
            if fallback_to_sync:
                logger.warning(
                    f"Ошибка подключения к брокеру: {type(e).__name__}: {e}, "
                    "переключение на синхронное выполнение"
                )
                return task_func(**params)
            else:
                raise BrokerUnavailableError(
                    f"Ошибка подключения к Celery брокеру: {type(e).__name__}: {e}. "
                    "Запустите Celery worker: ergoms start-worker"
                ) from e
        else:
            raise
    
    except Exception as e:
        if is_broker_error(e):
            if fallback_to_sync:
                logger.warning(
                    f"Ошибка брокера ({type(e).__name__}: {e}), "
                    "переключение на синхронное выполнение"
                )
                return task_func(**params)
            else:
                raise BrokerUnavailableError(
                    f"Ошибка Celery брокера: {type(e).__name__}: {e}. "
                    "Запустите Celery worker: ergoms start-worker"
                ) from e
        else:
            raise
