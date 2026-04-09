"""
HTML парсеры для HeadHunter, Habr Career и SuperJob.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from .base import BaseParser, ParserFactory, ParserError, NetworkError, BlockedError

logger = logging.getLogger('celery.module.vacancies_parser')


class BaseHTMLParser(BaseParser):
    """
    Базовый класс для HTML парсеров.
    
    Предоставляет общие методы для работы с HTML:
    - HTTP запросы с retry логикой
    - Парсинг HTML через BeautifulSoup
    - Построение URL для поиска
    """
    
    def __init__(self, source: str, parsing_mode: str = 'html', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def _make_request(self, url: str) -> requests.Response:
        """
        Выполняет HTTP GET запрос с retry логикой.
        
        Args:
            url: URL для запроса
            
        Returns:
            requests.Response: Объект ответа
            
        Raises:
            NetworkError: При сетевых ошибках после всех попыток
            BlockedError: При блокировке (403, капча)
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=self.timeout)
                
                # Проверка на блокировку
                if response.status_code == 403:
                    raise BlockedError(f"Доступ запрещён (403) для {url}")
                
                # Проверка на капчу (базовая проверка)
                if 'captcha' in response.text.lower() or 'captcha' in response.url.lower():
                    raise BlockedError(f"Обнаружена капча для {url}")
                
                # Успешный ответ
                if response.status_code == 200:
                    return response
                
                # Другие HTTP ошибки
                response.raise_for_status()
                
            except BlockedError:
                raise
            except requests.Timeout as e:
                last_error = e
                self.logger.warning(f"Таймаут запроса {url} (попытка {attempt + 1}/{self.max_retries})")
            except requests.HTTPError as e:
                last_error = e
                self.logger.warning(f"HTTP ошибка {e.response.status_code} для {url} (попытка {attempt + 1}/{self.max_retries})")
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(f"Ошибка запроса {url} (попытка {attempt + 1}/{self.max_retries}): {e}")
            
            # Exponential backoff перед следующей попыткой
            if attempt < self.max_retries - 1:
                delay = min(2 ** attempt, 10)  # Максимум 10 секунд
                time.sleep(delay)
        
        # Все попытки исчерпаны
        raise NetworkError(f"Не удалось выполнить запрос {url} после {self.max_retries} попыток: {last_error}")
    
    def _parse_html(self, html_text: str) -> BeautifulSoup:
        """
        Парсит HTML текст через BeautifulSoup.
        
        Args:
            html_text: HTML текст для парсинга
            
        Returns:
            BeautifulSoup: Объект BeautifulSoup
        """
        return BeautifulSoup(html_text, 'html.parser')
    
    def _build_search_url(self, config: Dict[str, Any], page: int, items_per_page: Optional[int] = None) -> str:
        """
        Базовый метод для построения URL поиска.
        
        Может быть переопределен в дочерних классах для специфичной логики.
        
        Args:
            config: Конфигурация поиска
            page: Номер страницы
            items_per_page: Количество элементов на странице (опционально)
            
        Returns:
            str: URL для поиска
        """
        raise NotImplementedError("Метод должен быть переопределен в дочернем классе")
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Обнаружение элементов для парсинга (должен быть переопределен)."""
        raise NotImplementedError("Метод должен быть переопределен в дочернем классе")
    
    def parse_item(self, item_id: str, url: str) -> Dict[str, Any]:
        """Парсинг элемента (должен быть переопределен)."""
        raise NotImplementedError("Метод должен быть переопределен в дочернем классе")
    
    def fetch_item(self, item_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Получение детальной информации об элементе (должен быть переопределен)."""
        raise NotImplementedError("Метод должен быть переопределен в дочернем классе")


