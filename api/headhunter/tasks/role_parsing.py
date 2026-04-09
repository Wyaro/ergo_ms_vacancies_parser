"""
Парсинг вакансий по профессиональным ролям.
"""

import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
import asyncio

from celery import chord, shared_task
from django.apps import apps as django_apps
from django.db.models import Max
from django.utils import timezone

from ..scripts import HeadHunterParser, ParsingMetrics
from ..models import Vacancy

from .base import _load_target_category_id
from .batch_processing import _create_vacancy_from_api_data, _update_vacancy_from_api_data, _merge_snippet_into_details

logger = logging.getLogger('modules.vacancies_parser.headhunter')

logger = logging.getLogger('modules.vacancies_parser.headhunter')


def _format_duration(seconds: float) -> str:
    return f"{seconds:.2f} сек"


def _speed_cap_delay(value: float, *, min_value: float = 0.0, max_value: float = 0.25) -> float:
    """Ограничивает задержки для ускоренного профиля парсинга."""
    return max(min_value, min(float(value), max_value))


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=18000,
    time_limit=21600,
    # ВАЖНО: имя должно совпадать с уже настроенными задачами Beat
    name="modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_professional_roles",
)
def parse_vacancies_by_professional_roles(
    self,
    area: int = 113,
    pages: int = 3,
    delay: float = 1.5,
    get_details: bool = True,
    max_concurrent_roles: int = 5,
    batch_size: int = 10,
    force_refresh_roles: bool = False,
    no_delays: bool = False,
    parallel_workers: int = 1,  # Количество параллельных задач для ролей
    incremental: bool = False,  # Инкрементальный парсинг
    skip_existing_roles: bool = False,  # Пропускать уже парсированные роли
    # Дополнительные параметры фильтрации из API HH
    experience: Optional[str] = None,
    employment: Optional[str] = None,
    schedule: Optional[str] = None,
    only_with_salary: bool = False,
    period: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salary_from: Optional[int] = None,
    salary_to: Optional[int] = None
):
    """
    Celery-задача для парсинга вакансий по профессиональным ролям IT.

    Получает актуальный список IT ролей и парсит вакансии по каждой роли
    с использованием параметра professional_role в API.

    Args:
        area (int): ID региона для поиска (по умолчанию Россия)
        pages (int): Количество страниц для каждой роли
        delay (float): Задержка между запросами
        get_details (bool): Получать ли детальную информацию о вакансиях
        max_concurrent_roles (int): Максимум параллельных ролей
        batch_size (int): Размер батча для обработки
        force_refresh_roles (bool): Принудительно обновить список ролей из API

    Returns:
        dict: Статистика парсинга
    """
    # utils лежит уровнем выше, а не внутри пакета tasks
    from ..utils.professional_roles_config import ProfessionalRolesManager

    logger.info('Запуск парсинга вакансий по профессиональным ролям IT')
    logger.info(f'Параметры: area={area}, pages={pages}, delay={delay}, get_details={get_details}, parallel_workers={parallel_workers}')

    try:
        # Инициализируем менеджер ролей
        roles_manager = ProfessionalRolesManager()

        # Получаем список IT ролей
        it_roles = roles_manager.get_it_roles(force_refresh=force_refresh_roles)

        if not it_roles:
            return {
                'mode': 'by_professional_roles',
                'error': 'Не удалось получить список IT ролей',
                'total_roles': 0,
                'parsed_roles': 0,
                'total_vacancies': 0,
                'new_vacancies': 0
            }

        logger.info(f'Будет обработано {len(it_roles)} IT ролей')

        # ФИЛЬТРАЦИЯ РОЛЕЙ для оптимизации
        if skip_existing_roles or incremental:
            filtered_roles = _filter_roles_for_parsing(it_roles, skip_existing_roles, incremental)
            if len(filtered_roles) != len(it_roles):
                logger.info(f'После фильтрации: {len(filtered_roles)} из {len(it_roles)} ролей')
                it_roles = filtered_roles

        # ДОБАВЛЯЕМ ФИЛЬТР ПО ДАТЕ для инкрементального парсинга
        date_from_filter = None
        if incremental:
            from django.db.models import Max
            try:
                latest_vacancy = Vacancy.objects.aggregate(latest=Max('published_at'))['latest']
                if latest_vacancy:
                    # Парсим вакансии начиная с дня после последней
                    date_from_filter = (latest_vacancy - timedelta(days=1)).strftime('%Y-%m-%d')
                    logger.info(f'Инкрементальный режим: парсинг с даты {date_from_filter}')
            except Exception as e:
                logger.warning(f'Не удалось определить дату последней вакансии: {e}')

        # РАСПАРАЛЛЕЛИВАНИЕ: если указано больше 1 worker'а
        if parallel_workers > 1:
            parallel_workers = max(1, min(parallel_workers, len(it_roles)))

            # Корректируем delay для параллельной работы
            if not no_delays:
                original_delay = delay
                # При параллельной работе увеличиваем delay для снижения нагрузки
                delay = max(delay, 0.5) * (0.8 + parallel_workers * 0.2)  # Увеличиваем на 20-60%
                logger.info(
                    f'[ADJUST] Скорректирован delay для {parallel_workers} воркеров: '
                    f'{original_delay:.2f} → {delay:.2f} сек'
                )

            logger.info(f'Запуск РАСПАРАЛЛЕЛИВАНИЯ: {parallel_workers} параллельных задач')

            # Собираем фрагменты ролей и строим подпроцессы Celery
            chord_header = _build_parallel_role_signatures(
                it_roles=it_roles,
                parallel_workers=parallel_workers,
                area=area,
                pages=pages,
                delay=delay,
                get_details=get_details,
                max_concurrent_roles=max_concurrent_roles,
                batch_size=batch_size,
                no_delays=no_delays,
                experience=experience,
                employment=employment,
                schedule=schedule,
                only_with_salary=only_with_salary,
                period=period,
                date_from=date_from,
                date_to=date_to,
                salary_from=salary_from,
                salary_to=salary_to
            )
            
            # Логируем распределение ролей для отладки
            if chord_header:
                roles_per_worker = len(it_roles) // parallel_workers
                remainder = len(it_roles) % parallel_workers
                for worker_idx in range(parallel_workers):
                    worker_roles_count = roles_per_worker + (1 if worker_idx < remainder else 0)
                    logger.info(
                        f'[DISTRIBUTION] Worker {worker_idx + 1} получит {worker_roles_count} ролей '
                        f'(из {len(it_roles)} всего)'
                    )

            if not chord_header:
                return {
                    'mode': 'by_professional_roles_parallel',
                    'error': 'Не удалось подготовить задачи для парсинга ролей',
                    'total_roles': len(it_roles),
                    'parsed_roles': 0
                }

            finalize_signature = finalize_role_fragments.s(
                total_roles=len(it_roles),
                area=area,
                pages=pages,
                get_details=get_details,
                parallel_workers=parallel_workers
            ).set(queue='headhunter')

            # Делегируем выполнение в Celery-chord, чтобы результаты агрегировались автоматически
            return self.replace(chord(chord_header)(finalize_signature))

        # Создаем парсер
        parser = HeadHunterParser(
            metrics=ParsingMetrics(),
            use_jitter=True,
            rotate_user_agent=True,
            use_proxy=False
        )

        total_vacancies = 0
        total_new_vacancies = 0
        total_updated_vacancies = 0
        parsed_roles = 0
        total_roles = len(it_roles)
        task_start_time = time.time()  # Время начала всей задачи

        # Обрабатываем роли батчами для контроля нагрузки
        # Если batch_size = 0 или >= количества ролей, обрабатываем все сразу
        effective_batch_size = batch_size if batch_size > 0 and batch_size < len(it_roles) else len(it_roles)

        for i in range(0, len(it_roles), effective_batch_size):
            batch_roles = it_roles[i:i + effective_batch_size]
            batch_num = i//effective_batch_size + 1
            total_batches = (len(it_roles) + effective_batch_size - 1)//effective_batch_size

            if total_batches > 1:
                logger.info(f'Обработка батча {batch_num}/{total_batches} ({len(batch_roles)} ролей)')
            else:
                logger.info(f'Обработка всех {len(it_roles)} ролей за один проход')

            # Для каждой роли в батче выполняем поиск
            for role in batch_roles:
                role_start_time = time.time()  # Время начала обработки роли
                try:
                    logger.info(f'Парсинг роли: {role.name} (ID: {role.id})')

                    role_vacancies = 0
                    role_new_vacancies = 0
                    role_updated_vacancies = 0
                    role_errors = 0

                    # Оптимизированные параметры для максимального покрытия (лимит 2000 вакансий)
                    # Если pages <= 20: используем 100 вакансий на страницу (20 × 100 = 2000)
                    # Если pages > 20: используем 10 вакансий на страницу (200 × 10 = 2000)
                    if pages <= 20:
                        per_page_limit = 100  # 100 вакансий на страницу (лимит API HH)
                        max_pages_per_role = 20  # Максимум 20 страниц
                    else:
                        per_page_limit = 10   # 10 вакансий на страницу
                        max_pages_per_role = 200  # Максимум 200 страниц (200 × 10 = 2000)
                    
                    actual_pages = min(pages if pages > 0 else max_pages_per_role, max_pages_per_role)

                    # Сначала получаем общее количество вакансий и страниц для роли
                    logger.info(f'[INFO] Получение информации о количестве вакансий для роли {role.name} (ID: {role.id})...')
                    info_params = {
                        'professional_role': role.id,
                        'area': area,
                        'per_page': 1,  # Минимум для получения метаданных
                        'page': 0
                    }
                    logger.debug(f'[DEBUG] Параметры информационного запроса: {info_params}')
                    
                    # Добавляем дополнительные параметры фильтрации для информационного запроса
                    if experience:
                        info_params['experience'] = experience
                    if employment:
                        info_params['employment'] = employment
                    if schedule:
                        info_params['schedule'] = schedule
                    if only_with_salary:
                        info_params['only_with_salary'] = only_with_salary
                    if period:
                        info_params['period'] = period
                    if date_from:
                        info_params['date_from'] = date_from
                    if date_to:
                        info_params['date_to'] = date_to
                    if salary_from or salary_to:
                        info_params['currency'] = 'RUR'
                        if salary_from:
                            info_params['salary_from'] = salary_from
                        if salary_to:
                            info_params['salary_to'] = salary_to
                    
                    try:
                        info_result = parser.search_vacancies(**info_params)
                    except Exception as e:
                        logger.warning(f'Роль {role.name}: ошибка при получении информации о количестве вакансий: {e}, используем запрошенное количество страниц')
                        info_result = None
                    
                    if not info_result or 'found' not in info_result:
                        logger.warning(f'Роль {role.name}: не удалось получить информацию о количестве вакансий, используем запрошенное количество страниц')
                        total_found = 0
                        total_pages_api = actual_pages
                    else:
                        total_found = info_result.get('found', 0)
                        # ВАЖНО: API возвращает pages для per_page=1, нужно пересчитать для нашего per_page_limit
                        pages_api_info = info_result.get('pages', 0)  # Страниц при per_page=1
                        
                        # Пересчитываем количество страниц для нашего per_page_limit
                        if total_found > 0 and per_page_limit > 0:
                            total_pages_api = (total_found + per_page_limit - 1) // per_page_limit  # Округление вверх
                        else:
                            total_pages_api = 0
                        
                        logger.debug(f'Роль {role.name}: API вернул found={total_found}, pages (при per_page=1)={pages_api_info}, пересчитано для per_page={per_page_limit}: {total_pages_api} страниц')
                        
                        # Рассчитываем оптимальное количество страниц на основе лимита 2000 вакансий.
                        # Если метаданные от API есть, берем максимум возможного: по лимиту и по количеству страниц в API,
                        # а параметр pages используем только как fallback, когда инфо от API нет.
                        max_vacancies_limit = 2000
                        if total_found > 0:
                            # Рассчитываем количество страниц для достижения лимита
                            pages_needed_for_limit = (max_vacancies_limit + per_page_limit - 1) // per_page_limit  # Округление вверх
                            
                            # Берем минимум из: нужного для лимита и доступного в API
                            pages_needed = min(
                                pages_needed_for_limit,
                                total_pages_api,
                            )
                            
                            actual_pages = pages_needed
                            logger.info(f'Роль {role.name}: найдено {total_found} вакансий, доступно {total_pages_api} страниц (при {per_page_limit} вакансий/страницу), будем парсить {actual_pages} страниц (лимит: {max_vacancies_limit} вакансий)')
                        else:
                            logger.info(f'Роль {role.name}: вакансий не найдено, пропускаем')
                            continue

                    logger.info(f'Начинаем парсинг роли {role.name} (ID: {role.id}): {actual_pages} страниц по {per_page_limit} вакансий')
                    total_expected = actual_pages * per_page_limit  # Ожидаемое количество вакансий

                    # Парсим страницы с улучшенным логированием
                    for page in range(actual_pages):
                        try:
                            # Поиск вакансий по профессиональной роли с оптимизированными параметрами
                            search_params = {
                                'professional_role': role.id,
                                'area': area,
                                'per_page': per_page_limit,
                                'page': page
                            }

                            # Добавляем дополнительные параметры фильтрации
                            if experience:
                                search_params['experience'] = experience
                            if employment:
                                search_params['employment'] = employment
                            if schedule:
                                search_params['schedule'] = schedule
                            if only_with_salary:
                                search_params['only_with_salary'] = only_with_salary
                            if period:
                                search_params['period'] = period
                            if date_from:
                                search_params['date_from'] = date_from
                            if date_to:
                                search_params['date_to'] = date_to
                            if salary_from or salary_to:
                                # Для зарплаты используем currency=RUR по умолчанию
                                search_params['currency'] = 'RUR'
                                if salary_from:
                                    search_params['salary_from'] = salary_from
                                if salary_to:
                                    search_params['salary_to'] = salary_to

                            search_result = parser.search_vacancies(**search_params)

                            if not search_result or 'items' not in search_result:
                                logger.info(f'Роль {role.name}: страница {page + 1}/{actual_pages} - нет результатов, завершаем парсинг роли')
                                break

                            page_vacancies = search_result['items']
                            page_vacancy_count = len(page_vacancies)
                            role_vacancies += page_vacancy_count

                            # Прогресс для роли
                            progress_percent = ((page + 1) / actual_pages) * 100
                            logger.info(f'Роль {role.name}: страница {page + 1}/{actual_pages} ({progress_percent:.1f}%) - найдено {page_vacancy_count} вакансий (всего: {role_vacancies})')

                            # Обрабатываем каждую вакансию на странице (пакетно для ускорения деталей)
                            page_new = 0
                            page_updated = 0
                            page_errors = 0

                            vacancy_ids: List[str] = []
                            new_vacancies_buffer: Dict[str, Vacancy] = {}
                            existing_vacancies_buffer: Dict[str, Vacancy] = {}
                            vacancy_snippets: Dict[str, Dict[str, Any]] = {}

                            for vacancy_data in page_vacancies:
                                vacancy_id = str(vacancy_data.get('id')) if vacancy_data.get('id') else ''
                                if not vacancy_id:
                                    logger.warning(f'Пропускаем вакансию без ID в роли {role.name}')
                                    page_errors += 1
                                    continue

                                vacancy_ids.append(vacancy_id)
                                vacancy_snippets[vacancy_id] = vacancy_data

                                existing_vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
                                if existing_vacancy:
                                    existing_vacancies_buffer[vacancy_id] = existing_vacancy
                                else:
                                    vacancy_obj = _create_vacancy_from_api_data(vacancy_data, role.id, role.name)
                                    new_vacancies_buffer[vacancy_id] = vacancy_obj

                            # Загружаем детали пачками, чтобы минимизировать суммарную задержку
                            details_map: Dict[str, Any] = {}
                            if get_details and vacancy_ids:
                                detail_chunk_size = 25  # как в технологиях: небольшие пачки, но без больших пауз
                                for i in range(0, len(vacancy_ids), detail_chunk_size):
                                    chunk_ids = vacancy_ids[i:i + detail_chunk_size]
                                    try:
                                        chunk_details = asyncio.run(_fetch_vacancy_details_batch_async(
                                            parser, chunk_ids, '[Roles] '
                                        ))
                                        if chunk_details:
                                            details_map.update(chunk_details)
                                    except Exception as e:  # noqa: BLE001
                                        logger.warning(f'Ошибка при пакетной загрузке деталей ролей: {e}')
                                    # Минимальная пауза между пачками, только если задержки разрешены
                                    if not no_delays and delay > 0 and i + detail_chunk_size < len(vacancy_ids):
                                        time.sleep(_speed_cap_delay(delay * 0.15, min_value=0.08, max_value=0.375))

                            # Применяем детали и сохраняем
                            for vacancy_id in vacancy_ids:
                                try:
                                    if vacancy_id in existing_vacancies_buffer:
                                        existing_vacancy = existing_vacancies_buffer[vacancy_id]
                                        details = details_map.get(vacancy_id)
                                        updated = False
                                        if details:
                                            details = _merge_snippet_into_details(details, vacancy_snippets.get(vacancy_id, {}))
                                            updated = _update_vacancy_from_api_data(existing_vacancy, details)
                                        existing_vacancy.updated_at = timezone.now()
                                        existing_vacancy.save()
                                        if updated:
                                            page_updated += 1
                                            role_updated_vacancies += 1
                                    else:
                                        vacancy_obj = new_vacancies_buffer.get(vacancy_id)
                                        if not vacancy_obj:
                                            continue
                                        details = details_map.get(vacancy_id)
                                        if details:
                                            details = _merge_snippet_into_details(details, vacancy_snippets.get(vacancy_id, {}))
                                            _update_vacancy_from_api_data(vacancy_obj, details)
                                        vacancy_obj.save()
                                        page_new += 1
                                        role_new_vacancies += 1
                                        total_new_vacancies += 1

                                except Exception as e:  # noqa: BLE001
                                    logger.error(f'Ошибка обработки вакансии {vacancy_id} для роли {role.name}: {e}')
                                    page_errors += 1
                                    role_errors += 1
                                    continue

                            # Логируем результаты обработки страницы
                            logger.info(f'Роль {role.name}: страница {page + 1} обработана - новых: {page_new}, обновлено: {page_updated}, ошибок: {page_errors}')

                        except Exception as e:
                            logger.error(f'Ошибка при парсинге страницы {page + 1} для роли {role.name}: {e}')
                            role_errors += 1
                            continue

                        # Задержка между страницами для обхода rate limiting
                        if not no_delays and page < actual_pages - 1:
                            time.sleep(_speed_cap_delay(delay * 0.75, min_value=0.15, max_value=1.5))

                    # Логируем итоги парсинга роли
                    logger.info(f'Роль {role.name} завершена: обработано {role_vacancies} вакансий, '
                               f'новых: {role_new_vacancies}, обновлено: {role_updated_vacancies}, ошибок: {role_errors}')

                    total_vacancies += role_vacancies

                    # Общий прогресс
                    parsed_roles += 1
                    overall_progress = (parsed_roles / total_roles) * 100

                    # Расчет примерного времени
                    elapsed_time = time.time() - task_start_time
                    avg_time_per_role = elapsed_time / parsed_roles
                    remaining_roles = total_roles - parsed_roles
                    estimated_remaining = remaining_roles * avg_time_per_role

                    logger.info(f'ПРОГРЕСС: {parsed_roles}/{total_roles} ролей ({overall_progress:.1f}%) завершено')
                    logger.info(f'Статистика: вакансий={total_vacancies}, новых={total_new_vacancies}, обновлено={total_updated_vacancies}')
                    if remaining_roles > 0:
                        logger.info(f'Осталось: {remaining_roles} ролей, ~{estimated_remaining/60:.1f} мин (общее время: {elapsed_time/60:.1f} мин)')
                    total_updated_vacancies += role_updated_vacancies

                except Exception as e:
                    logger.error(f'Ошибка обработки роли {role.name}: {e}')
                    continue

                # Задержка между ролями
                if not no_delays and delay > 0:
                    time.sleep(_speed_cap_delay(delay * 0.75, min_value=0.15, max_value=1.5))

            # Дополнительная задержка между батчами (только если батчи включены)
            if not no_delays and effective_batch_size < len(it_roles) and i + effective_batch_size < len(it_roles):
                batch_delay = _speed_cap_delay(delay * 1.5, min_value=0.5, max_value=3.0)
                logger.info(f'Задержка между батчами: {_format_duration(float(batch_delay))}')
                time.sleep(batch_delay)

        total_time = time.time() - task_start_time
        parser.metrics.log_summary()

        chunk_results = [{
            'roles_processed': parsed_roles,
            'total_vacancies': total_vacancies,
            'new_vacancies': total_new_vacancies,
            'updated_vacancies': total_updated_vacancies,
            'total_time_minutes': total_time / 60,
        }]

        result = _aggregate_role_results(
            chunk_results=chunk_results,
            total_roles=len(it_roles),
            area=area,
            pages=pages,
            get_details=get_details,
            mode='by_professional_roles',
            metrics=parser.metrics.to_dict()
        )

        logger.info(f'ПАРСИНГ ЗАВЕРШЕН! Обработано {parsed_roles}/{len(it_roles)} ролей за {total_time/60:.1f} мин')
        logger.info(f'ФИНАЛЬНАЯ СТАТИСТИКА: {total_vacancies} вакансий, {total_new_vacancies} новых, {total_updated_vacancies} обновлено')
        logger.info(f'Производительность: {total_vacancies/total_time:.1f} вакансий/сек, {parsed_roles/total_time*60:.1f} ролей/час')

        return result

    except Exception as e:
        error_msg = f'Критическая ошибка в задаче парсинга по ролям: {str(e)}'
        logger.error(error_msg, exc_info=True)

        return {
            'mode': 'by_professional_roles',
            'error': error_msg,
            'total_roles': 0,
            'parsed_roles': 0,
            'total_vacancies': 0,
            'new_vacancies': 0
        }


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=300,
    time_limit=600,
)
def get_professional_roles_task(self):
    """
    Celery-задача для получения списка всех профессиональных ролей с API HeadHunter.

    Returns:
        dict: Словарь с результатами запроса
            - success (bool): Успешность выполнения
            - roles (list): Список ролей или пустой список при ошибке
            - categories_count (int): Количество категорий (если успех)
            - total_roles (int): Общее количество ролей (если успех)
            - error (str): Сообщение об ошибке (если неудача)
    """
    try:
        logger.info('Начало выполнения задачи получения профессиональных ролей')

        target_category_id = _load_target_category_id()
        logger.info('Фильтрация ролей по категории %s (IT)', target_category_id)

        # Создаем парсер
        parser = HeadHunterParser()

        # Получаем роли (ограничиваемся целевой категорией)
        roles = parser.get_professional_roles(category_id=target_category_id)

        if roles is None:
            logger.error('Не удалось получить профессиональные роли - ответ None')
            return {
                'success': False,
                'roles': [],
                'error': 'Не удалось получить данные с API HeadHunter'
            }

        if not roles:
            logger.warning('Получен пустой список профессиональных ролей')
            return {
                'success': False,
                'roles': [],
                'error': 'Получен пустой список ролей'
            }

        # Получаем статистику по категориям
        raw_data = parser._make_request(f"{parser.base_url}/professional_roles")
        categories_count = 1  # По умолчанию 1 категория (IT)
        if raw_data and 'categories' in raw_data:
            # Проверяем, существует ли целевая категория в списке
            categories_count = 1 if any(
                str(category.get('id')) == target_category_id
                for category in raw_data['categories']
            ) else 1  # Если категория не найдена, но роли есть, считаем что категория 1

        total_roles = len(roles)

        logger.info(f'Успешно получено {total_roles} профессиональных ролей из {categories_count} категорий')

        return {
            'success': True,
            'roles': roles,
            'categories_count': categories_count,
            'total_roles': total_roles
        }

    except Exception as e:
        error_msg = f'Ошибка при получении профессиональных ролей: {str(e)}'
        logger.error(error_msg, exc_info=True)

        return {
            'success': False,
            'roles': [],
            'error': error_msg
        }


