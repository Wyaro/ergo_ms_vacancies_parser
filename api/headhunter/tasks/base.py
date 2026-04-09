"""
Базовые задачи парсинга HeadHunter и вспомогательные функции.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from celery import shared_task
from django.apps import apps as django_apps
from django.utils import timezone

from ...core.tasks import get_error_handler_for_task, get_metrics_for_task
from ..scripts import parse_vacancies_by_text, parse_all_vacancies, HeadHunterParser
from ..models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.headhunter')
SKILL_MAP_APP = 'modules.competence_core.api.skill_map'
PROFESSIONAL_ROLES_CONFIG = Path(__file__).parent.parent / 'config' / 'professional_roles_config.json'


def _load_target_category_id() -> str:
    """
    Загружает ID целевой категории ролей (для IT) из конфигурации.
    По умолчанию возвращает '11' (IT категория), если конфиг недоступен или ID не задан.
    
    Returns:
        str: ID категории (по умолчанию '11' для IT)
    """
    # Категория 11 - IT по умолчанию
    DEFAULT_CATEGORY_ID = '11'
    
    try:
        if PROFESSIONAL_ROLES_CONFIG.exists():
            with open(PROFESSIONAL_ROLES_CONFIG, 'r', encoding='utf-8') as config_file:
                config_data = json.load(config_file)
            category_id = config_data.get('target_category', {}).get('id')
            if category_id:
                logger.debug(f'Загружена категория {category_id} из конфига')
                return str(category_id)
        else:
            logger.debug(f'Файл конфигурации {PROFESSIONAL_ROLES_CONFIG} не найден, используем категорию по умолчанию: {DEFAULT_CATEGORY_ID}')
    except Exception as exc:
        logger.warning('Не удалось загрузить target_category.id из конфига: %s, используем категорию по умолчанию: %s', exc, DEFAULT_CATEGORY_ID)
    
    return DEFAULT_CATEGORY_ID


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
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    config: Optional[dict] = None
):
    """
    Celery-задача для парсинга вакансий с HeadHunter.
    Возвращает статистику по результатам парсинга.
    """
    task_id = self.request.id
    error_handler = get_error_handler_for_task(self.name)
    metrics = get_metrics_for_task(self.name)
    
    metrics.record_task_start(task_id, task_name=self.name, universal=universal)
    
    logger.info(
        "Запуск задачи parse_hh_vacancies_task: text_list=%s, universal=%s",
        text_list,
        universal,
    )
    
    if not universal and not text_list:
        error_msg = 'Необходимо указать text_list или universal=True'
        logger.error(error_msg)
        metrics.record_task_failure(task_id, ValueError(error_msg))
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
            result_data = {
                'mode': 'universal',
                'areas_processed': result.get('areas_processed'),
                'roles_processed': result.get('roles_processed'),
                'pages_processed': result.get('pages_processed'),
                'total_vacancies': result.get('total_vacancies'),
                'new_vacancies': result.get('new_vacancies'),
                'updated_vacancies': result.get('updated_vacancies'),
                'total_in_db': result.get('total_in_db'),
            }
            metrics.record_task_success(task_id, result_data)
            return result_data
        
        assert text_list is not None
        queries = list(text_list)
        logger.info("Выполняется парсинг по списку текстов (%d)", len(queries))
        result = parse_vacancies_by_text(
            text_list=queries,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            date_from=date_from,
            date_to=date_to
        )
        logger.info("Парсинг по тексту завершен")
        result_data = {
            'mode': 'by_text',
            'total_vacancies': result.get('total_vacancies'),
            'new_vacancies': result.get('new_vacancies'),
            'updated_vacancies': result.get('updated_vacancies'),
            'total_in_db': result.get('total_in_db'),
        }
        metrics.record_task_success(task_id, result_data)
        return result_data
    except Exception as exc:
        logger.error('Ошибка выполнения parse_hh_vacancies_task', exc_info=True)
        metrics.record_task_failure(task_id, exc)
        error_handler.handle_error(exc, {'task_id': task_id})
        
        # Проверка необходимости retry
        retries = self.request.retries
        if error_handler.should_retry(exc, retries, self.max_retries):
            delay = error_handler.get_retry_delay(exc, retries, base_delay=self.default_retry_delay)
            raise self.retry(exc=exc, countdown=delay)
        raise


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
    task_id = self.request.id
    error_handler = get_error_handler_for_task(self.name)
    metrics = get_metrics_for_task(self.name)
    
    metrics.record_task_start(task_id, task_name=self.name, vacancy_id=vacancy_id)
    
    logger.info(f"Запуск задачи parse_single_vacancy_task для вакансии {vacancy_id}, force_update={force_update}")
    
    try:
        parser = HeadHunterParser()
        vacancy_manager = getattr(Vacancy, 'objects')
        existing_vacancy = vacancy_manager.filter(hh_id=vacancy_id).first()
        if existing_vacancy and not force_update:
            msg = f'Вакансия {vacancy_id} уже есть в базе'
            logger.info(msg)
            result = {'status': 'exists', 'message': msg}
            metrics.record_task_success(task_id, result)
            return result
        
        vacancy_data = parser.get_vacancy_details(vacancy_id)
        if not vacancy_data or not isinstance(vacancy_data, dict) or 'id' not in vacancy_data:
            msg = f'Вакансия {vacancy_id} не найдена или данные некорректны'
            logger.error(msg)
            result = {'status': 'error', 'message': msg}
            metrics.record_task_failure(task_id, ValueError(msg))
            return result
        
        vacancy = parser.parse_vacancy(vacancy_data)
        if not vacancy:
            msg = 'Ошибка при парсинге вакансии'
            logger.error(msg)
            result = {'status': 'error', 'message': msg}
            metrics.record_task_failure(task_id, ValueError(msg))
            return result
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
                    result = {'status': 'updated', 'message': f'Вакансия {vacancy_id} обновлена'}
                    metrics.record_task_success(task_id, result)
                    return result
                result = {'status': 'no_changes', 'message': 'Изменений не обнаружено'}
                metrics.record_task_success(task_id, result)
                return result
            result = {'status': 'exists', 'message': f'Вакансия {vacancy_id} уже есть в базе'}
            metrics.record_task_success(task_id, result)
            return result
        else:
            vacancy.save()
            result = {'status': 'created', 'message': f'Вакансия {vacancy_id} успешно сохранена'}
            metrics.record_task_success(task_id, result)
            return result
    except Exception as exc:
        logger.error('Ошибка при обработке вакансии %s', vacancy_id, exc_info=True)
        metrics.record_task_failure(task_id, exc)
        error_handler.handle_error(exc, {'task_id': task_id, 'vacancy_id': vacancy_id})
        
        # Проверка необходимости retry
        retries = self.request.retries
        if error_handler.should_retry(exc, retries, self.max_retries):
            delay = error_handler.get_retry_delay(exc, retries, base_delay=self.default_retry_delay)
            raise self.retry(exc=exc, countdown=delay)
        raise
