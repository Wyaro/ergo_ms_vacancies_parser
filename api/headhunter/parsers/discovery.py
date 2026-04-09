"""
Функции для обнаружения и парсинга вакансий.

Содержит функции высокого уровня для парсинга вакансий:
- parse_vacancies_by_text: парсинг по текстовым запросам
- parse_all_vacancies: универсальный парсинг по регионам и ролям
- _parse_area: парсинг по региону
- _parse_role: парсинг по профессиональной роли
"""

import time
import logging

from .hh_parser import HeadHunterParser
from .utils import ParsingMetrics
from ..models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.headhunter')


def _format_duration(seconds: float) -> str:
    return f"{seconds:.2f} сек"

def parse_vacancies_by_text(text_list, area=113, pages=2, delay=1.0, get_details=True,
                           date_from=None, date_to=None):
    """
    Парсинг вакансий по списку текстовых запросов

    Args:
        text_list (list): Список текстов для поиска (например: ["Python разработчик", "Java программист"])
        area (int): ID региона (1 - Москва, 2 - СПб, 113 - Россия)
        pages (int): Количество страниц для каждого запроса
        delay (float): Задержка между запросами в секундах
        get_details (bool): Получать ли детальную информацию о вакансиях
        date_from (str): Дата публикации от (формат YYYY-MM-DD)
        date_to (str): Дата публикации до (формат YYYY-MM-DD)

    Returns:
        dict: Статистика парсинга
    """
    # Создаём метрики и парсер
    metrics = ParsingMetrics()
    parser = HeadHunterParser(metrics=metrics)
    
    # Загружаем существующие ID для проверки дубликатов
    existing_hh_ids = set(Vacancy.objects.values_list('hh_id', flat=True))
    logger.info('Загружено %d существующих вакансий для проверки дубликатов', len(existing_hh_ids))
    
    total_vacancies = 0
    total_new_vacancies = 0
    total_updated_vacancies = 0
    
    for i, text in enumerate(text_list, 1):
        logger.info('[%d/%d] Парсинг запроса: "%s"', i, len(text_list), text)
        
        vacancies_to_save = []
        query_vacancies = 0
        query_new_vacancies = 0
        query_updated_vacancies = 0
        total_available_pages = pages  # Будет обновлено после первого запроса
        
        for page in range(pages):
            # Пропускаем страницы, которых не существует
            if page >= total_available_pages:
                logger.debug('Страница %d не существует (всего %d)', page + 1, total_available_pages)
                break
            
            logger.debug('Страница %d из %d', page + 1, min(pages, total_available_pages))
            
            # Поиск вакансий
            search_result = parser.search_vacancies(
                text=text,
                area=area,
                per_page=100,
                page=page,
                date_from=date_from,
                date_to=date_to
            )
            
            if not search_result:
                logger.warning('Не удалось получить данные для страницы %d', page + 1)
                continue
            
            # Обновляем информацию о доступных страницах (только на первой странице)
            if page == 0:
                total_found = search_result.get('found', 0)
                total_available_pages = min(search_result.get('pages', 1), pages, 20)  # API лимит 20 страниц
                logger.info('Запрос "%s": найдено %d вакансий, доступно %d страниц', 
                           text, total_found, total_available_pages)

            vacancies = search_result.get('items', [])
            query_vacancies += len(vacancies)

            if not vacancies:
                logger.debug('Вакансии не найдены на странице %d', page + 1)
                break
            
            # Парсинг каждой вакансии
            for j, vacancy_data in enumerate(vacancies, 1):
                vacancy_id = vacancy_data.get('id')
                vacancy_title = vacancy_data.get('name', 'Без названия')
                company_name = (vacancy_data.get('employer') or {}).get('name', 'Не указано')
                city = (vacancy_data.get('area') or {}).get('name', 'не указан')
                
                # Пропускаем уже существующие вакансии
                if vacancy_id in existing_hh_ids:
                    logger.debug('[%d/%d] %s | %s | %s - уже существует', 
                               j, len(vacancies), city, vacancy_title, company_name)
                    continue
                
                # Получаем детальную информацию о вакансии для навыков
                if get_details and vacancy_id:
                    detailed_vacancy = parser.get_vacancy_details(vacancy_id)
                    if detailed_vacancy:
                        # Сохраняем snippet из поисковых данных, т.к. в детальных данных его нет
                        search_snippet = vacancy_data.get('snippet')
                        vacancy_data = detailed_vacancy
                        # Восстанавливаем snippet если его нет в детальных данных
                        if search_snippet and not vacancy_data.get('snippet'):
                            vacancy_data['snippet'] = search_snippet
                
                vacancy = parser.parse_vacancy(vacancy_data)
                if vacancy:
                    # Проверяем, существует ли вакансия
                    existing_vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
                    
                    if existing_vacancy:
                        # Проверяем, есть ли изменения
                        new_data = {
                            'title': vacancy.title,
                            'company_name': vacancy.company_name,
                            'salary_from': vacancy.salary_from,
                            'salary_to': vacancy.salary_to,
                            'salary_currency': vacancy.salary_currency,
                            'salary_gross': vacancy.salary_gross,
                            'city': vacancy.city,
                            'address': vacancy.address,
                            'description': vacancy.description,
                            'requirements': vacancy.requirements,
                            'responsibilities': vacancy.responsibilities,
                            'employment_type': vacancy.employment_type,
                            'experience_level': vacancy.experience_level,
                            'key_skills': vacancy.key_skills,
                            'schedule_type': vacancy.schedule_type,
                            'professional_role': vacancy.professional_role,
                            'employer_name': vacancy.employer_name,
                            'premium': vacancy.premium,
                            'has_test': vacancy.has_test,
                            'response_letter_required': vacancy.response_letter_required,
                        }
                        
                        if existing_vacancy.has_changes(new_data):
                            # Создаем новую версию с историей изменений
                            existing_vacancy.create_version(new_data)
                            # Обновляем данные вакансии
                            for field, value in new_data.items():
                                setattr(existing_vacancy, field, value)
                            existing_vacancy.save()
                            logger.info('[%d/%d] %s | %s | %s - обновлена (новая версия)', 
                                      j, len(vacancies), city, vacancy_title, company_name)
                            query_updated_vacancies += 1
                        else:
                            logger.debug('[%d/%d] %s | %s | %s - без изменений', 
                                       j, len(vacancies), city, vacancy_title, company_name)
                    else:
                        # Новая вакансия
                        vacancies_to_save.append(vacancy)
                        existing_hh_ids.add(vacancy_id)
                        logger.info('[%d/%d] %s | %s | %s - новая вакансия', 
                                  j, len(vacancies), city, vacancy_title, company_name)
                        query_new_vacancies += 1
                else:
                    logger.warning('[%d/%d] %s | %s | %s - ошибка парсинга', 
                                 j, len(vacancies), city, vacancy_title, company_name)
                
                # Небольшая задержка между запросами детальной информации
                if get_details:
                    time.sleep(0.1)
            
            # Задержка между страницами
            if page < pages - 1:
                time.sleep(0.5)
        
        # Массовое сохранение вакансий для этого запроса
        if vacancies_to_save:
            Vacancy.objects.bulk_create(vacancies_to_save, ignore_conflicts=True)
            new_vacancies = len(vacancies_to_save)
            logger.info('Запрос "%s": сохранено %d новых вакансий', text, new_vacancies)
            total_new_vacancies += new_vacancies
        else:
            logger.debug('Запрос "%s": новых вакансий не найдено', text)

        # Выводим статистику по обновлениям
        if query_updated_vacancies > 0:
            logger.info('Создано %d новых версий вакансий', query_updated_vacancies)
            total_updated_vacancies += query_updated_vacancies
        
        total_vacancies += query_vacancies
        
        # Задержка между запросами
        if i < len(text_list):
            time.sleep(delay)
    
    # Обновляем метрики
    metrics.new_vacancies = total_new_vacancies
    metrics.updated_vacancies = total_updated_vacancies
    
    # Логируем сводку
    metrics.log_summary()
    
    return {
        'total_vacancies': total_vacancies,
        'new_vacancies': total_new_vacancies,
        'updated_vacancies': total_updated_vacancies,
        'total_in_db': Vacancy.objects.count(),
        'metrics': metrics.to_dict()
    }


