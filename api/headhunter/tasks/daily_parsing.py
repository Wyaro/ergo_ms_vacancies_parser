"""
Ежедневный парсинг вакансий за вчера и сегодня.

Обеспечивает стабильный максимально результативный парсинг за последние 2 дня
с использованием всех технологий и их синонимов.
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional

from celery import shared_task

from .base import _skill_map_installed
from .date_parsing import parse_date_range_recursive
from ..utils.technology_search_generator import TechnologySearchGenerator

logger = logging.getLogger('modules.vacancies_parser.headhunter')


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    soft_time_limit=14400,  # 4 часа
    time_limit=18000,  # 5 часов
    name='modules.vacancies_parser.api.headhunter.tasks.parse_daily_vacancies_yesterday_today',
)
def parse_daily_vacancies_yesterday_today(
    self,
    area: int = 113,
    pages: int = 20,
    delay: float = 1.5,
    get_details: bool = True,
    use_aliases: bool = True,
    max_queries: Optional[int] = None
) -> Dict[str, Any]:
    """
    Ежедневный парсинг вакансий за вчера и сегодня.
    
    Обеспечивает максимально результативный парсинг:
    - Парсинг за вчера (полный день)
    - Парсинг за сегодня (до текущего момента)
    - Использование всех технологий и их синонимов
    - Автоматическая рекурсивная сегментация при превышении лимита
    
    Args:
        area: ID региона (113 = Россия)
        pages: Количество страниц на запрос (максимум 20 для максимального покрытия)
        delay: Задержка между запросами в секундах
        get_details: Получать детальную информацию о вакансиях
        use_aliases: Использовать алиасы технологий как отдельные запросы
        max_queries: Максимальное количество запросов (если None - все технологии)
    
    Returns:
        dict: Статистика парсинга за вчера и сегодня
    """
    logger.info('='*80)
    logger.info('ЕЖЕДНЕВНЫЙ ПАРСИНГ: Запуск парсинга за вчера и сегодня')
    logger.info('='*80)
    
    if not _skill_map_installed():
        error_msg = 'Приложение modules.competence_core.api.skill_map не подключено'
        logger.error(error_msg)
        return {
            'error': error_msg,
            'yesterday': {},
            'today': {}
        }
    
    try:
        # Определение дат
        today = date.today()
        yesterday = today - timedelta(days=1)
        
        logger.info(f'Период парсинга: вчера ({yesterday.isoformat()}) и сегодня ({today.isoformat()})')
        
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
                'yesterday': {},
                'today': {}
            }
        
        # Парсинг за вчера (полный день)
        logger.info('='*80)
        logger.info(f'ПАРСИНГ ЗА ВЧЕРА ({yesterday.isoformat()})')
        logger.info('='*80)
        
        yesterday_result = parse_date_range_recursive(
            search_queries=search_queries,
            date_from=yesterday,
            date_to=yesterday,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=3
        )
        
        logger.info(
            f'Вчера ({yesterday.isoformat()}): '
            f'новых={yesterday_result.get("new_vacancies", 0)}, '
            f'обновлено={yesterday_result.get("updated_vacancies", 0)}, '
            f'всего={yesterday_result.get("total_vacancies", 0)}'
        )
        
        # Парсинг за сегодня (до текущего момента)
        logger.info('='*80)
        logger.info(f'ПАРСИНГ ЗА СЕГОДНЯ ({today.isoformat()})')
        logger.info('='*80)
        
        today_result = parse_date_range_recursive(
            search_queries=search_queries,
            date_from=today,
            date_to=today,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=3
        )
        
        logger.info(
            f'Сегодня ({today.isoformat()}): '
            f'новых={today_result.get("new_vacancies", 0)}, '
            f'обновлено={today_result.get("updated_vacancies", 0)}, '
            f'всего={today_result.get("total_vacancies", 0)}'
        )
        
        # Агрегированная статистика
        total_new = yesterday_result.get('new_vacancies', 0) + today_result.get('new_vacancies', 0)
        total_updated = yesterday_result.get('updated_vacancies', 0) + today_result.get('updated_vacancies', 0)
        total_vacancies = yesterday_result.get('total_vacancies', 0) + today_result.get('total_vacancies', 0)
        
        result = {
            'yesterday': {
                'date': yesterday.isoformat(),
                'new_vacancies': yesterday_result.get('new_vacancies', 0),
                'updated_vacancies': yesterday_result.get('updated_vacancies', 0),
                'total_vacancies': yesterday_result.get('total_vacancies', 0),
                'segment_type': yesterday_result.get('segment_type', 'direct'),
                'segments_count': yesterday_result.get('segments_count', 1)
            },
            'today': {
                'date': today.isoformat(),
                'new_vacancies': today_result.get('new_vacancies', 0),
                'updated_vacancies': today_result.get('updated_vacancies', 0),
                'total_vacancies': today_result.get('total_vacancies', 0),
                'segment_type': today_result.get('segment_type', 'direct'),
                'segments_count': today_result.get('segments_count', 1)
            },
            'total': {
                'new_vacancies': total_new,
                'updated_vacancies': total_updated,
                'total_vacancies': total_vacancies
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
        
        logger.info('='*80)
        logger.info('ЕЖЕДНЕВНЫЙ ПАРСИНГ ЗАВЕРШЕН')
        logger.info(f'Итого: новых={total_new}, обновлено={total_updated}, всего={total_vacancies}')
        logger.info('='*80)
        
        return result
    
    except Exception as e:
        logger.exception(f'Ошибка при ежедневном парсинге: {e}')
        return {
            'error': str(e),
            'yesterday': {},
            'today': {}
        }
