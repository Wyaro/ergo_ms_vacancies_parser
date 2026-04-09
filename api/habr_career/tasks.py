import logging
from typing import Optional, List, Dict, Any

from celery import shared_task, group

from .scripts import (
    parse_habr_vacancies,
    parse_habr_archived_vacancies,
    parse_habr_all_vacancies,
)
from modules.vacancies_parser.api.core.parsing_config import get_habr_chunk_size

logger = logging.getLogger('modules.vacancies_parser.habr_career')


@shared_task(bind=True)
def parse_habr_vacancies_task(self, pages=5, delay=1.0, get_details=True, search_text=None):
    """
    Celery задача для парсинга вакансий с Хабр Карьеры

    Args:
        pages (int): Количество страниц для парсинга
        delay (float): Задержка между запросами в секундах
        get_details (bool): Получать ли детальную информацию о вакансиях
        search_text (str | None): Текстовый фильтр поиска вакансий
    """
    self.update_state(
        state='PROGRESS',
        meta={
            'current': 0,
            'total': pages,
            'status': 'Начинаем парсинг вакансий с Хабр Карьеры...'
        }
    )

    result = parse_habr_vacancies(
        pages=pages,
        delay=delay,
        get_details=get_details,
        search_text=search_text,
    )

    return {
        'status': 'SUCCESS',
        'result': result,
        'message': (
            f'Парсинг завершен. Обработано: {result["total"]}, '
            f'Новых: {result["new"]}, Обновлено: {result["updated"]}, '
            f'Ошибок: {result["errors"]}'
        ),
    }


@shared_task(bind=True)
def parse_habr_archived_vacancies_task(self, pages=5, delay=1.0, search_text=None):
    """
    Celery задача для парсинга архивных вакансий с Хабр Карьеры

    Args:
        pages (int): Количество страниц для парсинга
        delay (float): Задержка между запросами в секундах
        search_text (str | None): Текстовый фильтр поиска вакансий
    """
    self.update_state(
        state='PROGRESS',
        meta={
            'current': 0,
            'total': pages,
            'status': 'Начинаем парсинг архивных вакансий с Хабр Карьеры...'
        }
    )

    result = parse_habr_archived_vacancies(
        pages=pages,
        delay=delay,
        search_text=search_text,
    )

    return {
        'status': 'SUCCESS',
        'result': result,
        'message': (
            f'Парсинг архивных вакансий завершен. Обработано: {result["total"]}, '
            f'Новых: {result["new"]}, Обновлено: {result["updated"]}, '
            f'Ошибок: {result["errors"]}'
        ),
    }


@shared_task(bind=True)
def parse_habr_all_vacancies_task(
    self, pages=5, delay=1.0, get_details=True, search_text=None
):
    """
    Celery задача для парсинга всех вакансий (активных и архивных) с Хабр Карьеры

    Args:
        pages (int): Количество страниц для парсинга
        delay (float): Задержка между запросами в секундах
        get_details (bool): Получать ли детальную информацию о вакансиях
        search_text (str | None): Текстовый фильтр поиска вакансий
    """
    self.update_state(
        state='PROGRESS',
        meta={
            'current': 0,
            'total': pages * 2,
            'status': 'Начинаем парсинг всех вакансий с Хабр Карьеры...'
        }
    )

    result = parse_habr_all_vacancies(
        pages=pages,
        delay=delay,
        get_details=get_details,
        search_text=search_text,
    )

    return {
        'status': 'SUCCESS',
        'result': result,
        'message': (
            f'Парсинг всех вакансий завершен. '
            f'Всего обработано: {result["total"]["total"]}, '
            f'Новых: {result["total"]["new"]}, '
            f'Обновлено: {result["total"]["updated"]}, '
            f'Ошибок: {result["total"]["errors"]}'
        ),
    }


@shared_task(bind=True, soft_time_limit=1500, time_limit=1800)
def parse_habr_vacancies_chunk_task(
    self,
    queries: List[str],
    pages_per_query: int = 3,
    delay: float = 1.2,
    get_details: bool = False,
) -> Dict[str, Any]:
    """Парсинг одного чанка запросов Habr (для параллельного режима по технологиям)."""
    if not queries:
        return {
            'status': 'SUCCESS',
            'result': {'total_processed': 0, 'new': 0, 'updated': 0, 'errors': 0},
            'message': 'Пустой чанк',
        }
    total_processed = 0
    total_new = 0
    total_updated = 0
    total_errors = 0
    for search_text in queries:
        try:
            result = parse_habr_vacancies(
                pages=pages_per_query,
                delay=delay,
                get_details=get_details,
                search_text=search_text,
            )
            total_processed += result['total']
            total_new += result['new']
            total_updated += result['updated']
            total_errors += result['errors']
        except Exception as e:
            logger.exception("Ошибка парсинга Habr по запросу %s: %s", search_text, e)
            total_errors += 1
    return {
        'status': 'SUCCESS',
        'result': {
            'total_processed': total_processed,
            'new': total_new,
            'updated': total_updated,
            'errors': total_errors,
        },
        'message': (
            f'Чанк: обработано {total_processed}, новых {total_new}, '
            f'обновлено {total_updated}, ошибок {total_errors}'
        ),
    }


