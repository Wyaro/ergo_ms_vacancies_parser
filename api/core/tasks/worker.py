"""
Утилиты для worker задач парсинга.

Используется для:
- Обработки отдельных TaskItems через scheduler
- Claiming items
- Парсинга и сохранения результатов
"""

import logging
from typing import List, Optional, Any

from django.db import models, transaction
from django.db.models.fields import NOT_PROVIDED
from django.utils import timezone

from .base import BaseParsingTaskMixin

logger = logging.getLogger('celery.module.vacancies_parser.tasks.worker')


def validate_worker_params(**kwargs) -> bool:
    """
    Валидация параметров worker задачи.
    
    Args:
        **kwargs: Параметры задачи
    
    Returns:
        bool: True если параметры валидны
    
    Raises:
        ValueError: При невалидных параметрах
    """
    if 'task_id' not in kwargs:
        raise ValueError("Отсутствует обязательный параметр: task_id")
    
    if 'worker_id' not in kwargs:
        raise ValueError("Отсутствует обязательный параметр: worker_id")
    
    return True


def claim_items_for_worker(task_id: int, worker_id: str, limit: int = 10) -> List:
    """
    Получение items для обработки через scheduler.
    
    Args:
        task_id: ID ParsingTask
        worker_id: ID worker'а
        limit: Максимальное количество items
    
    Returns:
        List: Список TaskItems для обработки
    """
    from ..scheduler import default_scheduler
    
    return default_scheduler.claim_items_for_worker(
        task_id=task_id,
        worker_id=worker_id,
        limit=limit
    )


_SOURCE_CONFIGS = {
    'headhunter': {
        'app_label': 'vacancies_parser_headhunter',
        'model_name': 'Vacancy',
        'id_field': 'hh_id',
        'field_remap': {
            'source_url': 'url',
            'area_name': 'city',
            'experience': 'experience_level',
            'schedule': 'schedule_type',
        },
    },
    'habr_career': {
        'app_label': 'vacancies_parser_habr_career',
        'model_name': 'Vacancy',
        'id_field': 'habr_id',
        'field_remap': {
            'source_url': 'url',
            'area_name': 'city',
            'key_skills': 'skills',
            'experience': 'experience_level',
            'schedule': 'schedule_type',
        },
    },
    'superjob': {
        'app_label': 'vacancies_parser_superjob',
        'model_name': 'SuperJobVacancy',
        'id_field': 'superjob_id',
        'field_remap': {
            'source_url': 'url',
            'area_name': 'city',
            'experience': 'experience_level',
            'schedule': 'schedule_type',
        },
    },
}

_SKIP_FIELDS = frozenset({
    'source', 'source_id', 'source_url', 'parsing_mode', 'archived',
})

_NORMALIZED_SKIP_FIELDS = frozenset({
    'id', 'created_at', 'updated_at', 'last_checked_at', 'version',
    'deduplication_hash', 'original_vacancy_id', 'deduplication_status',
})

_NORMALIZED_LIST_FIELDS = frozenset({
    'employment_type', 'schedule', 'key_skills', 'professional_roles',
})

_NORMALIZED_TRACKED_FIELDS = (
    'source_url',
    'parsing_mode',
    'title',
    'company_name',
    'company_url',
    'description',
    'salary_from',
    'salary_to',
    'salary_currency',
    'salary_gross',
    'area_name',
    'area_id',
    'address',
    'experience',
    'employment_type',
    'schedule',
    'key_skills',
    'professional_roles',
    'contacts',
    'is_active',
    'archived',
    'published_at',
    'has_test',
    'accepts_handicapped',
    'response_letter_required',
    'source_specific_data',
)


def _get_model_field_names(model) -> frozenset:
    return frozenset(f.name for f in model._meta.get_fields() if hasattr(f, 'column'))


def _ensure_not_null_defaults(mapped: dict, model) -> dict:
    """
    Гарантирует, что все NOT NULL поля модели имеют значения в mapped.

    Парсеры могут не возвращать часть полей (has_test, premium и т.д.)
    или возвращать None. Перед записью необходимо явно задать значения
    для всех NOT NULL полей, чтобы избежать IntegrityError.
    """
    for field in model._meta.concrete_fields:
        if field.primary_key:
            continue
        if getattr(field, 'auto_now', False) or getattr(field, 'auto_now_add', False):
            continue
        if field.null:
            continue

        name = field.name
        if name in mapped and mapped[name] is not None:
            continue

        if field.default is not NOT_PROVIDED:
            mapped[name] = field.default() if callable(field.default) else field.default
            continue

        if isinstance(field, models.BooleanField):
            mapped[name] = False
        elif isinstance(field, (models.CharField, models.TextField)):
            mapped[name] = ''
        elif isinstance(field, models.JSONField):
            mapped[name] = []
        elif isinstance(field, (models.IntegerField, models.SmallIntegerField,
                                models.BigIntegerField, models.FloatField,
                                models.DecimalField)):
            mapped[name] = 0
    return mapped


