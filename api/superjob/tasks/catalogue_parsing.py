"""
Задачи парсинга SuperJob по каталогам.

Поддерживает:
- Последовательный парсинг (parse_superjob_by_catalogues_task)
- Параллельный парсинг через chord (parse_superjob_catalogues_chord_task)
- Парсинг одного каталога (подзадача для chord)
"""

import logging
import os
from typing import Dict, List, Any

from celery import shared_task, chord

from ..parsers.discovery import (
    parse_vacancies_by_catalogue,
    parse_vacancies_by_catalogues,
)
from ..parsers.sj_parser import SuperJobParser
from .utils import run_task_with_error_handling, get_superjob_metrics

logger = logging.getLogger('modules.vacancies_parser.superjob')

TASK_PREFIX = 'modules.vacancies_parser.api.superjob.tasks'


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_by_catalogues_task',
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=14100,
    time_limit=14400,
)
def parse_superjob_by_catalogues_task(
    self,
    catalogue_ids: List[int] = None,
    max_pages_per_catalogue: int = 10,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Последовательный парсинг вакансий SuperJob по каталогам."""
    api_key = api_key or os.environ.get('SUPERJOB_API_KEY')

    def body():
        mode = f"{len(catalogue_ids)} выбранных" if catalogue_ids else "всех"
        logger.info("Парсинг SuperJob по каталогам (%s)", mode)
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 0,
                'total': len(catalogue_ids) if catalogue_ids else 0,
                'status': f'Парсинг по каталогам ({mode})',
            },
        )
        result = parse_vacancies_by_catalogues(
            catalogue_ids=catalogue_ids,
            max_pages_per_catalogue=max_pages_per_catalogue,
            delay=delay, api_key=api_key,
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Парсинг по каталогам завершен. '
                f'Каталогов: {result["catalogues_processed"]}/{result["total_catalogues"]}, '
                f'Вакансий: {result["total_vacancies"]}, '
                f'Сохранено: {result["total_saved"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_single_catalogue_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=3600,
    time_limit=3900,
)
def parse_superjob_single_catalogue_task(
    self,
    catalogue_id: int,
    catalogue_title: str = '',
    max_pages: int = 10,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Подзадача: парсинг одного каталога (для chord)."""
    api_key = api_key or os.environ.get('SUPERJOB_API_KEY')

    def body():
        logger.info("Парсинг каталога '%s' (id=%d)", catalogue_title, catalogue_id)
        return parse_vacancies_by_catalogue(
            catalogue_id=catalogue_id,
            catalogue_title=catalogue_title,
            max_pages=max_pages,
            delay=delay,
            api_key=api_key,
        )

    return run_task_with_error_handling(
        self, body, task_logger=logger,
        error_context={'catalogue_id': catalogue_id},
    )


@shared_task(
    name=f'{TASK_PREFIX}._finalize_catalogues_chord',
)
def _finalize_catalogues_chord(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Callback для chord: агрегация результатов подзадач."""
    total = {
        'total_catalogues': len(results),
        'catalogues_processed': 0,
        'catalogues_failed': 0,
        'total_vacancies': 0,
        'total_saved': 0,
        'total_updated': 0,
        'total_errors': 0,
    }

    for r in results:
        if r.get('error'):
            total['catalogues_failed'] += 1
            total['total_errors'] += 1
        else:
            total['catalogues_processed'] += 1
        total['total_vacancies'] += r.get('total_vacancies', 0)
        total['total_saved'] += r.get('saved_vacancies', 0)
        total['total_updated'] += r.get('updated_vacancies', 0)
        total['total_errors'] += r.get('errors', 0)

    logger.info("Chord парсинг каталогов завершен: %s", total)

    return {
        'status': 'SUCCESS',
        'result': total,
        'message': (
            f'Chord-парсинг завершен. '
            f'Каталогов: {total["catalogues_processed"]}/{total["total_catalogues"]}, '
            f'Вакансий: {total["total_vacancies"]}, '
            f'Сохранено: {total["total_saved"]}'
        ),
    }


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_catalogues_chord_task',
    bind=True,
    max_retries=1,
    default_retry_delay=120,
    soft_time_limit=14100,
    time_limit=14400,
)
def parse_superjob_catalogues_chord_task(
    self,
    catalogue_ids: List[int] = None,
    max_pages_per_catalogue: int = 10,
    delay: float = 1.0,
    api_key: str = None,
) -> Dict[str, Any]:
    """Параллельный парсинг каталогов через Celery chord."""
    api_key = api_key or os.environ.get('SUPERJOB_API_KEY')
    task_id = self.request.id
    metrics = get_superjob_metrics()
    metrics.record_task_start(task_id, task_name=self.name)

    try:
        if catalogue_ids:
            catalogues = [{'key': cid, 'title': f'Каталог {cid}'} for cid in catalogue_ids]
        else:
            parser = SuperJobParser(api_key=api_key)
            raw = parser.get_catalogues()
            if not raw:
                return {
                    'status': 'FAILURE',
                    'error': 'Не удалось получить каталоги',
                    'message': 'Не удалось получить список каталогов SuperJob',
                }
            catalogues = [{'key': c['key'], 'title': c.get('title', '')} for c in raw]

        logger.info("Chord-парсинг: %d каталогов параллельно", len(catalogues))

        header = [
            parse_superjob_single_catalogue_task.s(
                catalogue_id=cat['key'],
                catalogue_title=cat['title'],
                max_pages=max_pages_per_catalogue,
                delay=delay,
                api_key=api_key,
            )
            for cat in catalogues
        ]

        callback = _finalize_catalogues_chord.s()
        chord_result = chord(header)(callback)

        metrics.record_task_success(task_id)

        return {
            'status': 'CHORD_DISPATCHED',
            'chord_id': str(chord_result.id),
            'subtasks_count': len(catalogues),
            'message': f'Запущено {len(catalogues)} подзадач через chord',
        }

    except Exception as exc:
        logger.error("Ошибка запуска chord: %s", exc, exc_info=True)
        metrics.record_task_failure(task_id, exc)
        return {'status': 'FAILURE', 'error': str(exc), 'message': f'Ошибка: {exc}'}
