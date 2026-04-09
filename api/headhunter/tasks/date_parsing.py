"""
Рекурсивная сегментация дат для парсинга вакансий.

Обеспечивает автоматическое разбиение периодов на более мелкие сегменты
при превышении лимита API HeadHunter (2000 вакансий на запрос).
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

from ..parsers.hh_parser import HeadHunterParser
from ..scripts import parse_vacancies_by_text

logger = logging.getLogger('modules.vacancies_parser.headhunter')

# Лимит API HeadHunter: максимум 20 страниц × 100 вакансий = 2000 вакансий
HH_API_VACANCIES_LIMIT = 2000


def parse_date_range_recursive(
    search_queries: List[str],
    date_from: date,
    date_to: date,
    area: int = 113,
    pages: int = 20,
    delay: float = 1.5,
    get_details: bool = True,
    max_depth: int = 3
) -> Dict[str, Any]:
    """
    Рекурсивный парсинг диапазона дат с автоматической сегментацией.
    
    Алгоритм:
    1. Проверяет количество вакансий за период
    2. Если ≤2000 → парсит как есть
    3. Если >2000 → рекурсивно разбивает на более мелкие сегменты:
       - Период >1 дня → разбить на дни
       - День >2000 вакансий → разбить на 24 часа
       - Час >2000 вакансий → разбить на интервалы (30 минут)
    
    Args:
        search_queries: Список поисковых запросов
        date_from: Начальная дата
        date_to: Конечная дата
        area: ID региона (113 = Россия)
        pages: Количество страниц на запрос (максимум 20)
        delay: Задержка между запросами
        get_details: Получать детальную информацию
        max_depth: Максимальная глубина рекурсии (предотвращает бесконечную рекурсию)
    
    Returns:
        dict: Статистика парсинга с информацией о сегментации
    """
    if max_depth <= 0:
        logger.warning(f'Достигнута максимальная глубина рекурсии для периода {date_from} - {date_to}')
        return {
            'error': 'max_depth_reached',
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'total_vacancies': 0,
            'new_vacancies': 0,
            'updated_vacancies': 0
        }
    
    # Проверяем количество вакансий за период
    parser = HeadHunterParser()
    sample_query = search_queries[0] if search_queries else 'программист'
    
    vacancies_count = _check_vacancies_count(
        parser=parser,
        search_text=sample_query,
        date_from=date_from,
        date_to=date_to,
        area=area
    )
    
    logger.info(
        f'Период {date_from} - {date_to}: найдено ~{vacancies_count} вакансий '
        f'(лимит: {HH_API_VACANCIES_LIMIT}, глубина: {max_depth})'
    )
    
    # Если вакансий меньше лимита, парсим напрямую
    if vacancies_count <= HH_API_VACANCIES_LIMIT:
        logger.info(f'Период {date_from} - {date_to} в пределах лимита, парсим напрямую')
        return parse_vacancies_by_text(
            text_list=search_queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            date_from=date_from.isoformat() if isinstance(date_from, date) else date_from,
            date_to=date_to.isoformat() if isinstance(date_to, date) else date_to
        )
    
    # Если период больше 1 дня, разбиваем на дни
    period_days = (date_to - date_from).days + 1
    
    if period_days > 1:
        logger.info(f'Период {date_from} - {date_to} ({period_days} дней) превышает лимит, разбиваем на дни')
        return _parse_period_by_days(
            search_queries=search_queries,
            date_from=date_from,
            date_to=date_to,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=max_depth
        )
    
    # Если период = 1 день и превышает лимит, разбиваем на часы
    logger.info(f'День {date_from} превышает лимит ({vacancies_count} вакансий), разбиваем на часы')
    return _parse_day_by_hours(
        search_queries=search_queries,
        target_date=date_from,
        area=area,
        pages=pages,
        delay=delay,
        get_details=get_details,
        max_depth=max_depth
    )


def _parse_period_by_days(
    search_queries: List[str],
    date_from: date,
    date_to: date,
    area: int,
    pages: int,
    delay: float,
    get_details: bool,
    max_depth: int
) -> Dict[str, Any]:
    """Разбивает период на дни и парсит каждый день рекурсивно"""
    results = []
    current_date = date_from
    
    while current_date <= date_to:
        day_result = parse_date_range_recursive(
            search_queries=search_queries,
            date_from=current_date,
            date_to=current_date,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            max_depth=max_depth - 1
        )
        results.append(day_result)
        current_date += timedelta(days=1)
    
    # Агрегируем результаты
    return _aggregate_results(results, segment_type='days')


def _parse_day_by_hours(
    search_queries: List[str],
    target_date: date,
    area: int,
    pages: int,
    delay: float,
    get_details: bool,
    max_depth: int
) -> Dict[str, Any]:
    """Разбивает день на 24 часа и парсит каждый час рекурсивно"""
    hour_intervals = _split_date_to_hours(target_date)
    results = []
    
    for hour_start, hour_end in hour_intervals:
        # Проверяем количество вакансий за час
        parser = HeadHunterParser()
        sample_query = search_queries[0] if search_queries else 'программист'
        
        hour_vacancies = _check_vacancies_count(
            parser=parser,
            search_text=sample_query,
            date_from=hour_start.date(),
            date_to=hour_end.date(),
            area=area,
            hour_from=hour_start.hour,
            hour_to=hour_end.hour
        )
        
        if hour_vacancies <= HH_API_VACANCIES_LIMIT:
            # Парсим час напрямую
            hour_result = parse_vacancies_by_text(
                text_list=search_queries,
                area=area,
                pages=pages,
                delay=delay,
                get_details=get_details,
                date_from=hour_start.isoformat(),
                date_to=hour_end.isoformat()
            )
        else:
            # Разбиваем час на интервалы
            logger.info(
                f'Час {hour_start.hour:02d}:00 - {hour_end.hour:02d}:00 превышает лимит '
                f'({hour_vacancies} вакансий), разбиваем на интервалы'
            )
            hour_result = _parse_hour_by_intervals(
                search_queries=search_queries,
                hour_start=hour_start,
                hour_end=hour_end,
                area=area,
                pages=pages,
                delay=delay,
                get_details=get_details,
                max_depth=max_depth - 1
            )
        
        results.append(hour_result)
    
    return _aggregate_results(results, segment_type='hours')


def _parse_hour_by_intervals(
    search_queries: List[str],
    hour_start: datetime,
    hour_end: datetime,
    area: int,
    pages: int,
    delay: float,
    get_details: bool,
    max_depth: int
) -> Dict[str, Any]:
    """Разбивает час на интервалы (30 минут) и парсит каждый интервал"""
    intervals = _split_hour_to_intervals(hour_start, hour_end)
    results = []
    
    for interval_start, interval_end in intervals:
        interval_result = parse_vacancies_by_text(
            text_list=search_queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            date_from=interval_start.isoformat(),
            date_to=interval_end.isoformat()
        )
        results.append(interval_result)
    
    return _aggregate_results(results, segment_type='intervals')


def _split_date_to_hours(target_date: date) -> List[Tuple[datetime, datetime]]:
    """
    Разбивает день на 24 часа.
    
    Args:
        target_date: Дата для разбиения
    
    Returns:
        List[Tuple[datetime, datetime]]: Список интервалов (начало, конец) по часу
    """
    intervals = []
    
    for hour in range(24):
        hour_start = datetime.combine(target_date, datetime.min.time().replace(hour=hour))
        hour_end = hour_start + timedelta(hours=1) - timedelta(seconds=1)
        
        # Для последнего часа используем конец дня
        if hour == 23:
            hour_end = datetime.combine(target_date, datetime.max.time())
        
        intervals.append((hour_start, hour_end))
    
    return intervals


def _split_hour_to_intervals(hour_start: datetime, hour_end: datetime) -> List[Tuple[datetime, datetime]]:
    """
    Разбивает час на интервалы по 30 минут.
    
    Args:
        hour_start: Начало часа
        hour_end: Конец часа
    
    Returns:
        List[Tuple[datetime, datetime]]: Список интервалов (начало, конец) по 30 минут
    """
    intervals = []
    current = hour_start
    
    while current < hour_end:
        interval_start = current
        interval_end = min(current + timedelta(minutes=30), hour_end)
        intervals.append((interval_start, interval_end))
        current = interval_end
    
    return intervals


def _check_vacancies_count(
    parser: HeadHunterParser,
    search_text: str,
    date_from,
    date_to,
    area: int,
    hour_from: Optional[int] = None,
    hour_to: Optional[int] = None
) -> int:
    """
    Проверяет количество вакансий за период.
    
    Args:
        parser: Парсер HeadHunter
        search_text: Поисковый запрос
        date_from: Начальная дата (date или str ISO)
        date_to: Конечная дата (date или str ISO)
        area: ID региона
        hour_from: Начальный час (опционально, для фильтрации по часам)
        hour_to: Конечный час (опционально)
    
    Returns:
        int: Количество найденных вакансий
    """
    try:
        # Преобразуем в строки ISO если нужно
        if isinstance(date_from, date):
            date_from_str = date_from.isoformat()
        else:
            date_from_str = date_from
        
        if isinstance(date_to, date):
            date_to_str = date_to.isoformat()
        else:
            date_to_str = date_to
        
        # Делаем запрос для получения количества
        result = parser.search_vacancies(
            text=search_text,
            area=area,
            per_page=1,  # Минимум для получения количества
            page=0,
            date_from=date_from_str,
            date_to=date_to_str
        )
        
        if result and 'found' in result:
            return result['found']
        else:
            logger.warning(f'Не удалось получить количество вакансий для {search_text}')
            return 0
    
    except Exception as e:
        logger.error(f'Ошибка при проверке количества вакансий: {e}')
        return 0


def _aggregate_results(results: List[Dict[str, Any]], segment_type: str) -> Dict[str, Any]:
    """
    Агрегирует результаты парсинга из нескольких сегментов.
    
    Args:
        results: Список результатов парсинга
        segment_type: Тип сегментации ('days', 'hours', 'intervals')
    
    Returns:
        dict: Агрегированная статистика
    """
    total_vacancies = sum(r.get('total_vacancies', 0) for r in results)
    new_vacancies = sum(r.get('new_vacancies', 0) for r in results)
    updated_vacancies = sum(r.get('updated_vacancies', 0) for r in results)
    
    return {
        'total_vacancies': total_vacancies,
        'new_vacancies': new_vacancies,
        'updated_vacancies': updated_vacancies,
        'total_in_db': max((r.get('total_in_db', 0) for r in results), default=0),
        'segment_type': segment_type,
        'segments_count': len(results),
        'segments': results
    }
