"""
Асинхронный парсер вакансий SuperJob для ускоренного сбора данных.

Использует aiohttp для параллельных запросов к API SuperJob.
"""

import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

import aiohttp
from django.utils import timezone

from .models import SuperJobVacancy
from .parsers.utils import ParsingMetrics

logger = logging.getLogger('modules.vacancies_parser.superjob.async')


@dataclass
class AsyncParsingConfig:
    """Конфигурация асинхронного парсинга SuperJob."""
    max_concurrent_requests: int = 10
    request_delay: float = 0.1
    timeout: int = 30
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 60.0


class AsyncSuperJobParser:
    """
    Асинхронный парсер для работы с API SuperJob.

    Позволяет выполнять параллельные запросы для ускорения парсинга.
    Поддерживает Semaphore для контроля параллелизма и retry с backoff.
    """

    BASE_URL = "https://api.superjob.ru/2.0"

    def __init__(
        self,
        api_key: Optional[str] = None,
        config: Optional[AsyncParsingConfig] = None,
        metrics: Optional[ParsingMetrics] = None,
    ):
        self.api_key = api_key
        self.config = config or AsyncParsingConfig()
        self.metrics = metrics or ParsingMetrics()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def __aenter__(self):
        headers = {}
        if self.api_key:
            headers['X-Api-App-Id'] = self.api_key

        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def _make_request(
        self, url: str, params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Асинхронный HTTP GET с rate limiting и retry."""
        if not self._session:
            raise RuntimeError("Session not initialized. Use async context manager.")

        assert self._semaphore is not None
        last_error = None

        for attempt in range(self.config.max_retries):
            try:
                async with self._semaphore:
                    await asyncio.sleep(self.config.request_delay)

                    async with self._session.get(url, params=params) as response:
                        if response.status == 429:
                            self.metrics.record_rate_limit()
                            retry_after = int(response.headers.get('Retry-After', 60))
                            retry_after = min(retry_after, self.config.max_retry_delay)
                            logger.warning(
                                "Rate limit (429), ожидание %dс (попытка %d/%d)",
                                retry_after, attempt + 1, self.config.max_retries,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        if response.status == 403:
                            self.metrics.record_request(success=False)
                            logger.error("Доступ запрещён (403) для %s", url)
                            return None

                        if response.status == 404:
                            self.metrics.record_request(success=True)
                            return None

                        response.raise_for_status()
                        self.metrics.record_request(success=True)
                        return await response.json()

            except asyncio.TimeoutError as e:
                last_error = e
                self.metrics.record_request(success=False)
                logger.warning(
                    "Timeout %s (попытка %d/%d)", url, attempt + 1, self.config.max_retries
                )
            except aiohttp.ClientError as e:
                last_error = e
                self.metrics.record_request(success=False)
                logger.warning("Ошибка запроса %s: %s", url, e)

            if attempt < self.config.max_retries - 1:
                delay = min(
                    self.config.base_retry_delay * (2 ** attempt),
                    self.config.max_retry_delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "Не удалось выполнить запрос %s после %d попыток",
            url, self.config.max_retries,
        )
        return None

    async def get_vacancy_details(self, vacancy_id: str) -> Optional[Dict]:
        """Получить детали одной вакансии."""
        return await self._make_request(f"{self.BASE_URL}/vacancies/{vacancy_id}/")

    async def get_vacancy_details_batch(
        self, vacancy_ids: List[str]
    ) -> List[Tuple[str, Optional[Dict]]]:
        """Получить детали нескольких вакансий параллельно через asyncio.gather."""
        tasks = [self._fetch_vacancy_with_id(vid) for vid in vacancy_ids]
        return await asyncio.gather(*tasks)

    async def _fetch_vacancy_with_id(
        self, vacancy_id: str
    ) -> Tuple[str, Optional[Dict]]:
        data = await self.get_vacancy_details(vacancy_id)
        return (vacancy_id, data)

    async def check_vacancies_status_batch(
        self, sj_ids: List[str]
    ) -> Dict[str, bool]:
        """Проверить статус нескольких вакансий параллельно."""
        results = await self.get_vacancy_details_batch(sj_ids)

        statuses = {}
        for sj_id, data in results:
            if data is None:
                statuses[sj_id] = False
            elif data.get('is_archive'):
                statuses[sj_id] = False
            elif data.get('is_closed'):
                statuses[sj_id] = False
            else:
                statuses[sj_id] = True

        return statuses

    async def search_vacancies_page(self, page: int = 0, **kwargs) -> Dict[str, Any]:
        """Асинхронный поиск вакансий на одной странице."""
        params = {'page': page, 'count': kwargs.get('count', 100)}
        for key in ['keyword', 'town', 'catalogues', 'experience', 'type_of_work']:
            value = kwargs.get(key)
            if value is not None:
                params[key] = value

        result = await self._make_request(f"{self.BASE_URL}/vacancies/", params=params)
        if result is None:
            return {"objects": [], "total": 0, "more": False}
        return result


async def check_vacancies_status_async(
    api_key: Optional[str] = None,
    batch_size: int = 50,
    max_vacancies: int = 500,
) -> Dict[str, Any]:
    """Асинхронная проверка статуса вакансий SuperJob."""
    metrics = ParsingMetrics()
    config = AsyncParsingConfig(
        max_concurrent_requests=batch_size,
        request_delay=0.05,
    )

    active_vacancies = list(
        SuperJobVacancy.objects.filter(is_active=True)
        .order_by('updated_at')
        .values_list('id', 'superjob_id')[:max_vacancies]
    )

    total_count = len(active_vacancies)
    logger.info('Асинхронная проверка статуса: %d вакансий', total_count)

    if total_count == 0:
        return {'status': 'completed', 'checked': 0, 'archived': 0, 'still_active': 0}

    archived_count = 0
    still_active_count = 0

    async with AsyncSuperJobParser(api_key=api_key, config=config, metrics=metrics) as parser:
        for i in range(0, total_count, batch_size):
            batch = active_vacancies[i:i + batch_size]
            sj_ids = [sj_id for _, sj_id in batch]
            db_ids_map = {sj_id: db_id for db_id, sj_id in batch}

            statuses = await parser.check_vacancies_status_batch(sj_ids)

            ids_to_deactivate = [
                db_ids_map[sj_id]
                for sj_id, is_active in statuses.items()
                if not is_active
            ]

            if ids_to_deactivate:
                SuperJobVacancy.objects.filter(
                    id__in=ids_to_deactivate
                ).update(is_active=False, updated_at=timezone.now())
                archived_count += len(ids_to_deactivate)

            still_active_count += sum(1 for a in statuses.values() if a)

            processed = min(i + batch_size, total_count)
            logger.info(
                'Прогресс: %d/%d (%.1f%%), закрыто: %d',
                processed, total_count, (processed / total_count) * 100, archived_count,
            )

    metrics.log_summary()

    return {
        'status': 'completed',
        'checked': total_count,
        'archived': archived_count,
        'still_active': still_active_count,
        'metrics': metrics.to_dict(),
    }


def run_async_status_check(
    api_key: Optional[str] = None,
    batch_size: int = 50,
    max_vacancies: int = 500,
) -> Dict[str, Any]:
    """Синхронная обёртка для запуска асинхронной проверки статусов."""
    return asyncio.run(
        check_vacancies_status_async(api_key, batch_size, max_vacancies)
    )
