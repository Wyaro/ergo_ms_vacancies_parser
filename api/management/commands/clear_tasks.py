"""
Django команда для удаления задач парсинга.

Примеры использования:
    # Удалить все задачи
    ergoms api clear_tasks --all

    # Удалить задачи по статусу
    ergoms api clear_tasks --status=failed
    ergoms api clear_tasks --status=created
    
    # Удалить конкретную задачу
    ergoms api clear_tasks --id=4
    
    # Удалить задачи старше N дней
    ergoms api clear_tasks --days=30
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from modules.vacancies_parser.api.core.models import ParsingTask, TaskItem
from modules.vacancies_parser.api.core.normalized_models import NormalizedVacancy

logger = logging.getLogger('celery.module.vacancies_parser')


class Command(BaseCommand):
    help = 'Удаляет задачи парсинга'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Удалить ВСЕ задачи (требует подтверждения)'
        )
        parser.add_argument(
            '--status',
            type=str,
            choices=['created', 'running', 'paused', 'stopped', 'completed', 'failed'],
            help='Удалить задачи с определенным статусом'
        )
        parser.add_argument(
            '--id',
            type=int,
            help='Удалить задачу с конкретным ID'
        )
        parser.add_argument(
            '--days',
            type=int,
            help='Удалить задачи старше N дней'
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Не спрашивать подтверждение'
        )

    def handle(self, *args, **options):
        # Определяем что удалять
        queryset = ParsingTask.objects.all()
        
        if options['id']:
            queryset = queryset.filter(id=options['id'])
            description = f"задачу #{options['id']}"
        elif options['status']:
            queryset = queryset.filter(status=options['status'])
            description = f"задачи со статусом '{options['status']}'"
        elif options['days']:
            cutoff_date = timezone.now() - timedelta(days=options['days'])
            queryset = queryset.filter(created_at__lt=cutoff_date)
            description = f"задачи старше {options['days']} дней"
        elif options['all']:
            description = "ВСЕ задачи"
        else:
            self.stdout.write(self.style.ERROR(
                'Необходимо указать один из параметров: --all, --status, --id, --days'
            ))
            return

        # Подсчитываем что будет удалено
        tasks_count = queryset.count()
        items_count = TaskItem.objects.filter(task__in=queryset).count()
        
        if tasks_count == 0:
            self.stdout.write(self.style.WARNING('Нет задач для удаления'))
            return

        # Показываем что будет удалено
        self.stdout.write(self.style.WARNING(f'\n🗑️  Будет удалено:'))
        self.stdout.write(f'  • Задач: {tasks_count}')
        self.stdout.write(f'  • Элементов задач: {items_count}')
        self.stdout.write(f'\n📋 Описание: {description}\n')

        # Показываем список задач
        if tasks_count <= 10:
            self.stdout.write('Задачи для удаления:')
            for task in queryset:
                self.stdout.write(f'  #{task.id} - {task.name} ({task.status})')
        
        # Запрашиваем подтверждение
        if not options['yes']:
            confirm = input('\n❓ Продолжить? [y/N]: ')
            if confirm.lower() != 'y':
                self.stdout.write(self.style.WARNING('Отменено'))
                return

        # Удаляем
        try:
            deleted_count, deleted_details = queryset.delete()
            
            self.stdout.write(self.style.SUCCESS(f'\n✅ Удалено:'))
            self.stdout.write(f'  • Задач: {deleted_details.get("vacancies_parser.ParsingTask", 0)}')
            self.stdout.write(f'  • Элементов: {deleted_details.get("vacancies_parser.TaskItem", 0)}')
            
            # Показываем статистику
            remaining_tasks = ParsingTask.objects.count()
            remaining_items = TaskItem.objects.count()
            self.stdout.write(f'\n📊 Осталось:')
            self.stdout.write(f'  • Задач: {remaining_tasks}')
            self.stdout.write(f'  • Элементов: {remaining_items}')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Ошибка при удалении: {e}'))
            logger.error(f'Ошибка удаления задач: {e}', exc_info=True)
