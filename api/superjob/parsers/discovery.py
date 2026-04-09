"""
Высокоуровневые функции парсинга SuperJob.

Включает bulk-операции БД (bulk_create/bulk_update) вместо поштучного
сохранения и поддержку метрик.
"""

import logging
from typing import Dict, List, Optional, Any

from django.utils import timezone

from ..models import SuperJobVacancy
from .sj_parser import SuperJobParser
from .utils import RateLimiter, ParsingMetrics

logger = logging.getLogger('modules.vacancies_parser.superjob.discovery')

BATCH_SIZE = 100


def bulk_save_vacancies(parsed_list: List[Dict[str, Any]], metrics: ParsingMetrics) -> Dict[str, int]:
    """
    Пакетное сохранение вакансий через bulk_create / bulk_update.

    Предзагружает существующие записи для проверки дубликатов,
    создаёт новые через bulk_create и обновляет изменённые через bulk_update.
    """
    if not parsed_list:
        return {'saved': 0, 'updated': 0, 'errors': 0}

    sj_ids = [p['superjob_id'] for p in parsed_list if p.get('superjob_id')]
    existing_map = {}
    for vac in SuperJobVacancy.objects.filter(superjob_id__in=sj_ids):
        existing_map[vac.superjob_id] = vac

    to_create = []
    to_update = []
    saved = 0
    updated = 0
    errors = 0

    for parsed in parsed_list:
        try:
            sj_id = parsed.get('superjob_id')
            if not sj_id:
                errors += 1
                continue

            existing = existing_map.get(sj_id)
            if existing:
                if existing.has_changes(parsed):
                    existing.create_version(parsed, auto_save=False)
                    for field_name, value in parsed.items():
                        if hasattr(existing, field_name):
                            setattr(existing, field_name, value)
                    to_update.append(existing)
                    updated += 1
            else:
                to_create.append(SuperJobVacancy(**parsed))
                saved += 1
        except Exception as e:
            logger.error("Ошибка при подготовке вакансии к сохранению: %s", e)
            errors += 1

    if to_create:
        SuperJobVacancy.objects.bulk_create(to_create, batch_size=BATCH_SIZE, ignore_conflicts=True)

    if to_update:
        update_fields = [
            'title', 'company_name', 'salary_from', 'salary_to', 'salary_currency',
            'salary_gross', 'city', 'address', 'description', 'requirements',
            'responsibilities', 'employment_type', 'experience_level', 'schedule_type',
            'skills', 'key_skills', 'url', 'company_url', 'professional_role',
            'employer_id', 'employer_name', 'employer_trusted', 'premium',
            'published_at', 'current_version', 'updated_at',
        ]
        SuperJobVacancy.objects.bulk_update(to_update, update_fields, batch_size=BATCH_SIZE)

    metrics.vacancies_saved += saved
    metrics.vacancies_updated += updated
    metrics.errors += errors

    return {'saved': saved, 'updated': updated, 'errors': errors}


