"""
Проверка статуса вакансий SuperJob.

Асинхронная проверка активности вакансий через API SuperJob:
деактивация закрытых/архивных вакансий в БД.
"""

import logging
from typing import Dict, Any

from celery import shared_task

from ..async_parser import run_async_status_check
from .utils import run_task_with_error_handling

logger = logging.getLogger('modules.vacancies_parser.superjob.status')

TASK_PREFIX = 'modules.vacancies_parser.api.superjob.tasks'


@shared_task(
    name=f'{TASK_PREFIX}.check_superjob_vacancies_status_task',
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=7200,
    time_limit=7500,
)
def check_superjob_vacancies_status_task(
    self,
    api_key: str = None,
    batch_size: int = 50,
    max_vacancies: int = 500,
) -> Dict[str, Any]:
    """Проверка статуса активных вакансий SuperJob."""

    def body():
        logger.info(
            "Проверка статуса вакансий SuperJob (batch=%d, max=%d)",
            batch_size, max_vacancies,
        )
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 0,
                'total': max_vacancies,
                'status': 'Проверка статуса вакансий',
            },
        )
        result = run_async_status_check(
            api_key=api_key,
            batch_size=batch_size,
            max_vacancies=max_vacancies,
        )
        return {
            'status': 'SUCCESS',
            'result': result,
            'message': (
                f'Проверка завершена. Проверено: {result["checked"]}, '
                f'Закрыто: {result["archived"]}, '
                f'Активно: {result["still_active"]}'
            ),
        }

    return run_task_with_error_handling(self, body, task_logger=logger)
