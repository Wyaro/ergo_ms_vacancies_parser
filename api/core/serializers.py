"""
Serializers для API модуля vacancies_parser.

Содержит:
- ParsingTaskSerializer - для задач парсинга
- TaskItemSerializer - для элементов задач
- NormalizedVacancySerializer - для вакансий
- StatisticsSerializer - для статистики
"""

from rest_framework import serializers
from django.contrib.auth import get_user_model

from .models import ParsingTask, TaskItem
from .normalized_models import NormalizedVacancy, VacancyChangeHistory, ParsingStatistics
from .monitoring_models import TaskRun, ExternalApiEvent

User = get_user_model()


class ParsingTaskListSerializer(serializers.ModelSerializer):
    """Serializer для списка задач (сокращенная информация)"""
    
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    parsing_mode_display = serializers.CharField(source='get_parsing_mode_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    progress_percent = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_finished = serializers.BooleanField(read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    
    class Meta:
        model = ParsingTask
        fields = [
            'id',
            'source',
            'source_display',
            'parsing_mode',
            'parsing_mode_display',
            'name',
            'status',
            'status_display',
            'total_items',
            'completed_items',
            'failed_items',
            'progress_percent',
            'is_active',
            'is_finished',
            'created_at',
            'updated_at',
            'started_at',
            'completed_at',
            'error_message',
            'created_by_username',
        ]
        read_only_fields = [
            'id',
            'status',
            'total_items',
            'completed_items',
            'failed_items',
            'created_at',
            'updated_at',
            'started_at',
            'completed_at',
        ]


class ParsingTaskDetailSerializer(serializers.ModelSerializer):
    """Serializer для детальной информации о задаче"""
    
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    parsing_mode_display = serializers.CharField(source='get_parsing_mode_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    progress_percent = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    is_finished = serializers.BooleanField(read_only=True)
    
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    created_by_id = serializers.IntegerField(source='created_by.id', read_only=True, allow_null=True)
    
    # Статистика по items
    items_stats = serializers.SerializerMethodField()
    
    class Meta:
        model = ParsingTask
        fields = [
            'id',
            'source',
            'source_display',
            'parsing_mode',
            'parsing_mode_display',
            'name',
            'config',
            'config_hash',
            'status',
            'status_display',
            'total_items',
            'completed_items',
            'failed_items',
            'progress_percent',
            'is_active',
            'is_finished',
            'items_stats',
            'created_at',
            'updated_at',
            'started_at',
            'paused_at',
            'completed_at',
            'created_by_username',
            'created_by_id',
            'celery_task_id',
            'error_message',
            'result_data',
        ]
        read_only_fields = [
            'id',
            'config_hash',
            'status',
            'total_items',
            'completed_items',
            'failed_items',
            'created_at',
            'updated_at',
            'started_at',
            'paused_at',
            'completed_at',
            'celery_task_id',
            'error_message',
            'result_data',
        ]
    
    def get_items_stats(self, obj):
        """Статистика по статусам items"""
        from django.db.models import Count
        
        stats = TaskItem.objects.filter(task=obj).values('status').annotate(count=Count('id'))
        return {item['status']: item['count'] for item in stats}


class ParsingTaskCreateSerializer(serializers.Serializer):
    """Serializer для создания новой задачи парсинга"""
    
    source = serializers.ChoiceField(choices=ParsingTask.SOURCE_CHOICES)
    parsing_mode = serializers.ChoiceField(choices=ParsingTask.PARSING_MODE_CHOICES)
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    config = serializers.JSONField()
    
    def validate_config(self, value):
        """Валидация конфигурации парсинга"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Config должен быть объектом JSON")
        return value
    
    def create(self, validated_data):
        """Создание задачи через Celery"""
        from .celery_tasks import create_parsing_task
        from .utils.task_runner import safe_task_run
        from .utils.celery_broker import BrokerUnavailableError
        
        # Получение текущего пользователя из контекста
        request = self.context.get('request')
        created_by_id = request.user.id if request and request.user.is_authenticated else None
        
        # Параметры для задачи
        task_kwargs = {
            'source': validated_data['source'],
            'parsing_mode': validated_data['parsing_mode'],
            'config': validated_data['config'],
            'name': validated_data.get('name', ''),
            'created_by_id': created_by_id,
        }
        
        try:
            # Запуск Celery задачи создания с обработкой ошибок брокера
            task_result = safe_task_run(
                create_parsing_task.apply_async,
                {'kwargs': task_kwargs},
                prefer_async=True,
                fallback_to_sync=False
            )
            
            # Возвращаем task_id для отслеживания
            return {
                'celery_task_id': task_result.id,
                **validated_data
            }
        except BrokerUnavailableError as e:
            raise serializers.ValidationError({
                'broker': [
                    f'Celery брокер недоступен: {str(e)}. '
                    'Запустите Celery worker: ergoms start-worker'
                ]
            })


class TaskItemSerializer(serializers.ModelSerializer):
    """Serializer для TaskItem"""
    
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    error_type_display = serializers.CharField(source='get_last_error_type_display', read_only=True, allow_null=True)
    
    class Meta:
        model = TaskItem
        fields = [
            'id',
            'task',
            'source_item_id',
            'url',
            'status',
            'status_display',
            'attempts_count',
            'max_attempts',
            'last_attempt_at',
            'last_error',
            'last_error_type',
            'error_type_display',
            'worker_id',
            'claimed_at',
            'lease_expires_at',
            'result_vacancy_id',
            'created_at',
            'updated_at',
            'completed_at',
        ]
        read_only_fields = [
            'id',
            'task',
            'source_item_id',
            'url',
            'status',
            'attempts_count',
            'last_attempt_at',
            'last_error',
            'last_error_type',
            'worker_id',
            'claimed_at',
            'lease_expires_at',
            'result_vacancy_id',
            'created_at',
            'updated_at',
            'completed_at',
        ]


class NormalizedVacancyListSerializer(serializers.ModelSerializer):
    """Serializer для списка вакансий (сокращенная информация)"""
    
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    parsing_mode_display = serializers.CharField(source='get_parsing_mode_display', read_only=True)
    salary_display = serializers.CharField(source='get_salary_display', read_only=True)
    sources_meta = serializers.JSONField(read_only=True)
    sources = serializers.SerializerMethodField()
    sources_count = serializers.SerializerMethodField()
    
    class Meta:
        model = NormalizedVacancy
        fields = [
            'id',
            'source',
            'source_display',
            'source_id',
            'source_url',
            'sources_meta',
            'sources',
            'sources_count',
            'parsing_mode',
            'parsing_mode_display',
            'title',
            'company_name',
            'area_name',
            'salary_display',
            'experience',
            'is_active',
            'archived',
            'published_at',
            'created_at',
            'updated_at',
        ]

    def get_sources(self, obj):
        meta = obj.sources_meta or []
        sources = []
        for item in meta:
            if not isinstance(item, dict):
                continue
            src = item.get('source')
            if src and src not in sources:
                sources.append(src)
        return sources

    def get_sources_count(self, obj):
        return len(self.get_sources(obj))


class NormalizedVacancyDetailSerializer(serializers.ModelSerializer):
    """Serializer для детальной информации о вакансии"""
    
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    parsing_mode_display = serializers.CharField(source='get_parsing_mode_display', read_only=True)
    salary_display = serializers.CharField(source='get_salary_display', read_only=True)
    
    class Meta:
        model = NormalizedVacancy
        fields = '__all__'


class VacancyChangeHistorySerializer(serializers.ModelSerializer):
    """Serializer для истории изменений вакансии"""
    
    parsing_mode_display = serializers.CharField(source='get_parsing_mode_display', read_only=True)
    
    class Meta:
        model = VacancyChangeHistory
        fields = [
            'id',
            'vacancy',
            'version',
            'task_item',
            'changed_fields',
            'changed_at',
            'parsing_mode',
            'parsing_mode_display',
        ]


class ParsingStatisticsSerializer(serializers.ModelSerializer):
    """Serializer для статистики парсинга"""
    
    task_name = serializers.CharField(source='task.name', read_only=True)
    task_source = serializers.CharField(source='task.source', read_only=True)
    task_parsing_mode = serializers.CharField(source='task.parsing_mode', read_only=True)
    
    # Рассчитываемые поля
    success_rate = serializers.SerializerMethodField()
    error_rate = serializers.SerializerMethodField()
    
    class Meta:
        model = ParsingStatistics
        fields = [
            'id',
            'task',
            'task_name',
            'task_source',
            'task_parsing_mode',
            'started_at',
            'finished_at',
            'duration_seconds',
            'total_processed',
            'successful_items',
            'failed_items',
            'blocked_items',
            'avg_item_duration_ms',
            'items_per_second',
            'complete_records',
            'incomplete_records',
            'error_breakdown',
            'success_rate',
            'error_rate',
            'created_at',
        ]
    
    def get_success_rate(self, obj):
        """Процент успешных items"""
        if obj.total_processed == 0:
            return 0.0
        return round((obj.successful_items / obj.total_processed) * 100, 2)
    
    def get_error_rate(self, obj):
        """Процент ошибочных items"""
        if obj.total_processed == 0:
            return 0.0
        return round((obj.failed_items / obj.total_processed) * 100, 2)


class TaskRunListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = TaskRun
        fields = [
            'id',
            'celery_task_id',
            'task_name',
            'source',
            'parsing_task_id',
            'status',
            'status_display',
            'started_at',
            'finished_at',
            'duration_sec',
            'processed',
            'saved',
            'updated',
            'errors',
            'timeouts',
            'http_429',
            'retries',
            'error_type',
            'error_message',
            'updated_at',
        ]


class ExternalApiEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalApiEvent
        fields = [
            'id',
            'created_at',
            'source',
            'endpoint',
            'event_type',
            'count',
            'celery_task_id',
        ]


class TaskProgressSerializer(serializers.Serializer):
    """Serializer для прогресса выполнения задачи"""
    
    total = serializers.IntegerField()
    pending = serializers.IntegerField()
    in_progress = serializers.IntegerField()
    completed = serializers.IntegerField()
    failed = serializers.IntegerField()
    retrying = serializers.IntegerField()
    blocked = serializers.IntegerField()
    progress_percent = serializers.FloatField()
    task_status = serializers.CharField()


class TaskControlSerializer(serializers.Serializer):
    """Serializer для управления задачей (pause/resume/stop)"""
    
    action = serializers.ChoiceField(choices=['pause', 'resume', 'stop'])
    
    def validate_action(self, value):
        """Валидация действия"""
        task_id = self.context.get('task_id')
        if not task_id:
            raise serializers.ValidationError("Task ID не указан")
        
        try:
            task = ParsingTask.objects.get(id=task_id)
        except ParsingTask.DoesNotExist:
            raise serializers.ValidationError(f"Задача {task_id} не найдена")
        
        # Проверка допустимости действия
        if value == 'pause' and task.status != 'running':
            raise serializers.ValidationError("Можно приостановить только running задачу")
        
        if value == 'resume' and task.status != 'paused':
            raise serializers.ValidationError("Можно возобновить только paused задачу")
        
        if value == 'stop' and task.status not in ['running', 'paused']:
            raise serializers.ValidationError("Можно остановить только running или paused задачу")
        
        return value
