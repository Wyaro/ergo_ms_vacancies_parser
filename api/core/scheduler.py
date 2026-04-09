"""
Scheduler для конкурентно-безопасного claiming TaskItems.

Обеспечивает:
- Распределение TaskItems между workers
- Crash recovery через lease механизм
- Monitoring и статистика
"""

import logging
from datetime import timedelta
from typing import List, Optional
from django.db import transaction
from django.utils import timezone

from .models import ParsingTask, TaskItem

logger = logging.getLogger('celery.module.vacancies_parser.scheduler')


class TaskScheduler:
    """
    Scheduler для управления распределением TaskItems между workers.
    
    Функции:
    - Конкурентно-безопасное claiming через SELECT FOR UPDATE SKIP LOCKED
    - Автоматическое освобождение expired leases (crash recovery)
    - Мониторинг прогресса задач
    """
    
    def __init__(
        self,
        lease_duration_minutes: int = 5,
        batch_size: int = 10
    ):
        """
        Args:
            lease_duration_minutes: Длительность lease в минутах
            batch_size: Размер батча для claiming
        """
        self.lease_duration_minutes = lease_duration_minutes
        self.batch_size = batch_size
    
    def claim_items_for_worker(
        self,
        task_id: int,
        worker_id: str,
        limit: Optional[int] = None
    ) -> List[TaskItem]:
        """
        Извлечение TaskItems для обработки worker'ом.
        
        Конкурентно-безопасно: использует SELECT FOR UPDATE SKIP LOCKED
        для предотвращения race conditions.
        
        Args:
            task_id: ID ParsingTask
            worker_id: ID Celery worker'а
            limit: Максимальное количество items (по умолчанию batch_size)
        
        Returns:
            List[TaskItem]: Список claimed items
        """
        limit = limit or self.batch_size
        
        try:
            # Проверка статуса задачи
            task = ParsingTask.objects.get(id=task_id)
            if task.status != 'running':
                logger.warning(
                    f"Попытка claim items для задачи {task_id} в статусе '{task.status}'. "
                    f"Ожидается 'running'."
                )
                return []
            
            # Claiming items
            items = TaskItem.claim_items_for_worker(
                task_id=task_id,
                worker_id=worker_id,
                limit=limit,
                lease_minutes=self.lease_duration_minutes
            )
            
            if items:
                logger.info(
                    f"Worker {worker_id} claimed {len(items)} items "
                    f"для задачи {task_id}"
                )
            
            return items
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return []
        except Exception as e:
            logger.error(f"Ошибка при claiming items для задачи {task_id}: {e}")
            return []
    
    def release_expired_leases(self) -> int:
        """
        Освобождение TaskItems с истекшими leases (crash recovery).
        
        Вызывается периодической задачей Celery Beat каждые N минут.
        
        Returns:
            int: Количество освобожденных items
        """
        try:
            released_count = TaskItem.release_expired_leases()
            
            if released_count > 0:
                logger.warning(
                    f"Освобождено {released_count} TaskItems с истекшими leases. "
                    f"Возможен crash worker'ов."
                )
            
            return released_count
            
        except Exception as e:
            logger.error(f"Ошибка при освобождении expired leases: {e}")
            return 0
    
    def get_task_progress(self, task_id: int) -> dict:
        """
        Получение прогресса выполнения задачи.
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            dict: {
                'total': 100,
                'pending': 50,
                'in_progress': 10,
                'completed': 38,
                'failed': 2,
                'retrying': 0,
                'blocked': 0,
                'progress_percent': 38.0,
                'task_status': 'running'
            }
        """
        try:
            task = ParsingTask.objects.get(id=task_id)
            
            # Подсчет по статусам items (используем агрегацию для производительности)
            from django.db.models import Count, Q
            
            stats = TaskItem.objects.filter(task_id=task_id).aggregate(
                pending=Count('id', filter=Q(status='pending')),
                in_progress=Count('id', filter=Q(status='in_progress')),
                completed=Count('id', filter=Q(status='completed')),
                failed=Count('id', filter=Q(status='failed')),
                retrying=Count('id', filter=Q(status='retrying')),
                blocked=Count('id', filter=Q(status='blocked')),
            )
            
            progress = {
                'total': task.total_items,
                'pending': stats['pending'],
                'in_progress': stats['in_progress'],
                'completed': stats['completed'],
                'failed': stats['failed'],
                'retrying': stats['retrying'],
                'blocked': stats['blocked'],
                'progress_percent': task.progress_percent,
                'task_status': task.status,
            }
            
            return progress
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return {}
        except Exception as e:
            logger.error(f"Ошибка при получении прогресса задачи {task_id}: {e}")
            return {}
    
    def check_task_completion(self, task_id: int) -> bool:
        """
        Проверка завершенности задачи.
        
        Задача считается завершенной, если:
        - Все items в статусе 'completed' или 'failed' или 'blocked'
        - Нет items в статусе 'pending', 'in_progress', 'retrying'
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            bool: True если задача завершена
        """
        try:
            active_statuses = ['pending', 'in_progress', 'retrying']
            active_items_count = TaskItem.objects.filter(
                task_id=task_id,
                status__in=active_statuses
            ).count()
            
            is_completed = active_items_count == 0
            
            if is_completed:
                logger.info(f"Задача {task_id} завершена: нет активных items")
            
            return is_completed
            
        except Exception as e:
            logger.error(f"Ошибка при проверке завершенности задачи {task_id}: {e}")
            return False
    
    _TERMINAL_STATUSES = frozenset({'completed', 'failed', 'blocked'})

    def _cleanup_stuck_items(self, task_id: int):
        """
        Помечает все незавершённые items как failed перед финализацией.

        Chord вызывает финализацию после завершения ВСЕХ воркеров,
        поэтому любой item не в терминальном статусе (completed / failed /
        blocked) гарантированно никем не обрабатывается.  Причины:
        - pending: пропущен из-за SKIP LOCKED или нехватки воркеров
        - in_progress: worker завершился до обработки
        - retrying / другие: нештатное состояние
        """
        stuck = TaskItem.objects.filter(
            task_id=task_id,
        ).exclude(
            status__in=self._TERMINAL_STATUSES,
        )

        stuck_count = stuck.update(
            status='failed',
            last_error='Item не был обработан до финализации задачи',
            last_error_type='unknown',
            updated_at=timezone.now(),
        )
        if stuck_count:
            logger.warning(
                f"Задача {task_id}: {stuck_count} items не были обработаны "
                f"до финализации — помечены как failed"
            )

    def finalize_task(self, task_id: int) -> bool:
        """
        Финализация задачи после завершения обработки всех items.
        
        Действия:
        - Очистка застрявших items (in_progress / pending)
        - Переход задачи в статус 'completed' или 'failed'
        - Создание итоговой статистики
        - Логирование результатов
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            bool: True если финализация успешна
        """
        try:
            task = ParsingTask.objects.get(id=task_id)

            self._cleanup_stuck_items(task_id)
            
            if not self.check_task_completion(task_id):
                logger.warning(f"Попытка финализировать незавершенную задачу {task_id}")
                return False
            
            completed_count = TaskItem.objects.filter(
                task_id=task_id,
                status='completed'
            ).count()
            
            failed_count = TaskItem.objects.filter(
                task_id=task_id,
                status='failed'
            ).count()
            
            blocked_count = TaskItem.objects.filter(
                task_id=task_id,
                status='blocked'
            ).count()
            
            task.completed_items = completed_count
            task.failed_items = failed_count
            
            if task.total_items == 0:
                task.stop()
                logger.warning(f"Задача {task_id} остановлена: 0 items (discovery не нашел элементов)")
            elif failed_count == task.total_items:
                task.fail("Все элементы завершились с ошибкой")
                logger.error(f"Задача {task_id} провалилась: все items с ошибками")
            elif completed_count > 0:
                task.complete()
                logger.info(
                    f"Задача {task_id} завершена: "
                    f"{completed_count} completed, {failed_count} failed, {blocked_count} blocked"
                )
            else:
                task.stop()
                logger.warning(
                    f"Задача {task_id} остановлена: "
                    f"0 completed, {failed_count} failed, {blocked_count} blocked"
                )
            
            self._create_task_statistics(task)
            
            return True
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return False
        except Exception as e:
            logger.error(f"Ошибка при финализации задачи {task_id}: {e}")
            return False
    
    def _create_task_statistics(self, task: ParsingTask):
        """
        Создание итоговой статистики для задачи.
        
        Args:
            task: ParsingTask instance
        """
        from .normalized_models import ParsingStatistics
        
        try:
            # Подсчет по статусам
            completed = TaskItem.objects.filter(task=task, status='completed').count()
            failed = TaskItem.objects.filter(task=task, status='failed').count()
            blocked = TaskItem.objects.filter(task=task, status='blocked').count()
            
            # Разбивка ошибок по типам
            error_breakdown = {}
            for error_type, _ in TaskItem.ERROR_TYPE_CHOICES:
                count = TaskItem.objects.filter(
                    task=task,
                    status='failed',
                    last_error_type=error_type
                ).count()
                if count > 0:
                    error_breakdown[error_type] = count
            
            complete_count = TaskItem.objects.filter(
                task=task,
                status='completed',
                result_vacancy_id__isnull=False,
            ).count()
            incomplete_count = completed - complete_count
            
            # Создание статистики
            stats = ParsingStatistics.objects.create(
                task=task,
                started_at=task.started_at or task.created_at,
                finished_at=task.completed_at or timezone.now(),
                total_processed=task.total_items,
                successful_items=completed,
                failed_items=failed,
                blocked_items=blocked,
                complete_records=complete_count,
                incomplete_records=incomplete_count,
                error_breakdown=error_breakdown,
            )
            
            stats.calculate_metrics()
            
            logger.info(f"Создана статистика для задачи {task.id}: {stats}")
            
        except Exception as e:
            logger.error(f"Ошибка при создании статистики для задачи {task.id}: {e}")
    
    def pause_task(self, task_id: int) -> bool:
        """
        Приостановка задачи.
        
        Действия:
        - Перевод задачи в статус 'paused'
        - Освобождение всех claimed items
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            bool: True если пауза успешна
        """
        try:
            task = ParsingTask.objects.get(id=task_id)
            
            # Перевод в статус paused
            task.pause()
            
            # Освобождение in_progress items
            released_count = TaskItem.objects.filter(
                task_id=task_id,
                status='in_progress'
            ).update(
                status='pending',
                worker_id=None,
                claimed_at=None,
                lease_expires_at=None,
                updated_at=timezone.now()
            )
            
            logger.info(
                f"Задача {task_id} приостановлена, освобождено {released_count} items"
            )
            
            return True
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return False
        except ValueError as e:
            logger.error(f"Ошибка при паузе задачи {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при паузе задачи {task_id}: {e}")
            return False
    
    def resume_task(self, task_id: int) -> bool:
        """
        Возобновление приостановленной задачи.
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            bool: True если возобновление успешно
        """
        try:
            task = ParsingTask.objects.get(id=task_id)
            task.resume()
            
            logger.info(f"Задача {task_id} возобновлена")
            return True
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return False
        except ValueError as e:
            logger.error(f"Ошибка при возобновлении задачи {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при возобновлении задачи {task_id}: {e}")
            return False
    
    def stop_task(self, task_id: int) -> bool:
        """
        Остановка задачи.
        
        Действия:
        - Перевод задачи в статус 'stopped'
        - Освобождение всех claimed items
        - Создание итоговой статистики
        
        Args:
            task_id: ID ParsingTask
        
        Returns:
            bool: True если остановка успешна
        """
        try:
            task = ParsingTask.objects.get(id=task_id)
            
            # Перевод в статус stopped
            task.stop()
            
            # Освобождение in_progress items
            released_count = TaskItem.objects.filter(
                task_id=task_id,
                status='in_progress'
            ).update(
                status='pending',
                worker_id=None,
                claimed_at=None,
                lease_expires_at=None,
                updated_at=timezone.now()
            )
            
            # Создание итоговой статистики
            self._create_task_statistics(task)
            
            logger.info(
                f"Задача {task_id} остановлена, освобождено {released_count} items"
            )
            
            return True
            
        except ParsingTask.DoesNotExist:
            logger.error(f"Задача {task_id} не найдена")
            return False
        except ValueError as e:
            logger.error(f"Ошибка при остановке задачи {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при остановке задачи {task_id}: {e}")
            return False


# Глобальный экземпляр scheduler
default_scheduler = TaskScheduler()
