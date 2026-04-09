"""
Батчевая обработка вакансий.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any

from celery import shared_task
from django.utils import timezone

from ..scripts import HeadHunterParser
from ..async_parser import AsyncHeadHunterParser, AsyncParsingConfig
from ..scripts import ParsingMetrics
from ..models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.headhunter')


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=90,
    soft_time_limit=3600,
    time_limit=3900,
)
def parse_vacancies_batch_task(
    self,
    vacancy_ids: List[str],
    force_update: bool = False,
) -> Dict[str, Any]:
    """
    Батчевая Celery-задача для парсинга нескольких вакансий по ID.

    Использует асинхронный парсер для параллельных запросов к API HeadHunter.
    """
    logger.info(
        "Запуск задачи parse_vacancies_batch_task: count=%d, force_update=%s",
        len(vacancy_ids),
        force_update,
    )

    if not vacancy_ids:
        return {'status': 'no_ids', 'message': 'Список vacancy_ids пуст'}

    async def _fetch_batch(ids: List[str]) -> List[Any]:
        metrics = ParsingMetrics()
        config = AsyncParsingConfig(
            max_concurrent_requests=20,
            request_delay=0.1,
        )
        async with AsyncHeadHunterParser(config=config, metrics=metrics) as parser:
            return await parser.get_vacancy_details_batch(ids)

    try:
        # 1. Асинхронно получаем детали по всем ID
        results = asyncio.run(_fetch_batch(vacancy_ids))

        # 2. Парсим все вакансии
        parser = HeadHunterParser()
        vacancy_manager = getattr(Vacancy, 'objects')
        
        # Поля для отслеживания изменений и обновления
        CHANGE_TRACKED_FIELDS = [
            'title', 'company_name', 'salary_from', 'salary_to', 'salary_currency',
            'salary_gross', 'city', 'address', 'description', 'requirements',
            'responsibilities', 'employment_type', 'experience_level', 'key_skills',
            'schedule_type', 'professional_role', 'employer_name', 'premium',
            'has_test', 'response_letter_required'
        ]
        UPDATABLE_FIELDS = list(dict.fromkeys(CHANGE_TRACKED_FIELDS + [
            'skills', 'url', 'company_url', 'alternate_url', 'apply_alternate_url',
            'employer_id', 'employer_trusted', 'employer_blacklisted', 'published_at'
        ]))

        parsed_vacancies: List[Vacancy] = []
        vacancy_id_to_data: Dict[str, Dict[str, Any]] = {}
        errors = 0

        for vacancy_id, vacancy_data in results:
            try:
                if not vacancy_data or not isinstance(vacancy_data, dict) or 'id' not in vacancy_data:
                    logger.error(
                        'Вакансия %s не найдена или данные некорректны в batch-задаче',
                        vacancy_id,
                    )
                    errors += 1
                    continue

                vacancy = parser.parse_vacancy(vacancy_data)
                if not vacancy:
                    logger.error('Ошибка при парсинге вакансии %s в batch-задаче', vacancy_id)
                    errors += 1
                    continue

                if not vacancy.hh_id:
                    vacancy.hh_id = str(vacancy_id)

                parsed_vacancies.append(vacancy)
                vacancy_id_to_data[str(vacancy_id)] = vacancy_data

            except Exception as exc:
                logger.error(
                    'Ошибка при парсинге вакансии %s в batch-задаче', vacancy_id, exc_info=True
                )
                errors += 1

        if not parsed_vacancies:
            return {
                'status': 'error',
                'message': 'Не удалось распарсить ни одной вакансии',
                'total': len(vacancy_ids),
                'created': 0,
                'updated': 0,
                'exists': 0,
                'no_changes': 0,
                'errors': errors,
            }

        # 3. Загружаем все существующие вакансии одним запросом
        all_vacancy_ids = [v.hh_id for v in parsed_vacancies if v.hh_id]
        existing_vacancies = {
            v.hh_id: v for v in vacancy_manager.filter(hh_id__in=all_vacancy_ids)
        }

        # 4. Разделяем на новые и существующие, обрабатываем батчами
        BATCH_SIZE = 100
        created = 0
        updated = 0
        exists = 0
        no_changes = 0

        for batch_start in range(0, len(parsed_vacancies), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(parsed_vacancies))
            batch_vacancies = parsed_vacancies[batch_start:batch_end]

            new_vacancies: List[Vacancy] = []
            to_update: List[Vacancy] = []

            for vacancy in batch_vacancies:
                if not vacancy.hh_id:
                    errors += 1
                    continue

                existing = existing_vacancies.get(vacancy.hh_id)
                if existing:
                    if not force_update:
                        exists += 1
                        continue

                    # Проверяем изменения
                    new_data = {field: getattr(vacancy, field) for field in CHANGE_TRACKED_FIELDS}
                    if existing.has_changes(new_data):
                        existing.create_version(new_data)
                        # Обновляем поля для bulk_update
                        for field in UPDATABLE_FIELDS:
                            setattr(existing, field, getattr(vacancy, field))
                        to_update.append(existing)
                        updated += 1
                    else:
                        no_changes += 1
                else:
                    new_vacancies.append(vacancy)

            # Батчевое создание новых вакансий с оптимизацией batch_size
            if new_vacancies:
                try:
                    new_ids = [v.hh_id for v in new_vacancies if v.hh_id]
                    count_before = vacancy_manager.filter(hh_id__in=new_ids).count()
                    
                    # Используем batch_size для оптимизации bulk_create
                    # Разбиваем на батчи для лучшей производительности
                    created_in_batch = 0
                    for i in range(0, len(new_vacancies), BATCH_SIZE):
                        batch = new_vacancies[i:i + BATCH_SIZE]
                        vacancy_manager.bulk_create(batch, ignore_conflicts=True, batch_size=BATCH_SIZE)
                        created_in_batch += len(batch)
                    
                    count_after = vacancy_manager.filter(hh_id__in=new_ids).count()
                    actually_created = count_after - count_before
                    created += actually_created
                    
                    if actually_created < len(new_vacancies):
                        logger.warning(
                            'При bulk_create: попытка создать %d, реально создано %d, конфликтов %d',
                            len(new_vacancies), actually_created, len(new_vacancies) - actually_created
                        )
                except Exception as bulk_exc:
                    errors += len(new_vacancies)
                    logger.error('Ошибка при bulk_create в batch-задаче', exc_info=True)

            # Батчевое обновление существующих вакансий
            if to_update:
                try:
                    vacancy_manager.bulk_update(
                        to_update,
                        fields=UPDATABLE_FIELDS,
                        batch_size=BATCH_SIZE
                    )
                except Exception as bulk_exc:
                    errors += len(to_update)
                    logger.error('Ошибка при bulk_update в batch-задаче', exc_info=True)

        total = len(vacancy_ids)
        logger.info(
            'Batch-задача завершена: total=%d, created=%d, updated=%d, '
            'exists=%d, no_changes=%d, errors=%d',
            total,
            created,
            updated,
            exists,
            no_changes,
            errors,
        )

        return {
            'status': 'completed',
            'total': total,
            'created': created,
            'updated': updated,
            'exists': exists,
            'no_changes': no_changes,
            'errors': errors,
        }
    except Exception as exc:
        logger.error('Ошибка выполнения parse_vacancies_batch_task', exc_info=True)
        raise self.retry(exc=exc)


def _save_vacancies_batch_celery(vacancies_data: List[Dict[str, Any]], search_text: str) -> Dict[str, int]:
    """Сохранение пакета вакансий в БД"""
    stats = {'saved': 0, 'updated': 0, 'unchanged': 0, 'errors': 0}

    for vacancy_data in vacancies_data:
        vacancy_id: Optional[str] = None
        try:
            vacancy_id = vacancy_data.get('id')
            if not vacancy_id:
                continue

            # Поиск существующей вакансии
            vacancy, created = Vacancy.objects.get_or_create(
                hh_id=str(vacancy_id),
                defaults={
                    'title': vacancy_data.get('name', ''),
                    'company_name': vacancy_data.get('employer', {}).get('name', '') if vacancy_data.get('employer') else '',
                    'salary_from': vacancy_data.get('salary', {}).get('from'),
                    'salary_to': vacancy_data.get('salary', {}).get('to'),
                    'salary_currency': vacancy_data.get('salary', {}).get('currency') if vacancy_data.get('salary') else None,
                    'salary_gross': vacancy_data.get('salary', {}).get('gross') if vacancy_data.get('salary') else None,
                    'city': vacancy_data.get('area', {}).get('name') if vacancy_data.get('area') else None,
                    'description': vacancy_data.get('description', ''),
                    'requirements': vacancy_data.get('snippet', {}).get('requirement') if vacancy_data.get('snippet') else None,
                    'url': vacancy_data.get('alternate_url', ''),
                    'published_at': vacancy_data.get('published_at'),
                }
            )

            if created:
                stats['saved'] += 1
            else:
                # Проверяем изменения
                new_data = {
                    'title': vacancy_data.get('name', ''),
                    'description': vacancy_data.get('description', ''),
                }
                if vacancy.has_changes(new_data):
                    vacancy.create_version(new_data)
                    for field, value in new_data.items():
                        setattr(vacancy, field, value)
                    vacancy.save()
                    stats['updated'] += 1
                else:
                    stats['unchanged'] += 1

        except Exception as e:
            vacancy_id_str = str(vacancy_id) if vacancy_id else 'unknown'
            logger.error(f'Ошибка при сохранении вакансии {vacancy_id_str}: {e}')
            stats['errors'] += 1

    return stats


def _create_vacancy_from_api_data(vacancy_data: Dict[str, Any], role_id: str, role_name: str) -> Vacancy:
    """Создает объект Vacancy из данных API HeadHunter"""
    vacancy = Vacancy()

    # Основная информация
    vacancy.title = vacancy_data.get('name', '')
    vacancy.description = vacancy_data.get('description', '')
    if vacancy_data.get('snippet'):
        vacancy.requirements = vacancy_data['snippet'].get('requirement') or ''
        vacancy.responsibilities = vacancy_data['snippet'].get('responsibility') or ''

    # Зарплата
    salary_data = vacancy_data.get('salary')
    if salary_data:
        vacancy.salary_from = salary_data.get('from')
        vacancy.salary_to = salary_data.get('to')
        vacancy.salary_currency = salary_data.get('currency')
        vacancy.salary_gross = salary_data.get('gross', True)

    # Компания
    employer_data = vacancy_data.get('employer')
    if employer_data:
        vacancy.company_name = employer_data.get('name', '')
        vacancy.employer_id = str(employer_data.get('id', ''))
        vacancy.employer_name = employer_data.get('name', '')
        vacancy.employer_trusted = employer_data.get('trusted', False)

    # Локация
    area_data = vacancy_data.get('area')
    if area_data:
        vacancy.city = area_data.get('name')

    address_data = vacancy_data.get('address')
    if address_data:
        vacancy.address = address_data.get('raw')

    # Тип работы
    if vacancy_data.get('employment'):
        vacancy.employment_type = vacancy_data['employment'].get('name') or ''
    if vacancy_data.get('experience'):
        vacancy.experience_level = vacancy_data['experience'].get('name') or ''
    if vacancy_data.get('schedule'):
        vacancy.schedule_type = vacancy_data['schedule'].get('name') or ''

    # Роль и ID
    vacancy.professional_role = role_id
    vacancy.hh_id = str(vacancy_data.get('id', ''))
    vacancy.url = vacancy_data.get('alternate_url', '')

    # Даты
    published_at = vacancy_data.get('published_at')
    if published_at:
        from datetime import datetime
        vacancy.published_at = datetime.fromisoformat(published_at.replace('Z', '+00:00'))

    return vacancy


def _update_vacancy_from_api_data(vacancy: Vacancy, details: Dict[str, Any]) -> bool:
    """Обновляет объект Vacancy детальной информацией из API"""
    has_changes = False

    # Сохраняем старые значения для сравнения
    old_description = vacancy.description
    old_key_skills = vacancy.key_skills
    old_responsibilities = vacancy.responsibilities
    old_requirements = vacancy.requirements
    old_is_active = vacancy.is_active
    old_has_test = vacancy.has_test
    old_response_letter_required = vacancy.response_letter_required
    old_premium = vacancy.premium

    # Обновляем описание и требования из детальной информации
    if 'description' in details and details['description'] != old_description:
        vacancy.description = details['description']
        has_changes = True

    if 'key_skills' in details and details['key_skills'] != old_key_skills:
        vacancy.key_skills = details['key_skills']
        has_changes = True

    # Обновляем обязанности, если они есть в деталях
    if 'responsibilities' in details:
        new_responsibilities = details['responsibilities'] or ''
        if new_responsibilities != old_responsibilities:
            vacancy.responsibilities = new_responsibilities
            has_changes = True

    # Обновляем требования, если они есть в деталях
    if 'requirements' in details:
        new_requirements = details['requirements'] or ''
        if new_requirements != old_requirements:
            vacancy.requirements = new_requirements
            has_changes = True

    # Обновляем статус вакансии
    if 'archived' in details:
        new_is_active = not details['archived']
        if new_is_active != old_is_active:
            vacancy.is_active = new_is_active
            has_changes = True

    # Обновляем дополнительные поля
    if details.get('has_test', False) != old_has_test:
        vacancy.has_test = details.get('has_test', False)
        has_changes = True

    if details.get('response_letter_required', False) != old_response_letter_required:
        vacancy.response_letter_required = details.get('response_letter_required', False)
        has_changes = True

    if details.get('premium', False) != old_premium:
        vacancy.premium = details.get('premium', False)
        has_changes = True

    return has_changes


def _merge_snippet_into_details(details: Dict[str, Any], search_vacancy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Добавляет snippet из поисковой выдачи в детальные данные, если его нет.
    Это помогает не терять укороченный текст требований/обязанностей.
    """
    if 'snippet' not in details and search_vacancy.get('snippet'):
        details = dict(details)
        details['snippet'] = search_vacancy.get('snippet')

    # Если в деталях нет responsibilities/requirements, но есть в snippet — проставляем
    snippet = search_vacancy.get('snippet') or {}
    if 'responsibilities' not in details and snippet.get('responsibility'):
        details['responsibilities'] = snippet.get('responsibility')
    if 'requirements' not in details and snippet.get('requirement'):
        details['requirements'] = snippet.get('requirement')

    return details
