"""
Парсер для работы с API HeadHunter.

Содержит основной класс HeadHunterParser для взаимодействия с API.
"""

import re
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import SSLError as RequestsSSLError
import ssl
from typing import Optional, Dict, Any, List
from datetime import datetime
from django.utils import timezone

from .utils import ProxyRotator, UserAgentRotator, RequestJitter, ParsingMetrics, IPBlockingTracker
from ..models import Vacancy
from modules.vacancies_parser.api.core.monitoring_utils import (
    increment_taskrun_counter,
    record_external_api_event,
)

logger = logging.getLogger('modules.vacancies_parser.headhunter')


def _format_duration(seconds: float) -> str:
    """Форматирует длительность для логов только в секундах."""
    return f"{seconds:.2f} сек"


class HeadHunterParser:
    """Парсер для работы с API HeadHunter с ротацией User-Agent и jitter"""

    # Константы для rate limiting
    MAX_RETRIES = 3
    BASE_DELAY = 0.75
    MAX_DELAY = 45.0
    
    # Лимит API HeadHunter: 30 запросов в секунду
    API_RATE_LIMIT_PER_SECOND = 30
    MIN_DELAY_BETWEEN_REQUESTS = 1.0 / 30  # ≈ 0.033 сек
    SAFE_MIN_DELAY = 0.03  # 3/4 от исходного 0.04; лимит API контролируется _enforce_rate_limit

    def __init__(self, metrics: Optional[ParsingMetrics] = None, use_jitter: bool = True,
                 rotate_user_agent: bool = True, use_proxy: bool = False,
                 custom_proxies: Optional[List[Dict[str, str]]] = None):
        self.base_url = "https://api.hh.ru"
        self.metrics = metrics or ParsingMetrics()
        self.use_jitter = use_jitter
        self.rotate_user_agent = rotate_user_agent
        self.use_proxy = use_proxy

        # Инициализация компонентов
        self.ua_rotator = UserAgentRotator() if rotate_user_agent else None
        self.jitter = RequestJitter(base_delay=self.BASE_DELAY) if use_jitter else None
        self.proxy_rotator = ProxyRotator(custom_proxies) if use_proxy else None
        self.blocking_tracker = IPBlockingTracker()

        # Счетчики для ротации
        self.requests_since_ua_rotation = 0
        self.requests_since_proxy_rotation = 0
        self.session_start_time = time.time()
        
        # Трекер времени последнего запроса для контроля rate limit
        self._last_request_time = 0.0
        self._request_times = []  # Список времен последних запросов (скользящее окно)

        # Начальный User-Agent (должен быть вызван до создания сессии)
        self._update_headers()
        
        # Создаем HTTP сессию для переиспользования соединений
        # Увеличиваем размер connection pool для избежания предупреждений
        adapter = HTTPAdapter(
            pool_connections=20,  # Количество пулов соединений
            pool_maxsize=50,  # Максимальное количество соединений в пуле
            max_retries=3
        )
        self.session = requests.Session()
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update(self.headers)

    def _update_headers(self):
        """Обновить заголовки с новым User-Agent"""
        # Получаем User-Agent (с fallback если rotator не инициализирован)
        if self.ua_rotator:
            try:
                user_agent = self.ua_rotator.get_random_user_agent()
            except Exception:
                user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        else:
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

        # Всегда создаем headers (даже если что-то пошло не так)
        self.headers = {
            'User-Agent': user_agent,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Обновляем заголовки сессии (если она уже создана)
        if hasattr(self, 'session') and self.session:
            self.session.headers.update(self.headers)

    def _should_rotate_user_agent(self) -> bool:
        """Определить, нужно ли ротировать User-Agent"""
        if not self.ua_rotator:
            return False

        time_since_rotation = time.time() - self.ua_rotator.last_rotation
        return self.ua_rotator.should_rotate(self.requests_since_ua_rotation, time_since_rotation)

    def _should_rotate_proxy(self) -> bool:
        """Определить, нужно ли ротировать прокси"""
        if not self.proxy_rotator:
            return False

        time_since_rotation = time.time() - self.proxy_rotator.last_rotation
        return self.proxy_rotator.should_rotate(self.requests_since_proxy_rotation, time_since_rotation)

    def _rotate_user_agent(self):
        """Ротировать User-Agent"""
        if self.ua_rotator:
            old_ua = self.headers.get('User-Agent', '').split(' ')[0]
            self._update_headers()
            new_ua = self.headers.get('User-Agent', '').split(' ')[0]
            logger.debug(f'Ротирован User-Agent: {old_ua} -> {new_ua}')
            self.ua_rotator.last_rotation = time.time()
            self.requests_since_ua_rotation = 0

    def _rotate_proxy(self):
        """Ротировать прокси"""
        if self.proxy_rotator:
            old_proxy = getattr(self, '_current_proxy', None)
            self._current_proxy = self.proxy_rotator.get_random_proxy()
            logger.debug(f'Ротирован прокси: {old_proxy} -> {self._current_proxy}')
            self.proxy_rotator.last_rotation = time.time()
            self.requests_since_proxy_rotation = 0

    def _get_current_proxy(self) -> Optional[Dict[str, str]]:
        """Получить текущий прокси"""
        if not self.use_proxy or not self.proxy_rotator:
            return None

        if not hasattr(self, '_current_proxy') or self._current_proxy is None:
            self._current_proxy = self.proxy_rotator.get_random_proxy()

        return self._current_proxy

    def _recreate_session(self):
        """Закрывает текущую сессию и создает новую."""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
                logger.debug("Старая HTTP-сессия закрыта.")
            except Exception as e:
                logger.warning(f"Ошибка при закрытии старой сессии: {e}")
        
        # Создаем новую сессию с увеличенным connection pool
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=50,
            max_retries=3
        )
        self.session = requests.Session()
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update(self.headers)
        logger.debug("Новая HTTP-сессия создана.")

    def _get_delay(self, is_page_turn: bool = False, is_detail_request: bool = False) -> float:
        """Получить задержку между запросами с учетом типа запроса и лимита API"""
        if not self.use_jitter or not self.jitter:
            base_delay = self.BASE_DELAY
        elif is_page_turn:
            base_delay = self.jitter.get_page_turn_delay()
        elif is_detail_request:
            base_delay = self.jitter.get_detail_request_delay()
        else:
            base_delay = self.jitter.get_delay()
        
        # Убеждаемся, что задержка не меньше безопасного минимума для соблюдения лимита API
        return max(base_delay, self.SAFE_MIN_DELAY)
    
    def _enforce_rate_limit(self) -> float:
        """
        Обеспечивает соблюдение лимита 30 запросов в секунду.
        Возвращает необходимую задержку перед следующим запросом.
        """
        current_time = time.time()
        
        # Очищаем старые записи (старше 1 секунды)
        self._request_times = [t for t in self._request_times if current_time - t < 1.0]
        
        # Если уже достигли лимита (30 запросов за последнюю секунду), ждем
        if len(self._request_times) >= self.API_RATE_LIMIT_PER_SECOND:
            # Вычисляем, сколько нужно подождать до освобождения слота
            oldest_request_time = min(self._request_times)
            wait_time = 1.0 - (current_time - oldest_request_time)
            if wait_time > 0:
                logger.debug(
                    "Rate limit: достигнут лимит %d запросов/сек, ожидание %s",
                    self.API_RATE_LIMIT_PER_SECOND,
                    _format_duration(wait_time),
                )
                return max(wait_time, self.SAFE_MIN_DELAY)
        
        # Добавляем текущий запрос в список
        self._request_times.append(current_time)
        
        # Если с последнего запроса прошло меньше минимальной задержки, возвращаем необходимую задержку
        if self._last_request_time > 0:
            time_since_last = current_time - self._last_request_time
            if time_since_last < self.SAFE_MIN_DELAY:
                return self.SAFE_MIN_DELAY - time_since_last
        
        self._last_request_time = current_time
        return 0.0  # Задержка не нужна
    
    def _make_request(
        self,
        url: str,
        params: Optional[Dict] = None,
        max_retries: Optional[int] = None,
        is_page_turn: bool = False,
        is_detail_request: bool = False
    ) -> Optional[Dict]:
        """
        Выполнить HTTP-запрос с обработкой rate limiting, ротацией User-Agent и jitter.

        Args:
            url: URL для запроса
            params: Параметры запроса
            max_retries: Максимальное количество попыток
            is_page_turn: Запрос на следующую страницу
            is_detail_request: Запрос деталей вакансии

        Returns:
            JSON-ответ или None при ошибке
        """
        max_retries = max_retries or self.MAX_RETRIES
        last_error = None
        current_proxy = None  # Инициализируем перед циклом

        # Ротируем User-Agent и прокси если нужно
        if self._should_rotate_user_agent():
            self._rotate_user_agent()

        if self._should_rotate_proxy():
            self._rotate_proxy()

        for attempt in range(max_retries):
            try:
                # Обеспечиваем соблюдение лимита 30 запросов в секунду
                rate_limit_delay = self._enforce_rate_limit()
                if rate_limit_delay > 0:
                    time.sleep(rate_limit_delay)
                
                # Добавляем jitter задержку перед запросом (кроме первого)
                if attempt > 0 or self.requests_since_ua_rotation > 0:
                    delay = self._get_delay(is_page_turn, is_detail_request)
                    # Увеличиваем задержку при наличии блокировок
                    adaptive_multiplier = self.blocking_tracker.get_adaptive_delay_multiplier()
                    delay *= adaptive_multiplier
                    # Убеждаемся, что итоговая задержка не меньше безопасного минимума
                    delay = max(delay, self.SAFE_MIN_DELAY)
                    time.sleep(delay)
                    logger.debug(
                        "Jitter delay: %s (множитель: %.1fx)",
                        _format_duration(delay),
                        adaptive_multiplier,
                    )

                # Получаем текущий прокси
                current_proxy = self._get_current_proxy()
                self.requests_since_ua_rotation += 1
                self.requests_since_proxy_rotation += 1

                # Используем сессию для переиспользования соединений
                try:
                    response = self.session.get(url, params=params, proxies=current_proxy, timeout=22.5)
                except (requests.ConnectionError, requests.RequestException) as session_error:
                    # Если ошибка сессии, создаем новую сессию и повторяем попытку
                    error_msg = str(session_error).lower()
                    if 'connection' in error_msg and ('closed' in error_msg or 'reset' in error_msg):
                        logger.warning(f"Соединение закрыто, создаем новую сессию (попытка {attempt + 1}/{max_retries})")
                        self.session.close()
                        self.session = requests.Session()
                        self.session.headers.update(self.headers)
                        # Повторяем запрос с новой сессией
                        response = self.session.get(url, params=params, proxies=current_proxy, timeout=22.5)
                    else:
                        raise

                # Обработка rate limiting (429 Too Many Requests)
                if response.status_code == 429:
                    self.metrics.record_rate_limit()
                    increment_taskrun_counter('http_429', 1)
                    record_external_api_event(source='headhunter', event_type='http_429', endpoint=url)
                    retry_after = int(response.headers.get('Retry-After', 60))
                    retry_after = min(retry_after, self.MAX_DELAY)
                    logger.warning(
                        "Rate limit достигнут (попытка %d/%d), ожидание %s...",
                        attempt + 1, max_retries, _format_duration(float(retry_after))
                    )
                    time.sleep(retry_after)
                    # При rate limit ротируем User-Agent и прокси
                    self._rotate_user_agent()
                    if self.use_proxy:
                        self._rotate_proxy()
                    continue
                
                # Обработка 403 Forbidden (возможно бан)
                if response.status_code == 403:
                    self.metrics.record_request(success=False)
                    self.metrics.record_error(f"403 Forbidden для {url}")
                    
                    # Записываем факт блокировки в глобальный трекер
                    self.blocking_tracker.record_403()
                    
                    # Логируем только каждую 5-ю ошибку 403, чтобы не засорять логи
                    if self.blocking_tracker._403_count % 5 == 0 or self.blocking_tracker._403_count <= 3:
                        logger.warning(
                            "Доступ запрещён (403) для %s. Всего 403 ошибок: %d. Пауза %s...",
                            url,
                            self.blocking_tracker._403_count,
                            _format_duration(2.0),
                        )
                    time.sleep(1.5)

                    # Ротируем User-Agent и прокси при 403
                    self._rotate_user_agent()
                    if self.use_proxy:
                        self._rotate_proxy()
                    continue
                
                # Успешный запрос
                response.raise_for_status()
                self.metrics.record_request(success=True)
                # Сбрасываем счетчик блокировок при успешном запросе
                self.blocking_tracker.reset_on_success()
                return response.json()
                
            except requests.Timeout as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(f"Timeout для {url}")
                increment_taskrun_counter('timeouts', 1)
                record_external_api_event(source='headhunter', event_type='timeout', endpoint=url)
                logger.warning("Timeout при запросе %s (попытка %d/%d)", url, attempt + 1, max_retries)
                
            except (RequestsSSLError, ssl.SSLError) as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(f"SSL error для {url}")
                logger.warning("SSL ошибка для %s (попытка %d/%d): %s", url, attempt + 1, max_retries, str(e)[:100])
                
                # Пересоздаем сессию при SSL ошибках
                self._recreate_session()
                
                # Ротируем прокси при SSL ошибке
                if self.use_proxy and self.proxy_rotator and current_proxy:
                    self.proxy_rotator.mark_proxy_failed(current_proxy)
                    self._rotate_proxy()
                    
            except requests.ConnectionError as e:
                last_error = e
                self.metrics.record_request(success=False)
                error_msg = str(e).lower()
                
                # Обработка "connection already closed" или "connection broken" - пересоздаем сессию
                if 'connection' in error_msg and ('closed' in error_msg or 'reset' in error_msg or 'broken' in error_msg):
                    logger.warning("Соединение закрыто, пересоздаем сессию (попытка %d/%d)", attempt + 1, max_retries)
                    self._recreate_session()
                else:
                    self.metrics.record_error(f"Connection error для {url}")
                    logger.warning("Ошибка соединения %s (попытка %d/%d)", url, attempt + 1, max_retries)

                # Ротируем прокси при ошибке соединения
                if self.use_proxy and self.proxy_rotator and current_proxy:
                    self.proxy_rotator.mark_proxy_failed(current_proxy)
                    self._rotate_proxy()

            except requests.HTTPError as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(f"HTTP error {e.response.status_code} для {url}")
                logger.warning("HTTP ошибка %s: %s", url, e)
                
            except requests.RequestException as e:
                last_error = e
                self.metrics.record_request(success=False)
                self.metrics.record_error(str(e))
                logger.warning("Ошибка запроса %s: %s", url, e)
            
            # Exponential backoff перед следующей попыткой
            if attempt < max_retries - 1:
                increment_taskrun_counter('retries', 1)
                delay = min(self.BASE_DELAY * (2 ** attempt), self.MAX_DELAY)
                logger.debug("Ожидание %s перед повторной попыткой...", _format_duration(delay))
                time.sleep(delay)
        
        # Все попытки исчерпаны
        # Логируем только для детальных запросов или если это не 403 ошибка
        if is_detail_request or (last_error and '403' not in str(last_error)):
            logger.error("Не удалось выполнить запрос %s после %d попыток: %s", url, max_retries, last_error)
        else:
            logger.debug("Не удалось выполнить запрос %s после %d попыток (403): %s", url, max_retries, last_error)
        
        # Пересоздаем сессию при полном провале всех попыток
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        
        return None
    
    def __del__(self):
        """Закрываем сессию при удалении объекта"""
        if hasattr(self, 'session'):
            try:
                self.session.close()
            except Exception:
                pass
    
    def search_vacancies(self, text=None, area=None, experience=None, employment=None,
                        schedule=None, professional_role=None, per_page=100, page=0,
                        only_with_salary=False, date_from=None, date_to=None):
        """
        Поиск вакансий по параметрам

        Args:
            text (str): Текст для поиска (может содержать несколько слов)
            area (int): ID региона (1 - Москва, 2 - СПб, 113 - Россия)
            experience (str): Опыт работы (noExperience, between1And3, between3And6, moreThan6)
            employment (str): Тип занятости (full, part, project, volunteer, probation)
            schedule (str): График работы (fullDay, shift, flexible, remote, flyInFlyOut)
            professional_role (int): ID профессиональной роли
            per_page (int): Количество вакансий на странице (максимум 100)
            page (int): Номер страницы
            only_with_salary (bool): Только вакансии с указанной зарплатой
            date_from (str): Дата публикации от (формат YYYY-MM-DD)
            date_to (str): Дата публикации до (формат YYYY-MM-DD)
        """
        params = {
            'per_page': per_page,
            'page': page,
            'order_by': 'publication_time'
        }
        
        # Фильтр по зарплате (опционально)
        if only_with_salary:
            params['only_with_salary'] = True
        
        if text:
            params['text'] = text
        if area:
            params['area'] = area
        if experience:
            params['experience'] = experience
        if employment:
            params['employment'] = employment
        if schedule:
            params['schedule'] = schedule
        if professional_role:
            params['professional_role'] = professional_role
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to

        # Добавляем jitter для страниц после первой (имитация чтения)
        is_page_turn = page > 0
        return self._make_request(f"{self.base_url}/vacancies", params=params, is_page_turn=is_page_turn)
    
    def get_vacancy_details(self, vacancy_id):
        """Получение детальной информации о вакансии"""
        return self._make_request(f"{self.base_url}/vacancies/{vacancy_id}", is_detail_request=True)
    
    def check_vacancy_exists(self, vacancy_id) -> Optional[Dict]:
        """
        Проверить, существует ли вакансия и не архивирована ли она.
        
        Args:
            vacancy_id: ID вакансии на hh.ru
            
        Returns:
            Dict с информацией или None если вакансия не найдена/архивирована
        """
        result = self._make_request(f"{self.base_url}/vacancies/{vacancy_id}")
        if result and result.get('archived'):
            return None
        return result
    
    def parse_vacancy(self, vacancy_data):
        """Парсинг данных вакансии в модель"""
        if not vacancy_data:
            logger.error("Ошибка: vacancy_data is None")
            return None
            
        try:
            # Парсим зарплату (безопасно обрабатываем null)
            salary = vacancy_data.get('salary') or {}
            salary_from = salary.get('from')
            salary_to = salary.get('to')
            salary_currency = salary.get('currency')
            salary_gross = salary.get('gross', True)
            
            # Парсим локацию (безопасно обрабатываем null)
            area = vacancy_data.get('area') or {}
            city = area.get('name')
            
            # Парсим компанию (безопасно обрабатываем null)
            employer = vacancy_data.get('employer') or {}
            company_name = employer.get('name', 'Не указано')
            company_url = employer.get('alternate_url')
            employer_id = employer.get('id')
            employer_trusted = employer.get('trusted', False)
            employer_blacklisted = employer.get('blacklisted', False)
            
            # Парсим навыки
            key_skills = [skill.get('name', '') for skill in vacancy_data.get('key_skills', [])]
            
            # Парсим дату публикации
            published_at_str = vacancy_data.get('published_at')
            if published_at_str:
                # Убираем 'Z' и парсим дату
                if published_at_str.endswith('Z'):
                    published_at_str = published_at_str[:-1] + '+00:00'
                
                try:
                    published_at = datetime.fromisoformat(published_at_str)
                    # Если дата уже содержит часовой пояс, не делаем её aware
                    if published_at.tzinfo is None:
                        published_at = timezone.make_aware(published_at)
                except ValueError:
                    published_at = timezone.now()
            else:
                published_at = timezone.now()
            
            # Получаем описание и извлекаем секции
            description = vacancy_data.get('description', '')
            
            # Сначала пробуем получить из snippet (обрезанные данные)
            snippet = vacancy_data.get('snippet')
            requirements = self._get_snippet_field(snippet, 'requirement')
            responsibilities = self._get_snippet_field(snippet, 'responsibility')
            
            # Если есть полное описание, пробуем извлечь полные данные
            if description:
                extracted = self._extract_sections_from_description(description)
                if extracted['requirements'] and len(extracted['requirements']) > len(requirements or ''):
                    requirements = extracted['requirements']
                if extracted['responsibilities'] and len(extracted['responsibilities']) > len(responsibilities or ''):
                    responsibilities = extracted['responsibilities']
            else:
                # Фоллбек: строим описание из snippet, чтобы не терять текст при get_details=False
                description = self._build_description_from_snippet(snippet)
            
            # Создаем объект вакансии с полными данными
            vacancy = Vacancy(
                title=vacancy_data.get('name', 'Без названия'),
                company_name=company_name,
                salary_from=salary_from,
                salary_to=salary_to,
                salary_currency=salary_currency,
                salary_gross=salary_gross,
                city=city,
                address=self._get_address_raw(vacancy_data.get('address')),
                description=description,
                requirements=requirements,
                responsibilities=responsibilities,
                employment_type=(vacancy_data.get('employment') or {}).get('name'),
                experience_level=(vacancy_data.get('experience') or {}).get('name'),
                skills=[],
                key_skills=key_skills,
                hh_id=vacancy_data['id'],
                url=vacancy_data.get('alternate_url', ''),
                company_url=company_url,
                # Дополнительные поля
                schedule_type=(vacancy_data.get('schedule') or {}).get('name'),
                professional_role=self._get_professional_role_name(vacancy_data.get('professional_roles', [])),
                alternate_url=vacancy_data.get('alternate_url', ''),
                apply_alternate_url=vacancy_data.get('apply_alternate_url', ''),
                # Информация о работодателе
                employer_id=employer_id,
                employer_name=company_name,
                employer_trusted=employer_trusted,
                employer_blacklisted=employer_blacklisted,
                # Дополнительная информация
                premium=vacancy_data.get('premium', False),
                has_test=vacancy_data.get('has_test', False),
                response_letter_required=vacancy_data.get('response_letter_required', False),
                published_at=published_at
            )
            
            return vacancy
            
        except Exception as e:
            logger.error("Ошибка при парсинге вакансии %s: %s", vacancy_data.get('id', 'unknown'), e)
            return None
    
    def _get_professional_role_name(self, professional_roles):
        """Безопасное извлечение названия профессиональной роли"""
        try:
            if professional_roles and len(professional_roles) > 0:
                first_role = professional_roles[0]
                if isinstance(first_role, dict):
                    return first_role.get('name')
            return None
        except Exception:
            return None
    
    def _get_address_raw(self, address_data):
        """Безопасное извлечение адреса"""
        try:
            if address_data and isinstance(address_data, dict):
                return address_data.get('raw')
            return None
        except Exception:
            return None
    
    def _get_snippet_field(self, snippet_data, field_name):
        """Безопасное извлечение поля из snippet"""
        try:
            if snippet_data and isinstance(snippet_data, dict):
                return snippet_data.get(field_name, '')
            return ''
        except Exception:
            return ''

    def _build_description_from_snippet(self, snippet_data: Optional[Dict[str, Any]]) -> str:
        """
        Строит текст описания из snippet, если полного описания нет.
        """
        if not snippet_data or not isinstance(snippet_data, dict):
            return ''

        parts: List[str] = []
        req = snippet_data.get('requirement')
        resp = snippet_data.get('responsibility')

        if req:
            parts.append(f'Требования: {req}')
        if resp:
            parts.append(f'Обязанности: {resp}')

        return '\n'.join(parts)
    
    def _extract_sections_from_description(self, description_html):
        """
        Извлечение требований и обязанностей из полного HTML-описания вакансии.
        
        Args:
            description_html (str): HTML-описание вакансии
            
        Returns:
            dict: Словарь с ключами 'requirements' и 'responsibilities'
        """
        result = {
            'requirements': '',
            'responsibilities': ''
        }
        
        if not description_html:
            return result
        
        try:
            # Паттерны для поиска секций (различные варианты написания)
            requirements_patterns = [
                r'(?:требования|требуется|ожидания|что мы ждём|ждём от вас|вы нам подходите|наши требования|мы ожидаем|что нужно знать|необходимые навыки|обязательно)[:\s]*</(?:strong|b|p|h\d)>(.+?)(?=<(?:strong|b|p|h\d)[^>]*>(?:обязанности|условия|мы предлагаем|что предлагаем|будет плюсом|преимущества)|$)',
                r'<(?:strong|b)[^>]*>(?:требования|требуется|ожидания)[^<]*</(?:strong|b)>(.+?)(?=<(?:strong|b)[^>]*>|$)',
            ]
            
            responsibilities_patterns = [
                r'(?:обязанности|задачи|вам предстоит|чем предстоит заниматься|что нужно делать|будете заниматься|ваши задачи|основные задачи)[:\s]*</(?:strong|b|p|h\d)>(.+?)(?=<(?:strong|b|p|h\d)[^>]*>(?:требования|условия|мы предлагаем|что предлагаем)|$)',
                r'<(?:strong|b)[^>]*>(?:обязанности|задачи|вам предстоит)[^<]*</(?:strong|b)>(.+?)(?=<(?:strong|b)[^>]*>|$)',
            ]
            
            # Пробуем найти требования
            for pattern in requirements_patterns:
                match = re.search(pattern, description_html, re.IGNORECASE | re.DOTALL)
                if match:
                    requirements_html = match.group(1)
                    result['requirements'] = self._html_to_text(requirements_html)
                    break
            
            # Пробуем найти обязанности
            for pattern in responsibilities_patterns:
                match = re.search(pattern, description_html, re.IGNORECASE | re.DOTALL)
                if match:
                    responsibilities_html = match.group(1)
                    result['responsibilities'] = self._html_to_text(responsibilities_html)
                    break
            
        except Exception as e:
            logger.warning("Ошибка при извлечении секций из описания: %s", e)
        
        return result
    
    def _html_to_text(self, html_content):
        """
        Конвертирует HTML в чистый текст.
        
        Args:
            html_content (str): HTML-контент
            
        Returns:
            str: Чистый текст
        """
        if not html_content:
            return ''
        
        try:
            # Заменяем теги списков на переносы строк
            text = re.sub(r'<li[^>]*>', '• ', html_content)
            text = re.sub(r'</li>', '\n', text)
            text = re.sub(r'<br\s*/?>', '\n', text)
            text = re.sub(r'</p>', '\n', text)
            text = re.sub(r'</div>', '\n', text)
            
            # Убираем все оставшиеся HTML-теги
            text = re.sub(r'<[^>]+>', '', text)
            
            # Декодируем HTML-сущности
            text = text.replace('&nbsp;', ' ')
            text = text.replace('&amp;', '&')
            text = text.replace('&lt;', '<')
            text = text.replace('&gt;', '>')
            text = text.replace('&quot;', '"')
            text = text.replace('&#39;', "'")
            
            # Убираем множественные пробелы и переносы
            text = re.sub(r'[ \t]+', ' ', text)
            text = re.sub(r'\n\s*\n', '\n', text)
            text = text.strip()
            
            return text
        except Exception:
            return ''
    
    def get_areas(self):
        """Получение списка всех регионов"""
        areas = self._make_request(f"{self.base_url}/areas")
        
        if not areas:
            # Возвращаем основные регионы по умолчанию
            return [
                {'id': 113, 'name': 'Россия', 'type': 'country'},
                {'id': 1, 'name': 'Москва', 'type': 'city'},
                {'id': 2, 'name': 'Санкт-Петербург', 'type': 'city'},
            ]
        
        # Извлекаем основные регионы (страны и крупные города)
        main_areas = []
        
        for country in areas:
            if country['name'] in ['Россия', 'Российская Федерация']:
                main_areas.append({
                    'id': country['id'],
                    'name': country['name'],
                    'type': 'country'
                })
                
                # Добавляем крупные города России
                for region in country.get('areas', []):
                    if region['name'] in ['Москва', 'Санкт-Петербург', 'Новосибирск', 'Екатеринбург', 'Казань', 'Нижний Новгород']:
                        main_areas.append({
                            'id': region['id'],
                            'name': region['name'],
                            'type': 'city'
                        })
        
        return main_areas
    
    def get_professional_roles(self, category_id: Optional[str] = None):
        """
        Получение списка профессиональных ролей.

        Args:
            category_id: ID категории для фильтрации (например, '11' для IT).
                        Если не задан, возвращаются все роли всех категорий.
        """
        roles = self._make_request(f"{self.base_url}/professional_roles")
        
        if not roles:
            return []
        
        categories = roles.get('categories', [])

        if category_id:
            target_category = next(
                (category for category in categories if str(category.get('id')) == str(category_id)),
                None
            )
            if not target_category:
                logger.warning('Категория профессиональных ролей %s не найдена', category_id)
                return []

            return [
                {
                    'id': role['id'],
                    'name': role['name']
                }
                for role in target_category.get('roles', [])
            ]

        # Получаем все роли
        all_roles = []
        for category in categories:
            for role in category.get('roles', []):
                all_roles.append({
                    'id': role['id'],
                    'name': role['name']
                })

        return all_roles
    
    def search_all_vacancies(self, area_id, page=0, per_page=100):
        """Поиск всех вакансий в регионе"""
        params = {
            'per_page': per_page,
            'page': page,
            'area': area_id,
            'order_by': 'publication_time'
        }
        return self._make_request(f"{self.base_url}/vacancies", params=params)

