"""
Утилиты для парсинга SuperJob.

RateLimiter — контроль частоты запросов (120 req/min для SuperJob API).
ParsingMetrics — сбор метрик парсинга.
"""

import time
import random
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

logger = logging.getLogger('modules.vacancies_parser.superjob.utils')


class RateLimiter:
    """
    Контроль частоты запросов к API SuperJob.
    Лимит API: 120 запросов в минуту.
    """

    def __init__(self, max_requests_per_minute: int = 100, jitter: float = 0.3):
        self._max_rpm = max_requests_per_minute
        self._min_interval = 60.0 / max_requests_per_minute
        self._jitter = jitter
        self._last_request_time: float = 0.0

    def wait(self):
        """Блокирующее ожидание до следующего безопасного момента запроса."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        wait_time = self._min_interval - elapsed

        if wait_time > 0:
            jitter_delta = random.uniform(0, self._jitter)
            actual_wait = wait_time + jitter_delta
            time.sleep(actual_wait)

        self._last_request_time = time.monotonic()

    async def async_wait(self):
        """Асинхронное ожидание (для aiohttp)."""
        import asyncio

        now = time.monotonic()
        elapsed = now - self._last_request_time
        wait_time = self._min_interval - elapsed

        if wait_time > 0:
            jitter_delta = random.uniform(0, self._jitter)
            await asyncio.sleep(wait_time + jitter_delta)

        self._last_request_time = time.monotonic()


@dataclass
class ParsingMetrics:
    """Сбор метрик парсинга SuperJob."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limit_hits: int = 0
    vacancies_found: int = 0
    vacancies_saved: int = 0
    vacancies_updated: int = 0
    errors: int = 0
    start_time: float = field(default_factory=time.monotonic)

    def record_request(self, success: bool = True):
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1

    def record_rate_limit(self):
        self.rate_limit_hits += 1

    def record_error(self, message: str):
        self.errors += 1
        logger.warning("Ошибка парсинга: %s", message)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'rate_limit_hits': self.rate_limit_hits,
            'vacancies_found': self.vacancies_found,
            'vacancies_saved': self.vacancies_saved,
            'vacancies_updated': self.vacancies_updated,
            'errors': self.errors,
            'elapsed_seconds': round(self.elapsed_seconds, 2),
        }

    def log_summary(self):
        logger.info(
            "Метрики парсинга: запросов=%d (ok=%d, fail=%d), "
            "вакансий найдено=%d, сохранено=%d, обновлено=%d, "
            "ошибок=%d, время=%.1fс",
            self.total_requests, self.successful_requests, self.failed_requests,
            self.vacancies_found, self.vacancies_saved, self.vacancies_updated,
            self.errors, self.elapsed_seconds,
        )
