"""
Модуль задач парсинга HeadHunter.

Содержит декомпозированные задачи по категориям:
- base: базовые задачи и вспомогательные функции
- technology_parsing: парсинг по технологиям
- role_parsing: парсинг по профессиональным ролям
- batch_processing: батчевая обработка вакансий
- status_checking: проверка статусов вакансий
- time_period_parsing: парсинг по временным периодам
"""

# Импортируем все задачи для обратной совместимости
from .base import (
    parse_hh_vacancies_task,
    parse_single_vacancy_task,
    _load_target_category_id,
    _skill_map_installed,
)
from .technology_parsing import (
    parse_hh_segment_by_technologies,
    parse_vacancies_by_technologies,
    parse_vacancies_by_category,
    _split_segment_and_parse,
)
from .role_parsing import (
    parse_vacancies_by_professional_roles,
    get_professional_roles_task,
    parse_single_role_batch,
    finalize_role_fragments,
    _filter_roles_for_parsing,
    _build_parallel_role_signatures,
    _aggregate_role_results,
    _parse_roles_batch,
    _fetch_vacancy_details_batch_async,
)
from .batch_processing import (
    parse_vacancies_batch_task,
    _save_vacancies_batch_celery,
    _create_vacancy_from_api_data,
    _update_vacancy_from_api_data,
    _merge_snippet_into_details,
)
from .status_checking import (
    check_vacancies_status_task,
    update_vacancy_details_task,
)
from .time_period_parsing import (
    parse_vacancies_by_time_period_parallel,
    parse_single_query_segment_task,
    _collect_segments_generator_celery,
    _collect_segments_celery,
    _get_vacancies_count_celery,
    _process_segments_parallel_celery,
    _process_single_segment_celery,
    _fetch_segment_vacancies_data_celery,
)
from .daily_parsing import (
    parse_daily_vacancies_yesterday_today,
)
from .monthly_parsing import (
    parse_monthly_vacancies_recursive,
    _parse_single_day_recursive,
)

__all__ = [
    # Base
    'parse_hh_vacancies_task',
    'parse_single_vacancy_task',
    '_load_target_category_id',
    '_skill_map_installed',
    # Technology parsing
    'parse_hh_segment_by_technologies',
    'parse_vacancies_by_technologies',
    'parse_vacancies_by_category',
    '_split_segment_and_parse',
    # Role parsing
    'parse_vacancies_by_professional_roles',
    'get_professional_roles_task',
    'parse_single_role_batch',
    'finalize_role_fragments',
    '_filter_roles_for_parsing',
    '_build_parallel_role_signatures',
    '_aggregate_role_results',
    '_parse_roles_batch',
    '_fetch_vacancy_details_batch_async',
    # Batch processing
    'parse_vacancies_batch_task',
    '_save_vacancies_batch_celery',
    '_create_vacancy_from_api_data',
    '_update_vacancy_from_api_data',
    '_merge_snippet_into_details',
    # Status checking
    'check_vacancies_status_task',
    'update_vacancy_details_task',
    # Time period parsing
    'parse_vacancies_by_time_period_parallel',
    'parse_single_query_segment_task',
    '_collect_segments_generator_celery',
    '_collect_segments_celery',
    '_get_vacancies_count_celery',
    '_process_segments_parallel_celery',
    '_process_single_segment_celery',
    '_fetch_segment_vacancies_data_celery',
    # Daily parsing
    'parse_daily_vacancies_yesterday_today',
    # Monthly parsing
    'parse_monthly_vacancies_recursive',
    '_parse_single_day_recursive',
]