def parse_all_vacancies(pages_per_area=5, delay=1.0, max_total_pages=100, areas_only=False):
    """
    Универсальный парсинг всех вакансий по регионам и ролям
    
    Args:
        pages_per_area (int): Количество страниц для каждого региона
        delay (float): Задержка между запросами в секундах
        max_total_pages (int): Максимальное общее количество страниц
        areas_only (bool): Парсить только по регионам (без ролей)
    
    Returns:
        dict: Статистика парсинга
    """
    # Создаём метрики и парсер
    metrics = ParsingMetrics()
    parser = HeadHunterParser(metrics=metrics)
    
    # Получаем регионы
    areas = parser.get_areas()
    logger.info('Найдено %d регионов для парсинга', len(areas))
    
    # Получаем профессиональные роли (если нужно)
    roles = []
    if not areas_only:
        roles = parser.get_professional_roles()
        logger.info('Найдено %d профессиональных ролей для парсинга', len(roles))
    
    # Загружаем существующие ID для проверки дубликатов
    existing_hh_ids = set(Vacancy.objects.values_list('hh_id', flat=True))
    logger.info('Загружено %d существующих вакансий для проверки дубликатов', len(existing_hh_ids))
    
    total_vacancies = 0
    total_new_vacancies = 0
    total_updated_vacancies = 0
    total_pages_processed = 0
    
    # Парсинг по регионам
    for i, area in enumerate(areas, 1):
        if total_pages_processed >= max_total_pages:
            logger.warning('Достигнут лимит страниц (%d). Останавливаем парсинг.', max_total_pages)
            break
        
        logger.info('[%d/%d] Парсинг региона: %s (ID: %s)', i, len(areas), area["name"], area["id"])
        
        area_vacancies, area_new_vacancies, area_updated_vacancies, pages_processed = _parse_area(
            parser, area, existing_hh_ids, pages_per_area
        )
        
        total_vacancies += area_vacancies
        total_new_vacancies += area_new_vacancies
        total_updated_vacancies += area_updated_vacancies
        total_pages_processed += pages_processed
        
        logger.info('Регион %s: обработано %d, новых %d, обновлено %d, страниц %d', 
                   area["name"], area_vacancies, area_new_vacancies, area_updated_vacancies, pages_processed)
        
        # Задержка между регионами
        if i < len(areas):
            logger.debug('Ожидание %s перед следующим регионом...', _format_duration(delay))
            time.sleep(delay)
    
    # Парсинг по профессиональным ролям (если включено)
    if roles and not areas_only:
        logger.info('Начинаем парсинг по %d профессиональным ролям...', len(roles))
        
        for i, role in enumerate(roles, 1):
            if total_pages_processed >= max_total_pages:
                break
            
            logger.info('[%d/%d] Парсинг роли: %s (ID: %s)', i, len(roles), role["name"], role["id"])
            
            role_vacancies, role_new_vacancies, role_updated_vacancies, pages_processed = _parse_role(
                parser, role, existing_hh_ids, pages_per_area
            )
            
            total_vacancies += role_vacancies
            total_new_vacancies += role_new_vacancies
            total_updated_vacancies += role_updated_vacancies
            total_pages_processed += pages_processed
            
            logger.info('Роль %s: обработано %d, новых %d, обновлено %d, страниц %d', 
                       role["name"], role_vacancies, role_new_vacancies, role_updated_vacancies, pages_processed)
            
            # Задержка между ролями
            if i < len(roles):
                time.sleep(delay)
    
    # Обновляем метрики
    metrics.new_vacancies = total_new_vacancies
    metrics.updated_vacancies = total_updated_vacancies
    
    # Логируем сводку
    metrics.log_summary()
    
    return {
        'areas_processed': len(areas),
        'roles_processed': len(roles) if not areas_only else 0,
        'pages_processed': total_pages_processed,
        'total_vacancies': total_vacancies,
        'new_vacancies': total_new_vacancies,
        'updated_vacancies': total_updated_vacancies,
        'total_in_db': Vacancy.objects.count(),
        'metrics': metrics.to_dict()
    }


