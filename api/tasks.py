"""
Точка входа для задач Celery модуля vacancies_parser.

Импортирует все задачи из core/celery_tasks.py для автоматического обнаружения Celery.
"""

# Импортируем все задачи из core/celery_tasks.py (файл), а не из пакета core/tasks/ (директория)
# Используем явный импорт через importlib для избежания конфликта с пакетом tasks/
import importlib.util
import os
import sys

# Путь к файлу core/celery_tasks.py
current_dir = os.path.dirname(os.path.abspath(__file__))
tasks_file_path = os.path.join(current_dir, 'core', 'celery_tasks.py')

# Загружаем модуль явно
spec = importlib.util.spec_from_file_location('modules.vacancies_parser.api.core.celery_tasks', tasks_file_path)
if spec is None:
    raise ImportError(f'Не удалось загрузить spec для {tasks_file_path}')
core_tasks_module = importlib.util.module_from_spec(spec)
sys.modules['modules.vacancies_parser.api.core.celery_tasks'] = core_tasks_module
if spec.loader is None:
    raise ImportError(f'Не удалось загрузить loader для {tasks_file_path}')
spec.loader.exec_module(core_tasks_module)

# Экспортируем все задачи для Celery autodiscover
create_parsing_task = core_tasks_module.create_parsing_task
coordinate_parsing_task = core_tasks_module.coordinate_parsing_task
finalize_parsing_task = core_tasks_module.finalize_parsing_task
parse_items_worker = core_tasks_module.parse_items_worker
release_expired_leases = core_tasks_module.release_expired_leases
monitor_tasks_progress = core_tasks_module.monitor_tasks_progress
cleanup_monitoring_retention = core_tasks_module.cleanup_monitoring_retention
pause_task = core_tasks_module.pause_task
resume_task = core_tasks_module.resume_task
stop_task = core_tasks_module.stop_task
discover_and_start_task = getattr(core_tasks_module, 'discover_and_start_task', None)

# Задачи нормализации
from .core.celery_tasks_normalization import (  # noqa: E402
    rebuild_normalized_vacancies_for_task,
    run_deduplication_task,
)

__all__ = [
    'create_parsing_task',
    'discover_and_start_task',
    'coordinate_parsing_task',
    'finalize_parsing_task',
    'parse_items_worker',
    'release_expired_leases',
    'monitor_tasks_progress',
    'cleanup_monitoring_retention',
    'pause_task',
    'resume_task',
    'stop_task',
    'rebuild_normalized_vacancies_for_task',
    'run_deduplication_task',
]
