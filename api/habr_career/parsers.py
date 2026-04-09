"""
Module-level parser overrides for Habr Career.
"""

import logging
import time
import random

import requests

from ..core.parsers import ParserFactory
from ..core.parsers.base import BlockedError, NetworkError
from ..core.parsers.html_parsers import HabrCareerHTMLParser
from modules.vacancies_parser.api.core.monitoring_utils import (
    increment_taskrun_counter,
    record_external_api_event,
)

logger = logging.getLogger('celery.module.vacancies_parser.habr_career')


class HabrCareerModuleHTMLParser(HabrCareerHTMLParser):
    """
    Адаптер Habr Career для общего пайплайна парсинга.

    Переопределяет:
    - _make_request: убирает ложное срабатывание CAPTCHA по содержимому
      страницы (Habr Career грузит reCAPTCHA-скрипты на каждой странице)
    - parse_item: передаёт оригинальный URL в fetch_item
    """

    def _make_request(self, url: str) -> requests.Response:
        last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout)

                if response.status_code == 403:
                    raise BlockedError(f"Доступ запрещён (403) для {url}")

                if self._is_captcha_redirect(response):
                    raise BlockedError(f"Редирект на CAPTCHA для {url}")

                if response.status_code == 200:
                    return response

                response.raise_for_status()

            except BlockedError:
                raise
            except requests.Timeout as e:
                last_error = e
                increment_taskrun_counter('timeouts', 1)
                record_external_api_event(source='habr_career', event_type='timeout', endpoint=url)
                logger.warning(
                    "[Habr] Таймаут %s (попытка %s/%s)", url, attempt + 1, self.max_retries
                )
            except requests.HTTPError as e:
                last_error = e
                if getattr(e.response, 'status_code', None) == 429:
                    increment_taskrun_counter('http_429', 1)
                    record_external_api_event(source='habr_career', event_type='http_429', endpoint=url)
                logger.warning(
                    "[Habr] HTTP %s для %s (попытка %s/%s)",
                    e.response.status_code, url, attempt + 1, self.max_retries,
                )
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "[Habr] Ошибка запроса %s (попытка %s/%s): %s",
                    url, attempt + 1, self.max_retries, e,
                )

            if attempt < self.max_retries - 1:
                increment_taskrun_counter('retries', 1)
                delay = min(2 ** attempt, 10) + random.uniform(0.5, 1.5)
                time.sleep(delay)

        raise NetworkError(
            f"Не удалось выполнить запрос {url} после {self.max_retries} попыток: {last_error}"
        )

    @staticmethod
    def _is_captcha_redirect(response: requests.Response) -> bool:
        if 'captcha' in response.url.lower():
            return True
        if response.is_redirect or len(response.history) > 2:
            final_url = response.url.lower()
            if any(marker in final_url for marker in ('captcha', 'challenge', 'blocked')):
                return True
        return False

    def parse_item(self, item_id: str, url: str):
        normalized_item_id = str(item_id).strip() if item_id is not None else ""
        if not normalized_item_id and url:
            normalized_item_id = url.rstrip("/").split("/")[-1]

        if not normalized_item_id:
            raise ValueError("Empty item_id for Habr Career parse_item call")

        return self.fetch_item(normalized_item_id, {'url': url})


ParserFactory.register("habr_career", "html", HabrCareerModuleHTMLParser)