def _parse_area(parser, area, existing_hh_ids, pages):
    """Парсинг вакансий по региону"""
    vacancies_to_save = []
    total_vacancies = 0
    total_updated_vacancies = 0
    pages_processed = 0
    total_available_pages = pages
    
    for page in range(pages):
        # Пропускаем страницы, которых не существует
        if page >= total_available_pages:
            break
        
        search_result = parser.search_all_vacancies(
            area_id=area['id'],
            page=page,
            per_page=100
        )
        
        if not search_result:
            logger.warning('Регион %s: не удалось получить данные для страницы %d', area['name'], page + 1)
            continue
        
        # Обновляем информацию о доступных страницах
        if page == 0:
            total_available_pages = min(search_result.get('pages', 1), pages, 20)
        
        vacancies = search_result.get('items', [])
        total_vacancies += len(vacancies)
        pages_processed += 1
        
        if not vacancies:
            break
        
        # Парсинг каждой вакансии
        for j, vacancy_data in enumerate(vacancies, 1):
            vacancy_id = vacancy_data.get('id')
            vacancy_title = vacancy_data.get('name', 'Без названия')
            company_name = (vacancy_data.get('employer') or {}).get('name', 'Не указано')
            city = (vacancy_data.get('area') or {}).get('name', 'не указан')
            
            # Пропускаем уже существующие вакансии
            if vacancy_id in existing_hh_ids:
                logger.debug('[%d/%d] %s | %s | %s - уже существует', 
                           j, len(vacancies), city, vacancy_title, company_name)
                continue
            
            # Получаем детальную информацию о вакансии
            if vacancy_id:
                detailed_vacancy = parser.get_vacancy_details(vacancy_id)
                if detailed_vacancy:
                    # Сохраняем snippet из поисковых данных
                    search_snippet = vacancy_data.get('snippet')
                    vacancy_data = detailed_vacancy
                    # Восстанавливаем snippet если его нет в детальных данных
                    if search_snippet and not vacancy_data.get('snippet'):
                        vacancy_data['snippet'] = search_snippet
            
            # Проверяем, что у нас есть данные для парсинга
            if not vacancy_data:
                logger.warning('[%d/%d] %s | %s | %s - нет данных для парсинга', 
                             j, len(vacancies), city, vacancy_title, company_name)
                continue
                
            vacancy = parser.parse_vacancy(vacancy_data)
            if vacancy:
                # Проверяем, существует ли вакансия
                existing_vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
                
                if existing_vacancy:
                    # Проверяем, есть ли изменения
                    new_data = {
                        'title': vacancy.title,
                        'company_name': vacancy.company_name,
                        'salary_from': vacancy.salary_from,
                        'salary_to': vacancy.salary_to,
                        'salary_currency': vacancy.salary_currency,
                        'salary_gross': vacancy.salary_gross,
                        'city': vacancy.city,
                        'address': vacancy.address,
                        'description': vacancy.description,
                        'requirements': vacancy.requirements,
                        'responsibilities': vacancy.responsibilities,
                        'employment_type': vacancy.employment_type,
                        'experience_level': vacancy.experience_level,
                        'key_skills': vacancy.key_skills,
                        'schedule_type': vacancy.schedule_type,
                        'professional_role': vacancy.professional_role,
                        'employer_name': vacancy.employer_name,
                        'premium': vacancy.premium,
                        'has_test': vacancy.has_test,
                        'response_letter_required': vacancy.response_letter_required,
                    }
                    
                    if existing_vacancy.has_changes(new_data):
                        # Создаем новую версию с историей изменений
                        existing_vacancy.create_version(new_data)
                        # Обновляем данные вакансии
                        for field, value in new_data.items():
                            setattr(existing_vacancy, field, value)
                        existing_vacancy.save()
                        logger.info('[%d/%d] %s | %s | %s - обновлена (новая версия)', 
                                  j, len(vacancies), city, vacancy_title, company_name)
                        total_updated_vacancies += 1
                    else:
                        logger.debug('[%d/%d] %s | %s | %s - без изменений', 
                                   j, len(vacancies), city, vacancy_title, company_name)
                else:
                    # Новая вакансия
                    vacancies_to_save.append(vacancy)
                    existing_hh_ids.add(vacancy_id)
                    logger.info('[%d/%d] %s | %s | %s - новая вакансия', 
                              j, len(vacancies), city, vacancy_title, company_name)
            else:
                logger.warning('[%d/%d] %s | %s | %s - ошибка парсинга', 
                             j, len(vacancies), city, vacancy_title, company_name)
            
            # Задержка между запросами детальной информации
            time.sleep(0.1)
        
        # Задержка между страницами
        if page < pages - 1:
            time.sleep(0.5)
    
    # Массовое сохранение вакансий
    if vacancies_to_save:
        logger.info('Регион %s: сохранение %d вакансий в базу данных...', area['name'], len(vacancies_to_save))
        Vacancy.objects.bulk_create(vacancies_to_save, ignore_conflicts=True)
        logger.info('Регион %s: сохранено %d вакансий', area['name'], len(vacancies_to_save))
        return total_vacancies, len(vacancies_to_save), total_updated_vacancies, pages_processed
    else:
        logger.debug('Регион %s: новых вакансий не найдено', area['name'])
        return total_vacancies, 0, total_updated_vacancies, pages_processed


