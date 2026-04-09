"""
Задачи парсинга вакансий по технологиям.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from celery import shared_task

from .base import _skill_map_installed
from ..scripts import parse_vacancies_by_text, HeadHunterParser, ParsingMetrics

logger = logging.getLogger('modules.vacancies_parser.headhunter')


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=6900,
    time_limit=7200,
    # ВАЖНО: сохраняем старое имя задачи для обратной совместимости
    # с уже существующими периодическими задачами Celery Beat
    name="modules.vacancies_parser.api.headhunter.tasks.parse_hh_segment_by_technologies",
)
def parse_hh_segment_by_technologies(
    self,
    date_from: str,
    date_to: str,
    categories: Optional[List[str]] = None,
    top_n: int = 50,
    use_aliases: bool = False,
    area: int = 113,
    pages: int = 2,
    delay: float = 1.5,
    get_details: bool = True,
    max_queries: Optional[int] = None,
    tech_min_popularity: int = 0,
    use_jitter: bool = True,
    rotate_user_agent: bool = True,
    use_proxy: bool = False,
    custom_proxies: Optional[List[Dict[str, str]]] = None
):
    """
    Celery-задача для парсинга вакансий по технологиям в заданном временном сегменте.

    Args:
        date_from (str): Дата начала сегмента (YYYY-MM-DD)
        date_to (str): Дата окончания сегмента (YYYY-MM-DD)
        categories (List[str]): Список категорий технологий
        top_n (int): Количество топовых технологий
        use_aliases (bool): Использовать алиасы технологий
        area (int): ID региона
        pages (int): Количество страниц на запрос
        delay (float): Задержка между запросами
        get_details (bool): Получать детали вакансий
        max_queries (int): Максимальное количество запросов
        tech_min_popularity (int): Минимальная популярность технологий

    Returns:
        dict: Статистика парсинга сегмента
    """
    logger.info('='*70)
    logger.info(f'Парсинг сегмента {date_from} - {date_to} по технологиям')
    logger.info('='*70)

    if not _skill_map_installed():
        msg = f'Приложение modules.competence_core.api.skill_map не подключено'
        logger.warning(msg)
        return {'error': msg, 'segment': f'{date_from}_{date_to}'}

    try:
        from ..utils.technology_search_generator import TechnologySearchGenerator
        generator = TechnologySearchGenerator()

        # Создаем парсер с улучшенными настройками обхода блокировок
        metrics = ParsingMetrics()
        parser = HeadHunterParser(
            metrics=metrics,
            use_jitter=use_jitter,
            rotate_user_agent=rotate_user_agent,
            use_proxy=use_proxy,
            custom_proxies=custom_proxies
        )

        # Загружаем технологии
        if categories:
            logger.info(f'Загрузка технологий категорий: {categories}')
            generator.load_technologies(
                categories=categories,
                min_popularity=tech_min_popularity,
                limit=top_n,
                include_aliases=use_aliases
            )
        else:
            logger.info(f'Загрузка технологий (лимит: {top_n})')
            generator.load_technologies(
                min_popularity=tech_min_popularity,
                limit=top_n,
                include_aliases=use_aliases
            )

        # Генерируем поисковые запросы
        search_queries = generator.generate_search_queries(
            use_aliases=use_aliases,
            max_queries=max_queries
        )

        logger.info(f'Сгенерировано запросов: {len(search_queries)}')

        if not search_queries:
            msg = 'Не найдено подходящих технологий для парсинга'
            logger.warning(msg)
            return {
                'error': msg,
                'segment': f'{date_from}_{date_to}',
                'technologies_count': 0,
                'search_queries_count': 0
            }

        # Парсим вакансии для сегмента с автоматической рекурсивной сегментацией
        logger.info(f'Запуск парсинга {len(search_queries)} запросов для сегмента {date_from}-{date_to}')

        # Используем рекурсивную сегментацию из date_parsing
        from .date_parsing import parse_date_range_recursive
        
        start_date = datetime.fromisoformat(date_from.replace('T', ' ')).date()
        end_date = datetime.fromisoformat(date_to.replace('T', ' ')).date()
        
        result = parse_date_range_recursive(
            search_queries=search_queries,
            date_from=start_date,
            date_to=end_date,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=3
        )

        # Добавляем информацию о сегменте
        result.update({
            'segment': f'{date_from}_{date_to}',
            'technologies_count': len(generator.technologies),
            'search_queries_count': len(search_queries),
            'search_queries': search_queries[:10]  # Первые 10 для логов
        })

        logger.info(f'Сегмент {date_from}-{date_to} завершен: {result.get("new_vacancies", 0)} новых, '
                   f'{result.get("updated_vacancies", 0)} обновлено')

        return result

    except Exception as e:
        logger.exception(f'Ошибка при парсинге сегмента {date_from}-{date_to}')
        return {
            'error': str(e),
            'segment': f'{date_from}_{date_to}',
            'technologies_count': 0,
            'search_queries_count': 0
        }


def _split_segment_and_parse(search_queries, start_date, end_date, area, pages, delay, get_details,
                           parser, orig_date_from, orig_date_to):
    """
    Разделяет сегмент на меньшие части при превышении лимита вакансий.
    
    Использует рекурсивную сегментацию из date_parsing для оптимального разбиения.
    """
    from .date_parsing import parse_date_range_recursive
    
    # Преобразуем datetime в date если нужно
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    
    logger.info(f'Рекурсивная сегментация сегмента {orig_date_from}-{orig_date_to}')
    
    # Используем рекурсивную сегментацию
    result = parse_date_range_recursive(
        search_queries=search_queries,
        date_from=start_date,
        date_to=end_date,
        area=area,
        pages=pages,
        delay=delay,
        get_details=get_details,
        max_depth=3
    )
    
    # Добавляем информацию о разделении для обратной совместимости
    result['segment_split'] = True
    result['sub_segments'] = result.get('segments', [])
    
    return result


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    soft_time_limit=5100,
    time_limit=5400,
    # ВАЖНО: имя должно совпадать с уже настроенными задачами Beat
    name="modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies",
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
        msg = f'Приложение modules.competence_core.api.skill_map не подключено'
        logger.warning(msg)
        return {'error': msg}

    try:
        from ..utils.technology_search_generator import TechnologySearchGenerator
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
    name='modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category',
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
            'error': f'Приложение modules.competence_core.api.skill_map не подключено'
        }

    try:
        from ..utils.technology_search_generator import TechnologySearchGenerator
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
