import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from .models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.habr_career')

class HabrCareerParser:
    """Парсер вакансий Хабр Карьеры через HTML + BeautifulSoup."""

    BASE_URL = "https://career.habr.com"
    VACANCIES_URL = f"{BASE_URL}/vacancies"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        })

    def get_vacancies(self, page=1, per_page=100, search_text=None):
        """
        Получение списка активных вакансий через HTML.
        """
        try:
            params = {'page': page}
            if search_text:
                params['q'] = search_text
            soup = self._fetch_soup(self.VACANCIES_URL, params=params)
            links = self._extract_vacancy_links(soup)
            return {'vacancies': links}
        except requests.RequestException as e:
            logger.error(f"Ошибка при получении вакансий через HTML: {e}")
            return None

    def get_archived_vacancies(self, page=1, per_page=100, search_text=None):
        """
        Получение списка архивных вакансий через HTML.
        """
        candidates = [
            (f"{self.VACANCIES_URL}/archive", {'page': page}),
            (self.VACANCIES_URL, {'page': page, 'archived': 'true'}),
            (self.VACANCIES_URL, {'page': page, 'is_archived': 'true'}),
        ]

        if search_text:
            for _, params in candidates:
                params['q'] = search_text

        for url, params in candidates:
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                if not self._looks_like_archive_page(soup, response.url):
                    logger.warning(
                        "Пропущен источник архивных вакансий без признаков архива: %s",
                        response.url
                    )
                    continue

                links = self._extract_vacancy_links(soup)
                if links:
                    return {'vacancies': links}
            except requests.RequestException as e:
                logger.debug("Ошибка при проверке источника архивных вакансий %s: %s", url, e)
                continue

        logger.warning("Не удалось получить архивные вакансии через HTML (страница может отсутствовать)")
        return {'vacancies': []}

    def get_vacancy_details(self, vacancy_id=None, vacancy_url=None):
        """
        Получение детальной информации о вакансии через HTML.
        """
        if vacancy_url:
            url = vacancy_url
        elif vacancy_id:
            url = f"{self.VACANCIES_URL}/{vacancy_id}"
        else:
            return None

        try:
            soup = self._fetch_soup(url)
            vacancy_id = vacancy_id or self._extract_vacancy_id(url)
            return self._parse_vacancy_page(soup, url, vacancy_id)
        except requests.RequestException as e:
            logger.error(f"Ошибка при получении деталей вакансии {vacancy_id or vacancy_url}: {e}")
            return None

    def parse_vacancy(self, vacancy_data, is_archived=False):
        """Парсинг данных вакансии в модель"""
        if not vacancy_data:
            logger.warning("vacancy_data is None")
            return None

        try:
            salary_from, salary_to, salary_currency, salary_gross = self._parse_salary(vacancy_data)

            company = vacancy_data.get('company') or {}

            specializations = [
                {'id': spec.get('id'), 'title': spec.get('title', '')}
                for spec in vacancy_data.get('specializations', [])
            ]

            skills = [
                skill.get('title', '') if isinstance(skill, dict) else str(skill)
                for skill in vacancy_data.get('skills', [])
            ]

            published_at = self._parse_datetime(vacancy_data.get('published_at'))

            return {
                'title': vacancy_data.get('title', ''),
                'company_name': company.get('name', 'Не указано'),
                'salary_from': salary_from,
                'salary_to': salary_to,
                'salary_currency': salary_currency,
                'salary_gross': salary_gross,
                'city': vacancy_data.get('city', ''),
                'address': vacancy_data.get('address') or '',
                'description': vacancy_data.get('description', ''),
                'requirements': vacancy_data.get('requirements') or '',
                'responsibilities': vacancy_data.get('responsibilities') or '',
                'employment_type': vacancy_data.get('employment_type', ''),
                'experience_level': (
                    vacancy_data.get('experience')
                    or vacancy_data.get('experience_level', '')
                ),
                'qualification': vacancy_data.get('qualification'),
                'skills': skills,
                'specializations': specializations,
                'divisions': vacancy_data.get('divisions', []),
                'schedule_type': (
                    vacancy_data.get('schedule')
                    or vacancy_data.get('schedule_type', '')
                ),
                'habr_id': str(vacancy_data.get('id', '')),
                'url': vacancy_data.get('url', ''),
                'company_url': company.get('url'),
                'company_alias': company.get('alias_name'),
                'company_logo_url': company.get('logo_url'),
                'marked': vacancy_data.get('marked', False),
                'premium': vacancy_data.get('premium', False),
                'has_test': vacancy_data.get('has_test', False),
                'response_letter_required': vacancy_data.get('response_letter_required', False),
                'is_active': not is_archived,
                'published_at': published_at,
            }

        except Exception as e:
            logger.error(f"Ошибка при парсинге вакансии: {e}", exc_info=True)
            return None

    def _parse_salary(self, vacancy_data):
        """Парсинг информации о зарплате."""
        salary_from = None
        salary_to = None
        salary_currency = None
        salary_gross = True

        salary_info = vacancy_data.get('salary')

        if isinstance(salary_info, dict):
            salary_from = salary_info.get('from') or salary_info.get('salary_from')
            salary_to = salary_info.get('to') or salary_info.get('salary_to')
            salary_currency = salary_info.get('currency')
            salary_gross = salary_info.get('gross', True)
            return salary_from, salary_to, salary_currency, salary_gross

        if isinstance(salary_info, str) and salary_info:
            salary_gross = 'на руки' not in salary_info.lower()

            normalized_salary = salary_info.replace('\xa0', ' ')

            match = re.search(r'от\s+([\d\s]+)\s+до\s+([\d\s]+)\s+([\w$€₽]+)', normalized_salary)
            if match:
                salary_from = int(match.group(1).replace(' ', ''))
                salary_to = int(match.group(2).replace(' ', ''))
                salary_currency = match.group(3)
            else:
                match = re.search(r'от\s+([\d\s]+)\s+([\w$€₽]+)', normalized_salary)
                if match:
                    salary_from = int(match.group(1).replace(' ', ''))
                    salary_currency = match.group(2)
                else:
                    match = re.search(r'до\s+([\d\s]+)\s+([\w$€₽]+)', normalized_salary)
                    if match:
                        salary_to = int(match.group(1).replace(' ', ''))
                        salary_currency = match.group(2)

        return salary_from, salary_to, salary_currency, salary_gross

    def _parse_datetime(self, dt_str):
        """Парсинг даты из строки ISO 8601"""
        if not dt_str:
            return timezone.now()

        try:
            parsed = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = timezone.make_aware(parsed)
            return parsed
        except (ValueError, TypeError):
            return timezone.now()
    
    def save_vacancy(self, vacancy_data):
        """Сохранение вакансии в базу данных.

        Returns:
            tuple[Vacancy | None, str]: (объект, статус)
            Статусы: created, updated, unchanged, error
        """
        if not vacancy_data:
            return None, 'error'
        
        try:
            habr_id = vacancy_data.get('habr_id')
            if not habr_id:
                logger.error("Отсутствует habr_id")
                return None, 'error'
            
            existing_vacancy = Vacancy.objects.filter(habr_id=habr_id).first()
            
            if existing_vacancy:
                changes = existing_vacancy.has_changes(vacancy_data)
                if changes:
                    logger.info(f"Обновление вакансии {habr_id} с изменениями: {list(changes.keys())}")
                    existing_vacancy.create_version(vacancy_data)
                    
                    for field, value in vacancy_data.items():
                        if hasattr(existing_vacancy, field):
                            setattr(existing_vacancy, field, value)
                    
                    existing_vacancy.save()
                    return existing_vacancy, 'updated'
                else:
                    logger.debug(f"Вакансия {habr_id} не изменилась")
                    return existing_vacancy, 'unchanged'
            else:
                logger.info(f"Создание новой вакансии {habr_id}")
                vacancy = Vacancy.objects.create(**vacancy_data)
                return vacancy, 'created'
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении вакансии: {e}", exc_info=True)
            return None, 'error'

    def _fetch_soup(self, url, params=None):
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser')

    def _looks_like_archive_page(self, soup, final_url):
        """
        Проверяет, что HTML действительно относится к архиву вакансий.
        Защищает от ложной деактивации активных вакансий.
        """
        normalized_url = (final_url or '').lower()
        if '/archive' in normalized_url:
            return True

        title = (soup.title.get_text(strip=True).lower() if soup.title else '')
        if 'архив' in title or 'archive' in title:
            return True

        marker_selectors = [
            'h1',
            '.tabs',
            '.tab',
            '.page-title',
            '.vacancies-tabs',
            '[aria-current="page"]',
        ]

        for selector in marker_selectors:
            for node in soup.select(selector):
                text = node.get_text(separator=' ', strip=True).lower()
                if 'архив' in text or 'archive' in text:
                    return True

        return False

    def _extract_vacancy_links(self, soup):
        links = []
        seen_ids = set()

        selectors = [
            'div.vacancy-card a.vacancy-card__title-link',
            'article.vacancy-card a.vacancy-card__title-link',
            'a.vacancy-card__title-link',
            'a[data-qa="vacancy-card__title-link"]',
            'a[href*="/vacancies/"]',
        ]

        for selector in selectors:
            for link in soup.select(selector):
                href = link.get('href')
                if not href:
                    continue

                full_url = urljoin(self.BASE_URL, href)
                vacancy_id = self._extract_vacancy_id(full_url)
                if not vacancy_id or vacancy_id in seen_ids:
                    continue

                seen_ids.add(vacancy_id)
                links.append({
                    'id': vacancy_id,
                    'url': full_url,
                    'title': link.get_text(strip=True),
                })

            if links:
                break

        return links

    def _extract_vacancy_id(self, url):
        match = re.search(r'/vacancies/(\d+)', url or '')
        return match.group(1) if match else None

    def _parse_vacancy_page(self, soup, url, vacancy_id):
        posting = self._extract_job_posting(soup)

        title = (
            posting.get('title')
            or self._first_text(soup, [
                'h1.page-title__title',
                'h1[data-qa="vacancy-title"]',
                'h1',
            ])
            or 'Без названия'
        )

        company_name = (
            posting.get('company_name')
            or self._first_text(soup, [
                'a.company-name',
                'a[data-qa="vacancy-company-name"]',
                '.company_name',
            ])
            or 'Не указано'
        )

        company_url = posting.get('company_url')
        company_alias = posting.get('company_alias')
        if not company_url:
            company_href = self._first_attr(soup, [
                'a.company-name',
                'a[data-qa="vacancy-company-name"]',
            ], 'href')
            if company_href:
                company_url = urljoin(self.BASE_URL, company_href)
                company_alias = urlparse(company_href).path.strip('/').split('/')[-1] or None

        salary_raw = (
            posting.get('salary_raw')
            or self._first_text(soup, [
                'div.basic-salary',
                '[data-qa="vacancy-salary"]',
            ])
        )
        salary_from, salary_to, salary_currency, salary_gross = self._parse_salary({
            'salary': salary_raw
        })

        description = (
            posting.get('description')
            or self._first_text(soup, [
                'div.vacancy-description__text',
                '[data-qa="vacancy-description"]',
                '.vacancy-description',
            ], separator='\n')
            or ''
        )

        published_at = self._parse_datetime(
            posting.get('date_posted')
            or self._first_attr(soup, ['meta[property="article:published_time"]'], 'content')
            or self._first_attr(soup, ['time[datetime]'], 'datetime')
        )

        city = (
            posting.get('city')
            or self._first_text(soup, [
                'div.vacancy-locations',
                '[data-qa="vacancy-location"]',
                '[data-qa="vacancy-view-location"]',
            ])
            or ''
        )

        skills = posting.get('skills')
        if not skills:
            skills = [
                item.get_text(strip=True)
                for item in soup.select('.skills a.skill, .skills .skill, [data-qa="skills-element"] a')
                if item.get_text(strip=True)
            ]

        return {
            'id': vacancy_id,
            'title': title,
            'company': {
                'name': company_name,
                'url': company_url,
                'alias_name': company_alias,
                'logo_url': None,
            },
            'salary': salary_raw,
            'city': city,
            'address': '',
            'description': description,
            'requirements': '',
            'responsibilities': '',
            'employment_type': posting.get('employment_type') or '',
            'experience': posting.get('experience_level') or '',
            'experience_level': posting.get('experience_level') or '',
            'qualification': posting.get('qualification'),
            'skills': skills or [],
            'specializations': [],
            'divisions': [],
            'schedule': posting.get('schedule_type') or '',
            'schedule_type': posting.get('schedule_type') or '',
            'url': url,
            'published_at': published_at.isoformat(),
            'premium': False,
            'marked': False,
            'has_test': False,
            'response_letter_required': False,
            '_parsed_salary': {
                'from': salary_from,
                'to': salary_to,
                'currency': salary_currency,
                'gross': salary_gross,
            }
        }

    def _extract_job_posting(self, soup):
        scripts = soup.select('script[type="application/ld+json"]')

        for script in scripts:
            raw = script.string or script.get_text(strip=True)
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            posting = self._find_job_posting(data)
            if not posting:
                continue

            salary_raw = None
            base_salary = posting.get('baseSalary')
            if isinstance(base_salary, dict):
                value_data = base_salary.get('value') or {}
                currency = base_salary.get('currency') or value_data.get('currency')
                min_value = value_data.get('minValue')
                max_value = value_data.get('maxValue')
                if min_value and max_value:
                    salary_raw = f"от {int(min_value)} до {int(max_value)} {currency or ''}".strip()
                elif min_value:
                    salary_raw = f"от {int(min_value)} {currency or ''}".strip()
                elif max_value:
                    salary_raw = f"до {int(max_value)} {currency or ''}".strip()

            company = posting.get('hiringOrganization') or {}
            if not isinstance(company, dict):
                company = {'name': str(company)}

            location = posting.get('jobLocation') or {}
            if isinstance(location, list):
                location = location[0] if location else {}

            city = None
            if isinstance(location, dict):
                location_address = location.get('address')
                if isinstance(location_address, dict):
                    city = location_address.get('addressLocality')
                elif isinstance(location_address, str):
                    city = location_address
            elif isinstance(location, str):
                city = location

            skills = posting.get('skills')
            if isinstance(skills, str):
                skills = [item.strip() for item in skills.split(',') if item.strip()]
            elif isinstance(skills, list):
                normalized_skills = []
                for item in skills:
                    if isinstance(item, str):
                        normalized_skills.append(item.strip())
                    elif isinstance(item, dict):
                        value = item.get('name') or item.get('title')
                        if value:
                            normalized_skills.append(str(value).strip())
                skills = [item for item in normalized_skills if item]

            return {
                'title': posting.get('title'),
                'description': posting.get('description'),
                'date_posted': posting.get('datePosted'),
                'employment_type': posting.get('employmentType'),
                'company_name': company.get('name'),
                'company_url': company.get('sameAs'),
                'company_alias': None,
                'city': city,
                'skills': skills if isinstance(skills, list) else [],
                'salary_raw': salary_raw,
                'experience_level': None,
                'schedule_type': None,
                'qualification': posting.get('qualifications'),
            }

        return {}

    def _find_job_posting(self, data):
        if isinstance(data, dict):
            if data.get('@type') == 'JobPosting':
                return data

            graph = data.get('@graph')
            if isinstance(graph, list):
                for item in graph:
                    result = self._find_job_posting(item)
                    if result:
                        return result

            for value in data.values():
                result = self._find_job_posting(value)
                if result:
                    return result

        if isinstance(data, list):
            for item in data:
                result = self._find_job_posting(item)
                if result:
                    return result

        return None

    @staticmethod
    def _first_text(soup, selectors, separator=' '):
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(separator=separator, strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _first_attr(soup, selectors, attr_name):
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                value = node.get(attr_name)
                if value:
                    return value
        return None

def parse_habr_vacancies(pages=5, delay=1.0, get_details=True, search_text=None):
    """Парсинг активных вакансий с Хабр Карьеры."""
    parser = HabrCareerParser()
    
    total_vacancies = 0
    new_vacancies = 0
    updated_vacancies = 0
    errors = 0
    
    logger.info(
        "Начинаем HTML-парсинг вакансий с Хабр Карьеры через BeautifulSoup. "
        f"Параметры: страниц={pages}, задержка={delay}с, детали={get_details}, "
        f"поиск={search_text or 'без фильтра'}"
    )
    
    for page in range(1, pages + 1):
        logger.info(f"Обрабатываем страницу {page}/{pages}")
        
        vacancies_data = parser.get_vacancies(page=page, search_text=search_text)
        if not vacancies_data:
            logger.error(f"Ошибка при получении вакансий со страницы {page}")
            errors += 1
            continue
        
        vacancies = vacancies_data.get('vacancies', [])
        if not vacancies:
            logger.info(f"На странице {page} нет вакансий")
            break
        
        logger.info(f"Найдено {len(vacancies)} вакансий на странице {page}")
        
        for i, vacancy_data in enumerate(vacancies, 1):
            try:
                logger.debug(f"Обрабатываем вакансию {i}/{len(vacancies)}: "
                             f"{vacancy_data.get('title', 'Без названия')}")
                
                if get_details:
                    vacancy_id = vacancy_data.get('id')
                    vacancy_url = vacancy_data.get('url')
                    if vacancy_id or vacancy_url:
                        detailed_data = parser.get_vacancy_details(vacancy_id, vacancy_url)
                        if detailed_data:
                            vacancy_data = detailed_data
                
                parsed_data = parser.parse_vacancy(vacancy_data)
                if parsed_data:
                    saved_vacancy, save_status = parser.save_vacancy(parsed_data)
                    if saved_vacancy and save_status != 'error':
                        total_vacancies += 1
                        if save_status == 'created':
                            new_vacancies += 1
                        elif save_status == 'updated':
                            updated_vacancies += 1
                    else:
                        errors += 1
                else:
                    errors += 1
                
                if delay > 0 and i < len(vacancies):
                    time.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке вакансии: {e}", exc_info=True)
                errors += 1
        
        if delay > 0 and page < pages:
            time.sleep(delay)
    
    logger.info(f"Парсинг завершен. Всего: {total_vacancies}, "
                f"Новых: {new_vacancies}, Обновлено: {updated_vacancies}, Ошибок: {errors}")
    
    return {
        'total': total_vacancies,
        'new': new_vacancies,
        'updated': updated_vacancies,
        'errors': errors
    }

def parse_habr_archived_vacancies(pages=5, delay=1.0, search_text=None):
    """Парсинг архивных вакансий с Хабр Карьеры."""
    parser = HabrCareerParser()
    
    total_vacancies = 0
    new_vacancies = 0
    updated_vacancies = 0
    errors = 0
    
    logger.info(
        "Начинаем HTML-парсинг архивных вакансий с Хабр Карьеры. "
        f"Параметры: страниц={pages}, задержка={delay}с, поиск={search_text or 'без фильтра'}"
    )
    
    for page in range(1, pages + 1):
        logger.info(f"Обрабатываем страницу {page}/{pages}")
        
        vacancies_data = parser.get_archived_vacancies(page=page, search_text=search_text)
        if not vacancies_data:
            logger.error(f"Ошибка при получении архивных вакансий со страницы {page}")
            errors += 1
            continue
        
        vacancies = vacancies_data.get('vacancies', [])
        if not vacancies:
            logger.info(f"На странице {page} нет архивных вакансий")
            break
        
        logger.info(f"Найдено {len(vacancies)} архивных вакансий на странице {page}")
        
        for i, vacancy_data in enumerate(vacancies, 1):
            try:
                logger.debug(f"Обрабатываем архивную вакансию {i}/{len(vacancies)}: "
                             f"{vacancy_data.get('title', 'Без названия')}")

                vacancy_id = vacancy_data.get('id')
                vacancy_url = vacancy_data.get('url')
                if vacancy_id or vacancy_url:
                    detailed_data = parser.get_vacancy_details(vacancy_id, vacancy_url)
                    if detailed_data:
                        vacancy_data = detailed_data
                
                parsed_data = parser.parse_vacancy(vacancy_data, is_archived=True)
                if parsed_data:
                    saved_vacancy, save_status = parser.save_vacancy(parsed_data)
                    if saved_vacancy and save_status != 'error':
                        total_vacancies += 1
                        if save_status == 'created':
                            new_vacancies += 1
                        elif save_status == 'updated':
                            updated_vacancies += 1
                    else:
                        errors += 1
                else:
                    errors += 1
                
                if delay > 0 and i < len(vacancies):
                    time.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке архивной вакансии: {e}", exc_info=True)
                errors += 1
        
        if delay > 0 and page < pages:
            time.sleep(delay)
    
    logger.info(f"Парсинг архивных вакансий завершен. Всего: {total_vacancies}, "
                f"Новых: {new_vacancies}, Обновлено: {updated_vacancies}, Ошибок: {errors}")
    
    return {
        'total': total_vacancies,
        'new': new_vacancies,
        'updated': updated_vacancies,
        'errors': errors
    }

def parse_habr_all_vacancies(pages=5, delay=1.0, get_details=True, search_text=None):
    """Парсинг всех вакансий (активных и архивных)."""
    logger.info(f"Начинаем парсинг всех вакансий с Хабр Карьеры. "
                f"Параметры: страниц={pages}, задержка={delay}с, детали={get_details}, "
                f"поиск={search_text or 'без фильтра'}")

    active_result = parse_habr_vacancies(
        pages=pages,
        delay=delay,
        get_details=get_details,
        search_text=search_text
    )
    logger.info("Активные вакансии обработаны, парсим архивные...")

    archived_result = parse_habr_archived_vacancies(
        pages=pages,
        delay=delay,
        search_text=search_text
    )

    total_result = {
        'active': active_result,
        'archived': archived_result,
        'total': {
            'total': active_result['total'] + archived_result['total'],
            'new': active_result['new'] + archived_result['new'],
            'updated': active_result['updated'] + archived_result['updated'],
            'errors': active_result['errors'] + archived_result['errors']
        }
    }
    logger.info(f"Парсинг всех вакансий завершен. "
                f"Всего: {total_result['total']['total']}, "
                f"Новых: {total_result['total']['new']}, "
                f"Обновлено: {total_result['total']['updated']}, "
                f"Ошибок: {total_result['total']['errors']}")
    return total_result
