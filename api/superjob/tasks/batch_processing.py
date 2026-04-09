"""
Батчевая обработка вакансий SuperJob с использованием AsyncSuperJobParser.

Параллельные HTTP-запросы через asyncio.run() внутри Celery задачи,
пакетное сохранение через bulk_create / bulk_update.
"""

import asyncio
import logging
from typing import Dict, List, Any

from celery import shared_task

from ..async_parser import AsyncSuperJobParser, AsyncParsingConfig
from ..parsers.sj_parser import SuperJobParser
from ..parsers.discovery import bulk_save_vacancies
from ..parsers.utils import ParsingMetrics
from .utils import run_task_with_error_handling

logger = logging.getLogger('modules.vacancies_parser.superjob.batch')

TASK_PREFIX = 'modules.vacancies_parser.api.superjob.tasks'


async def _fetch_batch(
    vacancy_ids: List[str],
    api_key: str = None,
    batch_size: int = 20,
) -> List[Dict[str, Any]]:
    """Асинхронно получить детали нескольких вакансий."""
    config = AsyncParsingConfig(
        max_concurrent_requests=batch_size,
        request_delay=0.1,
    )

    results = []
    async with AsyncSuperJobParser(api_key=api_key, config=config) as parser:
        batch_results = await parser.get_vacancy_details_batch(vacancy_ids)
        for sj_id, data in batch_results:
            if data:
                results.append(data)

    return results


@shared_task(
    name=f'{TASK_PREFIX}.parse_superjob_batch_task',
    bind=True,
    max_retries=3,
    default_retry_delay=90,
    soft_time_limit=3600,
    time_limit=3900,
)
def parse_superjob_batch_task(
    self,
    vacancy_ids: List[str],
    api_key: str = None,
    batch_size: int = 20,
) -> Dict[str, Any]:
    """Батчевый парсинг вакансий SuperJob по списку ID."""

    def body():
        logger.info("Батчевый парсинг SuperJob: %d вакансий", len(vacancy_ids))
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 0,
                'total': len(vacancy_ids),
                'status': f'Батчевый парсинг {len(vacancy_ids)} вакансий',
            },
        )

        raw_vacancies = asyncio.run(
            _fetch_batch(vacancy_ids, api_key=api_key, batch_size=batch_size)
        )

        parsed_list = []
        for vac_data in raw_vacancies:
            try:
                parsed_list.append(SuperJobParser.parse_vacancy_data(vac_data))
            except Exception as e:
                logger.error("Ошибка парсинга вакансии в батче: %s", e)

        parsing_metrics = ParsingMetrics()
        parsing_metrics.vacancies_found = len(raw_vacancies)
        save_result = bulk_save_vacancies(parsed_list, parsing_metrics)

        result = {
            'requested': len(vacancy_ids),
            'fetched': len(raw_vacancies),
            'saved': save_result['saved'],
            'updated': save_result['updated'],
            'errors': save_result['errors'],
        }

        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Батч завершен. Запрошено: {result["requested"]}, '
                f'Получено: {result["fetched"]}, '
                f'Сохранено: {result["saved"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)
