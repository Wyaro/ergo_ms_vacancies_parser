"""
Celery задачи для парсинга вакансий.

Содержит:
- Координирующие задачи (orchestration)
- Worker задачи (парсинг отдельных items)
- Периодические задачи (crash recovery, monitoring)
"""

import logging
from datetime import timedelta
from celery import shared_task, group, chord
from typing import Dict, Any, List, Optional

from django.utils import timezone

from .models import ParsingTask, TaskItem
from .scheduler import default_scheduler
from .parsers import ParserFactory
# Импортируем утилиты из пакета tasks/ (директория), а не из этого файла tasks.py
from .tasks.base import (
    get_error_handler_for_task,
    get_metrics_for_task,
)
from .tasks.worker import (
    validate_worker_params,
    claim_items_for_worker,
    process_item,
    handle_item_error,
)
from .tasks.orchestration import validate_orchestration_params

logger = logging.getLogger('celery.module.vacancies_parser.tasks')


# ============================================================
# КООРДИНИРУЮЩИЕ ЗАДАЧИ (ORCHESTRATION)
# ============================================================

@shared_task(
    name='vacancies_parser.tasks.create_parsing_task',
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def create_parsing_task(
    self,
    source: str,
    parsing_mode: str,
    config: Dict[str, Any],
    name: Optional[str] = None,
    created_by_id: Optional[int] = None
) -> int:
    """
    Создание задачи парсинга и обнаружение items (discovery фаза).
    
    Args:
        source: Источник (headhunter, habr_career, superjob)
        parsing_mode: Режим парсинга (api, html)
        config: Конфигурация парсинга
        name: Название задачи (опционально)
        created_by_id: ID пользователя-создателя (опционально)
    
    Returns:
        int: ID созданной ParsingTask
    
    Raises:
        Exception: При ошибках создания задачи или discovery
    """
    task_id = self.request.id
    metrics = get_metrics_for_task(self.name)
    error_handler = get_error_handler_for_task(self.name)
    
    # Валидация параметров
    try:
        validate_orchestration_params(source=source, parsing_mode=parsing_mode, config=config)
    except ValueError as e:
        logger.error(f"Ошибка валидации параметров задачи {task_id}: {e}")
        raise
    
    # Запись начала задачи
    metrics.record_task_start(task_id, task_name=self.name, source=source, parsing_mode=parsing_mode)
    
    try:
        logger.info(f"Создание задачи парсинга: {source}/{parsing_mode}")
        
        # Создание задачи
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        created_by = None
        if created_by_id:
            try:
                created_by = User.objects.get(id=created_by_id)
            except User.DoesNotExist:
                logger.warning(f"Пользователь {created_by_id} не найден")

        config_hash = ParsingTask.get_config_hash(source, parsing_mode, config)
        existing = ParsingTask.objects.filter(
            source=source,
            config_hash=config_hash
        ).exclude(status__in=['completed', 'failed', 'stopped']).first()
        if existing:
            logger.info(f"Задача с такой конфигурацией уже существует: {existing.id}, возврат id")
            metrics.record_task_success(task_id, existing.id)
            return existing.id

        task = ParsingTask.objects.create(
            source=source,
            parsing_mode=parsing_mode,
            config=config,
            name=name or f"{source} {parsing_mode} парсинг",
            created_by=created_by
        )
        
        logger.info(f"Создана задача {task.id}: {task.name}")
        
        # Discovery фаза - обнаружение items
        try:
            logger.info(f"Создание парсера: source={source}, parsing_mode={parsing_mode}")
            parser = ParserFactory.create_parser(source, parsing_mode)
            logger.info(f"Парсер создан: {type(parser).__name__}")
            parser.validate_config(config)
            
            discovered_items = parser.discover_items(config)
            
            logger.info(f"Discovery завершен: обнаружено {len(discovered_items)} items")
            
            # Создание TaskItems
            task_items = []
            for item_data in discovered_items:
                task_item = TaskItem(
                    task=task,
                    source_item_id=item_data['source_item_id'],
                    url=item_data['url'],
                )
                task_items.append(task_item)
            
            # Bulk create для производительности с оптимизацией batch_size
            BATCH_SIZE = 500
            created_count = 0
            for i in range(0, len(task_items), BATCH_SIZE):
                batch = task_items[i:i + BATCH_SIZE]
                TaskItem.objects.bulk_create(batch, ignore_conflicts=True, batch_size=BATCH_SIZE)
                created_count += len(batch)
            
            logger.debug(f"Bulk create TaskItems: создано {created_count} из {len(task_items)}")
            
            # Обновление счетчика total_items
            task.total_items = len(task_items)
            task.save(update_fields=['total_items', 'updated_at'])
            
            logger.info(f"Создано {len(task_items)} TaskItems для задачи {task.id}")
            
            # Запуск задачи
            task.start()
            
            # Запуск координатора парсинга с обработкой ошибок брокера
            try:
                coordinate_parsing_task.apply_async(
                    args=[task.id],
                    countdown=2
                )
            except Exception as e:
                error_msg = f"Не удалось запустить координатор парсинга: {str(e)}"
                logger.warning(error_msg)
                logger.warning(
                    "Задача создана, но координатор не запущен. "
                    "Запустите Celery worker и координатор запустится автоматически при следующей проверке."
                )
                task.error_message = error_msg
                task.save(update_fields=['error_message', 'updated_at'])
            
            result = task.id
            metrics.record_task_success(task_id, result)
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при discovery для задачи {task.id}: {e}")
            # Обновляем задачу напрямую, так как она еще не в статусе 'running'
            task.status = 'failed'
            task.error_message = f"Ошибка при discovery: {str(e)}"
            task.save(update_fields=['status', 'error_message', 'updated_at'])
            
            # Обработка ошибки
            error_handler.handle_error(e, {'task_id': task.id, 'phase': 'discovery'})
            raise
    
    except Exception as e:
        logger.error(f"Ошибка при создании задачи парсинга: {e}")
        metrics.record_task_failure(task_id, e)
        error_handler.handle_error(e, {'task_id': task_id})
        raise


@shared_task(
    name='vacancies_parser.tasks.coordinate_parsing_task',
    bind=True,
    max_retries=0  # Координатор не должен retry, чтобы избежать дублирования
)
def coordinate_parsing_task(self, task_id: int):
    """
    Координация выполнения задачи парсинга.
    
    Функции:
    - Распределение TaskItems между workers через scheduler
    - Запуск worker задач для обработки items
    - Мониторинг прогресса
    - Финализация задачи при завершении
    
    Args:
        task_id: ID ParsingTask
    """
    try:
        task = ParsingTask.objects.get(id=task_id)
        
        if task.status != 'running':
            logger.warning(
                f"Координатор для задачи {task_id}: задача не в статусе 'running' ({task.status})"
            )
            return
        
        logger.info(f"Координатор запущен для задачи {task_id}")
        
        # Сохранение Celery task ID координатора
        task.celery_task_id = self.request.id
        task.save(update_fields=['celery_task_id', 'updated_at'])
        
        # Запуск worker'ов параллельно через Celery group
        # Worker'ы сами будут claiming items через scheduler
        worker_count = 10  # Количество параллельных worker'ов
        
        worker_tasks = [
            parse_items_worker.si(task_id, worker_id=f"worker-{i}")
            for i in range(worker_count)
        ]
        
        # Использование chord для финализации после завершения всех worker'ов
        callback = finalize_parsing_task.si(task_id)
        
        chord(worker_tasks)(callback)
        
        logger.info(f"Запущено {worker_count} worker'ов для задачи {task_id}")
        
    except ParsingTask.DoesNotExist:
        logger.error(f"Задача {task_id} не найдена")
    except Exception as e:
        logger.error(f"Ошибка в координаторе для задачи {task_id}: {e}")


@shared_task(
    name='vacancies_parser.tasks.finalize_parsing_task',
    bind=True,
    max_retries=3
)
def finalize_parsing_task(self, task_id: int):
    """
    Финализация задачи парсинга после завершения всех worker'ов.
    
    Args:
        task_id: ID ParsingTask
    """
    try:
        logger.info(f"Финализация задачи {task_id}")
        
        # Используем scheduler для финализации
        success = default_scheduler.finalize_task(task_id)
        
        if success:
            logger.info(f"Задача {task_id} успешно финализирована")
        else:
            logger.error(f"Ошибка финализации задачи {task_id}")
    
    except Exception as e:
        logger.error(f"Ошибка при финализации задачи {task_id}: {e}")
        raise


# ============================================================
# WORKER ЗАДАЧИ (ПАРСИНГ ITEMS)
# ============================================================

@shared_task(
    name='vacancies_parser.tasks.parse_items_worker',
    bind=True,
    max_retries=0  # Worker не делает retry, items управляются через scheduler
)
def parse_items_worker(self, task_id: int, worker_id: str):
    """
    Worker для обработки TaskItems.
    
    Функции:
    - Claiming items через scheduler
    - Парсинг каждого item через соответствующий парсер
    - Сохранение результатов в NormalizedVacancy
    - Обработка ошибок и retry логика
    
    Args:
        task_id: ID ParsingTask
        worker_id: ID worker'а для идентификации
    """
    celery_task_id = self.request.id
    metrics = get_metrics_for_task(self.name)
    error_handler = get_error_handler_for_task(self.name)
    
    # Валидация параметров
    try:
        validate_worker_params(task_id=task_id, worker_id=worker_id)
    except ValueError as e:
        logger.error(f"Ошибка валидации параметров worker задачи {celery_task_id}: {e}")
        raise
    
    # Запись начала задачи
    metrics.record_task_start(celery_task_id, task_name=self.name, parsing_task_id=task_id, worker_id=worker_id)
    
    try:
        task = ParsingTask.objects.get(id=task_id)
        
        if task.status != 'running':
            logger.info(f"Worker {worker_id}: задача {task_id} не в статусе 'running', завершение")
            metrics.record_task_success(celery_task_id, {'status': 'skipped'}, parsing_task_id=task_id)
            return
        
        logger.info(f"Worker {worker_id} запущен для задачи {task_id}")
        
        # Создание парсера
        logger.info(f"Worker {worker_id}: создание парсера source={task.source}, parsing_mode={task.parsing_mode}")
        try:
            parser = ParserFactory.create_parser(task.source, task.parsing_mode)
            logger.info(f"Worker {worker_id}: парсер создан: {type(parser).__name__}")
        except ValueError as e:
            logger.error(f"Worker {worker_id}: ошибка создания парсера: {e}")
            logger.error(f"Worker {worker_id}: доступные парсеры: {ParserFactory.get_available_parsers()}")
            raise
        
        import time
        import random
        from .parsers.base import BlockedError as _BlockedError

        processed_count = 0
        consecutive_blocks = 0
        max_consecutive_blocks = task.config.get('max_consecutive_blocks', 5)

        while True:
            task.refresh_from_db()
            if task.status != 'running':
                logger.info(f"Worker {worker_id}: задача {task_id} больше не running, завершение")
                break

            items = claim_items_for_worker(task_id=task_id, worker_id=worker_id, limit=10)

            if not items:
                logger.info(f"Worker {worker_id}: нет доступных items для задачи {task_id}")
                break

            for item in items:
                try:
                    result = process_item(item, parser, task, error_handler)
                    processed_count += 1
                    consecutive_blocks = 0
                    metrics.record_item_processed(celery_task_id, success=True)

                    try:
                        if result.get('norm_created'):
                            metrics.increment_counter(celery_task_id, 'saved', 1)
                        elif result.get('norm_updated'):
                            metrics.increment_counter(celery_task_id, 'updated', 1)
                    except Exception:
                        pass

                    logger.info(f"Worker {worker_id}: успешно обработан item {item.id} (vacancy_id={result['vacancy_id']}, created={result['created']})")

                except Exception as e:
                    logger.error(
                        f"Worker {worker_id}: ошибка при парсинге item {item.id} (source_item_id={item.source_item_id}, url={item.url}): {e}",
                        exc_info=True
                    )

                    handle_item_error(item, e, task, error_handler)
                    metrics.record_item_processed(celery_task_id, success=False)

                    if isinstance(e, _BlockedError) or 'captcha' in str(e).lower():
                        consecutive_blocks += 1
                        if consecutive_blocks >= max_consecutive_blocks:
                            logger.warning(
                                f"Worker {worker_id}: {consecutive_blocks} блокировок подряд, "
                                f"остановка воркера для задачи {task_id}"
                            )
                            break
                    else:
                        consecutive_blocks = 0

                base_delay = task.config.get('delay', 1.5)
                delay = random.uniform(base_delay * 0.8, base_delay * 1.4)
                time.sleep(delay)
            else:
                continue
            break
        
        result = {'processed_count': processed_count, 'task_id': task_id}
        logger.info(f"Worker {worker_id} завершен для задачи {task_id}: обработано {processed_count} items")
        metrics.record_task_success(celery_task_id, result, parsing_task_id=task_id, processed_count=processed_count)
        
    except ParsingTask.DoesNotExist:
        error_msg = f"Задача {task_id} не найдена"
        logger.error(f"Worker {worker_id}: {error_msg}")
        metrics.record_task_failure(celery_task_id, Exception(error_msg), parsing_task_id=task_id)
        raise
    except Exception as e:
        logger.error(f"Worker {worker_id}: критическая ошибка для задачи {task_id}: {e}")
        metrics.record_task_failure(celery_task_id, e, parsing_task_id=task_id)
        error_handler.handle_error(e, {'task_id': task_id, 'worker_id': worker_id})
        raise


# ============================================================
# ПЕРИОДИЧЕСКИЕ ЗАДАЧИ (CELERY BEAT)
# ============================================================

@shared_task(name='vacancies_parser.tasks.release_expired_leases')
def release_expired_leases():
    """
    Периодическая задача для освобождения застрявших items (crash recovery).
    
    Запускается каждые 5 минут через Celery Beat.
    """
    from celery import current_task
    task_id = current_task.request.id if current_task else 'unknown'
    metrics = get_metrics_for_task('vacancies_parser.tasks.release_expired_leases')
    error_handler = get_error_handler_for_task('vacancies_parser.tasks.release_expired_leases')
    
    metrics.record_task_start(task_id, task_name='release_expired_leases')
    
    try:
        released_count = default_scheduler.release_expired_leases()
        
        if released_count > 0:
            logger.warning(f"Освобождено {released_count} expired leases")
        
        result = {'released_count': released_count}
        metrics.record_task_success(task_id, result, released_count=released_count)
        return released_count
        
    except Exception as e:
        logger.error(f"Ошибка при освобождении expired leases: {e}")
        metrics.record_task_failure(task_id, e)
        error_handler.handle_error(e, {'task_id': task_id})
        return 0


@shared_task(name='vacancies_parser.tasks.monitor_tasks_progress')
def monitor_tasks_progress():
    """
    Периодическая задача для мониторинга прогресса running задач.
    
    Запускается каждые 10 минут через Celery Beat.
    """
    from celery import current_task
    task_id = current_task.request.id if current_task else 'unknown'
    metrics = get_metrics_for_task('vacancies_parser.tasks.monitor_tasks_progress')
    error_handler = get_error_handler_for_task('vacancies_parser.tasks.monitor_tasks_progress')
    
    metrics.record_task_start(task_id, task_name='monitor_tasks_progress')
    
    try:
        running_tasks = ParsingTask.objects.filter(status='running')
        stuck_minutes = 20
        try:
            from django.conf import settings
            stuck_minutes = int(getattr(settings, 'VACANCIES_PARSER_STUCK_MINUTES', stuck_minutes))
        except Exception:
            stuck_minutes = 20
        now = timezone.now()
        stuck_threshold = now - timedelta(minutes=stuck_minutes)
        stuck_tasks = []
        finalized_count = 0
        
        for task in running_tasks:
            if task.updated_at and task.updated_at < stuck_threshold:
                stuck_tasks.append(task)
            progress = default_scheduler.get_task_progress(task.id)
            
            logger.info(
                f"Task {task.id} progress: "
                f"{progress.get('completed', 0)}/{progress.get('total', 0)} "
                f"({progress.get('progress_percent', 0):.1f}%), "
                f"failed: {progress.get('failed', 0)}"
            )
            
            # Проверка завершенности
            if default_scheduler.check_task_completion(task.id):
                logger.info(f"Task {task.id} обнаружен как завершенный, запуск финализации")
                try:
                    finalize_parsing_task.apply_async(args=[task.id])
                    finalized_count += 1
                except Exception as e:
                    logger.warning(f"Не удалось запустить финализацию задачи {task.id}: {e}")
                    logger.warning("Финализация будет выполнена при следующей проверке или вручную")

        if stuck_tasks:
            stuck_ids = [t.id for t in stuck_tasks]
            logger.warning(
                "Обнаружены потенциально зависшие задачи (running без обновлений > %d мин): %s",
                stuck_minutes,
                stuck_ids,
            )
        
        result = {
            'monitored_tasks': len(running_tasks),
            'stuck_tasks': len(stuck_tasks),
            'finalize_triggered': finalized_count,
        }
        metrics.record_task_success(
            task_id,
            result,
            monitored_tasks=len(running_tasks),
            stuck_tasks=len(stuck_tasks),
            finalize_triggered=finalized_count,
        )
        # В TaskRun (DB) дополнительно подсветим stuck как errors (для обзора в админке)
        try:
            metrics.increment_counter(task_id, 'errors', len(stuck_tasks))
        except Exception:
            pass
        return len(running_tasks)
        
    except Exception as e:
        logger.error(f"Ошибка при мониторинге задач: {e}")
        metrics.record_task_failure(task_id, e)
        error_handler.handle_error(e, {'task_id': task_id})
        return 0


@shared_task(name='vacancies_parser.tasks.cleanup_monitoring_retention')
def cleanup_monitoring_retention() -> int:
    """
    Периодическая очистка мониторинговых данных (retention).

    Удаляет старые записи TaskRun и ExternalApiEvent, чтобы не раздувать БД.
    """
    from celery import current_task
    task_id = current_task.request.id if current_task else 'unknown'
    metrics = get_metrics_for_task('vacancies_parser.tasks.cleanup_monitoring_retention')
    error_handler = get_error_handler_for_task('vacancies_parser.tasks.cleanup_monitoring_retention')

    metrics.record_task_start(task_id, task_name='cleanup_monitoring_retention')

    retention_days = 60
    try:
        from django.conf import settings
        retention_days = int(getattr(settings, 'VACANCIES_PARSER_TASKRUN_RETENTION_DAYS', retention_days))
    except Exception:
        retention_days = 60

    try:
        from datetime import timedelta
        from django.utils import timezone
        from .monitoring_models import TaskRun, ExternalApiEvent

        threshold = timezone.now() - timedelta(days=retention_days)
        deleted_taskruns, _ = TaskRun.objects.filter(started_at__lt=threshold).delete()
        deleted_events, _ = ExternalApiEvent.objects.filter(created_at__lt=threshold).delete()
        result = {
            'deleted_taskruns': deleted_taskruns,
            'deleted_events': deleted_events,
            'retention_days': retention_days,
        }
        metrics.record_task_success(task_id, result, **result)
        return deleted_taskruns + deleted_events
    except Exception as e:
        logger.error("Ошибка очистки retention мониторинга: %s", e)
        metrics.record_task_failure(task_id, e)
        error_handler.handle_error(e, {'task_id': task_id})
        return 0


# ============================================================
# УПРАВЛЯЮЩИЕ ЗАДАЧИ (PAUSE/RESUME/STOP)
# ============================================================

@shared_task(name='vacancies_parser.tasks.pause_task')
def pause_task(task_id: int) -> bool:
    """Приостановка задачи"""
    return default_scheduler.pause_task(task_id)


@shared_task(name='vacancies_parser.tasks.resume_task')
def resume_task(task_id: int) -> bool:
    """Возобновление задачи"""
    success = default_scheduler.resume_task(task_id)
    
    if success:
        # Перезапуск координатора с обработкой ошибок брокера
        try:
            coordinate_parsing_task.apply_async(args=[task_id], countdown=2)
        except Exception as e:
            logger.warning(f"Не удалось запустить координатор при возобновлении задачи {task_id}: {e}")
            logger.warning("Координатор будет запущен автоматически при следующей проверке")
    
    return success


@shared_task(name='vacancies_parser.tasks.stop_task')
def stop_task(task_id: int) -> bool:
    """Остановка задачи"""
    return default_scheduler.stop_task(task_id)