def _map_to_source_fields(vacancy_data: dict, source: str, model) -> dict:
    """Конвертирует выход парсера в поля модели источника."""
    from django.utils import timezone as tz

    config = _SOURCE_CONFIGS[source]
    remap = config.get('field_remap', {})
    valid_fields = _get_model_field_names(model)
    mapped = {}

    for key, value in vacancy_data.items():
        if key in _SKIP_FIELDS:
            continue
        target_key = remap.get(key, key)
        if target_key in valid_fields:
            mapped[target_key] = value

    mapped[config['id_field']] = vacancy_data.get('source_id', '')
    mapped.setdefault('url', vacancy_data.get('source_url', ''))

    mapped.setdefault('published_at', tz.now())
    mapped.setdefault('description', '')
    mapped.setdefault('company_name', '')
    mapped.setdefault('title', '')

    mapped = _ensure_not_null_defaults(mapped, model)
    return _truncate_char_fields(mapped, model)


def _truncate_char_fields(mapped: dict, model) -> dict:
    """
    Обрезает строковые значения по max_length соответствующего CharField.

    Парсеры могут возвращать строки длиннее, чем позволяет БД-столбец
    (например, город «Москва, Санкт-Петербург, Новосибирск и ...»).
    """
    for field in model._meta.concrete_fields:
        max_len = getattr(field, 'max_length', None)
        if max_len is None:
            continue
        name = field.name
        value = mapped.get(name)
        if isinstance(value, str) and len(value) > max_len:
            mapped[name] = value[:max_len]
    return mapped


def _normalize_list_field(value):
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else None
    return [str(value)]


def _map_to_normalized_fields(vacancy_data: dict, task, item, model) -> dict:
    valid_fields = _get_model_field_names(model)
    mapped = {}

    for key, value in vacancy_data.items():
        if key in _NORMALIZED_SKIP_FIELDS or key not in valid_fields:
            continue
        mapped[key] = value

    mapped['source'] = task.source
    raw_source_id = str(vacancy_data.get('source_id') or item.source_item_id or '')
    if not raw_source_id.strip():
        raw_source_id = f'item_{item.id}'
    mapped['source_id'] = raw_source_id
    mapped['source_url'] = vacancy_data.get('source_url') or item.url or ''
    mapped['parsing_mode'] = task.parsing_mode
    mapped['task_item'] = item
    mapped['title'] = str(mapped.get('title') or '')
    mapped['company_name'] = str(mapped.get('company_name') or '')
    mapped['description'] = str(mapped.get('description') or '')
    mapped['source_specific_data'] = mapped.get('source_specific_data') or {}

    contacts = mapped.get('contacts')
    mapped['contacts'] = contacts if isinstance(contacts, dict) else None

    for field_name in _NORMALIZED_LIST_FIELDS:
        mapped[field_name] = _normalize_list_field(mapped.get(field_name))

    mapped = _truncate_char_fields(mapped, model)
    return _ensure_not_null_defaults(mapped, model)


