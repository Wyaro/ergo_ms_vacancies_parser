"""
Модели мониторинга выполнения задач vacancies_parser.

Хранят агрегированные метрики запусков задач Celery и события деградации внешних API.
Данные предназначены для просмотра через Django Admin и анализа инцидентов без внешнего стека.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class TaskRun(models.Model):
    """
    Одна запись на один запуск celery-задачи.

    Хранит агрегаты и итоговый статус. Связь с ParsingTask опциональна, т.к.
    многие celery-задачи не обязаны работать через ParsingTask.
    """

    STATUS_CHOICES = [
        ('running', 'Выполняется'),
        ('success', 'Успех'),
        ('failure', 'Ошибка'),
    ]

    # Идентификация
    celery_task_id = models.CharField(max_length=255, db_index=True, unique=True)
    task_name = models.CharField(max_length=255, db_index=True)
    source = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    parsing_task_id = models.IntegerField(blank=True, null=True, db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running', db_index=True)

    # Время
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True, db_index=True)
    duration_sec = models.FloatField(blank=True, null=True)

    # Ошибки
    error_type = models.CharField(max_length=100, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)

    # Агрегаты
    processed = models.IntegerField(default=0)
    saved = models.IntegerField(default=0)
    updated = models.IntegerField(default=0)
    errors = models.IntegerField(default=0)
    timeouts = models.IntegerField(default=0)
    http_429 = models.IntegerField(default=0)
    retries = models.IntegerField(default=0)

    # Для дедупликации/сравнения конфигурации (не обязательно хранить все kwargs)
    kwargs_digest = models.CharField(max_length=64, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        app_label = 'vacancies_parser'
        verbose_name = 'Запуск задачи (TaskRun)'
        verbose_name_plural = 'Запуски задач (TaskRun)'
        indexes = [
            models.Index(fields=['task_name', 'status', 'started_at']),
            models.Index(fields=['source', 'status', 'started_at']),
        ]

    def mark_finished(self, status: str):
        now = timezone.now()
        self.finished_at = now
        if self.started_at:
            self.duration_sec = (now - self.started_at).total_seconds()
        self.status = status

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.task_name} ({self.status}) {self.celery_task_id}"


class ExternalApiEvent(models.Model):
    """
    Агрегированное событие деградации внешнего API (timeouts/429 и т.п.).
    Используется для быстрых сводок без парсинга логов.
    """

    EVENT_CHOICES = [
        ('timeout', 'Timeout'),
        ('http_429', 'HTTP 429'),
        ('error', 'Error'),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    source = models.CharField(max_length=50, db_index=True)
    endpoint = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, db_index=True)
    count = models.IntegerField(default=1)

    celery_task_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)

    class Meta:
        app_label = 'vacancies_parser'
        verbose_name = 'Событие внешнего API'
        verbose_name_plural = 'События внешнего API'
        indexes = [
            models.Index(fields=['source', 'event_type', 'created_at']),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.source}:{self.event_type} x{self.count}"

