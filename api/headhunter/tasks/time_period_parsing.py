import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from celery import shared_task
from django.utils import timezone

from ..scripts import HeadHunterParser
from ..models import Vacancy

from .base import _skill_map_installed
from .batch_processing import _save_vacancies_batch_celery

logger = logging.getLogger('modules.vacancies_parser.headhunter')

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=7200,
    time_limit=7500,
)
def parse_vacancies_by_time_period_parallel(
    self,
    date_from: str,
    date_to: str,
    keywords: Optional[List[str]] = None,
    area: int = 113,
    segment_days: int = 2,
    segments_count: int = 10,
    max_workers: int = 3,
    concurrent_queries: int = 1,
    api_delay: float = 0.5,
    show_sample: int = 5
):
    """
    МАСТЕР Celery-задача для распределенного парсинга вакансий.

    Эта задача РАЗБИВАЕТ работу на подзадачи и распределяет их между worker'ами:
    1. Разбивает период на сегменты по времени
    2. Создает подзадачи для каждого поискового запроса
    3. Каждая подзадача обрабатывается отдельным worker'ом
    4. Агрегирует результаты всех подзадач

    Args:
        date_from (str): Дата начала периода (YYYY-MM-DD)
        date_to (str): Дата окончания периода (YYYY-MM-DD)
        keywords (List[str]): Список ключевых слов для поиска
        area (int): ID региона (113 = Россия)
        segment_days (int): Длительность сегмента в днях
        segments_count (int): Максимальное количество сегментов
        max_workers (int): Потоков на одного worker'а
        concurrent_queries (int): Одновременных запросов (для совместимости)
        api_delay (float): Задержка между API запросами
        show_sample (int): Количество примеров в выводе

    Returns:
        dict: Агрегированная статистика от всех подзадач
    """
    # parse_single_query_segment_task определена ниже в этом же файле

    start_time = time.time()
    logger.info('МАСТЕР ЗАДАЧА: Запуск распределенного парсинга')
    logger.info('='*100)
    logger.info(f'Период: {date_from} - {date_to}')
    logger.info(f'Запросов: {len(keywords) if keywords else "автогенерация"}')
    logger.info(f'Конфигурация: workers={max_workers}, delay={api_delay}')
    logger.info('='*100)

    if not keywords:
        # Автогенерация запросов
        if _skill_map_installed():
            from .utils.technology_search_generator import TechnologySearchGenerator
            generator = TechnologySearchGenerator()
            generator.load_technologies(limit=20, include_aliases=True)
            keywords = generator.generate_search_queries(use_aliases=True, max_queries=10)
        else:
            keywords = ["Python", "JavaScript", "Java", "C++", "PHP", "C#"]

    # Убеждаемся, что keywords - это список
    if not keywords:
        keywords = []

    # Создаем подзадачи для каждого ключевого слова с ограничением параллельности
    sub_tasks = []
    batch_size = 50  # Ограничение количества одновременно отправляемых задач
    batch_delay = 1.0  # Задержка между батчами в секундах

    for i, keyword in enumerate(keywords):
        task = parse_single_query_segment_task.delay(  # type: ignore[misc]
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            area=area,
            segment_days=segment_days,
            segments_count=segments_count,
            max_workers=max_workers,
            api_delay=api_delay,
            show_sample=show_sample
        )
        sub_tasks.append((keyword, task))
        logger.info(f'Отправлена подзадача для: "{keyword}" (task_id: {task.id})')

        # Задержка между батчами для предотвращения перегрузки
        if (i + 1) % batch_size == 0 and i + 1 < len(keywords):
            logger.info(f'Пауза {batch_delay} сек после отправки {batch_size} задач...')
            time.sleep(batch_delay)

    # В Celery нельзя блокировать задачу ожиданием других задач!
    # Вместо этого возвращаем информацию о запущенных подзадачах
    logger.info(f'Отправлено {len(sub_tasks)} подзадач для параллельной обработки')

    sub_task_info = [{'keyword': keyword, 'task_id': str(task.id)} for keyword, task in sub_tasks]

    # Возвращаем информацию без блокировки
    total_stats = {
        'processed': 0,  # Будет подсчитано позже
        'saved': 0,
        'updated': 0,
        'unchanged': 0,
        'errors': 0,
        'queries_sent': len(sub_tasks),
        'sub_tasks': sub_task_info,
        'note': 'Результаты доступны в Flower или через отдельный запрос агрегации'
    }

    elapsed_time = time.time() - start_time
    logger.info('='*100)
    logger.info('МАСТЕР ЗАДАЧА: ПОДЗАДАЧИ ОТПРАВЛЕНЫ')
    logger.info(f'Отправлено задач: {len(sub_tasks)}')
    logger.info(f'Время на подготовку: {elapsed_time:.1f} сек')
    logger.info(f'Производительность: {len(keywords) / elapsed_time:.1f} задач/сек')
    logger.info('Мониторьте выполнение через Flower: http://localhost:5555')
    logger.info('='*100)

    return {
        'mode': 'distributed_parallel',
        'status': 'tasks_dispatched',  # Задачи отправлены, но не завершены
        'master_task_id': self.request.id,
        'sub_tasks_count': len(sub_tasks),
        'date_from': date_from,
        'date_to': date_to,
        'keywords': keywords,
        'config': {
            'segment_days': segment_days,
            'segments_count': segments_count,
            'max_workers': max_workers,
            'api_delay': api_delay
        },
        'total_statistics': total_stats,
        'performance': {
            'elapsed_time': elapsed_time,
            'tasks_dispatched_per_second': len(keywords) / elapsed_time if elapsed_time > 0 else 0
        },
        'sub_tasks': sub_task_info,
        'monitoring': {
            'flower_url': 'http://localhost:5555',
            'note': 'Мониторьте выполнение подзадач через Flower'
        }
    }


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=3600,
    time_limit=3900,
)
def parse_single_query_segment_task(
    self,
    keyword: str,
    date_from: str,
    date_to: str,
    area: int = 113,
    segment_days: int = 2,
    segments_count: int = 10,
    max_workers: int = 3,
    api_delay: float = 0.5,
    show_sample: int = 5
):
    """
    ПОДЗАДАЧА: Парсинг одного ключевого слова с сегментацией по времени.

    Выполняет полную логику парсинга для одного поискового запроса
    с внутренней многопоточной обработкой сегментов.
    """
    import time as time_module
    start_time = time_module.time()  # Запоминаем время начала
    logger.info(f'ПОДЗАДАЧА: Обработка "{keyword}" за период {date_from}-{date_to}')

    try:
        # Инициализация (здесь должна быть логика из management команды)
        parser = HeadHunterParser()

        params = {
            'area': area,
            'date_from': date_from,
            'date_to': date_to,
            'segment_days': segment_days,
            'segments_count': segments_count,
            'show_sample': show_sample,
            'max_workers': max_workers,
            'api_delay': api_delay
        }

        # Реальная логика сбора и обработки сегментов
        segments_data = _collect_segments_celery(parser, keyword, params)

        # Инициализация статистики
        query_stats = {
            'processed': 0,
            'saved': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 0,
            'samples': []
        }

        # Обработка сегментов
        _process_segments_parallel_celery(segments_data, keyword, params, query_stats)

        elapsed = time_module.time() - start_time
        logger.info(f'ПОДЗАДАЧА "{keyword}" завершена: {query_stats["processed"]} вакансий за {elapsed:.1f} сек')

        return {
            'keyword': keyword,
            'task_id': self.request.id,
            'date_from': date_from,
            'date_to': date_to,
            'statistics': query_stats,
            'segments_processed': len(segments_data),
            'performance': {
                'elapsed_time': time_module.time() - start_time,
                'vacancies_per_second': query_stats['processed'] / max(time_module.time() - start_time, 0.001) if query_stats['processed'] > 0 else 0
            }
        }

    except Exception as exc:
        logger.error(f'Ошибка в подзадаче "{keyword}": {exc}', exc_info=True)
        raise self.retry(exc=exc)


