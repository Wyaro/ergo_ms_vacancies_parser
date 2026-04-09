"""
Асинхронный парсер вакансий HeadHunter для ускоренного сбора данных.

Использует aiohttp для параллельных запросов к API hh.ru.
Ускорение в 5-10 раз по сравнению с синхронным парсером.
"""

import asyncio
import logging
import time
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

import aiohttp
from django.utils import timezone

from .models import Vacancy
from .scripts import ParsingMetrics


logger = logging.getLogger('modules.vacancies_parser.headhunter.async')


@dataclass
class AsyncParsingConfig:
    """Конфигурация асинхронного парсинга"""
    max_concurrent_requests: int = 10  # Максимум одновременных запросов
    request_delay: float = 0.075  # Задержка между запросами (сек)
    timeout: int = 23  # Таймаут запроса (сек)
    max_retries: int = 3  # Максимум попыток
    base_retry_delay: float = 0.75  # Базовая задержка перед повтором
    max_retry_delay: float = 45.0  # Максимальная задержка перед повтором


class AsyncHeadHunterParser:
    """
    Асинхронный парсер для работы с API HeadHunter.
    
    Позволяет выполнять параллельные запросы для ускорения парсинга.
    """
    
    BASE_URL = "https://api.hh.ru"
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    def __init__(
        self, 
        config: Optional[AsyncParsingConfig] = None,
        metrics: Optional[ParsingMetrics] = None
    ):
        self.config = config or AsyncParsingConfig()
        self.metrics = metrics or ParsingMetrics()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    async def __aenter__(self):
        """Контекстный менеджер - вход"""
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        self._session = aiohttp.ClientSession(
            headers=self.DEFAULT_HEADERS,
            timeout=timeout
        )
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Контекстный менеджер - выход"""
        if self._session:
            await self._session.close()
    
    async def _make_request(
        self, 
        url: str, 
        params: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        Выполнить асинхронный HTTP-запрос с обработкой rate limiting.
        
        Args:
            url: URL для запроса
            params: Параметры запроса
            
        Returns:
            JSON-ответ или None при ошибке
        """
        if not self._session:
            raise RuntimeError("Session not initialized. Use async context manager.")
        
        last_error = None
        
        assert self._semaphore is not None

        for attempt in range(self.config.max_retries):
            try:
                async with self._semaphore:
                    # Небольшая задержка между запросами
                    await asyncio.sleep(self.config.request_delay)
                    
                    async with self._session.get(url, params=params) as response:
                        # Rate limiting
                        if response.status == 429:
                            self.metrics.record_rate_limit()
                            retry_after = int(response.headers.get('Retry-After', 60))
                            retry_after = min(retry_after, self.config.max_retry_delay)
                            logger.warning(
                                "Rate limit (429), ожидание %d сек (попытка %d/%d)",
                                retry_after, attempt + 1, self.config.max_retries
                            )
                            await asyncio.sleep(retry_after)
                            continue
                        
                        # Forbidden (постоянная ошибка доступа, повторять запрос нет смысла)
                        if response.status == 403:
                            self.metrics.record_request(success=False)
                            self.metrics.record_error(f"403 Forbidden для {url}")
                            logger.error("Доступ запрещён (403) для %s", url)
                            return None
                        
                        # Not Found (вакансия закрыта)
                        if response.status == 404:
                            self.metrics.record_request(success=True)
                            return None
                        
                        response.raise_for_status()
                        self.metrics.record_request(success=True)
                        return await response.json()
                        
            except asyncio.TimeoutError as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(f"Timeout для {url}")
                logger.warning("Timeout %s (попытка %d/%d)", url, attempt + 1, self.config.max_retries)
                
            except aiohttp.ClientError as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(str(e))
                logger.warning("Ошибка запроса %s: %s", url, e)
            
            # Exponential backoff
            if attempt < self.config.max_retries - 1:
                delay = min(
                    self.config.base_retry_delay * (2 ** attempt),
                    self.config.max_retry_delay
                )
                await asyncio.sleep(delay)
        
        logger.error("Не удалось выполнить запрос %s после %d попыток", url, self.config.max_retries)
        return None
    
    async def get_vacancy_details(self, vacancy_id: str) -> Optional[Dict]:
        """Получить детали вакансии"""
        return await self._make_request(f"{self.BASE_URL}/vacancies/{vacancy_id}")
    
    async def get_vacancy_details_batch(
        self, 
        vacancy_ids: List[str]
    ) -> List[Tuple[str, Optional[Dict]]]:
        """
        Получить детали нескольких вакансий параллельно.
        
        Args:
            vacancy_ids: Список ID вакансий
            
        Returns:
            Список кортежей (vacancy_id, data или None)
        """
        tasks = [
            self._fetch_vacancy_with_id(vid) 
            for vid in vacancy_ids
        ]
        return await asyncio.gather(*tasks)
    
    async def _fetch_vacancy_with_id(self, vacancy_id: str) -> Tuple[str, Optional[Dict]]:
        """Получить данные вакансии с сохранением ID"""
        data = await self.get_vacancy_details(vacancy_id)
        return (vacancy_id, data)
    
    async def check_vacancies_status_batch(
        self,
        hh_ids: List[str]
    ) -> Dict[str, bool]:
        """
        Проверить статус нескольких вакансий параллельно.
        
        Args:
            hh_ids: Список ID вакансий на hh.ru
            
        Returns:
            Словарь {hh_id: is_active}
        """
        results = await self.get_vacancy_details_batch(hh_ids)
        
        status = {}
        for hh_id, data in results:
            if data is None:
                status[hh_id] = False  # Вакансия закрыта или не найдена
            elif data.get('archived'):
                status[hh_id] = False  # Вакансия архивирована
            else:
                status[hh_id] = True  # Вакансия активна
        
        return status


