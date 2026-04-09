import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup, Comment

from ...core.parsers.base import BlockedError, NetworkError
from ...core.parsers.html_parsers import HeadHunterHTMLParser

logger = logging.getLogger('celery.module.vacancies_parser.headhunter.html')

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

_BROWSER_HEADERS_CHROME = {
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8'
    ),
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
    'sec-ch-ua': '"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

_BROWSER_HEADERS_FIREFOX = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'DNT': '1',
    'Priority': 'u=0, i',
}

_MIN_PAGE_DELAY = 1.5
_MAX_PAGE_DELAY = 3.75
_MIN_WARMUP_DELAY = 1.125
_MAX_WARMUP_DELAY = 2.625

_MIN_REQUEST_SPACING = 2.25
_MAX_REQUEST_SPACING = 6.0
_THROTTLE_PAUSE_INTERVAL = (90, 180)
_THROTTLE_PAUSE_DURATION = (11.25, 33.75)
_CAPTCHA_BASE_WAIT = 22.5
_CAPTCHA_MAX_WAIT = 225.0
_MAX_CAPTCHA_RETRIES = 2

_CAPTCHA_URL_PATTERNS = re.compile(
    r'captcha|challenge|verify|blocked|firewall',
    re.IGNORECASE,
)

_CAPTCHA_VISIBLE_RE = re.compile(
    r'\b(введите\s+код|пройдите\s+проверку|подтвердите.{0,20}робот'
    r'|are\s+you\s+a?\s*human|verify\s+you\s+are|robot\s+check'
    r'|access\s+denied|please\s+complete\s+the\s+captcha)\b',
    re.IGNORECASE,
)

_BLOCK_VISIBLE_RE = re.compile(
    r'\b(cloudflare|access\s+denied|403\s+forbidden|bot\s+detected)\b',
    re.IGNORECASE,
)

_VACANCY_LINK_RE = re.compile(r'^/vacancy/(\d+)(?:[?#].*)?$')
_VACANCY_ABSOLUTE_RE = re.compile(
    r'https?://[a-z]+\.hh\.ru(/vacancy/(\d+))(?:[?#].*)?'
)


def _format_duration(seconds: float) -> str:
    """Форматирует длительность для логов только в секундах."""
    return f"{seconds:.2f} сек"


def _extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all(['script', 'style', 'noscript', 'svg']):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    return soup.get_text(separator=' ', strip=True).lower()


def _is_captcha_page(response: requests.Response) -> bool:
    if _CAPTCHA_URL_PATTERNS.search(response.url):
        return True

    html = response.text
    if len(html) < 4000:
        lower = html.lower()
        if 'captcha' in lower or 'challenge' in lower:
            return True

    visible = _extract_visible_text(html)
    if _CAPTCHA_VISIBLE_RE.search(visible):
        return True

    return False


def _is_blocked_page(response: requests.Response) -> bool:
    if response.status_code == 403:
        return True
    if _is_captcha_page(response):
        return True
    visible = _extract_visible_text(response.text)
    if _BLOCK_VISIBLE_RE.search(visible):
        return True
    return False


