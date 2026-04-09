"""
Централизованная обработка ошибок для задач парсинга.

Содержит:
- ErrorHandler: базовый обработчик ошибок
- SourceSpecificErrorHandler: специфичные обработчики для каждого источника
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Type
from enum import Enum

logger = logging.getLogger('celery.module.vacancies_parser.error_handling')


class ErrorType(Enum):
    """Типы ошибок при парсинге"""
    NETWORK = 'network'
    BLOCKED = 'blocked'
    VALIDATION = 'validation'
    PARSING = 'parsing'
    RATE_LIMIT = 'rate_limit'
    TIMEOUT = 'timeout'
    UNKNOWN = 'unknown'


# Импортируем классы ошибок из parsers.base
# Используем ленивый импорт для избежания циклических зависимостей
# Классы будут импортированы при первом использовании в методах

# Базовый класс для ParsingError (может быть переопределен при импорте из parsers.base)
class ParserError(Exception):
    """Базовая ошибка парсера (fallback, если импорт из parsers.base не удался)"""
    pass


class ParsingError(ParserError):
    """Расширенное исключение для ошибок парсинга с типизацией"""
    def __init__(self, message: str, error_type: ErrorType = ErrorType.UNKNOWN, retryable: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


class RateLimitError(ParsingError):
    """Ошибки превышения лимита запросов"""
    def __init__(self, message: str):
        super().__init__(message, ErrorType.RATE_LIMIT, retryable=True)


class TimeoutError(ParsingError):
    """Ошибки таймаута"""
    def __init__(self, message: str):
        super().__init__(message, ErrorType.TIMEOUT, retryable=True)


class ErrorHandler(ABC):
    """
    Базовый обработчик ошибок для задач парсинга.
    
    Предоставляет единый интерфейс для классификации ошибок,
    определения стратегии retry и вычисления задержек.
    """
    
    def __init__(self, source: str):
        """
        Args:
            source: Источник парсинга (headhunter, habr_career, superjob)
        """
        self.source = source
        self.logger = logging.getLogger(f'celery.module.vacancies_parser.error_handling.{source}')
    
    def classify_error(self, exception: Exception) -> ErrorType:
        """
        Классификация типа ошибки.
        
        Args:
            exception: Исключение для классификации
        
        Returns:
            ErrorType: Тип ошибки
        """
        # Если это уже ParsingError, используем его тип
        if isinstance(exception, ParsingError):
            return exception.error_type
        
        # Ленивый импорт классов ошибок из parsers.base для избежания циклических зависимостей
        try:
            from .parsers.base import BlockedError as ParserBlockedError
            from .parsers.base import NetworkError as ParserNetworkError
            from .parsers.base import ValidationError as ParserValidationError
            
            if isinstance(exception, ParserBlockedError):
                return ErrorType.BLOCKED
            elif isinstance(exception, ParserNetworkError):
                return ErrorType.NETWORK
            elif isinstance(exception, ParserValidationError):
                return ErrorType.VALIDATION
        except (ImportError, ModuleNotFoundError):
            # Если импорт не удался, используем fallback классы
            pass
        
        # Классификация по типу исключения
        error_str = str(exception).lower()
        error_type_str = type(exception).__name__.lower()
        
        # Сетевые ошибки
        if isinstance(exception, (ConnectionError, TimeoutError)) or 'connection' in error_str or 'timeout' in error_str:
            return ErrorType.NETWORK
        
        # Rate limit ошибки
        if 'rate limit' in error_str or '429' in error_str or 'too many' in error_str:
            return ErrorType.RATE_LIMIT
        
        # Блокировки
        if 'blocked' in error_str or '403' in error_str or 'forbidden' in error_str:
            return ErrorType.BLOCKED
        
        # Валидация
        if isinstance(exception, (ValueError, TypeError, KeyError)) or 'validation' in error_str:
            return ErrorType.VALIDATION
        
        # Таймауты
        if 'timeout' in error_type_str or 'timeout' in error_str:
            return ErrorType.TIMEOUT
        
        return ErrorType.UNKNOWN
    
    def should_retry(self, exception: Exception, retries: int, max_retries: int) -> bool:
        """
        Определение необходимости retry.
        
        Args:
            exception: Исключение
            retries: Текущее количество попыток
            max_retries: Максимальное количество попыток
        
        Returns:
            bool: True если нужно делать retry
        """
        if retries >= max_retries:
            return False
        
        # Если это ParsingError, используем его флаг retryable
        if isinstance(exception, ParsingError):
            return exception.retryable
        
        # Ленивый импорт классов ошибок из parsers.base
        try:
            from .parsers.base import BlockedError as ParserBlockedError
            from .parsers.base import ValidationError as ParserValidationError
            
            # Блокировки не требуют retry
            if isinstance(exception, ParserBlockedError):
                return False
            
            # Валидация не требует retry
            if isinstance(exception, ParserValidationError):
                return False
        except (ImportError, ModuleNotFoundError):
            pass
        
        error_type = self.classify_error(exception)
        
        # Retry для сетевых ошибок, rate limit и таймаутов
        return error_type in [ErrorType.NETWORK, ErrorType.RATE_LIMIT, ErrorType.TIMEOUT]
    
    def get_retry_delay(self, exception: Exception, retries: int, base_delay: int = 60) -> int:
        """
        Вычисление задержки перед retry.
        
        Использует экспоненциальную задержку с базовой задержкой.
        
        Args:
            exception: Исключение
            retries: Текущее количество попыток
            base_delay: Базовая задержка в секундах
        
        Returns:
            int: Задержка в секундах
        """
        error_type = self.classify_error(exception)
        
        # Для rate limit используем увеличенную задержку
        if error_type == ErrorType.RATE_LIMIT:
            multiplier = 2.0
        else:
            multiplier = 1.0
        
        # Экспоненциальная задержка: base_delay * multiplier * (2 ^ retries)
        delay = int(base_delay * multiplier * (2 ** retries))
        
        # Максимальная задержка 20 минут
        max_delay = 1200
        return min(delay, max_delay)
    
    def handle_error(self, exception: Exception, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Обработка ошибки с логированием и созданием контекста.
        
        Args:
            exception: Исключение
            context: Дополнительный контекст (task_id, item_id и т.д.)
        
        Returns:
            dict: Информация об ошибке для логирования
        """
        error_type = self.classify_error(exception)
        context = context or {}
        
        error_info = {
            'error_type': error_type.value,
            'error_message': str(exception),
            'exception_type': type(exception).__name__,
            'source': self.source,
            **context
        }
        
        # Логирование в зависимости от типа ошибки
        if error_type == ErrorType.BLOCKED:
            self.logger.warning(f"Блокировка источника: {exception}", extra=error_info)
        elif error_type == ErrorType.RATE_LIMIT:
            self.logger.warning(f"Превышен лимит запросов: {exception}", extra=error_info)
        elif error_type == ErrorType.NETWORK:
            self.logger.warning(f"Сетевая ошибка: {exception}", extra=error_info)
        else:
            self.logger.error(f"Ошибка парсинга: {exception}", exc_info=True, extra=error_info)
        
        return error_info