def parse_vacancies_by_text(
    text: str = None,
    town: str = None,
    experience: int = None,
    employment: int = None,
    schedule: int = None,
    max_pages: int = 5,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Парсинг вакансий по текстовому запросу с bulk-сохранением."""
    metrics = ParsingMetrics()
    rate_limiter = RateLimiter()
    parser = SuperJobParser(api_key=api_key, rate_limiter=rate_limiter, metrics=metrics)

    logger.info("Парсинг вакансий по запросу: '%s'", text)

    total_vacancies = 0
    saved_total = 0
    updated_total = 0
    errors_total = 0

    for page in range(max_pages):
        try:
            search_result = parser.search_vacancies(
                keyword=text, town=town, experience=experience,
                type_of_work=employment, place_of_work=schedule,
                page=page, count=100,
            )

            vacancies = search_result.get('objects', [])
            if not vacancies:
                break

            total_vacancies += len(vacancies)
            metrics.vacancies_found += len(vacancies)

            parsed_batch = []
            for vac_data in vacancies:
                try:
                    parsed_batch.append(parser.parse_vacancy_data(vac_data))
                except Exception as e:
                    logger.error("Ошибка парсинга вакансии: %s", e)
                    errors_total += 1

            result = bulk_save_vacancies(parsed_batch, metrics)
            saved_total += result['saved']
            updated_total += result['updated']
            errors_total += result['errors']

            if not search_result.get('more', False):
                break

        except Exception as e:
            logger.error("Ошибка на странице %d: %s", page + 1, e)
            errors_total += 1

    metrics.log_summary()

    return {
        'total_vacancies': total_vacancies,
        'saved_vacancies': saved_total,
        'updated_vacancies': updated_total,
        'errors': errors_total,
        'search_query': text,
        'metrics': metrics.to_dict(),
    }


FALLBACK_SEARCH_QUERIES = [
    'Python', 'JavaScript', 'Java', 'C++', 'C#', 'PHP', 'Go',
    'React', 'Vue', 'Angular', 'Node.js', 'Django', 'Flask',
    'DevOps', 'Docker', 'Kubernetes', 'AWS',
    'Data Science', 'Machine Learning',
    'Frontend', 'Backend', 'Full Stack',
    'iOS', 'Android', 'Mobile',
    'QA', 'Automation', 'Selenium',
    'Project Manager', 'Product Manager', 'Scrum',
    'UI/UX', 'Web Design',
    'HR', 'Recruiter',
    'Аналитик', 'Бухгалтер', 'Юрист',
    'Менеджер по продажам', 'Маркетолог',
    'Инженер', 'Механик', 'Электрик',
    'Водитель', 'Логистика',
]


def parse_all_vacancies(
    max_pages_per_query: int = 3,
    delay: float = 1.0,
    api_key: str = None,
    use_competence_core: bool = True,
    tech_limit: Optional[int] = None,
    use_aliases: bool = True,
    max_queries: Optional[int] = 400,
) -> Dict[str, Any]:
    """Универсальный парсинг вакансий. Запросы из competence_core (все технологии + алиасы) или fallback."""
    search_queries: List[str] = []
    if use_competence_core:
        try:
            from modules.vacancies_parser.api.core.utils.technology_search_generator import (
                TechnologySearchGenerator,
            )
            generator = TechnologySearchGenerator()
            generator.load_technologies(limit=tech_limit, include_aliases=use_aliases)
            search_queries = generator.generate_search_queries(
                use_aliases=use_aliases,
                max_queries=max_queries,
            )
            if search_queries:
                logger.info(
                    "Запросы загружены из competence_core: %d (алиасы=%s)",
                    len(search_queries),
                    use_aliases,
                )
        except Exception as e:
            logger.warning("Не удалось загрузить запросы из competence_core: %s, используем fallback", e)
    if not search_queries:
        search_queries = list(FALLBACK_SEARCH_QUERIES)

    total_results = {
        'total_queries': len(search_queries),
        'total_vacancies': 0, 'total_saved': 0, 'total_updated': 0,
        'total_errors': 0, 'queries_processed': 0, 'queries_failed': 0,
    }

    logger.info("Универсальный парсинг: %d запросов", len(search_queries))
    return run_queries_list(
        search_queries, max_pages_per_query, delay, api_key, total_results,
    )


def run_queries_list(
    search_queries: List[str],
    max_pages_per_query: int,
    delay: float,
    api_key: str,
    total_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Выполняет парсинг по списку текстовых запросов.
    Используется и в последовательном режиме, и в chunk-задачах.
    """
    if total_results is None:
        total_results = {
            'total_queries': len(search_queries),
            'total_vacancies': 0, 'total_saved': 0, 'total_updated': 0,
            'total_errors': 0, 'queries_processed': 0, 'queries_failed': 0,
        }
    for i, query in enumerate(search_queries, 1):
        try:
            logger.info("Запрос %d/%d: '%s'", i, len(search_queries), query)
            result = parse_vacancies_by_text(
                text=query, max_pages=max_pages_per_query, delay=delay, api_key=api_key,
            )
            total_results['total_vacancies'] += result['total_vacancies']
            total_results['total_saved'] += result['saved_vacancies']
            total_results['total_updated'] += result['updated_vacancies']
            total_results['total_errors'] += result['errors']
            total_results['queries_processed'] += 1
        except Exception as e:
            logger.error("Ошибка при обработке запроса '%s': %s", query, e)
            total_results['queries_failed'] += 1
            total_results['total_errors'] += 1
    logger.info("Парсинг списка запросов завершен: %s", total_results)
    return total_results


def parse_vacancies_by_catalogue(
    catalogue_id: int, catalogue_title: str = '',
    max_pages: int = 10, delay: float = 1.0, api_key: str = None,
) -> Dict[str, Any]:
    """Парсинг вакансий по конкретному каталогу с bulk-сохранением."""
    metrics = ParsingMetrics()
    rate_limiter = RateLimiter()
    parser = SuperJobParser(api_key=api_key, rate_limiter=rate_limiter, metrics=metrics)

    total_vacancies = 0
    saved_total = 0
    updated_total = 0
    errors_total = 0

    logger.info("Парсинг каталога '%s' (id=%d)", catalogue_title, catalogue_id)

    for page in range(max_pages):
        try:
            search_result = parser.search_vacancies(
                catalogues=str(catalogue_id), page=page, count=100,
            )

            vacancies = search_result.get('objects', [])
            if not vacancies:
                break

            total_vacancies += len(vacancies)
            metrics.vacancies_found += len(vacancies)

            parsed_batch = []
            for vac_data in vacancies:
                try:
                    parsed_batch.append(parser.parse_vacancy_data(vac_data))
                except Exception as e:
                    logger.error("Ошибка парсинга вакансии: %s", e)
                    errors_total += 1

            result = bulk_save_vacancies(parsed_batch, metrics)
            saved_total += result['saved']
            updated_total += result['updated']
            errors_total += result['errors']

            if not search_result.get('more', False):
                break

        except Exception as e:
            logger.error("Ошибка на странице %d каталога '%s': %s", page + 1, catalogue_title, e)
            errors_total += 1

    logger.info(
        "Каталог '%s': найдено=%d, сохранено=%d, обновлено=%d",
        catalogue_title, total_vacancies, saved_total, updated_total,
    )

    return {
        'catalogue_id': catalogue_id,
        'catalogue_title': catalogue_title,
        'total_vacancies': total_vacancies,
        'saved_vacancies': saved_total,
        'updated_vacancies': updated_total,
        'errors': errors_total,
    }


def parse_vacancies_by_catalogues(
    catalogue_ids: List[int] = None,
    max_pages_per_catalogue: int = 10,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Парсинг вакансий по каталогам (отраслям) SuperJob."""
    parser = SuperJobParser(api_key=api_key)

    if catalogue_ids:
        catalogues = [{'key': cid, 'title': f'Каталог {cid}'} for cid in catalogue_ids]
    else:
        raw_catalogues = parser.get_catalogues()
        if not raw_catalogues:
            logger.error("Не удалось получить список каталогов SuperJob")
            return {
                'total_catalogues': 0, 'catalogues_processed': 0,
                'total_vacancies': 0, 'total_saved': 0,
                'total_updated': 0, 'total_errors': 1, 'catalogues_failed': 1,
            }
        catalogues = [{'key': c['key'], 'title': c.get('title', '')} for c in raw_catalogues]

    total_results = {
        'total_catalogues': len(catalogues), 'catalogues_processed': 0,
        'catalogues_failed': 0, 'total_vacancies': 0,
        'total_saved': 0, 'total_updated': 0, 'total_errors': 0,
    }

    logger.info("Парсинг по каталогам: %d каталогов", len(catalogues))

    for i, cat in enumerate(catalogues, 1):
        try:
            logger.info("Каталог %d/%d: '%s' (id=%s)", i, len(catalogues), cat['title'], cat['key'])
            result = parse_vacancies_by_catalogue(
                catalogue_id=cat['key'], catalogue_title=cat['title'],
                max_pages=max_pages_per_catalogue, delay=delay, api_key=api_key,
            )
            total_results['total_vacancies'] += result['total_vacancies']
            total_results['total_saved'] += result['saved_vacancies']
            total_results['total_updated'] += result['updated_vacancies']
            total_results['total_errors'] += result['errors']
            total_results['catalogues_processed'] += 1
        except Exception as e:
            logger.error("Ошибка при обработке каталога '%s': %s", cat['title'], e)
            total_results['catalogues_failed'] += 1
            total_results['total_errors'] += 1

    logger.info("Парсинг по каталогам завершен: %s", total_results)
    return total_results


def get_catalogues_list(api_key: str = None) -> List[Dict[str, Any]]:
    """Получение списка каталогов SuperJob (для UI)."""
    parser = SuperJobParser(api_key=api_key)
    raw = parser.get_catalogues()

    result = []
    for cat in raw:
        positions = [
            {'key': p['key'], 'title': p.get('title', '')}
            for p in cat.get('positions', [])
        ]
        result.append({
            'key': cat['key'],
            'title': cat.get('title', ''),
            'positions': positions,
        })
    return result


def get_vacancy_details(vacancy_id: str, api_key: str = None) -> Optional[Dict[str, Any]]:
    """Получение детальной информации о конкретной вакансии."""
    parser = SuperJobParser(api_key=api_key)
    return parser.get_vacancy_details(vacancy_id)