def _serialize_for_history(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def _collect_normalized_changes(vacancy, mapped: dict) -> dict:
    changes = {}
    for field_name in _NORMALIZED_TRACKED_FIELDS:
        if field_name not in mapped:
            continue
        old_value = getattr(vacancy, field_name, None)
        new_value = mapped[field_name]
        if old_value != new_value:
            changes[field_name] = {
                'old': _serialize_for_history(old_value),
                'new': _serialize_for_history(new_value),
            }
    return changes


def _save_normalized_vacancy(vacancy_data: dict, task, item):
    from ..normalized_models import NormalizedVacancy, VacancyChangeHistory

    NormalizedVacancyModel: Any = NormalizedVacancy
    VacancyChangeHistoryModel: Any = VacancyChangeHistory

    mapped = _map_to_normalized_fields(vacancy_data, task, item, NormalizedVacancy)

    lookup = {
        'source': mapped['source'],
        'source_id': mapped['source_id'],
    }

    with transaction.atomic():  # type: ignore[misc]
        normalized = (
            NormalizedVacancyModel.objects
            .select_for_update()
            .filter(**lookup)
            .first()
        )

        if normalized is None:
            # Новый экземпляр: создаем запись и инициализируем sources_meta автоматически
            normalized = NormalizedVacancyModel.upsert_from_normalized(mapped, task_item=item)
            return normalized, True, False

        changed_fields = _collect_normalized_changes(normalized, mapped)
        for field_name, value in mapped.items():
            setattr(normalized, field_name, value)

        normalized.last_checked_at = timezone.now()

        if changed_fields:
            normalized.version += 1
            normalized.deduplication_hash = normalized.generate_deduplication_hash()

        normalized.save()

        if changed_fields:
            VacancyChangeHistoryModel.objects.create(
                vacancy=normalized,
                version=normalized.version,
                task_item=item,
                changed_fields=changed_fields,
                parsing_mode=normalized.parsing_mode,
            )

        return normalized, False, bool(changed_fields)


def _get_source_model(source: str):
    from django.apps import apps
    config = _SOURCE_CONFIGS[source]
    return apps.get_model(config['app_label'], config['model_name'])


def process_item(item, parser, task, error_handler):
    """
    Обработка одного item.

    Сохраняет результат в таблицу конкретного источника
    (vpm_hh_vacancy / vpm_hc_vacancy / vpm_sj_vacancy)
    и параллельно обновляет агрегированную таблицу vpm_vacancy.
    """
    vacancy_data = parser.parse_item(item.source_item_id, item.url)

    source = task.source
    config = _SOURCE_CONFIGS.get(source)

    if not config:
        raise ValueError(f"Неизвестный источник: {source}")

    Model = _get_source_model(source)
    id_field = config['id_field']
    mapped = _map_to_source_fields(vacancy_data, source, Model)

    lookup_value = mapped.pop(id_field)
    vacancy, created = Model.objects.update_or_create(
        **{id_field: lookup_value},
        defaults=mapped,
    )

    normalized_vacancy, norm_created, norm_updated = _save_normalized_vacancy(
        vacancy_data=vacancy_data,
        task=task,
        item=item,
    )

    item.mark_completed(
        result_vacancy_id=normalized_vacancy.id,
        extracted_data=vacancy_data,
    )
    task.increment_completed()

    return {
        'success': True,
        'vacancy_id': vacancy.id,
        'created': created,
        'norm_created': norm_created,
        'norm_updated': norm_updated,
    }


def handle_item_error(item, exception, task, error_handler):
    """
    Обработка ошибки при обработке item.
    
    Args:
        item: TaskItem с ошибкой
        exception: Исключение
        task: ParsingTask
        error_handler: Обработчик ошибок
    """
    from ..parsers.base import BlockedError, NetworkError, ValidationError
    
    error_type = error_handler.classify_error(exception)
    
    # Обработка ошибок по типу
    if error_type.value == 'blocked' or isinstance(exception, BlockedError):
        item.mark_blocked(str(exception))
    elif error_type.value == 'network' or isinstance(exception, NetworkError):
        item.mark_failed(str(exception), 'network')
    elif error_type.value == 'validation' or isinstance(exception, ValidationError):
        item.mark_failed(str(exception), 'validation')
    else:
        item.mark_failed(str(exception), 'unknown')
    
    # Обновление счетчика failed
    task.increment_failed()
    
    # Логирование
    error_handler.handle_error(exception, {
        'task_id': task.id,
        'item_id': item.id,
        'source_item_id': item.source_item_id,
    })


class WorkerTaskMixin(BaseParsingTaskMixin):
    """
    Mixin для worker задач парсинга.
    
    Предоставляет общую логику для:
    - Claiming items через scheduler
    - Обработки items
    - Обработки ошибок items
    - Обновления прогресса задачи
    """
    
    def validate_params(self, **kwargs) -> bool:
        """Валидация параметров worker задачи"""
        return validate_worker_params(**kwargs)
    
    def claim_items(self, task_id: int, worker_id: str, limit: int = 10) -> List:
        """Получение items для обработки через scheduler"""
        return claim_items_for_worker(task_id, worker_id, limit)
    
    def process_item(self, item, parser, task):
        """Обработка одного item"""
        error_handler = self.get_error_handler()
        return process_item(item, parser, task, error_handler)
    
    def handle_item_error(self, item, exception, task):
        """Обработка ошибки при обработке item"""
        error_handler = self.get_error_handler()
        return handle_item_error(item, exception, task, error_handler)
