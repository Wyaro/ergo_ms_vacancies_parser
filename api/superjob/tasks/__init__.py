"""
Celery задачи для парсинга SuperJob.

Обратная совместимость: все задачи доступны через этот __init__.
"""

from .base import (
    parse_superjob_vacancies_task,
    parse_superjob_vacancies_chunk_task,
    parse_all_superjob_vacancies_task,
    get_superjob_vacancy_details_task,
    parse_superjob_vacancies_by_config_task,
)
from .catalogue_parsing import (
    parse_superjob_by_catalogues_task,
    parse_superjob_single_catalogue_task,
    parse_superjob_catalogues_chord_task,
)
from .batch_processing import parse_superjob_batch_task
from .status_checking import check_superjob_vacancies_status_task

__all__ = [
    'parse_superjob_vacancies_task',
    'parse_superjob_vacancies_chunk_task',
    'parse_all_superjob_vacancies_task',
    'get_superjob_vacancy_details_task',
    'parse_superjob_vacancies_by_config_task',
    'parse_superjob_by_catalogues_task',
    'parse_superjob_single_catalogue_task',
    'parse_superjob_catalogues_chord_task',
    'parse_superjob_batch_task',
    'check_superjob_vacancies_status_task',
]