def _parse_role(parser, role, existing_hh_ids, pages):
    """Парсинг вакансий по профессиональной роли"""
    vacancies_to_save = []
    total_vacancies = 0
    total_updated_vacancies = 0
    pages_processed = 0
    total_available_pages = pages
    
    for page in range(pages):
        # Пропускаем страницы, которых не существует
        if page >= total_available_pages:
            break
        
        # Поиск вакансий по роли
        search_result = parser.search_vacancies(
            professional_role=role['id'],
            per_page=100,
            page=page
        )
        
        if not search_result:
            logger.warning('Роль %s: не удалось получить данные для страницы %d', role['name'], page + 1)
            continue
        
        # Обновляем информацию о доступных страницах
        if page == 0:
            total_available_pages = min(search_result.get('pages', 1), pages, 20)
        
        vacancies = search_result.get('items', [])
        total_vacancies += len(vacancies)
        pages_processed += 1
        
        if not vacancies:
            break
        
        # Парсинг каждой вакансии
        for j, vacancy_data in enumerate(vacancies, 1):
            vacancy_id = vacancy_data.get('id')
            vacancy_title = vacancy_data.get('name', 'Без названия')
            company_name = (vacancy_data.get('employer') or {}).get('name', 'Не указано')
            city = (vacancy_data.get('area') or {}).get('name', 'не указан')
            
            # Пропускаем уже существующие вакансии
            if vacancy_id in existing_hh_ids:
                logger.debug('[%d/%d] %s | %s | %s - уже существует', 
                           j, len(vacancies), city, vacancy_title, company_name)
                continue
            
            # Получаем детальную информацию о вакансии
            if vacancy_id:
                detailed_vacancy = parser.get_vacancy_details(vacancy_id)
                if detailed_vacancy:
                    # Сохраняем snippet из поисковых данных
                    search_snippet = vacancy_data.get('snippet')
                    vacancy_data = detailed_vacancy
                    # Восстанавливаем snippet если его нет в детальных данных
                    if search_snippet and not vacancy_data.get('snippet'):
                        vacancy_data['snippet'] = search_snippet
            
            # Проверяем, что у нас есть данные для парсинга
            if not vacancy_data:
                logger.warning('[%d/%d] %s | %s | %s - нет данных для парсинга', 
                             j, len(vacancies), city, vacancy_title, company_name)
                continue
                
            vacancy = parser.parse_vacancy(vacancy_data)
            if vacancy:
                # Проверяем, существует ли вакансия
                existing_vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
                
                if existing_vacancy:
                    # Проверяем, есть ли изменения
                    new_data = {
                        'title': vacancy.title,
                        'company_name': vacancy.company_name,
                        'salary_from': vacancy.salary_from,
                        'salary_to': vacancy.salary_to,
                        'salary_currency': vacancy.salary_currency,
                        'salary_gross': vacancy.salary_gross,
                        'city': vacancy.city,
                        'address': vacancy.address,
                        'description': vacancy.description,
                        'requirements': vacancy.requirements,
                        'responsibilities': vacancy.responsibilities,
                        'employment_type': vacancy.employment_type,
                        'experience_level': vacancy.experience_level,
                        'key_skills': vacancy.key_skills,
                        'schedule_type': vacancy.schedule_type,
                        'professional_role': vacancy.professional_role,
                        'employer_name': vacancy.employer_name,
                        'premium': vacancy.premium,
                        'has_test': vacancy.has_test,
                        'response_letter_required': vacancy.response_letter_required,
                    }
                    
                    if existing_vacancy.has_changes(new_data):
                        # Создаем новую версию с историей изменений
                        existing_vacancy.create_version(new_data)
                        # Обновляем данные вакансии
                        for field, value in new_data.items():
                            setattr(existing_vacancy, field, value)
                        existing_vacancy.save()
                        logger.info('[%d/%d] %s | %s | %s - обновлена (новая версия)', 
                                  j, len(vacancies), city, vacancy_title, company_name)
                        total_updated_vacancies += 1
                    else:
                        logger.debug('[%d/%d] %s | %s | %s - без изменений', 
                                   j, len(vacancies), city, vacancy_title, company_name)
                else:
                    # Новая вакансия
                    vacancies_to_save.append(vacancy)
                    existing_hh_ids.add(vacancy_id)
                    logger.info('[%d/%d] %s | %s | %s - новая вакансия', 
                              j, len(vacancies), city, vacancy_title, company_name)
            else:
                logger.warning('[%d/%d] %s | %s | %s - ошибка парсинга', 
                             j, len(vacancies), city, vacancy_title, company_name)
            
            # Задержка между запросами детальной информации
            time.sleep(0.1)
        
        # Задержка между страницами
        if page < pages - 1:
            time.sleep(0.5)
    
    # Массовое сохранение вакансий
    if vacancies_to_save:
        logger.info('Роль %s: сохранение %d вакансий в базу данных...', role['name'], len(vacancies_to_save))
        Vacancy.objects.bulk_create(vacancies_to_save, ignore_conflicts=True)
        logger.info('Роль %s: сохранено %d вакансий', role['name'], len(vacancies_to_save))
        return total_vacancies, len(vacancies_to_save), total_updated_vacancies, pages_processed
    else:
        logger.debug('Роль %s: новых вакансий не найдено', role['name'])
        return total_vacancies, 0, total_updated_vacancies, pages_processed 