# Вспомогательные функции для Celery задач
def _collect_segments_generator_celery(parser: HeadHunterParser, search_text: str, params: Dict[str, Any]):
    """Генератор сегментов для Celery задачи"""
    # Параметры сегментации
    segment_days = params['segment_days']
    segments_count = params['segments_count']
    area = params['area']
    date_from = params['date_from']
    date_to = params['date_to']
    api_delay = params['api_delay']

    # Преобразование строковых дат в объекты date
    start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
    end_date = datetime.strptime(date_to, '%Y-%m-%d').date()

    # Проверка корректности диапазона
    if start_date >= end_date:
        logger.warning(f'Некорректный диапазон дат: {date_from} - {date_to}')
        return

    # Расчет общего периода в днях
    total_days = (end_date - start_date).days + 1

    # Автоматический расчет размера сегментов
    if segments_count <= 0:
        # Автоматический расчет: примерно по segment_days дней на сегмент
        segments_count = max(1, (total_days + segment_days - 1) // segment_days)
    else:
        # Корректировка размера сегментов под желаемое количество
        segment_days = max(1, total_days // segments_count)

    logger.info(f'Сегментация: {total_days} дней, {segments_count} сегментов по {segment_days} дней')

    # Генерация сегментов
    current_date = start_date
    segment_index = 0

    while current_date <= end_date and segment_index < segments_count:
        # Расчет конца сегмента
        segment_end = min(current_date + timedelta(days=segment_days - 1), end_date)

        # Получение количества вакансий для сегмента
        try:
            vacancies_count = _get_vacancies_count_celery(
                parser=parser,
                search_text=search_text,
                area=area,
                segment_start=current_date,
                segment_end=segment_end,
                api_delay=api_delay
            )

            segment_data = {
                'index': segment_index,
                'start': current_date.strftime('%Y-%m-%d'),
                'end': segment_end.strftime('%Y-%m-%d'),
                'vacancies_count': vacancies_count,
                'start_date': current_date,
                'end_date': segment_end
            }

            logger.info(f'Сегмент {segment_index}: {current_date} - {segment_end}, вакансий: {vacancies_count}')
            yield segment_data

        except Exception as e:
            logger.error(f'Ошибка при обработке сегмента {segment_index}: {e}')
            # Продолжаем с пустым сегментом
            yield {
                'index': segment_index,
                'start': current_date.strftime('%Y-%m-%d'),
                'end': segment_end.strftime('%Y-%m-%d'),
                'vacancies_count': 0,
                'start_date': current_date,
                'end_date': segment_end
            }

        # Переход к следующему сегменту
        current_date = segment_end + timedelta(days=1)
        segment_index += 1


def _collect_segments_celery(parser: HeadHunterParser, search_text: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Собирает все сегменты для Celery задачи"""
    return list(_collect_segments_generator_celery(parser, search_text, params))


def _get_vacancies_count_celery(
    parser: HeadHunterParser,
    search_text: str,
    area: int,
    segment_start: date,
    segment_end: date,
    api_delay: float = 0.5
) -> int:
    """Получает количество найденных вакансий для диапазона дат"""
    try:
        # Форматируем даты
        date_from_str = segment_start.strftime('%Y-%m-%d')
        date_to_str = segment_end.strftime('%Y-%m-%d')

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
        logger.error(f'Ошибка при получении количества вакансий: {e}')
        return 0


def _process_segments_parallel_celery(all_segments, search_text, params, query_stats):
    """Параллельная обработка сегментов для Celery"""
    max_workers = params.get('max_workers', 3)
    api_delay = params.get('api_delay', 0.5)

    if max_workers <= 1 or len(all_segments) <= 1:
        # Последовательная обработка
        for seg_idx, segment in enumerate(all_segments, start=1):
            _process_single_segment_celery(
                segment=segment,
                seg_idx=seg_idx,
                search_text=search_text,
                params=params,
                query_stats=query_stats
            )
        return

    logger.info(f'Параллельная обработка {len(all_segments)} сегментов ({max_workers} потоков)')

    # Параллельная обработка с ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Подготовка задач
        future_to_segment = {}
        for seg_idx, segment in enumerate(all_segments, start=1):
            future = executor.submit(
                _process_single_segment_celery,
                segment=segment,
                seg_idx=seg_idx,
                search_text=search_text,
                params=params,
                query_stats=query_stats
            )
            future_to_segment[future] = (seg_idx, segment)

        # Сбор результатов
        for future in as_completed(future_to_segment):
            seg_idx, segment = future_to_segment[future]
            try:
                result = future.result()
                if result:
                    # Агрегация статистики
                    query_stats['processed'] += result.get('processed', 0)
                    query_stats['saved'] += result.get('saved', 0)
                    query_stats['updated'] += result.get('updated', 0)
                    query_stats['unchanged'] += result.get('unchanged', 0)
                    query_stats['errors'] += result.get('errors', 0)

                    # Добавление примеров
                    if result.get('samples'):
                        query_stats['samples'].extend(result['samples'])

            except Exception as e:
                logger.error(f'Ошибка в сегменте {seg_idx}: {e}')
                query_stats['errors'] += 1


def _process_single_segment_celery(segment: Dict[str, Any], seg_idx: int,
                                 search_text: str, params: Dict[str, Any],
                                 query_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Обработка одного сегмента для Celery"""
    try:
        # Создаем новый парсер для сегмента
        parser = HeadHunterParser()
        area = params['area']
        api_delay = params.get('api_delay', 0.5)

        # Получаем данные сегмента
        start_date = segment['start_date']
        end_date = segment['end_date']

        # Получаем данные вакансий для сегмента
        vacancies_data = _fetch_segment_vacancies_data_celery(
            parser=parser,
            search_text=search_text,
            area=area,
            segment_start=start_date,
            segment_end=end_date,
            api_delay=api_delay
        )

        # Сохраняем вакансии в БД
        stats = _save_vacancies_batch_celery(vacancies_data, search_text)

        # Формируем примеры для статистики
        samples = []
        if vacancies_data:
            for item in vacancies_data[:5]:  # Первые 5 вакансий как примеры
                samples.append({
                    'id': item.get('id', ''),
                    'title': item.get('name', ''),
                    'company': item.get('employer', {}).get('name', '') if item.get('employer') else ''
                })

        return {
            'processed': len(vacancies_data),
            'saved': stats['saved'],
            'updated': stats['updated'],
            'unchanged': stats['unchanged'],
            'errors': stats['errors'],
            'samples': samples
        }

    except Exception as e:
        logger.error(f'Критическая ошибка в сегменте {seg_idx}: {e}')
        return {
            'processed': 0,
            'saved': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 1,
            'samples': []
        }


def _fetch_segment_vacancies_data_celery(parser: HeadHunterParser, search_text: str,
                                       area: int, segment_start: date, segment_end: date,
                                       api_delay: float = 0.5) -> List[Dict[str, Any]]:
    """Получение данных вакансий для сегмента"""
    vacancies_data = []

    try:
        date_from_str = segment_start.strftime('%Y-%m-%d')
        date_to_str = segment_end.strftime('%Y-%m-%d')

        # Получаем все вакансии из сегмента
        page = 0
        per_page = 100  # Максимум для API

        while True:
            result = parser.search_vacancies(
                text=search_text,
                area=area,
                per_page=per_page,
                page=page,
                date_from=date_from_str,
                date_to=date_to_str
            )

            if not result or 'items' not in result:
                break

            items = result['items']
            if not items:
                break

            # Получаем детальную информацию по каждой вакансии
            for item in items:
                vacancy_id = item.get('id')
                if vacancy_id:
                    vacancy_details = parser.get_vacancy_details(vacancy_id)
                    if vacancy_details:
                        vacancies_data.append(vacancy_details)

                        # Задержка между запросами
                        if api_delay > 0:
                            time.sleep(api_delay)

            page += 1

            # Проверка на последнюю страницу
            if len(items) < per_page:
                break

    except Exception as e:
        logger.error(f'Ошибка при получении данных сегмента: {e}')

    return vacancies_data