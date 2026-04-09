"""
Модели для управления задачами парсинга вакансий.

Содержит:
- ParsingTask: модель задачи парсинга с state machine
- TaskItem: модель атомарной единицы работы с lease механизмом
"""

import hashlib
import json
from datetime import timedelta
from typing import List, Optional

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

User = get_user_model()


class ParsingTask(models.Model):
    """
    Модель для управления задачами парсинга вакансий.
    
    Поддерживает:
    - State machine (created/running/paused/stopped/completed/failed)
    - Двойной режим парсинга (API/HTML)
    - Pause/resume/stop функциональность
    - Персистентное отслеживание прогресса
    - Crash recovery через lease механизм
    """
    
    # ============================================================
    # ИДЕНТИФИКАЦИЯ И КОНФИГУРАЦИЯ
    # ============================================================
    
    SOURCE_CHOICES = [
        ('headhunter', 'HeadHunter'),
        ('habr_career', 'Habr Career'),
        ('superjob', 'SuperJob'),
    ]
    source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        verbose_name="Источник",
        db_index=True
    )
    
    PARSING_MODE_CHOICES = [
        ('api', 'API режим'),
        ('html', 'HTML режим'),
    ]
    parsing_mode = models.CharField(
        max_length=10,
        choices=PARSING_MODE_CHOICES,
        default='api',
        verbose_name="Режим парсинга",
        db_index=True,
        help_text="API режим использует официальные API, HTML режим парсит веб-страницы"
    )
    
    name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Название задачи",
        help_text="Опциональное название для UI"
    )
    
    config = models.JSONField(
        default=dict,
        verbose_name="Конфигурация парсинга",
        help_text="JSON с параметрами парсинга (area, pages, technologies и т.д.)"
    )
    
    config_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Хэш конфигурации",
        help_text="SHA256 хэш для дедупликации задач"
    )
    
    # ============================================================
    # СОСТОЯНИЕ ЗАДАЧИ (STATE MACHINE)
    # ============================================================
    
    STATUS_CHOICES = [
        ('created', 'Создана'),
        ('running', 'Выполняется'),
        ('paused', 'Приостановлена'),
        ('stopped', 'Остановлена'),
        ('completed', 'Завершена'),
        ('failed', 'Ошибка'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='created',
        verbose_name="Статус",
        db_index=True
    )
    
    # ============================================================
    # ПРОГРЕСС ВЫПОЛНЕНИЯ
    # ============================================================
    
    total_items = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Всего элементов"
    )
    
    completed_items = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Завершено элементов"
    )
    
    failed_items = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name="Элементов с ошибками"
    )
    
    # ============================================================
    # МЕТАДАННЫЕ
    # ============================================================
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
        db_index=True
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления"
    )
    
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата запуска"
    )
    
    paused_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата приостановки"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата завершения"
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parsing_tasks',
        verbose_name="Создатель"
    )
    
    # ============================================================
    # CELERY ИНТЕГРАЦИЯ
    # ============================================================
    
    celery_task_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Celery Task ID",
        help_text="ID основной Celery задачи-координатора"
    )
    
    # ============================================================
    # ДОПОЛНИТЕЛЬНЫЕ ПОЛЯ
    # ============================================================
    
    error_message = models.TextField(
        null=True,
        blank=True,
        verbose_name="Сообщение об ошибке"
    )
    
    result_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Результат",
        help_text="Итоговые данные выполнения задачи"
    )
    
    class Meta:
        verbose_name = "Задача парсинга"
        verbose_name_plural = "Задачи парсинга"
        ordering = ['-created_at']
        db_table = 'vpm_parsing_task'
        
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['parsing_mode', 'status']),
            models.Index(fields=['created_at', 'status']),
            models.Index(fields=['config_hash']),
            models.Index(fields=['celery_task_id']),
        ]
        
        constraints = [
            models.CheckConstraint(
                check=models.Q(completed_items__lte=models.F('total_items')),
                name='vpm_parsing_task_completed_lte_total'
            ),
            models.CheckConstraint(
                check=models.Q(failed_items__lte=models.F('total_items')),
                name='vpm_parsing_task_failed_lte_total'
            ),
            models.UniqueConstraint(
                fields=['source', 'config_hash'],
                name='vpm_parsing_task_unique_config'
            ),
        ]
    
    def __str__(self):
        name = self.name or f"{self.get_source_display()} ({self.get_parsing_mode_display()})"
        return f"[{self.id}] {name} - {self.get_status_display()}"
    
    # ============================================================
    # PROPERTIES
    # ============================================================
    
    @property
    def progress_percent(self) -> float:
        """Прогресс выполнения в процентах"""
        if self.total_items == 0:
            return 0.0
        return round((self.completed_items / self.total_items) * 100, 2)
    
    @property
    def is_active(self) -> bool:
        """Проверка, активна ли задача"""
        return self.status in ['running', 'paused']
    
    @property
    def is_finished(self) -> bool:
        """Проверка, завершена ли задача"""
        return self.status in ['completed', 'stopped', 'failed']
    
    # ============================================================
    # STATE MACHINE МЕТОДЫ
    # ============================================================
    
    def start(self):
        """Запуск задачи (created → running)"""
        if self.status != 'created':
            raise ValueError(f"Cannot start task in status '{self.status}'. Expected 'created'.")
        
        self.status = 'running'
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'updated_at'])
    
    def pause(self):
        """Приостановка задачи (running → paused)"""
        if self.status != 'running':
            raise ValueError(f"Cannot pause task in status '{self.status}'. Expected 'running'.")
        
        self.status = 'paused'
        self.paused_at = timezone.now()
        self.save(update_fields=['status', 'paused_at', 'updated_at'])
    
    def resume(self):
        """Возобновление задачи (paused → running)"""
        if self.status != 'paused':
            raise ValueError(f"Cannot resume task in status '{self.status}'. Expected 'paused'.")
        
        self.status = 'running'
        self.save(update_fields=['status', 'updated_at'])
    
    def stop(self):
        """Остановка задачи (running/paused → stopped)"""
        if self.status not in ['running', 'paused']:
            raise ValueError(f"Cannot stop task in status '{self.status}'. Expected 'running' or 'paused'.")
        
        self.status = 'stopped'
        self.save(update_fields=['status', 'updated_at'])
    
    def complete(self):
        """Завершение задачи (running → completed)"""
        if self.status != 'running':
            raise ValueError(f"Cannot complete task in status '{self.status}'. Expected 'running'.")
        
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
    
    def fail(self, error_message: str):
        """Ошибка задачи (running → failed)"""
        if self.status != 'running':
            raise ValueError(f"Cannot fail task in status '{self.status}'. Expected 'running'.")
        
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def generate_config_hash(self) -> str:
        """Генерация хэша конфигурации для дедупликации"""
        return self.get_config_hash(self.source, self.parsing_mode, self.config)

    @staticmethod
    def get_config_hash(source: str, parsing_mode: str, config: dict) -> str:
        """Генерация хэша конфигурации без экземпляра (для проверки дубликатов)."""
        config_str = json.dumps(config, sort_keys=True)
        hash_input = f"{source}:{parsing_mode}:{config_str}"
        return hashlib.sha256(hash_input.encode()).hexdigest()
    
    def save(self, *args, **kwargs):
        """Переопределение save для генерации config_hash"""
        if not self.config_hash:
            self.config_hash = self.generate_config_hash()
        super().save(*args, **kwargs)
    
    def increment_completed(self):
        """Атомарное увеличение счетчика completed_items"""
        ParsingTask.objects.filter(id=self.id).update(
            completed_items=models.F('completed_items') + 1,
            updated_at=timezone.now()
        )
        self.refresh_from_db()
    
    def increment_failed(self):
        """Атомарное увеличение счетчика failed_items"""
        ParsingTask.objects.filter(id=self.id).update(
            failed_items=models.F('failed_items') + 1,
            updated_at=timezone.now()
        )
        self.refresh_from_db()


