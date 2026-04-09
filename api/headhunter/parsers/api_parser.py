"""
Переопределение API-парсера HeadHunter с anti-detection.

Добавляет к базовому HeadHunterAPIParser:
- Человекоподобные задержки (нормальное распределение)
- Ротация User-Agent при каждом запросе
- Периодические длинные паузы (throttle)
- Экспоненциальный backoff при 403/429
- Пересоздание сессии при блокировке
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter

from ...core.parsers.base import BlockedError, NetworkError
from ...core.parsers.api_parsers import HeadHunterAPIParser

logger = logging.getLogger('celery.module.vacancies_parser.headhunter.api')

_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) '
    'Gecko/20100101 Firefox/133.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) '
    'Gecko/20100101 Firefox/132.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) '
    'Gecko/20100101 Firefox/133.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
]

_MIN_REQUEST_SPACING = 1.5
_MAX_REQUEST_SPACING = 3.75
_THROTTLE_PAUSE_INTERVAL = (120, 220)
_THROTTLE_PAUSE_DURATION = (7.5, 22.5)
_BLOCK_BASE_WAIT = 22.5
_BLOCK_MAX_WAIT = 225.0
_MAX_BLOCK_RETRIES = 3


def _format_duration(seconds: float) -> str:
    """Форматирует длительность для логов только в секундах."""
    return f"{seconds:.2f} сек"


class HeadHunterAPIParserOverride(HeadHunterAPIParser):
    """
    API-парсер HeadHunter с anti-detection:
    - Браузерный User-Agent вместо идентификации парсера
    - Человекоподобные задержки между запросами
    - Периодические паузы (имитация чтения)
    - Ротация UA и пересоздание сессии при блокировке
    - Экспоненциальный backoff при 403/429
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_request_time: Optional[float] = None
        self._request_count = 0
        self._next_throttle_at = random.randint(*_THROTTLE_PAUSE_INTERVAL)
        self._rotate_session()

    def _rotate_session(self):
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=2)
        self.session = requests.Session()
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        ua = random.choice(_USER_AGENTS)
        self.session.headers.update({
            'User-Agent': ua,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        logger.debug("[API][HH] Сессия создана: UA=%s", ua[:60])

    def _ensure_request_spacing(self):
        if self._last_request_time is None:
            return
        elapsed = time.monotonic() - self._last_request_time
        target = max(
            _MIN_REQUEST_SPACING,
            min(_MAX_REQUEST_SPACING, random.gauss(2.625, 0.75)),
        )
        if elapsed < target:
            time.sleep(target - elapsed)

    def _throttle_check(self):
        self._request_count += 1
        if self._request_count >= self._next_throttle_at:
            pause = random.uniform(*_THROTTLE_PAUSE_DURATION)
            logger.info(
                "[API][HH] Пауза %s после %d запросов",
                _format_duration(pause), self._request_count,
            )
            time.sleep(pause)
            self._request_count = 0
            self._next_throttle_at = random.randint(*_THROTTLE_PAUSE_INTERVAL)

    def _get_with_retry(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        self._ensure_request_spacing()
        self._throttle_check()

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_time = time.monotonic()

                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    wait = min(retry_after, _BLOCK_MAX_WAIT)
                    logger.warning(
                        "[API][HH] Rate limit (429) для %s, ожидание %s",
                        url, _format_duration(wait),
                    )
                    time.sleep(wait)
                    self._rotate_session()
                    continue

                if response.status_code == 403:
                    raise BlockedError(
                        f"Доступ заблокирован (403) для {url}"
                    )

                return response

            except BlockedError:
                raise
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                last_error = e
                self.logger.warning(
                    "[API][HH] Сетевая ошибка %s (попытка %d/%d): %s",
                    url, attempt + 1, self.max_retries, e,
                )
                self._rotate_session()
            except requests.exceptions.Timeout as e:
                last_error = e
                self.logger.warning(
                    "[API][HH] Таймаут %s (timeout=%s, попытка %d/%d)",
                    url, _format_duration(float(self.timeout)), attempt + 1, self.max_retries,
                )
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(
                    "[API][HH] Ошибка %s (попытка %d/%d): %s",
                    url, attempt + 1, self.max_retries, e,
                )

            if attempt < self.max_retries - 1:
                delay = min((0.75 * (2 ** attempt)) + random.uniform(0.375, 1.5), 11.25)
                time.sleep(delay)

        raise NetworkError(
            f"Не удалось выполнить запрос {url} "
            f"после {self.max_retries} попыток: {last_error}"
        )

    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        self.validate_config(config)

        items: List[Dict[str, str]] = []
        area = config['area']
        pages = config.get('pages', 1)
        per_page = config.get('per_page', 100)

        search_params: Dict[str, Any] = {
            'area': area,
            'per_page': per_page,
            'only_with_salary': False,
        }

        for key in ('professional_role', 'text', 'specialization'):
            if key in config:
                search_params[key] = config[key]

        self.logger.info("[API][HH] Начало discovery: %s", search_params)

        for page in range(pages):
            search_params['page'] = page

            try:
                response = self._get_with_retry(
                    f"{self.BASE_URL}/vacancies",
                    params=search_params,
                )
                response.raise_for_status()
                data = response.json()

                vacancies = data.get('items', [])
                for vacancy in vacancies:
                    vacancy_id = str(vacancy.get('id'))
                    url = vacancy.get(
                        'alternate_url',
                        f"https://hh.ru/vacancy/{vacancy_id}",
                    )
                    items.append({
                        'source_item_id': vacancy_id,
                        'url': url,
                    })

                self.logger.info(
                    "[API][HH] Страница %d/%d: %d вакансий",
                    page + 1, pages, len(vacancies),
                )

            except (BlockedError, NetworkError):
                raise
            except requests.RequestException as e:
                raise NetworkError(f"Ошибка сети при discovery: {e}")

        self.logger.info("[API][HH] Discovery завершен: %d вакансий", len(items))
        return items

    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        last_blocked: Optional[BlockedError] = None

        for block_attempt in range(_MAX_BLOCK_RETRIES + 1):
            try:
                response = self._get_with_retry(
                    f"{self.BASE_URL}/vacancies/{item_id}",
                )

                if response.status_code == 404:
                    from ...core.parsers.base import ValidationError
                    raise ValidationError(
                        f"Вакансия {item_id} не найдена (404)"
                    )

                response.raise_for_status()
                return self._normalize_vacancy_data(response.json())

            except BlockedError as e:
                last_blocked = e
                if block_attempt < _MAX_BLOCK_RETRIES:
                    wait = min(
                        _BLOCK_BASE_WAIT * (2 ** block_attempt),
                        _BLOCK_MAX_WAIT,
                    )
                    logger.warning(
                        "[API][HH] Блокировка #%d для вакансии %s, "
                        "ожидание %s, ротация сессии",
                        block_attempt + 1, item_id, _format_duration(wait),
                    )
                    time.sleep(wait)
                    self._rotate_session()
                    self._ensure_request_spacing()
                    continue
                raise

            except (NetworkError, requests.RequestException) as e:
                raise NetworkError(
                    f"Ошибка сети при парсинге вакансии {item_id}: {e}"
                )

        raise last_blocked  # type: ignore[misc]
