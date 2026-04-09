"""
Месячный парсинг вакансий с рекурсивной сегментацией.

Обеспечивает парсинг за прошедший месяц (30 дней) с автоматической
адаптацией под лимит API HeadHunter через рекурсивную сегментацию.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List
from celery import shared_task, group

from .base import _skill_map_installed
from .date_parsing import parse_date_range_recursive
from ..utils.technology_search_generator import TechnologySearchGenerator

logger = logging.getLogger('modules.vacancies_parser.headhunter')


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    soft_time_limit=28800,  # 8 часов
    time_limit=36000,  # 10 часов
    name='modules.vacancies_parser.api.headhunter.tasks.parse_monthly_vacancies_recursive',
)
def parse_monthly_vacancies_recursive(
    self,
    days_back: int = 30,
    area: int = 113,
    pages: int = 20,
    delay: float = 1.5,
    get_details: bool = True,
    use_aliases: bool = True,
    max_queries: Optional[int] = None,
    parallel_days: int = 5
) -> Dict[str, Any]:
    """
    Месячный парсинг вакансий за прошедший период с рекурсивной сегментацией.
    
    Парсит вакансии за указанный период (по умолчанию 30 дней назад - сегодня)
    с автоматической рекурсивной сегментацией при превышении лимита 2000 вакансий:
    - Месяц → дни → часы → интервалы
    
    Args:
        days_back: Количество дней назад для начала периода (по умолчанию 30)
        area: ID региона (113 = Россия)
        pages: Количество страниц на запрос (максимум 20)
        delay: Задержка между запросами в секундах
        get_details: Получать детальную информацию о вакансиях
        use_aliases: Использовать алиасы технологий как отдельные запросы
        max_queries: Максимальное количество запросов (если None - все технологии)
        parallel_days: Количество дней для параллельной обработки через Celery group
    
    Returns:
        dict: Статистика парсинга за период
    """
    logger.info('='*80)
    logger.info('МЕСЯЧНЫЙ ПАРСИНГ: Запуск парсинга за прошедший период')
    logger.info('='*80)
    
    if not _skill_map_installed():
        error_msg = 'Приложение modules.competence_core.api.skill_map не подключено'
        logger.error(error_msg)
        return {
            'error': error_msg,
            'period': {},
            'statistics': {}
        }
    
    try:
        # Определение периода
        today = date.today()
        date_from = today - timedelta(days=days_back)
        date_to = today
        
        logger.info(f'Период парсинга: {date_from.isoformat()} - {date_to.isoformat()} ({days_back} дней)')
        
        # Загрузка всех технологий
        generator = TechnologySearchGenerator()
        technologies_count = generator.load_technologies(
            categories=None,  # Все категории
            min_popularity=0,  # Все технологии
            include_aliases=use_aliases,
            limit=None  # Все технологии
        )
        
        logger.info(f'Загружено {technologies_count} технологий')
        
        # Генерация поисковых запросов
        search_queries = generator.generate_search_queries(
            use_aliases=use_aliases,
            max_queries=max_queries,
            include_duplicate_aliases=False
        )
        
        logger.info(f'Сгенерировано {len(search_queries)} поисковых запросов')
        
        if not search_queries:
            error_msg = 'Не найдено подходящих технологий для парсинга'
            logger.warning(error_msg)
            return {
                'error': error_msg,
                'period': {},
                'statistics': {}
            }
        
        # Разбиваем период на батчи дней для параллельной обработки
        period_days = (date_to - date_from).days + 1
        
        if period_days <= parallel_days:
            # Если период небольшой, парсим напрямую
            logger.info(f'Период небольшой ({period_days} дней), парсим напрямую')
            result = parse_date_range_recursive(
                search_queries=search_queries,
                date_from=date_from,
                date_to=date_to,
                area=area,
                pages=pages,
                delay=delay,
                get_details=get_details,
                max_depth=3
            )
            
            return {
                'period': {
                    'date_from': date_from.isoformat(),
                    'date_to': date_to.isoformat(),
                    'days': period_days
                },
                'statistics': {
                    'new_vacancies': result.get('new_vacancies', 0),
                    'updated_vacancies': result.get('updated_vacancies', 0),
                    'total_vacancies': result.get('total_vacancies', 0),
                    'segment_type': result.get('segment_type', 'direct'),
                    'segments_count': result.get('segments_count', 1)
                },
                'technologies_count': technologies_count,
                'search_queries_count': len(search_queries),
                'config': {
                    'area': area,
                    'pages': pages,
                    'delay': delay,
                    'get_details': get_details,
                    'use_aliases': use_aliases
                }
            }
        
        # Для больших периодов используем параллельную обработку по дням
        logger.info(f'Период большой ({period_days} дней), используем параллельную обработку')
        
        # Создаем задачи для каждого дня
        day_tasks = []
        current_date = date_from
        
        while current_date <= date_to:
            day_date = current_date
            day_task = _parse_single_day_recursive.si(
                search_queries=search_queries,
                target_date=day_date.isoformat(),
                area=area,
                pages=pages,
                delay=delay,
                get_details=get_details
            )
            day_tasks.append(day_task)
            current_date += timedelta(days=1)
        
        # Запускаем параллельную обработку через Celery group
        logger.info(f'Запуск {len(day_tasks)} задач для параллельной обработки дней')
        job = group(day_tasks)
        result_group = job.apply_async()
        
        # Ждем завершения всех задач
        results = result_group.get()
        
        # Агрегируем результаты
        total_new = sum(r.get('new_vacancies', 0) for r in results if isinstance(r, dict))
        total_updated = sum(r.get('updated_vacancies', 0) for r in results if isinstance(r, dict))
        total_vacancies = sum(r.get('total_vacancies', 0) for r in results if isinstance(r, dict))
        
        successful_days = sum(1 for r in results if isinstance(r, dict) and 'error' not in r)
        failed_days = len(results) - successful_days
        
        result = {
            'period': {
                'date_from': date_from.isoformat(),
                'date_to': date_to.isoformat(),
                'days': period_days
            },
            'statistics': {
                'new_vacancies': total_new,
                'updated_vacancies': total_updated,
                'total_vacancies': total_vacancies,
                'successful_days': successful_days,
                'failed_days': failed_days,
                'total_days': len(results)
            },
            'technologies_count': technologies_count,
            'search_queries_count': len(search_queries),
            'config': {
                'area': area,
                'pages': pages,
                'delay': delay,
                'get_details': get_details,
                'use_aliases': use_aliases,
                'parallel_days': parallel_days
            },
            'daily_results': results[:10] if len(results) > 10 else results  # Первые 10 для логов
        }
        
        logger.info('='*80)
        logger.info('МЕСЯЧНЫЙ ПАРСИНГ ЗАВЕРШЕН')
        logger.info(
            f'Период {date_from.isoformat()} - {date_to.isoformat()}: '
            f'новых={total_new}, обновлено={total_updated}, всего={total_vacancies}, '
            f'успешных дней={successful_days}, ошибок={failed_days}'
        )
        logger.info('='*80)
        
        return result
    
    except Exception as e:
        logger.exception(f'Ошибка при месячном парсинге: {e}')
        return {
            'error': str(e),
            'period': {},
            'statistics': {}
        }


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    soft_time_limit=7200,  # 2 часа на день
    time_limit=9000,  # 2.5 часа максимум
    name='modules.vacancies_parser.api.headhunter.tasks._parse_single_day_recursive',
)
def _parse_single_day_recursive(
    self,
    search_queries: List[str],
    target_date: str,
    area: int,
    pages: int,
    delay: float,
    get_details: bool
) -> Dict[str, Any]:
    """
    Вспомогательная задача для парсинга одного дня с рекурсивной сегментацией.
    
    Используется для параллельной обработки дней в месячном парсинге.
    
    Args:
        search_queries: Список поисковых запросов
        target_date: Дата для парсинга (YYYY-MM-DD)
        area: ID региона
        pages: Количество страниц на запрос
        delay: Задержка между запросами
        get_details: Получать детальную информацию
    
    Returns:
        dict: Статистика парсинга за день
    """
    try:
        target_date_obj = date.fromisoformat(target_date)
        
        logger.info(f'Парсинг дня {target_date}')
        
        result = parse_date_range_recursive(
            search_queries=search_queries,
            date_from=target_date_obj,
            date_to=target_date_obj,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=3
        )
        
        result['date'] = target_date
        return result
    
    except Exception as e:
        logger.error(f'Ошибка при парсинге дня {target_date}: {e}')
        return {
            'error': str(e),
            'date': target_date,
            'new_vacancies': 0,
            'updated_vacancies': 0,
            'total_vacancies': 0
        }