class TaskItem(models.Model):
    """
    Модель для атомарных единиц работы в задаче парсинга.
    
    Поддерживает:
    - Конкурентно-безопасное claiming через SELECT FOR UPDATE SKIP LOCKED
    - Lease механизм для crash recovery
    - Retry логику с типизацией ошибок
    - State machine (pending/in_progress/completed/failed/retrying/blocked)
    """
    
    # ============================================================
    # СВЯЗЬ С ЗАДАЧЕЙ
    # ============================================================
    
    task = models.ForeignKey(
        ParsingTask,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name="Задача парсинга"
    )
    
    # ============================================================
    # ИДЕНТИФИКАЦИЯ ЭЛЕМЕНТА
    # ============================================================
    
    source_item_id = models.CharField(
        max_length=100,
        verbose_name="ID элемента на источнике",
        help_text="Например, hh_id вакансии"
    )
    
    url = models.URLField(
        verbose_name="URL элемента"
    )
    
    url_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name="Хэш URL",
        help_text="SHA256 хэш для дедупликации"
    )
    
    # ============================================================
    # СОСТОЯНИЕ ЭЛЕМЕНТА (STATE MACHINE)
    # ============================================================
    
    STATUS_CHOICES = [
        ('pending', 'Ожидает обработки'),
        ('in_progress', 'Обрабатывается'),
        ('completed', 'Завершено'),
        ('failed', 'Ошибка'),
        ('retrying', 'Повторная попытка'),
        ('blocked', 'Заблокировано'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Статус",
        db_index=True
    )
    
    # ============================================================
    # ПРОГРЕСС И RETRY
    # ============================================================
    
    attempts_count = models.IntegerField(
        default=0,
        verbose_name="Количество попыток"
    )
    
    max_attempts = models.IntegerField(
        default=3,
        verbose_name="Максимум попыток"
    )
    
    last_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время последней попытки"
    )
    
    last_error = models.TextField(
        null=True,
        blank=True,
        verbose_name="Последняя ошибка"
    )
    
    ERROR_TYPE_CHOICES = [
        ('network', 'Сетевая ошибка'),
        ('blocked', 'Блокировка'),
        ('parsing', 'Ошибка парсинга'),
        ('validation', 'Ошибка валидации'),
        ('unknown', 'Неизвестная ошибка'),
    ]
    last_error_type = models.CharField(
        max_length=20,
        choices=ERROR_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Тип ошибки"
    )
    
    # ============================================================
    # LEASE МЕХАНИЗМ
    # ============================================================
    
    worker_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Worker ID",
        help_text="ID Celery worker'а, обрабатывающего элемент"
    )
    
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Время захвата"
    )
    
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Истечение lease",
        help_text="Для crash recovery"
    )
    
    # ============================================================
    # РЕЗУЛЬТАТ ОБРАБОТКИ
    # ============================================================
    
    result_vacancy_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="ID результата",
        help_text="FK к нормализованной Vacancy"
    )
    
    extracted_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Извлеченные данные",
        help_text="Сырые данные для отладки/reprocessing"
    )
    
    # ============================================================
    # МЕТАДАННЫЕ
    # ============================================================
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления"
    )
    
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата завершения"
    )
    
    class Meta:
        verbose_name = "Элемент задачи"
        verbose_name_plural = "Элементы задач"
        ordering = ['id']
        db_table = 'vpm_task_item'
        
        unique_together = [['task', 'source_item_id']]
        
        indexes = [
            # КРИТИЧЕСКИЙ индекс для claiming
            models.Index(fields=['task', 'status', 'lease_expires_at']),
            # Для crash recovery
            models.Index(fields=['status', 'lease_expires_at']),
            # Для поиска по worker
            models.Index(fields=['worker_id', 'status']),
            # Для дедупликации
            models.Index(fields=['url_hash']),
            # Для статистики
            models.Index(fields=['task', 'status', 'updated_at']),
            # Для быстрого поиска по task и source_item_id
            models.Index(fields=['task', 'source_item_id']),
        ]
    
    def __str__(self):
        return f"[{self.id}] Task {self.task_id} - {self.source_item_id} ({self.get_status_display()})"
    
    # ============================================================
    # CLAIMING И LEASE
    # ============================================================
    
    @classmethod
    def claim_items_for_worker(
        cls,
        task_id: int,
        worker_id: str,
        limit: int = 10,
        lease_minutes: int = 5
    ) -> List['TaskItem']:
        """
        Конкурентно-безопасное извлечение items для обработки.
        
        Использует SELECT ... FOR UPDATE SKIP LOCKED для предотвращения
        race conditions при параллельной обработке.
        
        Args:
            task_id: ID задачи
            worker_id: ID worker'а
            limit: Максимальное количество items
            lease_minutes: Длительность lease в минутах
        
        Returns:
            List[TaskItem]: Список claimed items
        """
        with transaction.atomic():
            # Безопасное извлечение pending items
            items = list(
                cls.objects
                .select_for_update(skip_locked=True)
                .filter(
                    task_id=task_id,
                    status='pending'
                )[:limit]
            )
            
            if not items:
                return []
            
            # Обновление состояния items
            now = timezone.now()
            lease_expires = now + timedelta(minutes=lease_minutes)
            
            item_ids = [item.id for item in items]
            
            cls.objects.filter(id__in=item_ids).update(
                status='in_progress',
                worker_id=worker_id,
                claimed_at=now,
                lease_expires_at=lease_expires,
                attempts_count=models.F('attempts_count') + 1,
                last_attempt_at=now,
                updated_at=now
            )
            
            # Перезагрузка с обновленными данными
            return list(cls.objects.filter(id__in=item_ids))
    
    @classmethod
    def release_expired_leases(cls) -> int:
        """
        Освобождение застрявших items (crash recovery).
        
        Периодическая задача (Celery Beat) вызывает каждые 5 минут.
        
        Returns:
            int: Количество освобожденных items
        """
        now = timezone.now()
        
        expired_items = cls.objects.filter(
            status='in_progress',
            lease_expires_at__lt=now
        )
        
        count = 0
        for item in expired_items:
            if item.attempts_count >= item.max_attempts:
                # Превышен лимит попыток
                item.status = 'failed'
                item.last_error = f"Превышено максимальное количество попыток ({item.max_attempts})"
                item.worker_id = None
                item.save(update_fields=['status', 'last_error', 'worker_id', 'updated_at'])
                item.task.increment_failed()
            else:
                # Вернуть в pending для повтора
                item.status = 'pending'
                item.worker_id = None
                item.save(update_fields=['status', 'worker_id', 'updated_at'])
            
            count += 1
        
        return count
    
    # ============================================================
    # STATE MACHINE МЕТОДЫ
    # ============================================================
    
    def mark_completed(
        self,
        result_vacancy_id: Optional[int] = None,
        extracted_data: Optional[dict] = None
    ):
        """Отметить элемент как завершенный"""
        self.status = 'completed'
        self.result_vacancy_id = result_vacancy_id
        
        # Конвертируем datetime объекты в строки для JSON
        if extracted_data:
            self.extracted_data = self._serialize_datetime_fields(extracted_data)
        else:
            self.extracted_data = extracted_data
        
        self.completed_at = timezone.now()
        self.save(update_fields=[
            'status', 'result_vacancy_id', 'extracted_data',
            'completed_at', 'updated_at'
        ])
    
    @staticmethod
    def _serialize_datetime_fields(data: dict) -> dict:
        """Конвертирует datetime объекты в ISO строки для JSON сериализации"""
        from datetime import datetime, date
        
        result = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, date):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = TaskItem._serialize_datetime_fields(value)
            elif isinstance(value, list):
                result[key] = [
                    TaskItem._serialize_datetime_fields(item) if isinstance(item, dict)
                    else item.isoformat() if isinstance(item, (datetime, date))
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result
    
    def mark_failed(self, error_message: str, error_type: str = 'unknown'):
        """Отметить элемент как ошибочный"""
        self.status = 'failed'
        self.last_error = error_message
        self.last_error_type = error_type
        self.save(update_fields=[
            'status', 'last_error', 'last_error_type', 'updated_at'
        ])
    
    def mark_blocked(self, reason: str):
        """Отметить элемент как заблокированный"""
        self.status = 'blocked'
        self.last_error = reason
        self.save(update_fields=['status', 'last_error', 'updated_at'])
    
    def should_retry(self) -> bool:
        """Проверить, нужно ли повторить попытку"""
        return (
            self.attempts_count < self.max_attempts and
            self.last_error_type in ['network', 'blocked']
        )
    
    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================
    
    def generate_url_hash(self) -> str:
        """Генерация хэша URL"""
        return hashlib.sha256(self.url.encode()).hexdigest()
    
    def save(self, *args, **kwargs):
        """Переопределение save для генерации url_hash"""
        if not self.url_hash:
            self.url_hash = self.generate_url_hash()
        super().save(*args, **kwargs)
