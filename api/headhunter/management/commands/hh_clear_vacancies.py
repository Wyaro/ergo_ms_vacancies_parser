"""
Команда для очистки таблицы вакансий HeadHunter.

Позволяет очистить все вакансии или выборочно по фильтрам.
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from modules.vacancies_parser.api.headhunter.models import (
    Vacancy,
    VacancyVersion,
    VacancyChangeHistory
)

logger = logging.getLogger('modules.vacancies_parser.headhunter')


class Command(BaseCommand):
    help = 'Очистка таблицы вакансий HeadHunter'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Удалить ВСЕ вакансии (требует подтверждения)'
        )
        parser.add_argument(
            '--older-than',
            type=int,
            metavar='DAYS',
            help='Удалить вакансии старше указанного количества дней'
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Удалить вакансии только из указанного города'
        )
        parser.add_argument(
            '--company',
            type=str,
            help='Удалить вакансии только указанной компании'
        )
        parser.add_argument(
            '--inactive',
            action='store_true',
            help='Удалить только неактивные вакансии (is_active=False)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Выполнить без подтверждения (опасно!)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Показать что будет удалено, но не удалять'
        )

    def handle(self, *args, **options):
        delete_all = options.get('all')
        older_than_days = options.get('older_than')
        city = options.get('city')
        company = options.get('company')
        inactive_only = options.get('inactive')
        force = options.get('force')
        dry_run = options.get('dry_run')

        self.stdout.write('=== ОЧИСТКА ТАБЛИЦЫ ВАКАНСИЙ ===')
        self.stdout.write('')

        # Проверяем что указан хотя бы один фильтр
        if not any([delete_all, older_than_days, city, company, inactive_only]):
            self.stdout.write(self.style.ERROR(
                'Необходимо указать хотя бы один параметр фильтрации:'
            ))
            self.stdout.write('  --all            Удалить все вакансии')
            self.stdout.write('  --older-than N   Удалить вакансии старше N дней')
            self.stdout.write('  --city "Город"   Удалить вакансии из города')
            self.stdout.write('  --company "Имя"  Удалить вакансии компании')
            self.stdout.write('  --inactive       Удалить неактивные вакансии')
            self.stdout.write('')
            self.stdout.write('Дополнительные опции:')
            self.stdout.write('  --force          Без подтверждения')
            self.stdout.write('  --dry-run        Только показать (не удалять)')
            return

        # Формируем queryset
        queryset = Vacancy.objects.all()
        filters_applied = []

        if not delete_all:
            if older_than_days:
                cutoff_date = timezone.now() - timedelta(days=older_than_days)
                queryset = queryset.filter(published_at__lt=cutoff_date)
                filters_applied.append(f'старше {older_than_days} дней')

            if city:
                queryset = queryset.filter(city__icontains=city)
                filters_applied.append(f'город: {city}')

            if company:
                queryset = queryset.filter(company_name__icontains=company)
                filters_applied.append(f'компания: {company}')

            if inactive_only:
                queryset = queryset.filter(is_active=False)
                filters_applied.append('только неактивные')
        else:
            filters_applied.append('ВСЕ ВАКАНСИИ')

        # Получаем статистику
        vacancy_count = queryset.count()
        
        # Подсчитываем связанные записи
        vacancy_ids = list(queryset.values_list('id', flat=True))
        version_count = VacancyVersion.objects.filter(vacancy_id__in=vacancy_ids).count()
        history_count = VacancyChangeHistory.objects.filter(vacancy_id__in=vacancy_ids).count()

        # Выводим информацию
        self.stdout.write('Применённые фильтры:')
        for f in filters_applied:
            self.stdout.write(f'  - {f}')
        self.stdout.write('')

        self.stdout.write('Будет удалено:')
        self.stdout.write(f'  - Вакансий: {vacancy_count}')
        self.stdout.write(f'  - Версий вакансий: {version_count}')
        self.stdout.write(f'  - Записей истории изменений: {history_count}')
        self.stdout.write('')

        if vacancy_count == 0:
            self.stdout.write(self.style.WARNING('Нет вакансий для удаления.'))
            return

        # Dry run - только показываем
        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] Удаление не выполнено.'))
            
            # Показываем примеры вакансий
            sample_vacancies = queryset[:10]
            if sample_vacancies:
                self.stdout.write('')
                self.stdout.write('Примеры вакансий для удаления:')
                for v in sample_vacancies:
                    self.stdout.write(f'  - [{v.hh_id}] {v.title} ({v.company_name}, {v.city})')
                if vacancy_count > 10:
                    self.stdout.write(f'  ... и ещё {vacancy_count - 10} вакансий')
            return

        # Запрашиваем подтверждение
        if not force:
            if delete_all:
                self.stdout.write(self.style.WARNING(
                    'ВНИМАНИЕ! Вы собираетесь удалить ВСЕ вакансии!'
                ))
            
            confirm = input(f'Удалить {vacancy_count} вакансий? (yes/no): ')
            if confirm.lower() not in ['yes', 'y', 'да']:
                self.stdout.write(self.style.WARNING('Операция отменена.'))
                return

        # Выполняем удаление
        try:
            with transaction.atomic():
                self.stdout.write('Удаление...')
                
                # Удаляем вакансии (связанные записи удалятся автоматически через CASCADE)
                deleted_count, deleted_details = queryset.delete()
                
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('=== УДАЛЕНИЕ ЗАВЕРШЕНО ==='))
                self.stdout.write(f'Всего удалено объектов: {deleted_count}')
                
                if deleted_details:
                    self.stdout.write('Детализация:')
                    for model, count in deleted_details.items():
                        self.stdout.write(f'  - {model}: {count}')
                
                # Выводим текущее состояние
                self.stdout.write('')
                self.stdout.write('Текущее состояние базы:')
                self.stdout.write(f'  - Вакансий: {Vacancy.objects.count()}')
                self.stdout.write(f'  - Версий: {VacancyVersion.objects.count()}')
                self.stdout.write(f'  - Записей истории: {VacancyChangeHistory.objects.count()}')
                
                logger.info(
                    'Очистка вакансий выполнена: удалено %d вакансий, фильтры: %s',
                    deleted_count,
                    ', '.join(filters_applied)
                )
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка при удалении: {e}'))
            logger.exception('Ошибка при очистке вакансий')

