import logging

from celery import shared_task
from django.apps import apps as django_apps
from django.utils import timezone
from typing import List, Optional, Sequence

from .scripts import parse_vacancies_by_text, parse_all_vacancies, HeadHunterParser
from .models import Vacancy


logger = logging.getLogger('celery.module.headhunter')
SKILL_MAP_APP = 'modules.competence_core.api.skill_map'


def _skill_map_installed() -> bool:
    """Проверяет, подключено ли приложение компетенций."""
    return django_apps.is_installed(SKILL_MAP_APP)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=6900,
    time_limit=7200,
)
def parse_hh_vacancies_task(
    self,
    text_list: Optional[Sequence[str]] = None,
    area: int = 113,
    pages: int = 2,
    delay: float = 1.0,
    get_details: bool = True,
    universal: bool = False,
    pages_per_area: int = 5,
    max_total_pages: int = 100,
    areas_only: bool = False,
    config: Optional[dict] = None
):
    """
    Celery-задача для парсинга вакансий с HeadHunter.
    Возвращает статистику по результатам парсинга.
    """
    logger.info(
        "Запуск задачи parse_hh_vacancies_task: text_list=%s, universal=%s",
        text_list,
        universal,
    )
    
    if not universal and not text_list:
        error_msg = 'Необходимо указать text_list или universal=True'
        logger.error(error_msg)
        return {'error': error_msg}
    
    try:
        if universal:
            logger.info("Выполняется универсальный парсинг")
            result = parse_all_vacancies(
                pages_per_area=pages_per_area,
                delay=delay,
                max_total_pages=max_total_pages,
                areas_only=areas_only
            )
            logger.info("Универсальный парсинг завершен")
            return {
                'mode': 'universal',
                'areas_processed': result.get('areas_processed'),
                'roles_processed': result.get('roles_processed'),
                'pages_processed': result.get('pages_processed'),
                'total_vacancies': result.get('total_vacancies'),
                'new_vacancies': result.get('new_vacancies'),
                'updated_vacancies': result.get('updated_vacancies'),
                'total_in_db': result.get('total_in_db'),
            }
        
        assert text_list is not None
        queries = list(text_list)
        logger.info("Выполняется парсинг по списку текстов (%d)", len(queries))
        result = parse_vacancies_by_text(
            text_list=queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details
        )
        logger.info("Парсинг по тексту завершен")
        return {
            'mode': 'by_text',
            'total_vacancies': result.get('total_vacancies'),
            'new_vacancies': result.get('new_vacancies'),
            'updated_vacancies': result.get('updated_vacancies'),
            'total_in_db': result.get('total_in_db'),
        }
    except Exception as exc:
        logger.error('Ошибка выполнения parse_hh_vacancies_task', exc_info=True)
        raise self.retry(exc=exc)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=5100,
    time_limit=5400,
)
def parse_vacancies_by_technologies(
    self,
    categories: Optional[List[str]] = None,
    top_n: int = 50,
    use_aliases: bool = False,
    area: int = 113,
    pages: int = 2,
    delay: float = 1.5,
    get_details: bool = True,
    max_queries: Optional[int] = None
):
    """
    Celery-задача для парсинга вакансий по технологиям из базы данных.
    
    Автоматически генерирует поисковые запросы на основе технологий
    и их синонимов, затем запускает парсинг вакансий.
    
    Args:
        categories (List[str]): Список категорий технологий для парсинга
                               (LANG, FRAMEWORK, DB, TOOL, PLATFORM, PROTOCOL, LIBRARY, SERVICE)
                               Если None - используются все категории
        top_n (int): Количество топовых технологий (по популярности)
        use_aliases (bool): Использовать ли алиасы технологий как отдельные запросы
        area (int): ID региона для поиска (113 = Россия)
        pages (int): Количество страниц для парсинга на запрос
        delay (float): Задержка между запросами в секундах
        get_details (bool): Получать ли детальную информацию о вакансиях
        max_queries (int): Максимальное количество поисковых запросов
    
    Returns:
        dict: Статистика парсинга
    """
    logger.info('='*70)
    logger.info('Запуск парсинга вакансий по технологиям')
    logger.info('='*70)
    logger.info(f'Параметры: categories={categories}, top_n={top_n}, '
               f'use_aliases={use_aliases}, area={area}, pages={pages}')
    
    if not _skill_map_installed():
        msg = f'Приложение {SKILL_MAP_APP} не подключено'
        logger.warning(msg)
        return {'error': msg}

    try:
        from .utils.technology_search_generator import TechnologySearchGenerator
        generator = TechnologySearchGenerator()
        
        if categories:
            logger.info(f'Загрузка технологий категорий: {categories}')
            generator.load_technologies(
                categories=categories,
                limit=top_n,
                include_aliases=use_aliases
            )
        else:
            logger.info(f'Загрузка топ-{top_n} технологий')
            generator.load_technologies(
                limit=top_n,
                include_aliases=use_aliases
            )
        
        stats = generator.get_statistics()
        logger.info(f"Загружено технологий: {stats.get('total_technologies')}")
        if use_aliases:
            logger.info(f"Всего алиасов: {stats.get('total_aliases')}")
        
        search_queries = generator.generate_search_queries(
            use_aliases=use_aliases,
            max_queries=max_queries
        )
        
        logger.info('Сгенерировано %d поисковых запросов', len(search_queries))
        
        result = parse_vacancies_by_text(
            text_list=search_queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details
        )
        
        logger.info('Парсинг завершен')
        logger.info('='*70)
        
        return {
            'mode': 'by_technologies',
            'technologies_count': stats.get('total_technologies'),
            'search_queries_count': len(search_queries),
            'search_queries': search_queries[:20],
            'total_vacancies': result.get('total_vacancies'),
            'new_vacancies': result.get('new_vacancies'),
            'updated_vacancies': result.get('updated_vacancies'),
            'total_in_db': result.get('total_in_db'),
        }
        
    except Exception as exc:
        logger.error('Ошибка при парсинге по технологиям', exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=90,
    soft_time_limit=3300,
    time_limit=3600,
)
def parse_vacancies_by_category(
    self,
    category,
    use_aliases=False,
    area=113,
    pages=2,
    delay=1.5,
    get_details=True,
    max_queries=50
):
    """
    Celery-задача для парсинга вакансий по конкретной категории технологий.
    
    Args:
        category (str): Категория технологий (LANG, FRAMEWORK, DB, и т.д.)
        use_aliases (bool): Использовать ли алиасы технологий
        area (int): ID региона для поиска
        pages (int): Количество страниц для парсинга
        delay (float): Задержка между запросами
        get_details (bool): Получать ли детальную информацию
        max_queries (int): Максимальное количество запросов
    
    Returns:
        dict: Статистика парсинга
    """
    logger.info(f'Запуск парсинга по категории: {category}')
    
    if not _skill_map_installed():
        return {
            'mode': 'by_category',
            'category': category,
            'error': f'Приложение {SKILL_MAP_APP} не подключено'
        }

    try:
        from .utils.technology_search_generator import TechnologySearchGenerator
        generator = TechnologySearchGenerator()
        
        # Генерируем запросы для категории
        search_queries = generator.generate_by_category(
            category=category,
            use_aliases=use_aliases,
            max_per_category=max_queries
        )
        
        logger.info(f'Сгенерировано {len(search_queries)} запросов для {category}')
        
        if not search_queries:
            return {
                'mode': 'by_category',
                'category': category,
                'error': 'Не найдено технологий для данной категории'
            }
        
        # Запускаем парсинг
        result = parse_vacancies_by_text(
            text_list=search_queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details
        )
        
        logger.info(f'Парсинг категории {category} завершен')
        
        return {
            'mode': 'by_category',
            'category': category,
            'search_queries_count': len(search_queries),
            'search_queries': search_queries,
            'total_vacancies': result.get('total_vacancies'),
            'new_vacancies': result.get('new_vacancies'),
            'updated_vacancies': result.get('updated_vacancies'),
            'total_in_db': result.get('total_in_db'),
        }
        
    except Exception as exc:
        logger.error('Ошибка при парсинге категории %s', category, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def parse_single_vacancy_task(self, vacancy_id, force_update=False):
    """
    Celery-задача для парсинга одной вакансии по ID.
    Возвращает результат сохранения/обновления.
    """
    logger.info(f"Запуск задачи parse_single_vacancy_task для вакансии {vacancy_id}, force_update={force_update}")
    
    try:
        parser = HeadHunterParser()
        vacancy_manager = getattr(Vacancy, 'objects')
        existing_vacancy = vacancy_manager.filter(hh_id=vacancy_id).first()
        if existing_vacancy and not force_update:
            msg = f'Вакансия {vacancy_id} уже есть в базе'
            logger.info(msg)
            return {'status': 'exists', 'message': msg}
        
        vacancy_data = parser.get_vacancy_details(vacancy_id)
        if not vacancy_data or not isinstance(vacancy_data, dict) or 'id' not in vacancy_data:
            msg = f'Вакансия {vacancy_id} не найдена или данные некорректны'
            logger.error(msg)
            return {'status': 'error', 'message': msg}
        
        vacancy = parser.parse_vacancy(vacancy_data)
        if not vacancy:
            msg = 'Ошибка при парсинге вакансии'
            logger.error(msg)
            return {'status': 'error', 'message': msg}
        if existing_vacancy:
            if force_update:
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
                    existing_vacancy.create_version(new_data)
                    for field, value in new_data.items():
                        setattr(existing_vacancy, field, value)
                    existing_vacancy.save()
                    return {'status': 'updated', 'message': f'Вакансия {vacancy_id} обновлена'}
                return {'status': 'no_changes', 'message': 'Изменений не обнаружено'}
            return {'status': 'exists', 'message': f'Вакансия {vacancy_id} уже есть в базе'}
        else:
            vacancy.save()
            return {'status': 'created', 'message': f'Вакансия {vacancy_id} успешно сохранена'}
    except Exception as exc:
        logger.error('Ошибка при обработке вакансии %s', vacancy_id, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=7200,
    time_limit=7500,
)
def check_vacancies_status_task(
    self,
    batch_size: int = 100,
    delay: float = 0.2,
    max_vacancies: int = 1000
):
    """
    Celery-задача для проверки статуса активных вакансий.
    
    Проверяет, не закрыты ли вакансии на hh.ru, и помечает их как неактивные.
    
    Args:
        batch_size: Размер пакета для обработки
        delay: Задержка между запросами в секундах
        max_vacancies: Максимальное количество вакансий для проверки за один запуск
    
    Returns:
        dict: Статистика проверки
    """
    import time
    from .scripts import HeadHunterParser, ParsingMetrics
    
    logger.info('='*70)
    logger.info('Запуск проверки статуса вакансий')
    logger.info('Параметры: batch_size=%d, delay=%.1f, max_vacancies=%d', batch_size, delay, max_vacancies)
    logger.info('='*70)
    
    try:
        metrics = ParsingMetrics()
        parser = HeadHunterParser(metrics=metrics)
        
        # Получаем активные вакансии для проверки (самые старые первыми)
        active_vacancies = Vacancy.objects.filter(
            is_active=True
        ).order_by('updated_at')[:max_vacancies]
        
        total_count = active_vacancies.count()
        logger.info('Найдено %d активных вакансий для проверки', total_count)
        
        if total_count == 0:
            return {
                'status': 'completed',
                'checked': 0,
                'archived': 0,
                'still_active': 0,
                'errors': 0
            }
        
        archived_count = 0
        still_active_count = 0
        error_count = 0
        
        # Обрабатываем пакетами
        vacancy_ids = list(active_vacancies.values_list('id', 'hh_id'))
        
        for i, (db_id, hh_id) in enumerate(vacancy_ids, 1):
            try:
                # Проверяем статус вакансии
                vacancy_data = parser.check_vacancy_exists(hh_id)
                
                if vacancy_data is None:
                    # Вакансия закрыта или удалена
                    Vacancy.objects.filter(id=db_id).update(
                        is_active=False,
                        updated_at=timezone.now()
                    )
                    archived_count += 1
                    logger.debug('Вакансия %s помечена как неактивная', hh_id)
                else:
                    still_active_count += 1
                
                # Задержка между запросами
                if i < len(vacancy_ids):
                    time.sleep(delay)
                
                # Логируем прогресс каждые batch_size записей
                if i % batch_size == 0:
                    logger.info(
                        'Прогресс: %d/%d (%.1f%%), закрыто: %d',
                        i, total_count, (i / total_count) * 100, archived_count
                    )
                    
            except Exception as e:
                error_count += 1
                metrics.record_error(f"Ошибка проверки вакансии {hh_id}: {e}")
                logger.warning('Ошибка при проверке вакансии %s: %s', hh_id, e)
        
        logger.info('='*70)
        logger.info('Проверка завершена')
        logger.info('Проверено: %d, закрыто: %d, активно: %d, ошибок: %d',
                   total_count, archived_count, still_active_count, error_count)
        logger.info('='*70)
        
        metrics.log_summary()
        
        return {
            'status': 'completed',
            'checked': total_count,
            'archived': archived_count,
            'still_active': still_active_count,
            'errors': error_count,
            'metrics': metrics.to_dict()
        }
        
    except Exception as exc:
        logger.error('Ошибка при проверке статуса вакансий', exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    soft_time_limit=300,
    time_limit=360,
)
def update_vacancy_details_task(self, vacancy_id: str):
    """
    Celery-задача для обновления деталей конкретной вакансии.
    
    Args:
        vacancy_id: ID вакансии на hh.ru
        
    Returns:
        dict: Результат обновления
    """
    from .scripts import HeadHunterParser
    
    logger.info('Обновление деталей вакансии %s', vacancy_id)
    
    try:
        parser = HeadHunterParser()
        
        # Получаем вакансию из БД
        vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
        if not vacancy:
            return {'status': 'not_found', 'message': f'Вакансия {vacancy_id} не найдена в БД'}
        
        # Получаем актуальные данные
        vacancy_data = parser.get_vacancy_details(vacancy_id)
        
        if not vacancy_data:
            # Вакансия закрыта
            vacancy.is_active = False
            vacancy.save(update_fields=['is_active', 'updated_at'])
            return {'status': 'archived', 'message': f'Вакансия {vacancy_id} закрыта'}
        
        if vacancy_data.get('archived'):
            vacancy.is_active = False
            vacancy.save(update_fields=['is_active', 'updated_at'])
            return {'status': 'archived', 'message': f'Вакансия {vacancy_id} архивирована'}
        
        # Парсим и обновляем
        parsed = parser.parse_vacancy(vacancy_data)
        if parsed:
            new_data = {
                'title': parsed.title,
                'description': parsed.description,
                'requirements': parsed.requirements,
                'responsibilities': parsed.responsibilities,
                'salary_from': parsed.salary_from,
                'salary_to': parsed.salary_to,
                'key_skills': parsed.key_skills,
            }
            
            if vacancy.has_changes(new_data):
                vacancy.create_version(new_data)
                for field, value in new_data.items():
                    setattr(vacancy, field, value)
                vacancy.save()
                return {'status': 'updated', 'message': f'Вакансия {vacancy_id} обновлена'}
            
            return {'status': 'no_changes', 'message': 'Изменений не обнаружено'}
        
        return {'status': 'parse_error', 'message': 'Ошибка парсинга данных'}
        
    except Exception as exc:
        logger.error('Ошибка при обновлении вакансии %s', vacancy_id, exc_info=True)
        raise self.retry(exc=exc)