"""
API парсеры для HeadHunter, Habr Career, SuperJob.

Используют официальные API источников для получения данных.
"""

import logging
import requests
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

from .base import (
    BaseParser,
    ParserFactory,
    ParserError,
    BlockedError,
    NetworkError,
    ValidationError
)

logger = logging.getLogger('celery.module.vacancies_parser')


class HeadHunterAPIParser(BaseParser):
    """
    Парсер HeadHunter через официальный API (https://api.hh.ru).
    
    Endpoints:
    - /vacancies - поиск вакансий
    - /vacancies/{id} - детальная информация
    - /professional_roles - список ролей
    """
    
    BASE_URL = "https://api.hh.ru"
    
    def __init__(self, source='headhunter', parsing_mode='api', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ErgoMS Vacancy Parser/1.0 (igoroffrus@mail.ru)'
        })

    def _get_with_retry(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                return response
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                last_error = e
                self.logger.warning(
                    f"SSL/сетевая ошибка для {url} (попытка {attempt + 1}/{self.max_retries}): {e}"
                )
            except requests.exceptions.Timeout as e:
                last_error = e
                self.logger.warning(
                    f"Таймаут для {url} (попытка {attempt + 1}/{self.max_retries})"
                )
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(
                    f"Ошибка запроса {url} (попытка {attempt + 1}/{self.max_retries}): {e}"
                )
            if attempt < self.max_retries - 1:
                delay = min(2 ** attempt, 10)
                time.sleep(delay)
        raise NetworkError(f"Не удалось выполнить запрос {url} после {self.max_retries} попыток: {last_error}")

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Валидация конфигурации для HeadHunter API.
        
        Требуемые поля:
        - area: ID региона (например, 1 для Москвы)
        - per_page: количество вакансий на страницу (по умолчанию 100)
        - pages: количество страниц для парсинга
        
        Опциональные:
        - professional_role: ID профессиональной роли
        - text: текст для поиска
        - specialization: ID специализации
        """
        required_fields = ['area']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Отсутствует обязательное поле в config: {field}")
        
        # Валидация типов
        if not isinstance(config.get('pages', 1), int):
            raise ValueError("Поле 'pages' должно быть числом")
        
        if config.get('pages', 1) < 1:
            raise ValueError("Поле 'pages' должно быть больше 0")
        
        return True
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Обнаружение вакансий через HeadHunter API.
        
        Args:
            config: {
                'area': '1',  # ID региона
                'pages': 10,  # Количество страниц
                'per_page': 100,  # Вакансий на страницу
                'professional_role': '96',  # Опционально
                'text': 'python',  # Опционально
            }
        
        Returns:
            List[Dict]: [{'source_item_id': '12345', 'url': 'https://hh.ru/vacancy/12345'}, ...]
        """
        self.validate_config(config)
        
        items = []
        area = config['area']
        pages = config.get('pages', 1)
        per_page = config.get('per_page', 100)
        
        # Параметры поиска
        search_params = {
            'area': area,
            'per_page': per_page,
            'only_with_salary': False,
        }
        
        # Опциональные параметры
        if 'professional_role' in config:
            search_params['professional_role'] = config['professional_role']
        
        if 'text' in config:
            search_params['text'] = config['text']
        
        if 'specialization' in config:
            search_params['specialization'] = config['specialization']
        
        self.logger.info(f"Начало discovery для HeadHunter API: {search_params}")
        
        for page in range(pages):
            search_params['page'] = page

            try:
                response = self._get_with_retry(
                    f"{self.BASE_URL}/vacancies",
                    params=search_params
                )

                if response.status_code == 403:
                    raise BlockedError("Доступ заблокирован HeadHunter API (403)")
                
                if response.status_code == 429:
                    self.logger.warning("Rate limit превышен, ждем 1 минуту")
                    time.sleep(60)
                    continue
                
                response.raise_for_status()
                data = response.json()
                
                vacancies = data.get('items', [])
                
                for vacancy in vacancies:
                    vacancy_id = str(vacancy.get('id'))
                    url = vacancy.get('alternate_url', f"https://hh.ru/vacancy/{vacancy_id}")
                    
                    items.append({
                        'source_item_id': vacancy_id,
                        'url': url
                    })
                
                self.logger.info(
                    f"Discovery HeadHunter: страница {page+1}/{pages}, "
                    f"найдено {len(vacancies)} вакансий"
                )
                
                # Задержка между запросами
                time.sleep(config.get('delay', 0.5))
                
            except requests.RequestException as e:
                self.logger.error(f"Ошибка при discovery HeadHunter: {e}")
                raise NetworkError(f"Ошибка сети при discovery: {e}")
        
        self.logger.info(f"Discovery HeadHunter завершен: найдено {len(items)} вакансий")
        return items
    
    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        """
        Парсинг одной вакансии HeadHunter.
        
        Args:
            item_id: ID вакансии на HeadHunter
            url: URL вакансии (используется для fallback)
        
        Returns:
            Dict: Нормализованные данные вакансии
        """
        try:
            response = self._get_with_retry(f"{self.BASE_URL}/vacancies/{item_id}")

            if response.status_code == 403:
                raise BlockedError(f"Доступ к вакансии {item_id} заблокирован (403)")
            
            if response.status_code == 404:
                raise ValidationError(f"Вакансия {item_id} не найдена (404)")
            
            if response.status_code == 429:
                raise BlockedError(f"Rate limit превышен для вакансии {item_id}")
            
            response.raise_for_status()
            raw_data = response.json()
            
            # Нормализация данных
            normalized = self._normalize_vacancy_data(raw_data)
            
            return normalized
            
        except requests.RequestException as e:
            self.logger.error(f"Ошибка при парсинге вакансии {item_id}: {e}")
            raise NetworkError(f"Ошибка сети при парсинге: {e}")
    
    def _normalize_vacancy_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Нормализация данных вакансии HeadHunter в унифицированный формат.
        
        Args:
            raw_data: Сырые данные от HeadHunter API
        
        Returns:
            Dict: Данные в формате NormalizedVacancy
        """
        # Основные поля
        normalized = {
            'source': 'headhunter',
            'source_id': str(raw_data.get('id')),
            'source_url': raw_data.get('alternate_url', ''),
            'parsing_mode': 'api',
            
            # Базовая информация
            'title': raw_data.get('name', ''),
            'description': raw_data.get('description', ''),
            
            # Компания
            'company_name': raw_data.get('employer', {}).get('name', ''),
            'company_url': raw_data.get('employer', {}).get('alternate_url'),
            
            # Зарплата
            **self._extract_salary(raw_data),
            
            # Локация
            **self._extract_location(raw_data),
            
            # Опыт и занятость
            'experience': raw_data.get('experience', {}).get('id'),
            'employment_type': self._extract_employment(raw_data),
            'schedule': self._extract_schedule(raw_data),
            
            # Навыки
            'key_skills': self._extract_skills(raw_data),
            'professional_roles': self._extract_roles(raw_data),
            
            # Контакты
            'contacts': raw_data.get('contacts'),
            
            # Статус
            'is_active': not raw_data.get('archived', False),
            'archived': raw_data.get('archived', False),
            'published_at': self._parse_datetime(raw_data.get('published_at')),
            
            # Дополнительно
            'has_test': raw_data.get('has_test', False),
            'accepts_handicapped': raw_data.get('accept_handicapped'),
            'response_letter_required': raw_data.get('response_letter_required'),
            
            # Специфичные данные
            'source_specific_data': {
                'premium': raw_data.get('premium', False),
                'billing_type': raw_data.get('billing_type', {}).get('name'),
                'apply_alternate_url': raw_data.get('apply_alternate_url'),
                'insider_interview': raw_data.get('insider_interview'),
            },
            
            # Сырые данные
            'raw_data': raw_data,
        }
        
        return normalized
    
    def _extract_salary(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечение информации о зарплате"""
        salary = raw_data.get('salary')
        if not salary:
            return {
                'salary_from': None,
                'salary_to': None,
                'salary_currency': None,
                'salary_gross': None,
            }
        
        return {
            'salary_from': salary.get('from'),
            'salary_to': salary.get('to'),
            'salary_currency': salary.get('currency'),
            'salary_gross': salary.get('gross'),
        }
    
    def _extract_location(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечение информации о локации"""
        area = raw_data.get('area', {})
        address = raw_data.get('address', {})
        
        return {
            'area_name': area.get('name'),
            'area_id': str(area.get('id')) if area.get('id') else None,
            'address': address.get('raw') if address else None,
        }
    
    def _extract_skills(self, raw_data: Dict[str, Any]) -> List[str]:
        """Извлечение навыков"""
        key_skills = raw_data.get('key_skills', [])
        return [skill.get('name') for skill in key_skills if skill.get('name')]
    
    def _extract_roles(self, raw_data: Dict[str, Any]) -> List[str]:
        """Извлечение профессиональных ролей"""
        roles = raw_data.get('professional_roles', [])
        return [role.get('name') for role in roles if role.get('name')]
    
    def _extract_employment(self, raw_data: Dict[str, Any]) -> List[str]:
        """Извлечение типов занятости"""
        employment = raw_data.get('employment')
        if not employment:
            return []
        return [employment.get('id')] if employment.get('id') else []
    
    def _extract_schedule(self, raw_data: Dict[str, Any]) -> List[str]:
        """Извлечение графиков работы"""
        schedule = raw_data.get('schedule')
        if not schedule:
            return []
        return [schedule.get('id')] if schedule.get('id') else []
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Парсинг datetime строки"""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None


class HabrCareerAPIParser(BaseParser):
    """
    Парсер Habr Career через неофициальный API.
    
    Note: Habr Career не имеет официального публичного API,
    используем endpoints из веб-версии.
    """
    
    BASE_URL = "https://career.habr.com"
    
    def __init__(self, source='habr_career', parsing_mode='api', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'ErgoMS Vacancy Parser/1.0',
            'Accept': 'application/json',
        })
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Валидация конфигурации для Habr Career"""
        # Habr Career использует более простую конфигурацию
        if 'pages' in config and not isinstance(config['pages'], int):
            raise ValueError("Поле 'pages' должно быть числом")
        return True
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Обнаружение вакансий через Habr Career.
        
        Note: На данный момент официальный стабильный API Habr Career
        не используется. Для Habr Career рекомендуется HTML режим.
        """
        message = (
            "API режим для Habr Career временно недоступен. "
            "Используйте HTML режим парсинга."
        )
        self.logger.warning(message)
        raise ValidationError(message)
    
    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        """Парсинг одной вакансии Habr Career"""
        message = (
            "API режим для Habr Career временно недоступен. "
            "Используйте HTML режим парсинга."
        )
        self.logger.warning(message)
        raise ValidationError(message)
    
    def _normalize_vacancy_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация данных Habr Career"""
        message = (
            "Нормализация данных для Habr Career API не реализована, "
            "так как API режим временно недоступен."
        )
        self.logger.warning(message)
        raise ValidationError(message)


class SuperJobAPIParser(BaseParser):
    """
    Парсер SuperJob через официальный API (https://api.superjob.ru/2.0).

    Требует API ключ (Secret key): https://api.superjob.ru/register/
    Лимит: 120 запросов/мин с одного IP.
    """

    BASE_URL = "https://api.superjob.ru/2.0"

    EXPERIENCE_MAP = {1: 'noExperience', 2: 'between1And3', 3: 'between3And6', 4: 'moreThan6'}
    EMPLOYMENT_MAP = {6: 'full', 10: 'part', 12: 'full', 13: 'part', 7: 'project', 9: 'full'}
    SCHEDULE_MAP = {1: 'fullDay', 2: 'remote', 3: 'fullDay'}
    SCHEDULE_FROM_WORK = {12: 'shift', 9: 'flyInFlyOut'}
    CURRENCY_MAP = {'rub': 'RUR', 'uah': 'UAH', 'uzs': 'RUR'}

    def __init__(self, source='superjob', parsing_mode='api', api_key: Optional[str] = None, *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
        self.api_key = api_key or self._load_api_key()
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'ErgoMS Vacancy Parser/1.0'})
        if self.api_key:
            self.session.headers['X-Api-App-Id'] = self.api_key

    @staticmethod
    def _load_api_key() -> Optional[str]:
        import os
        return os.environ.get('SUPERJOB_API_KEY')

    def _get_with_retry(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                return response
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                last_error = e
                self.logger.warning(f"Сетевая ошибка {url} (попытка {attempt + 1}/{self.max_retries}): {e}")
            except requests.exceptions.Timeout as e:
                last_error = e
                self.logger.warning(f"Таймаут {url} (попытка {attempt + 1}/{self.max_retries})")
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(f"Ошибка запроса {url} (попытка {attempt + 1}/{self.max_retries}): {e}")
            if attempt < self.max_retries - 1:
                time.sleep(min(2 ** attempt, 10))
        raise NetworkError(f"Не удалось выполнить запрос {url} после {self.max_retries} попыток: {last_error}")

    def validate_config(self, config: Dict[str, Any]) -> bool:
        if not self.api_key:
            raise ValueError(
                "Для SuperJob API требуется API ключ. "
                "Укажите его через переменную SUPERJOB_API_KEY или в параметре api_key."
            )
        if 'pages' in config and (not isinstance(config['pages'], int) or config['pages'] < 1):
            raise ValueError("Поле 'pages' должно быть положительным числом")
        return True

    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Обнаружение вакансий через SuperJob API.

        config: {
            'keyword': 'python',
            'town': 'Москва',
            'pages': 5,
            'count': 100,
            'experience': 2,
            'type_of_work': 6,
            'catalogues': '33',
            'delay': 0.5,
        }
        """
        self.validate_config(config)

        items = []
        pages = config.get('pages', 5)
        count = min(config.get('count', 100), 100)

        search_params = {'count': count}
        for key in ('keyword', 'town', 'experience', 'type_of_work', 'place_of_work',
                     'catalogues', 'payment_from', 'payment_to'):
            if key in config:
                search_params[key] = config[key]

        self.logger.info(f"Discovery SuperJob API: {search_params}, pages={pages}")

        for page in range(pages):
            search_params['page'] = page
            try:
                response = self._get_with_retry(f"{self.BASE_URL}/vacancies/", params=search_params)

                if response.status_code == 403:
                    raise BlockedError("Доступ заблокирован SuperJob API (403)")
                if response.status_code == 429:
                    self.logger.warning("Rate limit, ждем 60 секунд")
                    time.sleep(60)
                    continue

                response.raise_for_status()
                data = response.json()

                vacancies = data.get('objects', [])
                for vac in vacancies:
                    vac_id = str(vac.get('id', ''))
                    link = vac.get('link', f"https://www.superjob.ru/vakansii/{vac_id}.html")
                    items.append({'source_item_id': vac_id, 'url': link})

                self.logger.info(f"Discovery SuperJob: страница {page + 1}/{pages}, найдено {len(vacancies)}")

                if not data.get('more', False):
                    break

                time.sleep(config.get('delay', 0.5))

            except (BlockedError, NetworkError):
                raise
            except requests.RequestException as e:
                raise NetworkError(f"Ошибка сети при discovery SuperJob: {e}")

        self.logger.info(f"Discovery SuperJob завершен: {len(items)} вакансий")
        return items

    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        """Парсинг одной вакансии SuperJob через API."""
        try:
            response = self._get_with_retry(f"{self.BASE_URL}/vacancies/{item_id}/")

            if response.status_code == 403:
                raise BlockedError(f"Доступ к вакансии {item_id} заблокирован (403)")
            if response.status_code == 404:
                raise ValidationError(f"Вакансия {item_id} не найдена (404)")
            if response.status_code == 429:
                raise BlockedError(f"Rate limit для вакансии {item_id}")

            response.raise_for_status()
            return self._normalize_vacancy_data(response.json())

        except (BlockedError, ValidationError, NetworkError):
            raise
        except requests.RequestException as e:
            raise NetworkError(f"Ошибка сети при парсинге вакансии {item_id}: {e}")

    def _normalize_vacancy_data(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Нормализация данных SuperJob в формат NormalizedVacancy."""
        town = raw.get('town') or {}
        type_of_work_id = (raw.get('type_of_work') or {}).get('id')
        experience_id = (raw.get('experience') or {}).get('id')
        place_of_work_id = (raw.get('place_of_work') or {}).get('id')

        schedule_list = []
        if place_of_work_id in self.SCHEDULE_MAP:
            schedule_list.append(self.SCHEDULE_MAP[place_of_work_id])
        if type_of_work_id in self.SCHEDULE_FROM_WORK:
            schedule_list.append(self.SCHEDULE_FROM_WORK[type_of_work_id])

        employment_list = []
        if type_of_work_id in self.EMPLOYMENT_MAP:
            employment_list.append(self.EMPLOYMENT_MAP[type_of_work_id])

        catalogues = raw.get('catalogues', [])
        roles = []
        skills = []
        for cat in catalogues:
            if cat.get('title'):
                roles.append(cat['title'])
            for pos in cat.get('positions', []):
                if pos.get('title'):
                    skills.append(pos['title'])

        return {
            'source': 'superjob',
            'source_id': str(raw.get('id', '')),
            'source_url': raw.get('link', ''),
            'parsing_mode': 'api',

            'title': raw.get('profession', ''),
            'description': raw.get('work') or raw.get('candidat', ''),

            'company_name': raw.get('firm_name', ''),
            'company_url': raw.get('client_logo'),

            **self._extract_salary(raw),
            **self._extract_location(raw),

            'experience': self.EXPERIENCE_MAP.get(experience_id),
            'employment_type': employment_list or None,
            'schedule': schedule_list or None,

            'key_skills': skills or None,
            'professional_roles': roles or None,

            'contacts': None,

            'is_active': not raw.get('is_archive', False),
            'archived': raw.get('is_archive', False),
            'published_at': self._parse_datetime(raw.get('date_published')),

            'has_test': None,
            'accepts_handicapped': None,
            'response_letter_required': None,

            'source_specific_data': {
                'firm_activity': raw.get('firm_activity'),
                'agency': (raw.get('agency') or {}).get('title'),
                'education': (raw.get('education') or {}).get('title'),
                'gender': (raw.get('gender') or {}).get('title'),
                'age_from': raw.get('age_from'),
                'age_to': raw.get('age_to'),
                'moveable': raw.get('moveable'),
                'anonymous': raw.get('anonymous'),
                'metro': raw.get('metro'),
            },

            'raw_data': raw,
        }

    def _extract_salary(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        payment_from = raw.get('payment_from')
        payment_to = raw.get('payment_to')
        currency = raw.get('currency', '')
        return {
            'salary_from': payment_from if payment_from and payment_from > 0 else None,
            'salary_to': payment_to if payment_to and payment_to > 0 else None,
            'salary_currency': self.CURRENCY_MAP.get(currency, 'RUR'),
            'salary_gross': not raw.get('agreement', False),
        }

    def _extract_location(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        town = raw.get('town') or {}
        return {
            'area_name': town.get('title'),
            'area_id': str(town.get('id')) if town.get('id') else None,
            'address': raw.get('address'),
        }

    def _extract_skills(self, raw: Dict[str, Any]) -> List[str]:
        skills = []
        for cat in raw.get('catalogues', []):
            for pos in cat.get('positions', []):
                if pos.get('title'):
                    skills.append(pos['title'])
        return skills

    @staticmethod
    def _parse_datetime(timestamp) -> Optional[datetime]:
        if not timestamp:
            return None
        try:
            from django.utils import timezone as tz
            dt = datetime.fromtimestamp(int(timestamp))
            return tz.make_aware(dt)
        except (ValueError, TypeError, OSError):
            return None


# Регистрация API парсеров в фабрике при импорте модуля
ParserFactory.register('headhunter', 'api', HeadHunterAPIParser)
ParserFactory.register('superjob', 'api', SuperJobAPIParser)