@shared_task(bind=True, soft_time_limit=120, time_limit=180)
def parse_habr_vacancies_by_technologies_task(
    self,
    pages_per_query: int = 3,
    delay: float = 1.2,
    get_details: bool = False,
    tech_limit: Optional[int] = None,
    use_aliases: bool = True,
    max_queries: int = 200,
    chunk_size: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Парсинг Habr Career по списку технологий из competence_core (с алиасами).
    Для каждой технологии/алиаса вызывается поиск с search_text=название.
    При chunk_size > 0 запросы разбиваются на чанки и выполняются параллельно (group).
    """
    try:
        from modules.vacancies_parser.api.core.utils.technology_search_generator import (
            TechnologySearchGenerator,
        )
    except Exception as e:
        logger.warning("competence_core недоступен для Habr by_technologies: %s", e)
        return {
            'status': 'FAILURE',
            'error': str(e),
            'message': 'Не удалось загрузить технологии из competence_core',
        }
    generator = TechnologySearchGenerator()
    generator.load_technologies(limit=tech_limit, include_aliases=use_aliases)
    queries = generator.generate_search_queries(use_aliases=use_aliases, max_queries=max_queries)
    if not queries:
        return {
            'status': 'FAILURE',
            'error': 'Нет запросов',
            'message': 'Список технологий из competence_core пуст',
        }

    effective_chunk_size = chunk_size if chunk_size is not None else get_habr_chunk_size()
    if effective_chunk_size and effective_chunk_size > 0:
        chunks = [
            queries[i:i + effective_chunk_size]
            for i in range(0, len(queries), effective_chunk_size)
        ]
        logger.info(
            "Парсинг Habr по технологиям (параллельно): %d запросов, %d чанков",
            len(queries), len(chunks),
        )
        self.update_state(
            state='PROGRESS',
            meta={'status': f'Запуск {len(chunks)} чанков', 'chunks': len(chunks)},
        )
        job = group(
            parse_habr_vacancies_chunk_task.s(
                queries=chunk,
                pages_per_query=pages_per_query,
                delay=delay,
                get_details=get_details,
            )
            for chunk in chunks
        )
        result_group = job.apply_async()
        results = result_group.get(timeout=7200)
        if results is None:
            results = []
        total_processed = 0
        total_new = 0
        total_updated = 0
        total_errors = 0
        for r in results:
            if r and isinstance(r, dict) and r.get('result'):
                res = r['result']
                total_processed += res.get('total_processed', 0)
                total_new += res.get('new', 0)
                total_updated += res.get('updated', 0)
                total_errors += res.get('errors', 0)
        return {
            'status': 'SUCCESS',
            'result': {
                'queries_count': len(queries),
                'total_processed': total_processed,
                'new': total_new,
                'updated': total_updated,
                'errors': total_errors,
            },
            'message': (
                f'Парсинг по технологиям (чанки) завершен. Запросов: {len(queries)}, '
                f'Обработано: {total_processed}, Новых: {total_new}, '
                f'Обновлено: {total_updated}, Ошибок: {total_errors}'
            ),
        }

    total_processed = 0
    total_new = 0
    total_updated = 0
    total_errors = 0
    for i, search_text in enumerate(queries, 1):
        self.update_state(
            state='PROGRESS',
            meta={
                'current': i,
                'total': len(queries),
                'status': f'Парсинг по запросу: {search_text}',
            },
        )
        try:
            result = parse_habr_vacancies(
                pages=pages_per_query,
                delay=delay,
                get_details=get_details,
                search_text=search_text,
            )
            total_processed += result['total']
            total_new += result['new']
            total_updated += result['updated']
            total_errors += result['errors']
        except Exception as e:
            logger.exception("Ошибка парсинга Habr по запросу %s: %s", search_text, e)
            total_errors += 1
    return {
        'status': 'SUCCESS',
        'result': {
            'queries_count': len(queries),
            'total_processed': total_processed,
            'new': total_new,
            'updated': total_updated,
            'errors': total_errors,
        },
        'message': (
            f'Парсинг по технологиям завершен. Запросов: {len(queries)}, '
            f'Обработано: {total_processed}, Новых: {total_new}, '
            f'Обновлено: {total_updated}, Ошибок: {total_errors}'
        ),
    }
