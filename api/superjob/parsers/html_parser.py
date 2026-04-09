import logging
import random
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup, Comment

from ...core.parsers.base import BlockedError, NetworkError
from ...core.parsers.html_parsers import SuperJobHTMLParser

logger = logging.getLogger('celery.module.vacancies_parser.superjob.html')

_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) '
    'Gecko/20100101 Firefox/133.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) '
    'Gecko/20100101 Firefox/133.0',
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

_MIN_PAGE_DELAY = 2.0
_MAX_PAGE_DELAY = 5.0
_MIN_WARMUP_DELAY = 1.5
_MAX_WARMUP_DELAY = 3.5

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


class SuperJobHTMLParserOverride(SuperJobHTMLParser):
    """
    Переопределение HTML-парсера SuperJob на уровне superjob-модуля.

    Эмулирует полноценную браузерную сессию:
    - Полный набор HTTP-заголовков Chrome/Firefox
    - Прогрев сессии через главную страницу (сбор cookies)
    - Случайные задержки между запросами
    - Ротация User-Agent
    - Умная детекция капчи (по видимому тексту, а не по скриптам)
    """

    _VACANCY_LINK_RE = re.compile(r"^/vakansii/[^?#]+\.html(?:[?#].*)?$")
    _VACANCY_LINK_ANY_RE = re.compile(
        r'(/vakansii/[^"\'<>\s]+\.html(?:\?[^"\'<>\s]*)?)'
    )
    _VACANCY_ABSOLUTE_RE = re.compile(
        r'https?://www\.superjob\.ru(/vakansii/[^"\'<>\s]+\.html(?:\?[^"\'<>\s]*)?)'
    )
    _VACANCY_ID_RE = re.compile(r"-(\d+)\.html(?:[?#].*)?$")
    _VACANCY_ID_OLD_RE = re.compile(r"/vakansii/(\d+)\.html(?:[?#].*)?$")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_warmed = False
        self._last_request_url: Optional[str] = None
        self._setup_browser_session()

    def _setup_browser_session(self):
        ua = random.choice(_USER_AGENTS)
        is_firefox = 'Firefox' in ua
        headers = dict(_BROWSER_HEADERS_FIREFOX if is_firefox else _BROWSER_HEADERS_CHROME)
        headers['User-Agent'] = ua

        if not is_firefox:
            major = '131'
            headers['sec-ch-ua'] = (
                f'"Chromium";v="{major}", "Google Chrome";v="{major}", '
                f'"Not-A.Brand";v="99"'
            )

        self.session.headers.clear()
        self.session.headers.update(headers)
        logger.debug("[HTML][SuperJob] Сессия настроена: UA=%s", ua[:60])

    def _warmup_session(self):
        if self._session_warmed:
            return
        try:
            logger.info("[HTML][SuperJob] Прогрев сессии: запрос главной страницы")
            self.session.headers['Sec-Fetch-Site'] = 'none'
            resp = self.session.get(
                self.BASE_URL, timeout=self.timeout, allow_redirects=True,
            )
            logger.info(
                "[HTML][SuperJob] Прогрев: status=%s, cookies=%s",
                resp.status_code, len(self.session.cookies),
            )
            time.sleep(random.uniform(_MIN_WARMUP_DELAY, _MAX_WARMUP_DELAY))
        except Exception as exc:
            logger.warning("[HTML][SuperJob] Ошибка прогрева сессии: %s", exc)
        self._session_warmed = True

    def _make_request(self, url: str) -> requests.Response:
        self._warmup_session()

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
                    reason = 'капча' if _is_captcha_page(response) else 'блокировка'
                    raise BlockedError(
                        f"Обнаружена {reason} для {url} "
                        f"(status={response.status_code}, url={response.url})"
                    )

                if response.status_code == 200:
                    self._last_request_url = url
                    return response

                response.raise_for_status()

            except BlockedError:
                raise
            except requests.Timeout as e:
                last_error = e
                logger.warning(
                    "[HTML][SuperJob] Таймаут %s (попытка %s/%s)",
                    url, attempt + 1, self.max_retries,
                )
            except requests.HTTPError as e:
                last_error = e
                logger.warning(
                    "[HTML][SuperJob] HTTP %s для %s (попытка %s/%s)",
                    e.response.status_code, url, attempt + 1, self.max_retries,
                )
            except requests.RequestException as e:
                last_error = e
                logger.warning(
                    "[HTML][SuperJob] Ошибка %s (попытка %s/%s): %s",
                    url, attempt + 1, self.max_retries, e,
                )

            if attempt < self.max_retries - 1:
                delay = min(2 ** attempt + random.uniform(0.5, 2.0), 15)
                time.sleep(delay)

        raise NetworkError(
            f"Не удалось выполнить запрос {url} "
            f"после {self.max_retries} попыток: {last_error}"
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        max_pages = config.get('max_pages')
        if max_pages is not None:
            try:
                if int(max_pages) < 1:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        logger.info("[HTML][SuperJob] Старт discovery c config=%s", config)
        items: List[Dict[str, str]] = []
        seen_ids: Set[str] = set()

        page = 1
        try:
            max_pages = int(config.get("max_pages", 10))
        except (TypeError, ValueError):
            max_pages = 10

        while page <= max_pages:
            try:
                search_url = self._build_search_url(config, page)
                logger.info(
                    "[HTML][SuperJob] Запрос страницы %s: %s", page, search_url,
                )
                response = self._make_request(search_url)
                html_text = response.text

                logger.debug(
                    "[HTML][SuperJob] Страница %s: status=%s, html_len=%s",
                    page, response.status_code, len(html_text),
                )
                soup = self._parse_html(html_text)

                page_links = self._extract_vacancy_links(soup, html_text)
                logger.info(
                    "[HTML][SuperJob] Найдено ссылок на странице %s: %s",
                    page, len(page_links),
                )
                if not page_links:
                    logger.info(
                        "[HTML][SuperJob] Ссылки не найдены на странице %s, завершаем",
                        page,
                    )
                    break

                for vacancy_url in page_links:
                    vacancy_id = self._extract_vacancy_id(vacancy_url)
                    if not vacancy_id or vacancy_id in seen_ids:
                        continue
                    seen_ids.add(vacancy_id)
                    items.append({
                        "source_item_id": vacancy_id,
                        "url": urljoin(self.BASE_URL, vacancy_url),
                    })

                page += 1

                if page <= max_pages:
                    delay = random.uniform(_MIN_PAGE_DELAY, _MAX_PAGE_DELAY)
                    logger.debug(
                        "[HTML][SuperJob] Задержка %.1f сек перед страницей %s",
                        delay, page,
                    )
                    time.sleep(delay)

            except BlockedError as exc:
                logger.error(
                    "[HTML][SuperJob] Блокировка при парсинге страницы %s: %s",
                    page, exc,
                )
                break
            except Exception as exc:
                logger.error(
                    "[HTML][SuperJob] Ошибка на странице %s: %s",
                    page, exc, exc_info=True,
                )
                break

        logger.info("[HTML][SuperJob] Discovery завершён: %s вакансий", len(items))
        return items

    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        return self.fetch_item(item_id, {'url': url})

    def fetch_item(self, item_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        url = config.get('url') or f"{self.BASE_URL}/vakansii/{item_id}.html"

        try:
            response = self._make_request(url)
            soup = self._parse_html(response.text)

            salary_data = self._extract_salary(soup)

            return {
                'source': 'superjob',
                'source_id': str(item_id),
                'source_url': url,
                'parsing_mode': 'html',
                'title': self._extract_title(soup),
                'description': self._extract_description(soup),
                'company_name': self._extract_company(soup),
                'company_url': None,
                'salary_from': salary_data.get('from') if salary_data else None,
                'salary_to': salary_data.get('to') if salary_data else None,
                'salary_currency': salary_data.get('currency', 'RUR') if salary_data else None,
                'salary_gross': False,
                'area_name': self._extract_area(soup),
                'address': None,
                'is_active': True,
                'archived': False,
            }
        except BlockedError:
            raise
        except Exception as e:
            from ...core.parsers.base import ParserError
            raise ParserError(
                f"Ошибка парсинга вакансии SuperJob {item_id}: {e}"
            )

    def _build_search_url(self, config: Dict[str, Any], page: int) -> str:
        params: Dict[str, Any] = {"page": page - 1}
        keywords = (
            config.get("keywords")
            or config.get("keyword")
            or config.get("text")
            or config.get("query")
        )
        if keywords:
            params["keywords"] = str(keywords).strip()
        return f"{self.BASE_URL}/vakansii/?{urlencode(params, doseq=True)}"

    def _extract_vacancy_links(
        self, soup: BeautifulSoup, html_text: str,
    ) -> List[str]:
        links: List[str] = []
        seen: Set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            if self._VACANCY_LINK_RE.match(href) and href not in seen:
                links.append(href)
                seen.add(href)

        for anchor in soup.select("a[href*='superjob.ru/vakansii/']"):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            for match in self._VACANCY_ABSOLUTE_RE.findall(href):
                if match not in seen:
                    links.append(match)
                    seen.add(match)

        for match in self._VACANCY_LINK_ANY_RE.findall(html_text):
            if match not in seen:
                links.append(match)
                seen.add(match)

        return links

    def _extract_vacancy_id(self, vacancy_url: str) -> Optional[str]:
        match = self._VACANCY_ID_RE.search(vacancy_url)
        if match:
            return match.group(1)

        old_match = self._VACANCY_ID_OLD_RE.search(vacancy_url)
        if old_match:
            return old_match.group(1)

        fallback = vacancy_url.split("/vakansii/")[-1].split(".html")[0]
        return fallback if fallback.isdigit() else None
