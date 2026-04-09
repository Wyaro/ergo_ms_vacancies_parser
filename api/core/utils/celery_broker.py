"""
Утилиты для работы с Celery брокером.

Содержит:
- Проверка доступности Celery брокера
- Обработка ошибок подключения
"""

import logging
from typing import Optional, Tuple
from kombu.exceptions import OperationalError

logger = logging.getLogger('celery.module.vacancies_parser.broker')


class BrokerUnavailableError(Exception):
    """Исключение при недоступности Celery брокера"""
    pass


def check_broker_available(celery_app) -> Tuple[bool, Optional[str]]:
    """
    Проверяет доступность Celery брокера.
    
    Args:
        celery_app: Экземпляр Celery приложения
    
    Returns:
        Tuple[bool, Optional[str]]: (доступен ли брокер, сообщение об ошибке если нет)
    """
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        if inspect is None:
            return False, "Не удалось создать inspect объект"
        
        stats = inspect.stats()
        if stats is None:
            return False, "Брокер недоступен (stats вернул None)"
        
        return True, None
    except (OperationalError, ConnectionError, OSError) as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.debug(f"Ошибка проверки брокера: {error_type}: {error_msg}")
        return False, f"{error_type}: {error_msg}"
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.warning(f"Неожиданная ошибка при проверке брокера: {error_type}: {error_msg}")
        return False, f"{error_type}: {error_msg}"


def is_broker_error(exception: Exception) -> bool:
    """
    Проверяет, является ли исключение ошибкой подключения к брокеру.
    
    Args:
        exception: Исключение для проверки
    
    Returns:
        bool: True если это ошибка подключения к брокеру
    """
    broker_error_types = (
        ConnectionRefusedError,
        ConnectionError,
        OperationalError,
        OSError,
    )
    
    if isinstance(exception, broker_error_types):
        return True
    
    error_str = str(exception).lower()
    broker_error_keywords = [
        'connection refused',
        'connection error',
        'operational error',
        'broker',
        'amqp',
        'rabbitmq',
        'redis',
        'database',
    ]
    
    return any(keyword in error_str for keyword in broker_error_keywords)
