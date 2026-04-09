"""
Миграция: создание системных задач парсинга для отображения в UI.

Создаёт 5 задач в статусе 'stopped', которые немедленно видны в интерфейсе.
При следующем срабатывании Celery Beat новые запуски (create_parsing_task)
создадут задачи с другим config_hash (отличным от stopped-записей) и
поставят их в работу.
"""
import hashlib
import json

from django.db import migrations


SYSTEM_TASKS = [
    {
        'source': 'headhunter',
        'parsing_mode': 'api',
        'name': 'HH: ежедневный парсинг IT-вакансий',
        'config': {'area': 113, 'pages': 20, 'per_page': 100, 'delay': 1.5},
    },
    {
        'source': 'headhunter',
        'parsing_mode': 'api',
        'name': 'HH: ежемесячный глубокий прогон',
        'config': {'area': 113, 'pages': 20, 'per_page': 100, 'delay': 1.5, 'text': 'программист'},
    },
    {
        'source': 'superjob',
        'parsing_mode': 'api',
        'name': 'SJ: ежедневный парсинг IT-каталога',
        'config': {'catalogues': '33', 'pages': 100, 'count': 100, 'delay': 1.0},
    },
    {
        'source': 'superjob',
        'parsing_mode': 'api',
        'name': 'SJ: ежемесячный глубокий прогон',
        'config': {'catalogues': '33', 'pages': 100, 'count': 100, 'delay': 1.2, 'keyword': 'IT'},
    },
    {
        'source': 'habr_career',
        'parsing_mode': 'html',
        'name': 'HC: ежедневный полный прогон',
        'config': {'max_pages': 15, 'delay': 1.5},
    },
]


def _config_hash(source: str, parsing_mode: str, config: dict) -> str:
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(f"{source}:{parsing_mode}:{config_str}".encode()).hexdigest()


def seed_system_tasks(apps, schema_editor):
    ParsingTask = apps.get_model('vacancies_parser', 'ParsingTask')

    for task_data in SYSTEM_TASKS:
        h = _config_hash(task_data['source'], task_data['parsing_mode'], task_data['config'])
        if ParsingTask.objects.filter(config_hash=h).exists():
            continue
        ParsingTask.objects.create(
            source=task_data['source'],
            parsing_mode=task_data['parsing_mode'],
            name=task_data['name'],
            config=task_data['config'],
            config_hash=h,
            status='stopped',
            total_items=0,
            completed_items=0,
            failed_items=0,
        )


def remove_system_tasks(apps, schema_editor):
    ParsingTask = apps.get_model('vacancies_parser', 'ParsingTask')
    hashes = [
        _config_hash(t['source'], t['parsing_mode'], t['config'])
        for t in SYSTEM_TASKS
    ]
    ParsingTask.objects.filter(config_hash__in=hashes, status='stopped').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('vacancies_parser', '0005_externalapievent_taskrun'),
    ]

    operations = [
        migrations.RunPython(seed_system_tasks, remove_system_tasks),
    ]
