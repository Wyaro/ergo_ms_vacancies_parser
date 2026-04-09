"""
Задачи проверки статусов вакансий.
"""

import logging
import time
from typing import Dict, Any

from celery import shared_task
from django.utils import timezone

from ..scripts import HeadHunterParser, ParsingMetrics
from ..models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.headhunter')


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
                    Vacancy.objects.filter(
                        id=db_id
                    ).update(
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