def _filter_roles_for_parsing(it_roles, skip_existing_roles, incremental):
    """
    Фильтрует роли для оптимизации парсинга.

    Args:
        it_roles: Список всех ролей
        skip_existing_roles: Пропускать роли, парсированные сегодня
        incremental: Использовать инкрементальный режим

    Returns:
        Отфильтрованный список ролей
    """
    if not skip_existing_roles and not incremental:
        return it_roles

    filtered_roles = []

    for role in it_roles:
        should_include = True

        if skip_existing_roles:
            # Проверяем, парсилась ли эта роль сегодня
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            recent_vacancies = Vacancy.objects.filter(
                professional_role=str(role.id),
                created_at__gte=today_start
            ).exists()

            if recent_vacancies:
                logger.debug(f'Пропускаем роль {role.name} - уже парсилась сегодня')
                should_include = False

        if should_include:
            filtered_roles.append(role)

    return filtered_roles


async def _fetch_vacancy_details_batch_async(parser, vacancy_ids, worker_prefix):
    """
    Асинхронно получает детали нескольких вакансий одновременно.
    Возвращает словарь {vacancy_id: details} и статистику ошибок.
    """
    import aiohttp
    import asyncio

    errors_count = 0
    errors_403_count = 0
    last_error = None

    async def fetch_single(vacancy_id):
        nonlocal errors_count, errors_403_count, last_error
        try:
            details = await asyncio.get_event_loop().run_in_executor(
                None, parser.get_vacancy_details, str(vacancy_id)
            )
            return vacancy_id, details, None
        except Exception as e:
            errors_count += 1
            error_msg = str(e).lower()
            if '403' in error_msg or 'forbidden' in error_msg:
                errors_403_count += 1
            last_error = e
            # Логируем только каждую 10-ю ошибку, чтобы не засорять логи
            if errors_count % 10 == 0 or errors_count <= 3:
                logger.warning(f'{worker_prefix}Ошибка получения деталей вакансии {vacancy_id}: {e}')
            return vacancy_id, None, e

    # Создаем задачи для параллельного выполнения
    tasks = [fetch_single(vid) for vid in vacancy_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    details_map = {}
    for result in results:
        if isinstance(result, Exception):
            errors_count += 1
            continue
        if isinstance(result, tuple) and len(result) == 3:
            vacancy_id, details, error = result
            if details:
                details_map[vacancy_id] = details

    # Логируем итоговую статистику
    total = len(vacancy_ids)
    success = len(details_map)
    if errors_count > 0:
        logger.warning(
            f'{worker_prefix}Загрузка деталей завершена: {success}/{total} успешно, '
            f'ошибок: {errors_count} (403: {errors_403_count})'
        )
    else:
        logger.debug(f'{worker_prefix}Загрузка деталей завершена: {success}/{total} успешно')

    return details_map


def _build_parallel_role_signatures(
    it_roles: List[Any],
    parallel_workers: int,
    area: int,
    pages: int,
    delay: float,
    get_details: bool,
    max_concurrent_roles: int,
    batch_size: int,
    no_delays: bool,
    experience: Optional[str] = None,
    employment: Optional[str] = None,
    schedule: Optional[str] = None,
    only_with_salary: bool = False,
    period: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salary_from: Optional[int] = None,
    salary_to: Optional[int] = None,
) -> List[Any]:
    """
    Формирует список Celery-задач для распараллеленного парсинга ролей.
    """
    if not it_roles:
        return []

    parallel_workers = max(1, min(parallel_workers, len(it_roles)))

    roles_per_worker = len(it_roles) // parallel_workers
    remainder = len(it_roles) % parallel_workers

    headers = []
    start_idx = 0

    for worker_idx in range(parallel_workers):
        worker_roles_count = roles_per_worker + (1 if worker_idx < remainder else 0)
        end_idx = start_idx + worker_roles_count
        worker_roles = it_roles[start_idx:end_idx]
        start_idx = end_idx

        if not worker_roles:
            continue

        headers.append(
            parse_single_role_batch.s(
                [role.id for role in worker_roles],
                area,
                pages,
                delay,
                get_details,
                max_concurrent_roles,
                batch_size,
                no_delays,
                worker_idx + 1,
                experience,
                employment,
                schedule,
                only_with_salary,
                period,
                date_from,
                date_to,
                salary_from,
                salary_to,
            ).set(queue='headhunter')
        )

    return headers


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=900,
    time_limit=1200,
)
def finalize_role_fragments(
    self,
    chunk_results: List[Dict[str, Any]],
    total_roles: int,
    area: int,
    pages: int,
    get_details: bool,
    parallel_workers: int,
):
    """
    Callback-задача для агрегации результатов фрагментарного парсинга ролей.
    """
    logger.info(
        'Агрегация результатов фрагментов ролей: %d фрагментов, %d воркеров',
        len(chunk_results),
        parallel_workers,
    )

    summary = _aggregate_role_results(
        chunk_results=chunk_results,
        total_roles=total_roles,
        area=area,
        pages=pages,
        get_details=get_details,
        mode='by_professional_roles_parallel',
        metrics=None,
        extra={
            'parallel_workers': parallel_workers,
            'chunk_count': len(chunk_results),
        },
    )

    return summary


