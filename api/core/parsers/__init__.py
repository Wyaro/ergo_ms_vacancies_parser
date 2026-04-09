"""
Парсеры вакансий для различных источников и режимов.

Содержит:
- ParserInterface: базовый интерфейс для всех парсеров
- API парсеры: HeadHunterAPIParser, HabrCareerAPIParser, SuperJobAPIParser
- HTML парсеры: HeadHunterHTMLParser, HabrCareerHTMLParser, SuperJobHTMLParser
- ParserFactory: фабрика для создания парсеров
"""

from .base import ParserInterface, ParserFactory
from .api_parsers import (
    HeadHunterAPIParser,
    HabrCareerAPIParser,
    SuperJobAPIParser
)
from .html_parsers import (
    HeadHunterHTMLParser,
    HabrCareerHTMLParser,
    SuperJobHTMLParser
)

__all__ = [
    'ParserInterface',
    'ParserFactory',
    'HeadHunterAPIParser',
    'HabrCareerAPIParser',
    'SuperJobAPIParser',
    'HeadHunterHTMLParser',
    'HabrCareerHTMLParser',
    'SuperJobHTMLParser',
]
