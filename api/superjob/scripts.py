"""
Обратная совместимость: все функции парсинга доступны из этого модуля.

Реальная логика находится в parsers/ (sj_parser.py, discovery.py).
Этот файл сохраняет старый API для management commands и внешних импортов.
"""

import logging
from typing import Dict, Optional, Any

from .parsers.sj_parser import (
    SuperJobParser as SuperJobAPIClient,
    SuperJobParser,
    EMPLOYMENT_TYPE_MAP,
    EXPERIENCE_MAP,
    PLACE_OF_WORK_MAP,
)
from .parsers.discovery import (
    parse_vacancies_by_text,
    parse_all_vacancies,
    parse_vacancies_by_catalogue,
    parse_vacancies_by_catalogues,
    get_catalogues_list,
    get_vacancy_details,
    bulk_save_vacancies,
)
from .parsers.utils import ParsingMetrics
from .models import SuperJobVacancy

logger = logging.getLogger(__name__)


def parse_vacancy_data(vacancy_data: Dict[str, Any]) -> Dict[str, Any]:
    """Обратная совместимость: делегирует в SuperJobParser.parse_vacancy_data."""
    return SuperJobParser.parse_vacancy_data(vacancy_data)


def save_vacancy_to_db(vacancy_data: Dict[str, Any]) -> Optional[SuperJobVacancy]:
    """Обратная совместимость: поштучное сохранение вакансии."""
    try:
        superjob_id = vacancy_data.get('superjob_id')
        if not superjob_id:
            logger.warning("Отсутствует superjob_id для вакансии")
            return None

        existing = SuperJobVacancy.objects.filter(superjob_id=superjob_id).first()

        if existing:
            if existing.has_changes(vacancy_data):
                existing.create_version(vacancy_data, auto_save=False)
                for field, value in vacancy_data.items():
                    if hasattr(existing, field):
                        setattr(existing, field, value)
                existing.save()
            return existing

        vacancy = SuperJobVacancy.objects.create(**vacancy_data)
        return vacancy

    except Exception as e:
        logger.error("Ошибка при сохранении вакансии: %s", e)
        return None


__all__ = [
    'SuperJobAPIClient',
    'SuperJobParser',
    'EMPLOYMENT_TYPE_MAP',
    'EXPERIENCE_MAP',
    'PLACE_OF_WORK_MAP',
    'parse_vacancies_by_text',
    'parse_all_vacancies',
    'parse_vacancies_by_catalogue',
    'parse_vacancies_by_catalogues',
    'get_catalogues_list',
    'get_vacancy_details',
    'bulk_save_vacancies',
    'parse_vacancy_data',
    'save_vacancy_to_db',
    'ParsingMetrics',
]
