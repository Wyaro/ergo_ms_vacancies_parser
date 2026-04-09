from django.contrib import admin

from .core.models import ParsingTask, TaskItem
from .core.monitoring_models import TaskRun, ExternalApiEvent
from .core.normalized_models import NormalizedVacancy, VacancyChangeHistory, ParsingStatistics


@admin.register(ParsingTask)
class ParsingTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'source', 'parsing_mode', 'status', 'total_items', 'completed_items', 'failed_items', 'updated_at')
    list_filter = ('source', 'parsing_mode', 'status')
    search_fields = ('id', 'name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TaskItem)
class TaskItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'task_id', 'status', 'attempts_count', 'max_attempts', 'worker_id', 'lease_expires_at', 'updated_at')
    list_filter = ('status',)
    search_fields = ('id', 'task_id', 'worker_id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(NormalizedVacancy)
class NormalizedVacancyAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'source', 'title', 'company_name', 'area_name',
        'salary_display', 'experience', 'is_active', 'archived',
        'deduplication_status', 'published_at', 'created_at',
    )
    list_filter = (
        'source', 'parsing_mode', 'is_active', 'archived',
        'deduplication_status', 'experience',
    )
    search_fields = ('title', 'company_name', 'area_name', 'source_id')
    readonly_fields = (
        'created_at', 'updated_at', 'last_checked_at',
        'version', 'deduplication_hash',
    )
    date_hierarchy = 'published_at'

    @admin.display(description='Зарплата')
    def salary_display(self, obj):
        return obj.get_salary_display()


@admin.register(VacancyChangeHistory)
class VacancyChangeHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'vacancy_id', 'version', 'parsing_mode', 'changed_fields_count', 'changed_at')
    list_filter = ('parsing_mode',)
    search_fields = ('vacancy__title', 'vacancy__company_name')
    readonly_fields = ('changed_at',)

    @admin.display(description='Полей изменено')
    def changed_fields_count(self, obj):
        return len(obj.changed_fields) if isinstance(obj.changed_fields, dict) else 0


@admin.register(ParsingStatistics)
class ParsingStatisticsAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'task_id', 'total_processed', 'successful_items',
        'failed_items', 'blocked_items', 'complete_records',
        'incomplete_records', 'duration_seconds', 'items_per_second',
        'created_at',
    )
    list_filter = ('created_at',)
    search_fields = ('task__name',)
    readonly_fields = ('created_at',)


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = (
        'started_at', 'source', 'task_name', 'status',
        'duration_sec', 'processed', 'saved', 'updated',
        'errors', 'timeouts', 'http_429', 'retries',
    )
    list_filter = ('source', 'status', 'task_name')
    search_fields = ('celery_task_id', 'task_name', 'parsing_task_id', 'error_type')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ExternalApiEvent)
class ExternalApiEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'source', 'event_type', 'endpoint', 'count', 'celery_task_id')
    list_filter = ('source', 'event_type')
    search_fields = ('endpoint', 'celery_task_id')
    readonly_fields = ('created_at',)
