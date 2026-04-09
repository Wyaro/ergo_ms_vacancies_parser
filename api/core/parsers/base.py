"""
Базовые классы для парсеров вакансий.

Содержит:
- ParserInterface: абстрактный интерфейс парсера
- ParserFactory: фабрика для создания парсеров
- BaseParser: базовая реализация с общей логикой
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger('celery.module.vacancies_parser')


class ParserInterface(ABC):
    """
    Базовый интерфейс для всех парсеров вакансий.
    
    Определяет контракт, который должны реализовать все парсеры
    независимо от источника (HeadHunter, Habr, SuperJob) и
    режима (API, HTML).
    """
    
    @abstractmethod
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Обнаружение элементов для парсинга (discovery фаза).
        
        Args:
            config: Конфигурация парсинга из ParsingTask.config
                   Может содержать: area, pages, technologies, roles и т.д.
        
        Returns:
            List[Dict]: Список элементов для парсинга.
                       Каждый элемент: {'source_item_id': '123', 'url': 'https://...'}
        
        Raises:
            ParserError: При ошибках обнаружения элементов
        """
        pass
    
    @abstractmethod
    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        """
        Парсинг одного элемента (extraction фаза).
        
        Args:
            item_id: ID элемента на источнике (hh_id, habr_id и т.д.)
            url: URL элемента
        
        Returns:
            Dict: Нормализованные данные вакансии в формате NormalizedVacancy
        
        Raises:
            ParserError: При ошибках парсинга
            BlockedError: При блокировке источником
            NetworkError: При сетевых ошибках
        """
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Валидация конфигурации парсинга.
        
        Args:
            config: Конфигурация для проверки
        
        Returns:
            bool: True если конфигурация валидна
        
        Raises:
            ValueError: При невалидной конфигурации
        """
        pass


class BaseParser(ParserInterface):
    """
    Базовая реализация парсера с общей логикой.
    
    Предоставляет:
    - Управление прокси
    - Ротацию user-agent
    - Retry логику
    - Логирование
    """
    
    def __init__(
        self,
        source: str,
        parsing_mode: str,
        proxy_config: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Args:
            source: Источник (headhunter, habr_career, superjob)
            parsing_mode: Режим парсинга (api, html)
            proxy_config: Конфигурация прокси (optional)
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество повторов
        """
        self.source = source
        self.parsing_mode = parsing_mode
        self.proxy_config = proxy_config or {}
        self.timeout = timeout
        self.max_retries = max_retries
        
        self.logger = logging.getLogger(f'celery.module.vacancies_parser.{source}')
    
    def _normalize_vacancy_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Нормализация сырых данных вакансии в унифицированный формат.
        
        Преобразует данные из формата источника в формат NormalizedVacancy.
        
        Args:
            raw_data: Сырые данные от источника
        
        Returns:
            Dict: Нормализованные данные
        """
        # Переопределяется в конкретных парсерах
        raise NotImplementedError
    
    def _extract_salary(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечение информации о зарплате"""
        # Переопределяется в конкретных парсерах
        raise NotImplementedError
    
    def _extract_location(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечение информации о локации"""
        # Переопределяется в конкретных парсерах
        raise NotImplementedError
    
    def _extract_skills(self, raw_data: Dict[str, Any]) -> List[str]:
        """Извлечение навыков"""
        # Переопределяется в конкретных парсерах
        raise NotImplementedError


class ParserFactory:
    """
    Фабрика для создания парсеров.
    
    Централизованное создание парсеров по источнику и режиму.
    """
    
    _parsers = {}
    
    @classmethod
    def register(cls, source: str, parsing_mode: str, parser_class):
        """
        Регистрация парсера.
        
        Args:
            source: Источник (headhunter, habr_career, superjob)
            parsing_mode: Режим (api, html)
            parser_class: Класс парсера
        """
        key = (source, parsing_mode)
        
        # Проверка на дублирование регистрации
        if key in cls._parsers:
            existing_class = cls._parsers[key]
            if existing_class == parser_class:
                return
            # Модули намеренно переопределяют базовые парсеры ядра — ожидаемое поведение
            logger.debug(
                f"Парсер {source}/{parsing_mode}: {existing_class.__name__} заменён на {parser_class.__name__}"
            )
        
        cls._parsers[key] = parser_class
        logger.debug(f"Зарегистрирован парсер {source}/{parsing_mode}: {parser_class.__name__}")
    
    @classmethod
    def create_parser(
        cls,
        source: str,
        parsing_mode: str,
        **kwargs
    ) -> ParserInterface:
        """
        Создание парсера.
        
        Args:
            source: Источник
            parsing_mode: Режим парсинга
            **kwargs: Дополнительные параметры для конструктора парсера
        
        Returns:
            ParserInterface: Экземпляр парсера
        
        Raises:
            ValueError: Если парсер не зарегистрирован
        """
        key = (source, parsing_mode)
        parser_class = cls._parsers.get(key)
        
        if not parser_class:
            available = ', '.join([f"{s}/{m}" for s, m in cls._parsers.keys()])
            raise ValueError(
                f"Парсер для {source}/{parsing_mode} не найден. "
                f"Доступные: {available}"
            )
        
        logger.debug(f"Создан парсер {source}/{parsing_mode}")
        return parser_class(source=source, parsing_mode=parsing_mode, **kwargs)
    
    @classmethod
    def get_parser(cls, source: str, parsing_mode: str):
        """
        Получить класс парсера (без создания экземпляра).
        
        Args:
            source: Источник
            parsing_mode: Режим парсинга
        
        Returns:
            Класс парсера или None если не найден
        """
        key = (source, parsing_mode)
        return cls._parsers.get(key)
    
    @classmethod
    def get_available_parsers(cls) -> List[Dict[str, str]]:
        """
        Список доступных парсеров.
        
        Returns:
            List[Dict]: [{'source': 'headhunter', 'mode': 'api'}, ...]
        """
        return [
            {'source': source, 'mode': mode}
            for source, mode in cls._parsers.keys()
        ]


class ParserError(Exception):
    """Базовая ошибка парсера"""
    pass


class BlockedError(ParserError):
    """Блокировка источником (captcha, rate limit и т.д.)"""
    pass


class NetworkError(ParserError):
    """Сетевая ошибка"""
    pass


class ValidationError(ParserError):
    """Ошибка валидации данных"""
    pass