class HeadHunterHTMLParser(BaseHTMLParser):
    """
    Парсер HeadHunter через HTML (https://hh.ru).
    
    Используется когда API недоступен или ограничен.
    Парсит публичные страницы вакансий.
    """
    
    BASE_URL = "https://hh.ru"
    
    def __init__(self, source='headhunter', parsing_mode='html', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Валидация конфигурации для HeadHunter HTML.
        
        Поля:
        - text: поисковый запрос (опционально)
        - area: ID региона (опционально)
        - items_per_page: количество вакансий на страницу (20/50/100)
        - max_pages: максимальное количество страниц для парсинга
        """
        if 'items_per_page' in config:
            if config['items_per_page'] not in [20, 50, 100]:
                return False
        
        if 'max_pages' in config and config['max_pages'] < 1:
            return False
        
        return True
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Получает список вакансий через парсинг HTML страницы поиска.
        
        ВАЖНО: HH.ru использует JavaScript-рендеринг (SPA).
        Данный метод пытается найти вакансии через различные селекторы,
        но может не работать без headless браузера (Selenium/Playwright).
        
        Returns:
            Список словарей с полями:
            - item_id: ID вакансии
            - url: URL для получения полной информации
        """
        logger.info(f"[HTML] Начало поиска вакансий HH.ru с конфигом: {config}")
        
        items = []
        page = 0
        max_pages = config.get('max_pages', 10)
        items_per_page = config.get('items_per_page', 50)
        
        while page < max_pages:
            try:
                # Формируем URL для поиска
                search_url = self._build_search_url(config, page, items_per_page)
                logger.info(f"[HTML] Запрос страницы: {search_url}")
                
                # Выполняем запрос
                response = self._make_request(search_url)
                
                # Диагностика: проверяем что получили
                logger.debug(f"[HTML] Status: {response.status_code}, Content-Length: {len(response.text)}")
                
                soup = self._parse_html(response.text)
                
                # Пробуем разные селекторы (HH.ru часто меняет структуру)
                vacancies = []
                
                # Селектор 1: современный HH.ru (data-qa атрибуты)
                vacancies = soup.find_all('div', {'data-qa': 'vacancy-serp__vacancy'})
                logger.debug(f"[HTML] Селектор data-qa='vacancy-serp__vacancy': {len(vacancies)} элементов")
                
                # Селектор 2: альтернативный
                if not vacancies:
                    vacancies = soup.find_all('div', {'data-qa': 'vacancy-serp__vacancy vacancy-serp__vacancy_premium'})
                    logger.debug(f"[HTML] Селектор premium: {len(vacancies)} элементов")
                
                # Селектор 3: по классу serp-item (устаревший)
                if not vacancies:
                    vacancies = soup.find_all('div', class_='serp-item')
                    logger.debug(f"[HTML] Селектор class='serp-item': {len(vacancies)} элементов")
                
                # Селектор 4: по ссылкам на вакансии
                if not vacancies:
                    vacancy_links = soup.find_all('a', {'data-qa': 'serp-item__title'})
                    logger.debug(f"[HTML] Селектор a[data-qa='serp-item__title']: {len(vacancy_links)} элементов")
                    
                    for link in vacancy_links:
                        href = link.get('href', '')
                        if '/vacancy/' in href:
                            import re
                            match = re.search(r'/vacancy/(\d+)', href)
                            if match:
                                vacancy_id = match.group(1)
                                items.append({
                                    'source_item_id': str(vacancy_id),
                                    'url': f"{self.BASE_URL}/vacancy/{vacancy_id}"
                                })
                    
                    if items:
                        logger.info(f"[HTML] Найдено {len(vacancy_links)} вакансий через ссылки на странице {page}")
                        page += 1
                        continue
                
                if not vacancies:
                    # Проверяем на блокировку/капчу
                    if 'captcha' in response.text.lower():
                        logger.error("[HTML] Обнаружена капча! HH.ru заблокировал запросы.")
                        raise BlockedError("Обнаружена капча")
                    
                    # Проверяем наличие React-контейнера (SPA)
                    if 'HH.API' in response.text or '__NEXTJS' in response.text or 'window.__INITIAL_STATE__' in response.text:
                        logger.warning("[HTML] HH.ru использует JavaScript-рендеринг (SPA). "
                                      "HTML парсинг может не работать. Рекомендуется API режим.")
                    
                    logger.info(f"[HTML] Вакансии не найдены на странице {page}. "
                               f"HTML длина: {len(response.text)} символов")
                    
                    # Сохраняем фрагмент HTML для диагностики
                    html_preview = response.text[:2000] if len(response.text) > 2000 else response.text
                    logger.debug(f"[HTML] Начало ответа: {html_preview[:500]}...")
                    break
                
                for vacancy in vacancies:
                    try:
                        vacancy_id = self._extract_vacancy_id(vacancy)
                        if vacancy_id:
                            items.append({
                                'source_item_id': str(vacancy_id),
                                'url': f"{self.BASE_URL}/vacancy/{vacancy_id}"
                            })
                    except Exception as e:
                        logger.warning(f"[HTML] Ошибка парсинга вакансии: {e}")
                        continue
                
                logger.info(f"[HTML] Найдено {len(vacancies)} вакансий на странице {page}")
                page += 1
                
            except BlockedError as e:
                logger.error(f"[HTML] Блокировка при парсинге страницы {page}: {e}")
                break
            except Exception as e:
                logger.error(f"[HTML] Ошибка при парсинге страницы {page}: {e}", exc_info=True)
                break
        
        logger.info(f"[HTML] Всего найдено {len(items)} вакансий HH.ru")
        return items
    
    def fetch_item(self, item_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получает детальную информацию о вакансии через парсинг HTML.
        
        Использует несколько источников данных:
        1. JSON данные из HH-Lux-InitialState (SSR данные)
        2. Мета-теги (og:description, title)
        3. HTML селекторы (fallback)
        
        Returns:
            Словарь с данными в формате NormalizedVacancy
        """
        url = f"{self.BASE_URL}/vacancy/{item_id}"
        
        try:
            response = self._make_request(url)
            html_text = response.text
            soup = self._parse_html(html_text)
            
            # Пробуем извлечь данные из JSON (SSR данные)
            json_data = self._extract_json_data(html_text, item_id)
            
            # Извлекаем данные из мета-тегов
            meta_data = self._extract_meta_data(soup)
            
            # Извлекаем данные из HTML (fallback)
            html_data = {
                'title': self._extract_title(soup),
                'description': self._extract_description(soup),
                'company_name': self._extract_company(soup),
                'area_name': self._extract_area(soup),
                'experience': self._extract_experience(soup),
                'employment_type': self._extract_employment(soup),
                'schedule': self._extract_schedule(soup),
                'key_skills': self._extract_key_skills(soup),
            }
            
            # Извлекаем зарплату (только из HTML, так как в JSON может не быть)
            salary_data = self._extract_salary(soup)
            
            # Объединяем данные с приоритетом: JSON > Meta > HTML
            title = json_data.get('title') or meta_data.get('title') or html_data.get('title') or "Название не указано"
            description = json_data.get('description') or html_data.get('description') or ""
            company_name = json_data.get('company_name') or html_data.get('company_name') or "Компания не указана"
            area_name = json_data.get('area_name') or meta_data.get('area_name') or html_data.get('area_name')
            experience = json_data.get('experience') or meta_data.get('experience') or html_data.get('experience')
            employment_type = json_data.get('employment_type') or html_data.get('employment_type')
            schedule = json_data.get('schedule') or html_data.get('schedule')
            key_skills = json_data.get('key_skills') or html_data.get('key_skills') or []
            
            # Нормализуем в формат NormalizedVacancy
            data = {
                'source': 'headhunter',
                'source_id': str(item_id),
                'source_url': url,
                'parsing_mode': 'html',
                
                'title': title,
                'description': description,
                
                'company_name': company_name,
                'company_url': json_data.get('company_url'),
                
                'salary_from': salary_data.get('from') if salary_data else json_data.get('salary_from'),
                'salary_to': salary_data.get('to') if salary_data else json_data.get('salary_to'),
                'salary_currency': salary_data.get('currency', 'RUR') if salary_data else json_data.get('salary_currency', 'RUR'),
                'salary_gross': salary_data.get('gross', False) if salary_data else json_data.get('salary_gross', False),
                
                'area_name': area_name,
                'address': json_data.get('address'),
                
                'experience': experience,
                'employment_type': employment_type,
                'schedule': schedule,
                
                'key_skills': key_skills if isinstance(key_skills, list) else [],
                
                'is_active': True,
                'archived': False,
                'published_at': json_data.get('published_at') or meta_data.get('published_at'),
            }
            
            return data

        except (BlockedError, NetworkError):
            raise
        except Exception as e:
            raise ParserError(f"Ошибка парсинга вакансии {item_id}: {e}")

    def _extract_json_data(self, html_text: str, item_id: str) -> Dict[str, Any]:
        """
        Извлекает данные вакансии из JSON в HH-Lux-InitialState.
        
        HH.ru использует SSR (Server-Side Rendering) и встраивает данные в HTML.
        """
        import json
        import re
        
        data = {}
        
        try:
            # Ищем JSON в <template id="HH-Lux-InitialState">
            json_match = re.search(r'<template[^>]*id="HH-Lux-InitialState"[^>]*>(.*?)</template>', html_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(1).strip()
                # Убираем HTML entities
                json_text = json_text.replace('&quot;', '"').replace('&amp;', '&')
                state = json.loads(json_text)
                
                # Ищем данные вакансии в структуре state
                # Структура может быть разной, пробуем несколько путей
                vacancy_data = None
                
                # Путь 1: state.vacancy или state.vacancyView.vacancy
                if 'vacancy' in state:
                    vacancy_data = state['vacancy']
                elif 'vacancyView' in state and 'vacancy' in state['vacancyView']:
                    vacancy_data = state['vacancyView']['vacancy']
                
                if vacancy_data:
                    data['title'] = vacancy_data.get('title')
                    data['description'] = vacancy_data.get('description')
                    
                    # Компания
                    if 'employer' in vacancy_data:
                        employer = vacancy_data['employer']
                        data['company_name'] = employer.get('name')
                        if 'alternate_url' in employer:
                            data['company_url'] = f"{self.BASE_URL}{employer['alternate_url']}"
                    
                    # Регион
                    if 'area' in vacancy_data:
                        data['area_name'] = vacancy_data['area'].get('name')
                    
                    # Зарплата
                    if 'salary' in vacancy_data and vacancy_data['salary']:
                        salary = vacancy_data['salary']
                        data['salary_from'] = salary.get('from')
                        data['salary_to'] = salary.get('to')
                        data['salary_currency'] = salary.get('currency', 'RUR')
                        data['salary_gross'] = salary.get('gross', False)
                    
                    # Опыт
                    if 'experience' in vacancy_data and vacancy_data['experience']:
                        exp = vacancy_data['experience']
                        data['experience'] = exp.get('name')
                    
                    # Тип занятости
                    if 'employment' in vacancy_data and vacancy_data['employment']:
                        emp = vacancy_data['employment']
                        data['employment_type'] = emp.get('name')
                    
                    # График
                    if 'schedule' in vacancy_data and vacancy_data['schedule']:
                        sched = vacancy_data['schedule']
                        data['schedule'] = sched.get('name')
                    
                    # Навыки
                    if 'key_skills' in vacancy_data:
                        data['key_skills'] = [skill.get('name') for skill in vacancy_data['key_skills'] if skill.get('name')]
                    
                    # Дата публикации
                    if 'published_at' in vacancy_data:
                        try:
                            # Формат: "2026-01-11T00:00:00+0300"
                            pub_date = vacancy_data['published_at']
                            # Парсим datetime и делаем его timezone-aware
                            dt = datetime.fromisoformat(pub_date.replace('+0300', '+03:00'))
                            data['published_at'] = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                        except Exception as e:
                            logger.debug(f"Не удалось распарсить дату публикации: {e}")
                            pass
                    
        except json.JSONDecodeError as e:
            logger.debug(f"Не удалось распарсить JSON из HH-Lux-InitialState: {e}")
        except Exception as e:
            logger.debug(f"Ошибка извлечения JSON данных: {e}")
        
        return data
    
    def _extract_meta_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Извлекает данные из мета-тегов (og:description, title и т.д.)."""
        data = {}
        
        try:
            # Заголовок из <title>
            title_elem = soup.find('title')
            if title_elem:
                title_text = title_elem.get_text(strip=True)
                # Формат: "Вакансия Программист .Net в Москве, работа в компании..."
                if 'Вакансия' in title_text:
                    # Извлекаем название вакансии
                    parts = title_text.split(' в ')
                    if parts:
                        data['title'] = parts[0].replace('Вакансия ', '').strip()
            
            # Описание из og:description или meta description
            desc_elem = soup.find('meta', {'property': 'og:description'}) or soup.find('meta', {'name': 'description'})
            if desc_elem:
                desc_text = desc_elem.get('content', '')
                # Формат: "Зарплата: не указана. Москва. Требуемый опыт: 1–3 года. Полная. Дата публикации: 11.01.2026."
                
                # Извлекаем регион
                import re
                area_match = re.search(r'\.\s*([А-Яа-яЁё\s]+)\.\s*Требуемый опыт', desc_text)
                if area_match:
                    data['area_name'] = area_match.group(1).strip()
                
                # Извлекаем опыт
                exp_match = re.search(r'Требуемый опыт:\s*([^\.]+)', desc_text)
                if exp_match:
                    data['experience'] = exp_match.group(1).strip()
                
                # Извлекаем дату публикации
                date_match = re.search(r'Дата публикации:\s*(\d{2}\.\d{2}\.\d{4})', desc_text)
                if date_match:
                    try:
                        date_str = date_match.group(1)
                        # Парсим datetime и делаем его timezone-aware
                        naive_dt = datetime.strptime(date_str, '%d.%m.%Y')
                        data['published_at'] = timezone.make_aware(naive_dt)
                    except Exception as e:
                        logger.debug(f"Не удалось распарсить дату публикации из мета-тегов: {e}")
                        pass
                        
        except Exception as e:
            logger.debug(f"Ошибка извлечения мета-данных: {e}")
        
        return data
    
    def _build_search_url(self, config: Dict[str, Any], page: int, items_per_page: int) -> str:
        """Формирует URL для поиска вакансий."""
        params = {
            'page': page,
            'items_on_page': items_per_page,
        }
        
        if 'text' in config:
            params['text'] = config['text']
        
        if 'area' in config:
            params['area'] = config['area']
        
        if 'experience' in config:
            params['experience'] = config['experience']
        
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/search/vacancy?{query_string}"
    
    def _extract_vacancy_id(self, vacancy_element) -> Optional[str]:
        """
        Извлекает ID вакансии из элемента.
        Пробует несколько способов для разных версий HTML HH.ru.
        """
        import re
        
        # Способ 1: data-vacancy-id атрибут
        data_vacancy_id = vacancy_element.get('data-vacancy-id')
        if data_vacancy_id:
            return str(data_vacancy_id)
        
        # Способ 2: ищем в любом атрибуте data-*
        for attr, value in vacancy_element.attrs.items():
            if 'vacancy' in attr.lower() and value and str(value).isdigit():
                return str(value)
        
        # Способ 3: ищем ссылку с data-qa="serp-item__title"
        link = vacancy_element.find('a', {'data-qa': 'serp-item__title'})
        if not link:
            # Способ 4: ищем любую ссылку на /vacancy/
            link = vacancy_element.find('a', href=re.compile(r'/vacancy/\d+'))
        if not link:
            # Способ 5: старый класс
            link = vacancy_element.find('a', class_='serp-item__title')
        
        if link and link.get('href'):
            href = link['href']
            # Извлекаем ID из URL вида /vacancy/12345 или https://hh.ru/vacancy/12345
            match = re.search(r'/vacancy/(\d+)', href)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Извлекает название вакансии."""
        # Пробуем разные селекторы
        title_elem = (
            soup.find('h1', {'data-qa': 'vacancy-title'}) or
            soup.find('h1', class_='bloko-header-section-1') or
            soup.find('h1', class_='vacancy-title') or
            soup.find('h1')
        )
        if title_elem:
            title = title_elem.get_text(strip=True)
            # Убираем префикс "Вакансия" если есть
            if title.startswith('Вакансия '):
                title = title.replace('Вакансия ', '', 1)
            return title
        return "Название не указано"
    
    def _extract_company(self, soup: BeautifulSoup) -> str:
        """Извлекает название компании."""
        # Пробуем разные селекторы
        company_elem = (
            soup.find('a', {'data-qa': 'vacancy-company-name'}) or
            soup.find('span', {'data-qa': 'vacancy-company-name'}) or
            soup.find('a', class_='vacancy-company-name') or
            soup.find('span', {'data-qa': 'bloko-header-2'}) or
            soup.find('div', {'data-qa': 'vacancy-company'})
        )
        if company_elem:
            return company_elem.get_text(strip=True)
        return "Компания не указана"
    
    def _extract_salary(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Извлекает информацию о зарплате и парсит её."""
        salary_elem = soup.find('span', {'data-qa': 'vacancy-salary-compensation-type-net'})
        if not salary_elem:
            salary_elem = soup.find('span', class_='bloko-header-section-2')
        
        if not salary_elem:
            return None
        
        salary_text = salary_elem.get_text(strip=True)
        
        # Парсим текст зарплаты: "от 100 000 до 150 000 руб." или "100 000 - 150 000 ₽"
        import re
        
        result = {
            'from': None,
            'to': None,
            'currency': 'RUR',
            'gross': False,
            'raw': salary_text
        }
        
        # Определяем gross/net
        if 'на руки' in salary_text.lower():
            result['gross'] = False
        elif 'до вычета' in salary_text.lower() or 'gross' in salary_text.lower():
            result['gross'] = True
        
        # Извлекаем числа
        numbers = re.findall(r'(\d[\d\s]*\d|\d+)', salary_text)
        numbers = [int(n.replace(' ', '').replace('\xa0', '')) for n in numbers]
        
        if len(numbers) >= 2:
            result['from'] = min(numbers[0], numbers[1])
            result['to'] = max(numbers[0], numbers[1])
        elif len(numbers) == 1:
            if 'от' in salary_text.lower():
                result['from'] = numbers[0]
            elif 'до' in salary_text.lower():
                result['to'] = numbers[0]
            else:
                result['from'] = numbers[0]
                result['to'] = numbers[0]
        
        return result
    
    def _extract_area(self, soup: BeautifulSoup) -> str:
        """Извлекает город/регион."""
        # Пробуем разные селекторы
        area_elem = (
            soup.find('span', {'data-qa': 'vacancy-view-raw-address'}) or
            soup.find('p', {'data-qa': 'vacancy-view-location'}) or
            soup.find('span', {'data-qa': 'vacancy-location'}) or
            soup.find('div', {'data-qa': 'vacancy-location'})
        )
        if area_elem:
            return area_elem.get_text(strip=True)
        return None
    
    def _extract_experience(self, soup: BeautifulSoup) -> str:
        """Извлекает требуемый опыт."""
        exp_elem = soup.find('span', {'data-qa': 'vacancy-experience'})
        return exp_elem.get_text(strip=True) if exp_elem else None
    
    def _extract_schedule(self, soup: BeautifulSoup) -> str:
        """Извлекает график работы."""
        schedule_elem = soup.find('p', {'data-qa': 'vacancy-view-employment-mode'})
        return schedule_elem.get_text(strip=True) if schedule_elem else None
    
    def _extract_employment(self, soup: BeautifulSoup) -> str:
        """Извлекает тип занятости."""
        employment_elem = soup.find('p', {'data-qa': 'vacancy-view-employment-type'})
        return employment_elem.get_text(strip=True) if employment_elem else None
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        """Извлекает описание вакансии."""
        # Пробуем разные селекторы
        desc_elem = (
            soup.find('div', {'data-qa': 'vacancy-description'}) or
            soup.find('div', class_='vacancy-description') or
            soup.find('div', {'data-qa': 'vacancy-description-text'})
        )
        if desc_elem:
            # Сохраняем HTML структуру для лучшего форматирования
            return desc_elem.get_text(separator='\n', strip=True)
        return ""
    
    def _extract_key_skills(self, soup: BeautifulSoup) -> List[str]:
        """Извлекает ключевые навыки."""
        skills = []
        skills_section = soup.find('div', {'data-qa': 'skills-element'})
        if skills_section:
            skill_items = skills_section.find_all('span', {'data-qa': 'bloko-tag__text'})
            skills = [skill.get_text(strip=True) for skill in skill_items]
        return skills
    
    def _extract_published_date(self, soup: BeautifulSoup) -> Optional[str]:
        """Извлекает дату публикации."""
        date_elem = soup.find('p', class_='vacancy-creation-time-redesigned')
        if date_elem:
            return date_elem.get_text(strip=True)
        return None


class HabrCareerHTMLParser(BaseHTMLParser):
    """
    Парсер Habr Career через HTML (https://career.habr.com).
    """
    
    BASE_URL = "https://career.habr.com"
    
    def __init__(self, source='habr_career', parsing_mode='html', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Валидация конфигурации для Habr Career HTML."""
        return True
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Получает список вакансий через парсинг HTML Habr Career."""
        logger.info(f"[HTML] Начало поиска вакансий Habr Career с конфигом: {config}")
        
        items = []
        page = 1
        max_pages = config.get('max_pages', 10)
        
        while page <= max_pages:
            try:
                search_url = self._build_search_url(config, page)
                response = self._make_request(search_url)
                soup = self._parse_html(response.text)
                
                vacancies = soup.find_all('div', class_='vacancy-card')
                
                if not vacancies:
                    break
                
                for vacancy in vacancies:
                    try:
                        link = vacancy.find('a', class_='vacancy-card__title-link')
                        if link and 'href' in link.attrs:
                            vacancy_url = link['href']
                            vacancy_id = vacancy_url.split('/vacancies/')[-1].split('?')[0]
                            
                            items.append({
                                'source_item_id': str(vacancy_id),
                                'url': f"{self.BASE_URL}{vacancy_url}"
                            })
                    except Exception as e:
                        logger.warning(f"[HTML] Ошибка парсинга вакансии Habr: {e}")
                        continue
                
                logger.info(f"[HTML] Найдено {len(vacancies)} вакансий Habr на странице {page}")
                page += 1
                
            except Exception as e:
                logger.error(f"[HTML] Ошибка при парсинге страницы {page} Habr: {e}")
                break
        
        logger.info(f"[HTML] Всего найдено {len(items)} вакансий Habr Career")
        return items
    
    def fetch_item(self, item_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Получает детальную информацию о вакансии Habr Career в формате NormalizedVacancy."""
        url = config.get('url') or f"{self.BASE_URL}/vacancies/{item_id}"
        
        try:
            response = self._make_request(url)
            soup = self._parse_html(response.text)
            
            salary_data = self._extract_salary(soup)
            
            data = {
                'source': 'habr_career',
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
                
                'key_skills': self._extract_key_skills(soup),
                
                'is_active': True,
                'archived': False,
            }
            
            return data

        except (BlockedError, NetworkError):
            raise
        except Exception as e:
            raise ParserError(f"Ошибка парсинга вакансии Habr {item_id}: {e}")
    
    def _build_search_url(self, config: Dict[str, Any], page: int) -> str:
        """Формирует URL для поиска вакансий Habr."""
        params = {'page': page}
        
        if 'q' in config:
            params['q'] = config['q']
        
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/vacancies?{query_string}"
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        title_elem = soup.find('h1', class_='page-title__title')
        return title_elem.get_text(strip=True) if title_elem else "Название не указано"
    
    def _extract_company(self, soup: BeautifulSoup) -> str:
        company_elem = soup.find('a', class_='company-name')
        return company_elem.get_text(strip=True) if company_elem else "Компания не указана"
    
    def _extract_salary(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Извлекает и парсит зарплату."""
        salary_elem = soup.find('div', class_='basic-salary')
        if not salary_elem:
            return None
        
        import re
        salary_text = salary_elem.get_text(strip=True)
        
        result = {
            'from': None,
            'to': None,
            'currency': 'RUR',
            'raw': salary_text
        }
        
        numbers = re.findall(r'(\d[\d\s]*\d|\d+)', salary_text)
        numbers = [int(n.replace(' ', '').replace('\xa0', '')) for n in numbers]
        
        if len(numbers) >= 2:
            result['from'] = min(numbers[0], numbers[1])
            result['to'] = max(numbers[0], numbers[1])
        elif len(numbers) == 1:
            result['from'] = numbers[0]
        
        return result
    
    def _extract_area(self, soup: BeautifulSoup) -> str:
        area_elem = soup.find('div', class_='vacancy-locations')
        return area_elem.get_text(strip=True) if area_elem else None
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        desc_elem = soup.find('div', class_='vacancy-description__text')
        return desc_elem.get_text(separator='\n', strip=True) if desc_elem else ""
    
    def _extract_key_skills(self, soup: BeautifulSoup) -> List[str]:
        skills = []
        skills_section = soup.find('div', class_='skills')
        if skills_section:
            skill_items = skills_section.find_all('a', class_='skill')
            skills = [skill.get_text(strip=True) for skill in skill_items]
        return skills


class SuperJobHTMLParser(BaseHTMLParser):
    """
    Парсер SuperJob через HTML (https://www.superjob.ru).
    """
    
    BASE_URL = "https://www.superjob.ru"
    
    def __init__(self, source='superjob', parsing_mode='html', *args, **kwargs):
        super().__init__(source=source, parsing_mode=parsing_mode, *args, **kwargs)
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Валидация конфигурации для SuperJob HTML."""
        return True
    
    def discover_items(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """Получает список вакансий через парсинг HTML SuperJob."""
        logger.info(f"[HTML] Начало поиска вакансий SuperJob с конфигом: {config}")
        
        items = []
        page = 1
        max_pages = config.get('max_pages', 10)
        
        while page <= max_pages:
            try:
                search_url = self._build_search_url(config, page)
                response = self._make_request(search_url)
                soup = self._parse_html(response.text)
                
                vacancies = soup.find_all('div', class_='_1ID8B')
                
                if not vacancies:
                    break
                
                for vacancy in vacancies:
                    try:
                        link = vacancy.find('a')
                        if link and 'href' in link.attrs:
                            vacancy_url = link['href']
                            vacancy_id = vacancy_url.split('/vakansii/')[-1].split('.html')[0]
                            
                            items.append({
                                'source_item_id': str(vacancy_id),
                                'url': f"{self.BASE_URL}{vacancy_url}"
                            })
                    except Exception as e:
                        logger.warning(f"[HTML] Ошибка парсинга вакансии SuperJob: {e}")
                        continue
                
                logger.info(f"[HTML] Найдено {len(vacancies)} вакансий SuperJob на странице {page}")
                page += 1
                
            except Exception as e:
                logger.error(f"[HTML] Ошибка при парсинге страницы {page} SuperJob: {e}")
                break
        
        logger.info(f"[HTML] Всего найдено {len(items)} вакансий SuperJob")
        return items
    
    def fetch_item(self, item_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Получает детальную информацию о вакансии SuperJob в формате NormalizedVacancy."""
        url = f"{self.BASE_URL}/vakansii/{item_id}.html"
        
        try:
            response = self._make_request(url)
            soup = self._parse_html(response.text)
            
            salary_data = self._extract_salary(soup)
            
            data = {
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
            
            return data

        except (BlockedError, NetworkError):
            raise
        except Exception as e:
            raise ParserError(f"Ошибка парсинга вакансии SuperJob {item_id}: {e}")
    
    def _build_search_url(self, config: Dict[str, Any], page: int) -> str:
        """Формирует URL для поиска вакансий SuperJob."""
        params = {'page': page - 1}  # SuperJob начинает с 0
        
        if 'keywords' in config:
            params['keywords'] = config['keywords']
        
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"{self.BASE_URL}/vakansii/?{query_string}"
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        title_elem = soup.find('h1')
        return title_elem.get_text(strip=True) if title_elem else "Название не указано"
    
    def _extract_company(self, soup: BeautifulSoup) -> str:
        company_elem = soup.find('a', class_='_3mfro')
        return company_elem.get_text(strip=True) if company_elem else "Компания не указана"
    
    def _extract_salary(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Извлекает и парсит зарплату."""
        salary_elem = soup.find('span', class_='_2Wp8I')
        if not salary_elem:
            return None
        
        import re
        salary_text = salary_elem.get_text(strip=True)
        
        result = {
            'from': None,
            'to': None,
            'currency': 'RUR',
            'raw': salary_text
        }
        
        numbers = re.findall(r'(\d[\d\s]*\d|\d+)', salary_text)
        numbers = [int(n.replace(' ', '').replace('\xa0', '')) for n in numbers]
        
        if len(numbers) >= 2:
            result['from'] = min(numbers[0], numbers[1])
            result['to'] = max(numbers[0], numbers[1])
        elif len(numbers) == 1:
            result['from'] = numbers[0]
        
        return result
    
    def _extract_area(self, soup: BeautifulSoup) -> str:
        area_elem = soup.find('span', class_='_3mfro _2JVkc')
        return area_elem.get_text(strip=True) if area_elem else None
    
    def _extract_description(self, soup: BeautifulSoup) -> str:
        desc_elem = soup.find('div', class_='_3P3j9')
        return desc_elem.get_text(separator='\n', strip=True) if desc_elem else ""


# Регистрация HTML парсеров в фабрике при импорте модуля
# Регистрация происходит автоматически, дублирование предотвращается в ParserFactory.register()
ParserFactory.register('headhunter', 'html', HeadHunterHTMLParser)
ParserFactory.register('habr_career', 'html', HabrCareerHTMLParser)
ParserFactory.register('superjob', 'html', SuperJobHTMLParser)