def _aggregate_role_results(
    chunk_results: List[Dict[str, Any]],
    total_roles: int,
    area: int,
    pages: int,
    get_details: bool,
    mode: str,
    metrics: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Агрегирует метрики по фрагментам парсинга ролей.
    """
    parsed_roles = sum(result.get('roles_processed', 0) for result in chunk_results)
    total_vacancies = sum(result.get('total_vacancies', 0) for result in chunk_results)
    new_vacancies = sum(result.get('new_vacancies', 0) for result in chunk_results)
    updated_vacancies = sum(result.get('updated_vacancies', 0) for result in chunk_results)
    total_time_minutes = sum(result.get('total_time_minutes', 0.0) for result in chunk_results)

    summary: Dict[str, Any] = {
        'mode': mode,
        'status': 'completed',
        'total_roles': total_roles,
        'parsed_roles': parsed_roles,
        'total_vacancies': total_vacancies,
        'new_vacancies': new_vacancies,
        'updated_vacancies': updated_vacancies,
        'area': area,
        'pages_per_role': pages,
        'get_details': get_details,
        'fragments': len(chunk_results),
        'total_time_minutes': total_time_minutes,
    }

    if metrics:
        summary['metrics'] = metrics

    if extra:
        summary.update(extra)

    return summary


@shared_task(
    bind=True,
    max_retries=5,        # Увеличиваем количество повторных попыток
    default_retry_delay=60,  # Увеличиваем задержку между попытками
    soft_time_limit=9000,  # 2.5 часа на подзадачу
    time_limit=10800,     # 3 часа максимум
)
def parse_single_role_batch(
    self,
    role_ids: List[str],
    area: int,
    pages: int,
    delay: float,
    get_details: bool,
    max_concurrent_roles: int,
    batch_size: int,
    no_delays: bool,
    worker_id: int,
    experience: Optional[str] = None,
    employment: Optional[str] = None,
    schedule: Optional[str] = None,
    only_with_salary: bool = False,
    period: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    salary_from: Optional[int] = None,
    salary_to: Optional[int] = None,
):
    """
    Подзадача для парсинга батча ролей в параллельном режиме.

    Args:
        role_ids: Список ID ролей для обработки
        worker_id: ID worker'а (для логирования)

    Returns:
        Статистика обработки батча ролей
    """
    # utils лежит уровнем выше, а не внутри пакета tasks
    from ..utils.professional_roles_config import ProfessionalRolesManager

    logger.info(f'[Worker {worker_id}] Начинаем обработку батча из {len(role_ids)} ролей')

    # Добавляем внутреннюю задержку старта для координации воркеров
    if worker_id == 1:
        start_delay = 3.75
    elif worker_id == 2:
        start_delay = 22.5
    elif worker_id == 3:
        start_delay = 45.0
    else:
        start_delay = 45.0 + (worker_id - 3) * 22.5

    logger.info(f'[Worker {worker_id}] Ожидание {_format_duration(float(start_delay))} перед стартом...')
    time.sleep(start_delay)
    logger.info(f'[Worker {worker_id}] Начинаем парсинг после задержки')

    try:
        # Получаем объекты ролей по ID
        roles_manager = ProfessionalRolesManager()
        all_roles = roles_manager.get_it_roles()
        it_roles = [role for role in all_roles if str(role.id) in role_ids]

        if len(it_roles) != len(role_ids):
            logger.warning(f'Worker {worker_id}: Найдено {len(it_roles)} из {len(role_ids)} запрошенных ролей')

        # Запускаем обычную логику парсинга для этого батча
        return _parse_roles_batch(
            it_roles, area, pages, delay, get_details,
            max_concurrent_roles, batch_size, no_delays, worker_id, 1,  # parallel_workers=1 для подзадач
            experience, employment, schedule, only_with_salary,
            period, date_from, date_to, salary_from, salary_to
        )

    except Exception as e:
        logger.error(f'Worker {worker_id}: Критическая ошибка в батче: {e}', exc_info=True)

        # Умная логика повторных попыток
        retry_delay = min(8 * (2 ** self.request.retries), 60)

        # Если это ошибка API (rate limit), увеличиваем задержку
        if '400' in str(e) or 'rate' in str(e).lower() or 'block' in str(e).lower():
            retry_delay = min(retry_delay * 1.5, 90)

        logger.warning(
            f'Worker {worker_id}: Повторная попытка через {_format_duration(float(retry_delay))} '
            f'(попытка {self.request.retries + 1}/5)'
        )
        raise self.retry(countdown=retry_delay, exc=e)


def _parse_roles_batch(it_roles, area, pages, delay, get_details,
                      max_concurrent_roles, batch_size, no_delays, worker_id=None, parallel_workers=1,
                      experience=None, employment=None, schedule=None, only_with_salary=False,
                      period=None, date_from=None, date_to=None, salary_from=None, salary_to=None):
    """
    Основная логика парсинга батча ролей (выделена в отдельную функцию).
    """
    worker_prefix = f'[Worker {worker_id}] ' if worker_id else ''
    logger.info(f'{worker_prefix}Начат парсинг батча из {len(it_roles)} ролей')

    # Создаем парсер
    parser = HeadHunterParser(
        metrics=ParsingMetrics(),
        use_jitter=True,
        rotate_user_agent=True,
        use_proxy=False
    )

    total_vacancies = 0
    total_new_vacancies = 0
    total_updated_vacancies = 0
    parsed_roles = 0
    total_roles = len(it_roles)
    task_start_time = time.time()

    # Счетчики для защиты от блокировок и статистики ошибок
    consecutive_403_errors = 0
    max_consecutive_403 = 3  # После 3 подряд 403 останавливаем worker
    total_403_errors = 0  # Общее количество 403 ошибок
    total_details_errors = 0  # Ошибки при загрузке деталей
    total_other_errors = 0  # Другие ошибки

    # Обрабатываем роли батчами для контроля нагрузки
    effective_batch_size = batch_size if batch_size > 0 and batch_size < len(it_roles) else len(it_roles)

    for i in range(0, len(it_roles), effective_batch_size):
        batch_roles = it_roles[i:i + effective_batch_size]
        batch_num = i//effective_batch_size + 1
        total_batches = (len(it_roles) + effective_batch_size - 1)//effective_batch_size

        if total_batches > 1:
            logger.info(f'{worker_prefix}Обработка батча {batch_num}/{total_batches} ({len(batch_roles)} ролей)')
        else:
            logger.info(f'{worker_prefix}Обработка всех {len(it_roles)} ролей за один проход')

        # Для каждой роли в батче выполняем поиск
        for role in batch_roles:
            role_start_time = time.time()
            try:
                logger.info(f'{worker_prefix}Парсинг роли: {role.name} (ID: {role.id})')

                role_vacancies = 0
                role_new_vacancies = 0
                role_updated_vacancies = 0
                role_errors = 0

                # Оптимизированные параметры для максимального покрытия (лимит 2000 вакансий)
                # Если pages <= 20: используем 100 вакансий на страницу (20 × 100 = 2000)
                # Если pages > 20: используем 10 вакансий на страницу (200 × 10 = 2000)
                if pages <= 20:
                    per_page_limit = 100  # 100 вакансий на страницу (лимит API HH)
                    max_pages_per_role = 20  # Максимум 20 страниц
                else:
                    per_page_limit = 10   # 10 вакансий на страницу
                    max_pages_per_role = 200  # Максимум 200 страниц (200 × 10 = 2000)
                
                actual_pages = min(pages if pages > 0 else max_pages_per_role, max_pages_per_role)

                # Сначала получаем общее количество вакансий и страниц для роли
                logger.info(f'{worker_prefix}[INFO] Получение информации о количестве вакансий для роли {role.name} (ID: {role.id})...')
                info_params = {
                    'professional_role': role.id,
                    'area': area,
                    'per_page': 1,  # Минимум для получения метаданных
                    'page': 0
                }
                logger.debug(f'{worker_prefix}[DEBUG] Параметры информационного запроса: {info_params}')
                
                try:
                    info_result = parser.search_vacancies(**info_params)
                except Exception as e:
                    logger.warning(f'{worker_prefix}Роль {role.name}: ошибка при получении информации о количестве вакансий: {e}, используем запрошенное количество страниц')
                    info_result = None
                
                if not info_result or 'found' not in info_result:
                    logger.warning(f'{worker_prefix}Роль {role.name}: не удалось получить информацию о количестве вакансий, используем запрошенное количество страниц')
                    total_found = 0
                    total_pages_api = actual_pages
                else:
                    total_found = info_result.get('found', 0)
                    # ВАЖНО: API возвращает pages для per_page=1, нужно пересчитать для нашего per_page_limit
                    pages_api_info = info_result.get('pages', 0)  # Страниц при per_page=1
                    
                    # Пересчитываем количество страниц для нашего per_page_limit
                    if total_found > 0 and per_page_limit > 0:
                        total_pages_api = (total_found + per_page_limit - 1) // per_page_limit  # Округление вверх
                    else:
                        total_pages_api = 0
                    
                    logger.debug(f'{worker_prefix}Роль {role.name}: API вернул found={total_found}, pages (при per_page=1)={pages_api_info}, пересчитано для per_page={per_page_limit}: {total_pages_api} страниц')
                    
                    # Рассчитываем оптимальное количество страниц на основе лимита 2000 вакансий
                    max_vacancies_limit = 2000
                    if total_found > 0:
                        # Рассчитываем количество страниц для достижения лимита
                        pages_needed_for_limit = (max_vacancies_limit + per_page_limit - 1) // per_page_limit  # Округление вверх
                        
                        # Берем минимум из: нужного для лимита, доступного в API, запрошенного
                        pages_needed = min(
                            pages_needed_for_limit,
                            total_pages_api,
                            actual_pages
                        )
                        
                        actual_pages = pages_needed
                        logger.info(f'{worker_prefix}Роль {role.name}: найдено {total_found} вакансий, доступно {total_pages_api} страниц (при {per_page_limit} вакансий/страницу), будем парсить {actual_pages} страниц (лимит: {max_vacancies_limit} вакансий)')
                    else:
                        logger.info(f'{worker_prefix}Роль {role.name}: вакансий не найдено, пропускаем')
                        continue

                logger.info(f'{worker_prefix}Начинаем парсинг роли {role.name}: {actual_pages} страниц по {per_page_limit} вакансий')

                # Парсим страницы с улучшенным логированием
                for page in range(actual_pages):
                    try:
                        # Поиск вакансий по профессиональной роли с оптимизированными параметрами
                        search_params = {
                            'professional_role': role.id,
                            'area': area,
                            'per_page': per_page_limit,
                            'page': page
                        }

                        try:
                            search_result = parser.search_vacancies(**search_params)
                            # Сбрасываем счетчик 403 ошибок при успешном запросе
                            consecutive_403_errors = 0
                        except Exception as api_error:
                            error_msg = str(api_error).lower()
                            if '403' in error_msg or 'forbidden' in error_msg or 'доступ запрещён' in error_msg:
                                consecutive_403_errors += 1
                                pause_403 = 1.5
                                # Простая пауза 2 секунды при 403
                                logger.warning(f'{worker_prefix}Доступ запрещён (403) для роли {role.name} на странице {page + 1}. '
                                              f'Пауза {_format_duration(pause_403)}...')
                                time.sleep(pause_403)
                                continue

                            elif '400' in error_msg or 'rate' in error_msg or 'block' in error_msg:
                                rate_limit_pause = 22.5
                                logger.warning(
                                    f'{worker_prefix}Роль {role.name}: API rate limit на странице {page + 1}, '
                                    f'пауза {_format_duration(rate_limit_pause)}'
                                )
                                time.sleep(rate_limit_pause)  # Длительная пауза при rate limit
                                continue
                            else:
                                logger.error(f'{worker_prefix}Роль {role.name}: API ошибка на странице {page + 1}: {api_error}')
                                continue

                        if not search_result or 'items' not in search_result:
                                logger.info(f'{worker_prefix}Роль {role.name}: страница {page + 1}/{actual_pages} - нет результатов')
                                break

                        page_vacancies = search_result['items']
                        page_vacancy_count = len(page_vacancies)
                        role_vacancies += page_vacancy_count

                        progress_percent = ((page + 1) / actual_pages) * 100
                        logger.info(f'{worker_prefix}Роль {role.name}: {page + 1}/{actual_pages} ({progress_percent:.1f}%) - {page_vacancy_count} вакансий')

                        # АСИНХРОННАЯ ОБРАБОТКА ДЕТАЛЕЙ ВАКАНСИЙ для ускорения
                        vacancy_ids = []
                        vacancy_objects = []

                        # Создаем объекты вакансий и собираем ID для асинхронной загрузки
                        for vacancy_data in page_vacancies:
                                try:
                                    vacancy_id = vacancy_data.get('id')
                                    if not vacancy_id:
                                        continue

                                    vacancy_obj = _create_vacancy_from_api_data(vacancy_data, role.id, role.name)
                                    vacancy_objects.append(vacancy_obj)
                                    vacancy_ids.append(vacancy_id)

                                except Exception as e:
                                    logger.error(f'{worker_prefix}Ошибка обработки данных вакансии: {e}')
                                    role_errors += 1

                        # АСИНХРОННАЯ ЗАГРУЗКА ДЕТАЛЕЙ (если нужно и есть ID)
                        if get_details and vacancy_ids:
                            try:
                                logger.debug(f'{worker_prefix}Асинхронная загрузка деталей для {len(vacancy_ids)} вакансий')

                                # Запускаем асинхронную загрузку в отдельном event loop
                                details_map = asyncio.run(_fetch_vacancy_details_batch_async(
                                    parser, vacancy_ids, worker_prefix
                                ))

                                # Обновляем объекты деталями
                                for vacancy_obj in vacancy_objects:
                                    vacancy_id = vacancy_obj.hh_id
                                    if vacancy_id in details_map and details_map[vacancy_id]:
                                        _update_vacancy_from_api_data(vacancy_obj, details_map[vacancy_id])

                            except Exception as e:
                                error_msg = str(e).lower()
                                if '403' in error_msg or 'forbidden' in error_msg or 'доступ запрещён' in error_msg:
                                    consecutive_403_errors += 1
                                    total_403_errors += 1
                                    total_details_errors += 1
                                    if consecutive_403_errors >= max_consecutive_403:
                                        stop_pause = 3.75
                                        logger.error(f'{worker_prefix}СЛИШКОМ МНОГО 403 ОШИБОК ПРИ ЗАГРУЗКЕ ДЕТАЛЕЙ ({consecutive_403_errors}/{max_consecutive_403}). '
                                                    f'Останавливаем worker {worker_id} на {_format_duration(stop_pause)}...')
                                        time.sleep(stop_pause)  # 5 секунд паузы
                                        consecutive_403_errors = 0
                                        continue

                                    # Простая пауза 2 секунды при 403
                                    # Логируем только каждую 5-ю ошибку
                                    details_pause = 1.5
                                    if consecutive_403_errors % 5 == 0 or consecutive_403_errors <= 3:
                                        logger.warning(
                                            f'{worker_prefix}Доступ запрещён (403) при загрузке деталей '
                                            f'(всего: {consecutive_403_errors}). Пауза {_format_duration(details_pause)}...'
                                        )
                                    time.sleep(details_pause)
                                    continue

                                # Для других ошибок логируем только первую
                                total_other_errors += 1
                                total_details_errors += 1
                                logger.warning(f'{worker_prefix}Ошибка асинхронной загрузки деталей: {e}. Пропускаем детали для этой страницы.')
                                
                                # Fallback: синхронная загрузка только для критичных случаев (не используем, т.к. это может привести к еще большим 403)
                                # Вакансии сохранятся без деталей, детали можно загрузить позже

                        # ПАКЕТНОЕ СОХРАНЕНИЕ В БД (максимальная производительность!)
                        if vacancy_objects:
                            try:
                                # Bulk create с оптимизациями
                                created_count = 0
                                batch_size_db = 100  # Увеличен размер батча для БД

                                for i in range(0, len(vacancy_objects), batch_size_db):
                                    batch = vacancy_objects[i:i + batch_size_db]
                                    try:
                                        result = Vacancy.objects.bulk_create(
                                            batch,
                                            ignore_conflicts=True,
                                            batch_size=batch_size_db
                                        )
                                        created_count += len(batch)
                                    except Exception as batch_error:
                                        logger.warning(f'{worker_prefix}Ошибка батча {i//batch_size_db + 1}: {batch_error}')
                                        # Fallback: сохраняем по одной с игнорированием ошибок
                                        for vacancy in batch:
                                            try:
                                                vacancy.save()
                                                created_count += 1
                                            except Exception:
                                                pass  # Игнорируем дубликаты и другие ошибки

                                role_new_vacancies += created_count
                                logger.debug(f'{worker_prefix}Создано {created_count} вакансий из {len(vacancy_objects)}')

                            except Exception as e:
                                logger.error(f'{worker_prefix}Критическая ошибка пакетного сохранения: {e}')
                                role_errors += len(vacancy_objects)

                    except Exception as e:
                        logger.error(f'{worker_prefix}Ошибка страницы {page + 1} для роли {role.name}: {e}')
                        continue

                    # Задержка между страницами (минимум 0.1 сек даже при no_delays для предотвращения блокировки)
                    if page < actual_pages - 1:
                        actual_delay = _speed_cap_delay(
                            delay * 0.75 if not no_delays else delay * 0.4,
                            min_value=0.1,
                            max_value=1.5, 
                        )
                        time.sleep(actual_delay)

                # Итоги роли
                logger.info(f'{worker_prefix}Роль {role.name} завершена: {role_vacancies} вакансий, '
                           f'новых: {role_new_vacancies}, обновлено: {role_updated_vacancies}')

                total_vacancies += role_vacancies
                total_new_vacancies += role_new_vacancies
                total_updated_vacancies += role_updated_vacancies
                parsed_roles += 1

            except Exception as e:
                logger.error(f'{worker_prefix}Ошибка роли {role.name}: {e}')
                continue

            # Задержка между ролями (минимум 0.1 сек даже при no_delays)
            if delay > 0:
                actual_delay = _speed_cap_delay(
                    delay * 0.75 if not no_delays else delay * 0.4,
                    min_value=0.1,
                    max_value=1.5,
                )
                time.sleep(actual_delay)

        # Задержка между батчами (минимум 0.5 сек даже при no_delays)
        if effective_batch_size < len(it_roles) and i + effective_batch_size < len(it_roles):
            batch_delay = _speed_cap_delay(
                delay * (1.5 if not no_delays else 0.6),
                min_value=0.4,
                max_value=3.0,
            )
            logger.info(f'{worker_prefix}Задержка между батчами: {_format_duration(float(batch_delay))}')
            time.sleep(batch_delay)

    # Финальная статистика
    total_time = time.time() - task_start_time
    logger.info(f'{worker_prefix}🎉 Батч завершен за {total_time/60:.1f} мин: '
               f'{total_vacancies} вакансий, {total_new_vacancies} новых, {total_updated_vacancies} обновлено')

    return {
        'worker_id': worker_id,
        'roles_processed': parsed_roles,
        'total_vacancies': total_vacancies,
        'new_vacancies': total_new_vacancies,
        'updated_vacancies': total_updated_vacancies,
        'total_time_minutes': total_time / 60,
        'status': 'completed',
        'errors': {
            'total_403_errors': total_403_errors,
            'total_details_errors': total_details_errors,
            'total_other_errors': total_other_errors
        },
        'metrics': parser.metrics.to_dict() if parser.metrics else {}
    }