async def check_vacancies_status_async(
    batch_size: int = 50,
    max_vacancies: int = 500
) -> Dict[str, Any]:
    """
    Асинхронная проверка статуса вакансий.
    
    Args:
        batch_size: Размер пакета для параллельной обработки
        max_vacancies: Максимальное количество вакансий для проверки
        
    Returns:
        Статистика проверки
    """
    metrics = ParsingMetrics()
    config = AsyncParsingConfig(
        max_concurrent_requests=batch_size,
        request_delay=0.05
    )
    
    # Получаем активные вакансии
    active_vacancies = list(
        Vacancy.objects.filter(is_active=True)  # type: ignore[attr-defined]
        .order_by('updated_at')
        .values_list('id', 'hh_id')[:max_vacancies]
    )
    
    total_count = len(active_vacancies)
    logger.info('Асинхронная проверка: %d вакансий', total_count)
    
    if total_count == 0:
        return {
            'status': 'completed',
            'checked': 0,
            'archived': 0,
            'still_active': 0
        }
    
    archived_count = 0
    still_active_count = 0
    
    async with AsyncHeadHunterParser(config=config, metrics=metrics) as parser:
        # Обрабатываем пакетами
        for i in range(0, total_count, batch_size):
            batch = active_vacancies[i:i + batch_size]
            hh_ids = [hh_id for _, hh_id in batch]
            db_ids_map = {hh_id: db_id for db_id, hh_id in batch}
            
            # Проверяем статус параллельно
            statuses = await parser.check_vacancies_status_batch(hh_ids)
            
            # Обновляем в БД
            ids_to_deactivate = [
                db_ids_map[hh_id] 
                for hh_id, is_active in statuses.items() 
                if not is_active
            ]
            
            if ids_to_deactivate:
                Vacancy.objects.filter(  # type: ignore[attr-defined]
                    id__in=ids_to_deactivate
                ).update(
                    is_active=False,
                    updated_at=timezone.now()
                )
                archived_count += len(ids_to_deactivate)
            
            still_active_count += sum(1 for is_active in statuses.values() if is_active)
            
            # Логируем прогресс
            processed = min(i + batch_size, total_count)
            logger.info(
                'Прогресс: %d/%d (%.1f%%), закрыто: %d',
                processed, total_count, (processed / total_count) * 100, archived_count
            )
    
    metrics.log_summary()
    
    return {
        'status': 'completed',
        'checked': total_count,
        'archived': archived_count,
        'still_active': still_active_count,
        'metrics': metrics.to_dict()
    }


def run_async_status_check(batch_size: int = 50, max_vacancies: int = 500) -> Dict[str, Any]:
    """
    Синхронная обёртка для запуска асинхронной проверки.
    
    Args:
        batch_size: Размер пакета
        max_vacancies: Максимум вакансий
        
    Returns:
        Результат проверки
    """
    return asyncio.run(check_vacancies_status_async(batch_size, max_vacancies))

