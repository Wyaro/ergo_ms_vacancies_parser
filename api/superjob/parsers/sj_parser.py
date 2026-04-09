"""
Синхронный парсер SuperJob API с поддержкой rate limiting и retry.

контроль частоты запросов,
exponential backoff, обработка ошибок API.
"""

import logging
import time
import random
from datetime import datetime
from typing import Dict, List, Optional, Any

import requests
from django.utils import timezone

from .utils import RateLimiter, ParsingMetrics
from modules.vacancies_parser.api.core.monitoring_utils import (
    increment_taskrun_counter,
    record_external_api_event,
)

logger = logging.getLogger('modules.vacancies_parser.superjob.parser')

EMPLOYMENT_TYPE_MAP = {
    6: 'Полный рабочий день',
    10: 'Неполный день',
    12: 'Сменный график',
    13: 'Частичная занятость',
    7: 'Временная работа',
    9: 'Вахтовый метод',
}

EXPERIENCE_MAP = {
    1: 'Без опыта',
    2: 'От 1 года',
    3: 'От 3 лет',
    4: 'От 6 лет',
}

PLACE_OF_WORK_MAP = {
    1: 'На территории работодателя',
    2: 'На дому',
    3: 'Разъездной характер',
}


class SuperJobParser:
    """
    Синхронный парсер SuperJob API с rate limiting и retry.

    Возможности:
    - Контроль частоты запросов (120 req/min)
    - Retry с exponential backoff
    - Парсинг данных в формат модели
    - Сбор метрик
    """

    BASE_URL = "https://api.superjob.ru/2.0"
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 2.0
    MAX_RETRY_DELAY = 60.0
    REQUEST_TIMEOUT = 30

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        metrics: Optional[ParsingMetrics] = None,
    ):
        self.api_key = api_key
        self.headers: Dict[str, str] = {}
        if api_key:
            self.headers['X-Api-App-Id'] = api_key
        self.rate_limiter = rate_limiter or RateLimiter()
        self.metrics = metrics or ParsingMetrics()

    def _make_request(
        self, url: str, params: Optional[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """HTTP GET с rate limiting и retry (exponential backoff)."""
        last_error = None

        for attempt in range(self.MAX_RETRIES):
            try:
                self.rate_limiter.wait()

                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=self.REQUEST_TIMEOUT,
                )

                if response.status_code == 429:
                    self.metrics.record_rate_limit()
                    increment_taskrun_counter('http_429', 1)
                    record_external_api_event(source='superjob', event_type='http_429', endpoint=url)
                    retry_after = int(response.headers.get('Retry-After', 60))
                    retry_after = min(retry_after, self.MAX_RETRY_DELAY)
                    logger.warning(
                        "Rate limit (429), ожидание %dс (попытка %d/%d)",
                        retry_after, attempt + 1, self.MAX_RETRIES,
                    )
                    time.sleep(retry_after)
                    continue

                if response.status_code == 403:
                    self.metrics.record_request(success=False)
                    logger.error("Доступ запрещён (403) для %s", url)
                    return None

                if response.status_code == 404:
                    self.metrics.record_request(success=True)
                    return None

                response.raise_for_status()
                self.metrics.record_request(success=True)
                return response.json()

            except requests.Timeout as e:
                last_error = e
                self.metrics.record_request(success=False)
                increment_taskrun_counter('timeouts', 1)
                record_external_api_event(source='superjob', event_type='timeout', endpoint=url)
                logger.warning(
                    "Timeout %s (попытка %d/%d)", url, attempt + 1, self.MAX_RETRIES
                )
            except requests.ConnectionError as e:
                last_error = e
                self.metrics.record_request(success=False)
                logger.warning("Ошибка соединения %s: %s", url, e)
            except requests.RequestException as e:
                last_error = e
                self.metrics.record_request(success=False)
                logger.warning("Ошибка запроса %s: %s", url, e)

            if attempt < self.MAX_RETRIES - 1:
                increment_taskrun_counter('retries', 1)
                delay = min(
                    self.BASE_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1),
                    self.MAX_RETRY_DELAY,
                )
                time.sleep(delay)

        logger.error(
            "Не удалось выполнить запрос %s после %d попыток: %s",
            url, self.MAX_RETRIES, last_error,
        )
        return None

    def search_vacancies(self, **kwargs) -> Dict[str, Any]:
        """Поиск вакансий через API SuperJob."""
        params = {'page': kwargs.get('page', 0), 'count': kwargs.get('count', 100)}

        param_mapping = {
            'keyword': 'keyword', 'town': 'town', 'experience': 'experience',
            'type_of_work': 'type_of_work', 'place_of_work': 'place_of_work',
            'catalogues': 'catalogues', 'payment_from': 'payment_from',
            'payment_to': 'payment_to',
        }
        for key, api_param in param_mapping.items():
            value = kwargs.get(key)
            if value is not None:
                params[api_param] = value

        result = self._make_request(f"{self.BASE_URL}/vacancies/", params=params)
        if result is None:
            return {"objects": [], "total": 0, "more": False}
        return result

    def get_vacancy_details(self, vacancy_id: str) -> Optional[Dict[str, Any]]:
        """Получение детальной информации о вакансии."""
        return self._make_request(f"{self.BASE_URL}/vacancies/{vacancy_id}/")

    def get_catalogues(self) -> List[Dict[str, Any]]:
        """Получение списка каталогов (отраслей)."""
        result = self._make_request(f"{self.BASE_URL}/catalogues/")
        return result if isinstance(result, list) else []

    @staticmethod
    def parse_vacancy_data(vacancy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсинг данных вакансии из ответа API в формат модели."""
        payment_from = vacancy_data.get('payment_from')
        payment_to = vacancy_data.get('payment_to')
        salary_from = payment_from if payment_from and payment_from > 0 else None
        salary_to = payment_to if payment_to and payment_to > 0 else None

        catalogues = vacancy_data.get('catalogues', [])
        professional_role = None
        catalogue_skills = []
        for catalogue in catalogues:
            if not professional_role and catalogue.get('title'):
                professional_role = catalogue['title']
            for position in catalogue.get('positions', []):
                if position.get('title'):
                    catalogue_skills.append(position['title'])

        published_at = _parse_unixtime(vacancy_data.get('date_published'))
        if not published_at:
            published_at = timezone.now()

        return {
            'title': vacancy_data.get('profession', ''),
            'company_name': vacancy_data.get('firm_name', ''),
            'salary_from': salary_from,
            'salary_to': salary_to,
            'salary_currency': vacancy_data.get('currency'),
            'salary_gross': not vacancy_data.get('agreement', False),
            'city': _extract_object_field(vacancy_data, 'town'),
            'address': vacancy_data.get('address') or '',
            'description': _build_full_description(vacancy_data),
            'requirements': vacancy_data.get('candidat', ''),
            'responsibilities': vacancy_data.get('work', ''),
            'employment_type': _map_object_field(vacancy_data, 'type_of_work', EMPLOYMENT_TYPE_MAP),
            'experience_level': _map_object_field(vacancy_data, 'experience', EXPERIENCE_MAP),
            'schedule_type': _map_object_field(vacancy_data, 'place_of_work', PLACE_OF_WORK_MAP),
            'skills': catalogue_skills,
            'key_skills': [],
            'superjob_id': str(vacancy_data.get('id', '')),
            'url': vacancy_data.get('link', ''),
            'company_url': vacancy_data.get('client_logo') or None,
            'professional_role': professional_role,
            'employer_id': str(vacancy_data.get('id_client', '')),
            'employer_name': vacancy_data.get('firm_name', ''),
            'employer_trusted': False,
            'premium': False,
            'published_at': published_at,
        }


def _parse_unixtime(timestamp) -> Optional[datetime]:
    if not timestamp:
        return None
    try:
        dt = datetime.fromtimestamp(int(timestamp))
        return timezone.make_aware(dt)
    except (ValueError, TypeError, OSError):
        return None


def _extract_object_field(data: Dict, field_name: str) -> Optional[str]:
    obj = data.get(field_name)
    if isinstance(obj, dict):
        return obj.get('title')
    return None


def _map_object_field(data: Dict, field_name: str, mapping: Dict) -> Optional[str]:
    obj = data.get(field_name)
    if not isinstance(obj, dict):
        return None
    obj_id = obj.get('id')
    if obj_id in mapping:
        return mapping[obj_id]
    return obj.get('title')


def _build_full_description(vacancy_data: Dict[str, Any]) -> str:
    sections = []
    for key, label in [('work', 'Обязанности'), ('candidat', 'Требования'),
                        ('compensation', 'Условия'), ('firm_activity', 'О компании')]:
        value = vacancy_data.get(key)
        if value:
            sections.append(f"{label}:\n{value}")
    return '\n\n'.join(sections)
