"""
Базовые задачи парсинга SuperJob: текстовый поиск, универсальный, конфиг, детали, chunk.
"""

import logging
from typing import Dict, Any, Optional, List

from celery import shared_task, group

from ..parsers.discovery import (
    parse_vacancies_by_text,
    parse_all_vacancies,
    run_queries_list,
    get_vacancy_details,
)
from .utils import run_task_with_error_handling
from modules.vacancies_parser.api.core.parsing_config import get_superjob_chunk_size

logger = logging.getLogger('modules.vacancies_parser.superjob')

TASK_PREFIX = 'modules.vacancies_parser.api.superjob.tasks'


def _get_superjob_search_queries(
    tech_limit: Optional[int],
    use_aliases: bool,
    max_queries: int,
) -> List[str]:
    try:
        from modules.vacancies_parser.api.core.utils.technology_search_generator import (
            TechnologySearchGenerator,
        )
        generator = TechnologySearchGenerator()
        generator.load_technologies(limit=tech_limit, include_aliases=use_aliases)
        return generator.generate_search_queries(
            use_aliases=use_aliases,
            max_queries=max_queries,
        )
    except Exception as e:
        logger.warning("Не удалось загрузить запросы из competence_core: %s", e)
        from ..parsers.discovery import FALLBACK_SEARCH_QUERIES
        return list(FALLBACK_SEARCH_QUERIES)


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_vacancies_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=3300,
    time_limit=3600,
)
def parse_superjob_vacancies_task(
    self,
    text: str = None,
    town: str = None,
    experience=None,
    employment=None,
    schedule=None,
    max_pages: int = 5,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Парсинг вакансий SuperJob по текстовому запросу."""

    def body():
        logger.info("Парсинг SuperJob по запросу: '%s'", text)
        self.update_state(
            state='PROGRESS',
            meta={'current': 0, 'total': max_pages, 'status': f'Парсинг: {text}'},
        )
        result = parse_vacancies_by_text(
            text=text, town=town, experience=experience,
            employment=employment, schedule=schedule,
            max_pages=max_pages, delay=delay, api_key=api_key,
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Парсинг завершен. Найдено: {result["total_vacancies"]}, '
                f'Сохранено: {result["saved_vacancies"]}, '
                f'Обновлено: {result["updated_vacancies"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_vacancies_chunk_task',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=1500,
    time_limit=1800,
)
def parse_superjob_vacancies_chunk_task(
    self,
    queries: List[str],
    max_pages_per_query: int = 3,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Парсинг одного чанка запросов SuperJob (для параллельного режима)."""

    def body():
        if not queries:
            return {
                'status': 'SUCCESS',
                'result': {
                    'total_queries': 0, 'total_vacancies': 0, 'total_saved': 0,
                    'total_updated': 0, 'total_errors': 0, 'queries_processed': 0, 'queries_failed': 0,
                },
                'message': 'Пустой чанк',
            }
        logger.info("Чанк SuperJob: %d запросов", len(queries))
        total_results = {
            'total_queries': len(queries),
            'total_vacancies': 0, 'total_saved': 0, 'total_updated': 0,
            'total_errors': 0, 'queries_processed': 0, 'queries_failed': 0,
        }
        result = run_queries_list(
            queries, max_pages_per_query, delay, api_key, total_results,
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Чанк: запросов {result["queries_processed"]}, '
                f'вакансий {result["total_vacancies"]}, сохранено {result["total_saved"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)


@shared_task(
    name=f'{TASK_PREFIX}.parse_all_superjob_vacancies_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=120,
    time_limit=180,
)
def parse_all_superjob_vacancies_task(
    self,
    max_pages_per_query: int = 3,
    delay: float = 1.0,
    api_key: str = None,
    tech_limit: Optional[int] = None,
    use_aliases: bool = True,
    max_queries: int = 400,
    chunk_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Универсальный парсинг всех вакансий SuperJob (технологии + алиасы из competence_core)."""

    def body():
        effective_chunk_size = chunk_size if chunk_size is not None else get_superjob_chunk_size()
        search_queries = _get_superjob_search_queries(tech_limit, use_aliases, max_queries)
        if not search_queries:
            from ..parsers.discovery import FALLBACK_SEARCH_QUERIES
            search_queries = list(FALLBACK_SEARCH_QUERIES)

        if effective_chunk_size and effective_chunk_size > 0:
            chunks = [
                search_queries[i:i + effective_chunk_size]
                for i in range(0, len(search_queries), effective_chunk_size)
            ]
            logger.info(
                "Универсальный парсинг SuperJob (параллельно): %d запросов, %d чанков",
                len(search_queries), len(chunks),
            )
            self.update_state(
                state='PROGRESS',
                meta={'status': f'Запуск {len(chunks)} чанков', 'chunks': len(chunks)},
            )
            job = group(
                parse_superjob_vacancies_chunk_task.s(
                    queries=chunk,
                    max_pages_per_query=max_pages_per_query,
                    delay=delay,
                    api_key=api_key,
                )
                for chunk in chunks
            )
            result_group = job.apply_async()
            results = result_group.get(timeout=7200)
            if results is None:
                results = []
            aggregated = {
                'total_queries': len(search_queries),
                'total_vacancies': 0, 'total_saved': 0, 'total_updated': 0,
                'total_errors': 0, 'queries_processed': 0, 'queries_failed': 0,
            }
            for r in results:
                if r and isinstance(r, dict) and r.get('result'):
                    res = r['result']
                    aggregated['total_vacancies'] += res.get('total_vacancies', 0)
                    aggregated['total_saved'] += res.get('total_saved', 0)
                    aggregated['total_updated'] += res.get('total_updated', 0)
                    aggregated['total_errors'] += res.get('total_errors', 0)
                    aggregated['queries_processed'] += res.get('queries_processed', 0)
                    aggregated['queries_failed'] += res.get('queries_failed', 0)
            return {
                'status': 'SUCCESS',
                'result': aggregated,
                'message': (
                    f'Универсальный парсинг (чанки) завершен. '
                    f'Запросов: {aggregated["queries_processed"]}, '
                    f'Вакансий: {aggregated["total_vacancies"]}, '
                    f'Сохранено: {aggregated["total_saved"]}'
                ),
            }

        logger.info("Универсальный парсинг SuperJob запущен (алиасы=%s)", use_aliases)
        self.update_state(
            state='PROGRESS',
            meta={'current': 0, 'total': len(search_queries), 'status': 'Универсальный парсинг вакансий'},
        )
        result = parse_all_vacancies(
            max_pages_per_query=max_pages_per_query,
            delay=delay,
            api_key=api_key,
            use_competence_core=True,
            tech_limit=tech_limit,
            use_aliases=use_aliases,
            max_queries=max_queries,
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Универсальный парсинг завершен. '
                f'Запросов: {result["queries_processed"]}, '
                f'Вакансий: {result["total_vacancies"]}, '
                f'Сохранено: {result["total_saved"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)


@shared_task(
    name=f'{TASK_PREFIX}.get_superjob_vacancy_details_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def get_superjob_vacancy_details_task(
    self,
    vacancy_id: str,
    api_key: str = None,
) -> Dict[str, Any]:
    """Получение детальной информации о вакансии SuperJob."""

    def body():
        logger.info("Получение деталей вакансии SuperJob: %s", vacancy_id)
        self.update_state(
            state='PROGRESS',
            meta={'current': 0, 'total': 1, 'status': f'Получаем детали: {vacancy_id}'},
        )
        result = get_vacancy_details(vacancy_id, api_key)
        if result:
            return {
                'status': 'SUCCESS',
                'result': result,
                'message': f'Детали вакансии: {result.get("profession", vacancy_id)}',
            }
        return {
            'status': 'FAILURE',
            'error': 'Вакансия не найдена или недоступна',
            'message': f'Не удалось получить вакансию: {vacancy_id}',
        }

    return run_task_with_error_handling(
        self, body, task_logger=logger,
        error_context={'vacancy_id': vacancy_id},
    )


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_vacancies_by_config_task',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=5100,
    time_limit=5400,
)
def parse_superjob_vacancies_by_config_task(
    self,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Парсинг вакансий SuperJob по переданной конфигурации."""

    def body():
        text = config.get('text')
        logger.info("Парсинг SuperJob по конфигурации")
        self.update_state(
            state='PROGRESS',
            meta={'current': 0, 'total': config.get('max_pages', 5), 'status': f'Парсинг: {text}'},
        )
        result = parse_vacancies_by_text(
            text=text,
            town=config.get('town'),
            experience=config.get('experience'),
            employment=config.get('employment'),
            schedule=config.get('schedule'),
            max_pages=config.get('max_pages', 5),
            delay=config.get('delay', 1.0),
            api_key=config.get('api_key'),
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Парсинг завершен. Найдено: {result["total_vacancies"]}, '
                f'Сохранено: {result["saved_vacancies"]}, '
                f'Обновлено: {result["updated_vacancies"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)
