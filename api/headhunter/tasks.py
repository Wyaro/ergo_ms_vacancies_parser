"""
Модуль задач парсинга HeadHunter.

Этот файл обеспечивает обратную совместимость.
Все задачи теперь находятся в подмодулях в директории tasks/.
"""

# Импортируем все задачи из подмодулей для обратной совместимости
# Используем явный импорт из папки tasks/ чтобы избежать конфликта с именем файла
from .tasks import (  # noqa: F401
    # Base tasks
    parse_hh_vacancies_task,
    parse_single_vacancy_task,
    # Technology parsing
    parse_hh_segment_by_technologies,
    parse_vacancies_by_technologies,
    parse_vacancies_by_category,
    # Role parsing
    parse_vacancies_by_professional_roles,
    get_professional_roles_task,
    parse_single_role_batch,
    finalize_role_fragments,
    # Batch processing
    parse_vacancies_batch_task,
    # Status checking
    check_vacancies_status_task,
    update_vacancy_details_task,
    # Time period parsing
    parse_vacancies_by_time_period_parallel,
    parse_single_query_segment_task,
)
