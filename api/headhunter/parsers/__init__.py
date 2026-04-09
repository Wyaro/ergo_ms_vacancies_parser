"""
Парсеры для работы с HeadHunter API.

Модули:
- utils: вспомогательные классы (ProxyRotator, UserAgentRotator, и т.д.)
- hh_parser: основной класс HeadHunterParser
- discovery: функции для обнаружения и парсинга вакансий
"""

# Импортируем все для обратной совместимости
from .utils import (
    ProxyRotator,
    UserAgentRotator,
    RequestJitter,
    ParsingMetrics,
    IPBlockingTracker,
)
from .hh_parser import HeadHunterParser
from .discovery import (
    parse_vacancies_by_text,
    parse_all_vacancies,
    _parse_area,
    _parse_role,
)

__all__ = [
    # Utils
    'ProxyRotator',
    'UserAgentRotator',
    'RequestJitter',
    'ParsingMetrics',
    'IPBlockingTracker',
    # Parser
    'HeadHunterParser',
    # Discovery
    'parse_vacancies_by_text',
    'parse_all_vacancies',
    '_parse_area',
    '_parse_role',
]