class HeadHunterHTMLParserOverride(HeadHunterHTMLParser):
    """
    Переопределение HTML-парсера HeadHunter с anti-detection:
    - Человекоподобные задержки между запросами (нормальное распределение)
    - Периодические длинные паузы (имитация чтения страницы)
    - Ротация User-Agent и сброс сессии при обнаружении капчи
    - Экспоненциальный backoff при последовательных капчах
    - Прогрев сессии через главную страницу (сбор cookies)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_warmed = False
        self._last_request_url: Optional[str] = None
        self._last_request_time: Optional[float] = None
        self._request_count = 0
        self._next_throttle_at = random.randint(*_THROTTLE_PAUSE_INTERVAL)
        self._setup_browser_session()

    def _setup_browser_session(self):
        ua = random.choice(_USER_AGENTS)
        is_firefox = 'Firefox' in ua
        is_edge = 'Edg/' in ua
        headers = dict(_BROWSER_HEADERS_FIREFOX if is_firefox else _BROWSER_HEADERS_CHROME)
        headers['User-Agent'] = ua

        if not is_firefox:
            m = re.search(r'Chrome/(\d+)', ua)
            major = m.group(1) if m else '131'
            brand = '"Microsoft Edge"' if is_edge else '"Google Chrome"'
            headers['sec-ch-ua'] = (
                f'"Chromium";v="{major}", {brand};v="{major}", '
                f'"Not-A.Brand";v="99"'
            )

        self.session.headers.clear()
        self.session.headers.update(headers)
        logger.debug("[HTML][HH] Сессия настроена: UA=%s", ua[:60])

    def _warmup_session(self):
        if self._session_warmed:
            return
        try:
            logger.info("[HTML][HH] Прогрев сессии: запрос главной страницы")
            self.session.headers['Sec-Fetch-Site'] = 'none'
            resp = self.session.get(
                self.BASE_URL, timeout=self.timeout, allow_redirects=True,
            )
            logger.info(
                "[HTML][HH] Прогрев: status=%s, cookies=%s",
                resp.status_code, len(self.session.cookies),
            )
            time.sleep(random.uniform(_MIN_WARMUP_DELAY, _MAX_WARMUP_DELAY))
        except Exception as exc:
            logger.warning("[HTML][HH] Ошибка прогрева сессии: %s", exc)
        self._session_warmed = True

    def _ensure_request_spacing(self):
        if self._last_request_time is None:
            return
        elapsed = time.monotonic() - self._last_request_time
        target = max(
            _MIN_REQUEST_SPACING,
            min(_MAX_REQUEST_SPACING, random.gauss(3.75, 1.125)),
        )
        if elapsed < target:
            time.sleep(target - elapsed)

    def _throttle_check(self):
        self._request_count += 1
        if self._request_count >= self._next_throttle_at:
            pause = random.uniform(*_THROTTLE_PAUSE_DURATION)
            logger.info(
                "[HTML][HH] Пауза %s после %d запросов",
                _format_duration(pause), self._request_count,
            )
            time.sleep(pause)
            self._request_count = 0
            self._next_throttle_at = random.randint(*_THROTTLE_PAUSE_INTERVAL)

    def _rotate_session(self):
        self.session.cookies.clear()
        self._setup_browser_session()
        self._session_warmed = False
        self._last_request_url = None
        logger.info("[HTML][HH] Сессия пересоздана (новый UA, cookies сброшены)")

    def _make_request(self, url: str) -> requests.Response:
        last_blocked: Optional[BlockedError] = None
        for captcha_attempt in range(_MAX_CAPTCHA_RETRIES + 1):
            try:
                return self._execute_request(url)
            except BlockedError as e:
                last_blocked = e
                if captcha_attempt < _MAX_CAPTCHA_RETRIES:
                    wait = min(
                        _CAPTCHA_BASE_WAIT * (2 ** captcha_attempt),
                        _CAPTCHA_MAX_WAIT,
                    )
                    logger.warning(
                        "[HTML][HH] Капча #%d для %s, ожидание %s, "
                        "ротация сессии",
                        captcha_attempt + 1, url, _format_duration(wait),
                    )
                    time.sleep(wait)
                    self._rotate_session()
                    self._warmup_session()
                    self._ensure_request_spacing()
                    continue
                raise
        raise last_blocked  # type: ignore[misc]

    def _execute_request(self, url: str) -> requests.Response:
        self._warmup_session()
        self._ensure_request_spacing()
        self._throttle_check()

        if self._last_request_url:
            self.session.headers['Referer'] = self._last_request_url
        else:
            self.session.headers['Referer'] = self.BASE_URL + '/'
        self.session.headers['Sec-Fetch-Site'] = 'same-origin'

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(
                    url, timeout=self.timeout, allow_redirects=True,
                )

                if _is_blocked_page(response):
                    reason = 'captcha' if _is_captcha_page(response) else 'block'
                    raise BlockedError(
                        f"Обнаружена {reason} для {url} "
                        f"(status={response.status_code}, url={response.url})"
                    )

                if response.status_code == 200:
                    self._last_request_url = url
                    self._last_request_time = time.monotonic()
                    return response

                response.raise_for_status()

            except BlockedError:
                raise
            except requests.Timeout as e:
                last_error = e
                logger.warning(
                    "[HTML][HH] Таймаут %s (попытка %s/%s)",
                    url, attempt + 1, self.max_retries,
                )
            except requests.HTTPError as e:
                last_error = e
                logger.warning(
                    "[HTML][HH] HTTP %s для %s (попытка %s/%s)",
                    e.response.status_code, url, attempt + 1, self.max_retries,
                )
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "[HTML][HH] Ошибка %s (попытка %s/%s): %s",
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
        logger.info("[HTML][HH] Старт discovery с config=%s", config)
        items: List[Dict[str, str]] = []
        seen_ids: Set[str] = set()

        page = 0
        try:
            max_pages = int(config.get('max_pages', 10))
        except (TypeError, ValueError):
            max_pages = 10

        items_per_page = config.get('items_per_page', 50)

        while page < max_pages:
            try:
                search_url = self._build_search_url(config, page, items_per_page)
                logger.info("[HTML][HH] Запрос страницы %s: %s", page, search_url)

                response = self._make_request(search_url)
                html_text = response.text

                logger.debug(
                    "[HTML][HH] Страница %s: status=%s, html_len=%s",
                    page, response.status_code, len(html_text),
                )

                soup = self._parse_html(html_text)
                page_ids = self._extract_vacancy_links(soup, html_text)

                logger.info(
                    "[HTML][HH] Найдено вакансий на странице %s: %s",
                    page, len(page_ids),
                )

                if not page_ids:
                    if 'window.__INITIAL_STATE__' in html_text or 'HH.API' in html_text:
                        logger.warning(
                            "[HTML][HH] HH.ru использует JavaScript-рендеринг (SPA). "
                            "HTML парсинг может быть ограничен."
                        )
                    logger.info("[HTML][HH] Вакансии не найдены на странице %s, завершаем", page)
                    break

                for vacancy_id in page_ids:
                    if vacancy_id not in seen_ids:
                        seen_ids.add(vacancy_id)
                        items.append({
                            'source_item_id': vacancy_id,
                            'url': f"{self.BASE_URL}/vacancy/{vacancy_id}",
                        })

                page += 1

                if page < max_pages:
                    delay = random.uniform(_MIN_PAGE_DELAY, _MAX_PAGE_DELAY)
                    logger.debug(
                        "[HTML][HH] Задержка %s перед страницей %s",
                        _format_duration(delay), page,
                    )
                    time.sleep(delay)

            except BlockedError as exc:
                logger.error(
                    "[HTML][HH] Блокировка при парсинге страницы %s: %s",
                    page, exc,
                )
                break
            except Exception as exc:
                logger.error(
                    "[HTML][HH] Ошибка на странице %s: %s",
                    page, exc, exc_info=True,
                )
                break

        logger.info("[HTML][HH] Discovery завершен: %s вакансий", len(items))
        return items

    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        return self.fetch_item(item_id, {'url': url})

    def _build_search_url(self, config: Dict[str, Any], page: int,
                          items_per_page: int = 50) -> str:
        params: Dict[str, Any] = {
            'page': page,
            'items_on_page': items_per_page,
        }
        if config.get('text'):
            params['text'] = config['text']
        if config.get('area'):
            params['area'] = config['area']
        if config.get('experience'):
            params['experience'] = config['experience']

        return f"{self.BASE_URL}/search/vacancy?{urlencode(params, doseq=True)}"

    def _extract_vacancy_links(
        self, soup: BeautifulSoup, html_text: str,
    ) -> List[str]:
        ids: List[str] = []
        seen: Set[str] = set()

        for anchor in soup.select('a[href*="/vacancy/"]'):
            href = anchor.get('href')
            if not isinstance(href, str):
                continue

            m = _VACANCY_LINK_RE.match(href)
            if m:
                vid = m.group(1)
                if vid not in seen:
                    ids.append(vid)
                    seen.add(vid)
                continue

            for abs_match in _VACANCY_ABSOLUTE_RE.finditer(href):
                vid = abs_match.group(2)
                if vid not in seen:
                    ids.append(vid)
                    seen.add(vid)

        for anchor in soup.find_all('div', attrs={'data-qa': 'vacancy-serp__vacancy'}):
            data_id = anchor.get('data-vacancy-id')
            if data_id and str(data_id) not in seen:
                ids.append(str(data_id))
                seen.add(str(data_id))

        inline_re = re.compile(r'/vacancy/(\d+)')
        for match in inline_re.finditer(html_text):
            vid = match.group(1)
            if vid not in seen:
                ids.append(vid)
                seen.add(vid)

        return ids