class HeadHunterErrorHandler(ErrorHandler):
    """
    Специфичный обработчик ошибок для HeadHunter.
    
    Учитывает особенности API HH:
    - Rate limits (429)
    - Блокировки по IP (403)
    - Специфичные коды ошибок API
    """
    
    def __init__(self):
        super().__init__('headhunter')
    
    def classify_error(self, exception: Exception) -> ErrorType:
        """Переопределение классификации для специфичных ошибок HH"""
        error_str = str(exception).lower()
        
        # Специфичные ошибки HH API
        if '429' in error_str or 'rate limit' in error_str:
            return ErrorType.RATE_LIMIT
        
        if '403' in error_str or 'forbidden' in error_str or 'blocked' in error_str:
            return ErrorType.BLOCKED
        
        if '400' in error_str or 'bad request' in error_str:
            return ErrorType.VALIDATION
        
        # Вызываем базовую классификацию
        return super().classify_error(exception)
    
    def should_retry(self, exception: Exception, retries: int, max_retries: int) -> bool:
        """Переопределение логики retry для HH"""
        error_type = self.classify_error(exception)
        
        # Для блокировок не делаем retry
        if error_type == ErrorType.BLOCKED:
            return False
        
        # Для rate limit делаем retry с увеличенной задержкой
        if error_type == ErrorType.RATE_LIMIT:
            return retries < max_retries
        
        return super().should_retry(exception, retries, max_retries)
    
    def get_retry_delay(self, exception: Exception, retries: int, base_delay: int = 60) -> int:
        """Переопределение задержки для HH"""
        error_type = self.classify_error(exception)
        
        # Для rate limit используем более длинную задержку
        if error_type == ErrorType.RATE_LIMIT:
            # Минимум 2 минуты для rate limit
            delay = max(120, base_delay * 2 * (2 ** retries))
            return min(delay, 1800)  # Максимум 30 минут
        
        return super().get_retry_delay(exception, retries, base_delay)


class HabrCareerErrorHandler(ErrorHandler):
    """Специфичный обработчик ошибок для Habr Career"""
    
    def __init__(self):
        super().__init__('habr_career')
    
    def get_retry_delay(self, exception: Exception, retries: int, base_delay: int = 90) -> int:
        """Habr Career требует более длинные задержки"""
        return super().get_retry_delay(exception, retries, base_delay)


class SuperJobErrorHandler(ErrorHandler):
    """Специфичный обработчик ошибок для SuperJob"""
    
    def __init__(self):
        super().__init__('superjob')
    
    def get_retry_delay(self, exception: Exception, retries: int, base_delay: int = 120) -> int:
        """SuperJob требует еще более длинные задержки"""
        return super().get_retry_delay(exception, retries, base_delay)


def get_error_handler(source: str) -> ErrorHandler:
    """
    Фабрика для получения обработчика ошибок по источнику.
    
    Args:
        source: Источник парсинга
    
    Returns:
        ErrorHandler: Обработчик ошибок
    """
    handlers = {
        'headhunter': HeadHunterErrorHandler,
        'habr_career': HabrCareerErrorHandler,
        'superjob': SuperJobErrorHandler,
    }
    
    handler_class = handlers.get(source, ErrorHandler)
    return handler_class(source)
