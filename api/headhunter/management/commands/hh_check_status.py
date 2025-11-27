"""
Команда для проверки статуса вакансий и деактивации закрытых.

Позволяет найти и пометить как неактивные вакансии,
которые были закрыты или удалены на hh.ru.
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from modules.vacancies_parser.api.headhunter.tasks import (
    check_vacancies_status_task,
    update_vacancy_details_task
)
from modules.vacancies_parser.api.headhunter.models import Vacancy

logger = logging.getLogger('modules.vacancies_parser.headhunter')


class Command(BaseCommand):
    help = 'Проверка статуса вакансий и деактивация закрытых'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Размер пакета для обработки (по умолчанию: 100)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.2,
            help='Задержка между запросами в секундах (по умолчанию: 0.2)'
        )
        parser.add_argument(
            '--max',
            type=int,
            default=1000,
            help='Максимальное количество вакансий для проверки (по умолчанию: 1000)'
        )
        parser.add_argument(
            '--older-than',
            type=int,
            metavar='DAYS',
            help='Проверять только вакансии старше указанного количества дней'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Запустить асинхронно через Celery'
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Показать только статистику без проверки'
        )
        parser.add_argument(
            '--vacancy-id',
            type=str,
            help='Проверить конкретную вакансию по hh_id'
        )

    def handle(self, *args, **options):
        batch_size = options.get('batch_size')
        delay = options.get('delay')
        max_vacancies = options.get('max')
        older_than_days = options.get('older_than')
        is_async = options.get('async')
        show_stats = options.get('stats')
        vacancy_id = options.get('vacancy_id')

        self.stdout.write('=== ПРОВЕРКА СТАТУСА ВАКАНСИЙ ===')
        self.stdout.write('')

        # Показать статистику
        if show_stats:
            self._show_statistics()
            return

        # Проверить конкретную вакансию
        if vacancy_id:
            self._check_single_vacancy(vacancy_id, is_async)
            return

        # Статистика перед проверкой
        total_active = Vacancy.objects.filter(is_active=True).count()
        total_inactive = Vacancy.objects.filter(is_active=False).count()
        
        self.stdout.write(f'Текущее состояние:')
        self.stdout.write(f'  - Активных вакансий: {total_active}')
        self.stdout.write(f'  - Неактивных вакансий: {total_inactive}')
        self.stdout.write('')

        if total_active == 0:
            self.stdout.write(self.style.WARNING('Нет активных вакансий для проверки.'))
            return

        # Фильтр по возрасту
        queryset = Vacancy.objects.filter(is_active=True)
        if older_than_days:
            cutoff_date = timezone.now() - timedelta(days=older_than_days)
            queryset = queryset.filter(updated_at__lt=cutoff_date)
            self.stdout.write(f'Фильтр: вакансии старше {older_than_days} дней')
            self.stdout.write(f'К проверке: {queryset.count()} вакансий')
            self.stdout.write('')

        # Параметры
        self.stdout.write('Параметры проверки:')
        self.stdout.write(f'  - Размер пакета: {batch_size}')
        self.stdout.write(f'  - Задержка: {delay} сек')
        self.stdout.write(f'  - Максимум вакансий: {max_vacancies}')
        self.stdout.write(f'  - Режим: {"Асинхронный (Celery)" if is_async else "Синхронный"}')
        self.stdout.write('')

        # Запуск
        try:
            if is_async:
                task = check_vacancies_status_task.delay(
                    batch_size=batch_size,
                    delay=delay,
                    max_vacancies=max_vacancies
                )
                self.stdout.write(self.style.SUCCESS('Задача запущена в фоне!'))
                self.stdout.write(f'Task ID: {task.id}')
            else:
                self.stdout.write('Запуск проверки (ожидайте)...')
                self.stdout.write('')
                
                result = check_vacancies_status_task(
                    batch_size=batch_size,
                    delay=delay,
                    max_vacancies=max_vacancies
                )
                
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS('=== ПРОВЕРКА ЗАВЕРШЕНА ==='))
                self._print_result(result)
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка при запуске: {e}'))
            logger.exception('Ошибка при проверке статуса вакансий')

    def _show_statistics(self):
        """Показать статистику по вакансиям"""
        total = Vacancy.objects.count()
        active = Vacancy.objects.filter(is_active=True).count()
        inactive = Vacancy.objects.filter(is_active=False).count()
        
        # По возрасту
        now = timezone.now()
        last_day = Vacancy.objects.filter(updated_at__gte=now - timedelta(days=1)).count()
        last_week = Vacancy.objects.filter(updated_at__gte=now - timedelta(days=7)).count()
        last_month = Vacancy.objects.filter(updated_at__gte=now - timedelta(days=30)).count()
        older = Vacancy.objects.filter(updated_at__lt=now - timedelta(days=30)).count()
        
        self.stdout.write('Статистика вакансий:')
        self.stdout.write(f'  Всего: {total}')
        self.stdout.write(f'  Активных: {active} ({active/total*100:.1f}%)' if total else '  Активных: 0')
        self.stdout.write(f'  Неактивных: {inactive} ({inactive/total*100:.1f}%)' if total else '  Неактивных: 0')
        self.stdout.write('')
        self.stdout.write('По времени обновления:')
        self.stdout.write(f'  За последние 24 часа: {last_day}')
        self.stdout.write(f'  За последнюю неделю: {last_week}')
        self.stdout.write(f'  За последний месяц: {last_month}')
        self.stdout.write(f'  Старше месяца: {older}')

    def _check_single_vacancy(self, vacancy_id, is_async):
        """Проверить одну вакансию"""
        self.stdout.write(f'Проверка вакансии: {vacancy_id}')
        
        vacancy = Vacancy.objects.filter(hh_id=vacancy_id).first()
        if not vacancy:
            self.stdout.write(self.style.ERROR(f'Вакансия {vacancy_id} не найдена в БД'))
            return
        
        self.stdout.write(f'  Название: {vacancy.title}')
        self.stdout.write(f'  Компания: {vacancy.company_name}')
        self.stdout.write(f'  Статус: {"Активна" if vacancy.is_active else "Неактивна"}')
        self.stdout.write('')
        
        if is_async:
            task = update_vacancy_details_task.delay(vacancy_id)
            self.stdout.write(self.style.SUCCESS('Задача обновления запущена!'))
            self.stdout.write(f'Task ID: {task.id}')
        else:
            result = update_vacancy_details_task(vacancy_id)
            self.stdout.write(f'Результат: {result.get("status")}')
            self.stdout.write(f'Сообщение: {result.get("message")}')

    def _print_result(self, result):
        """Вывод результатов проверки"""
        self.stdout.write(f'Проверено вакансий: {result.get("checked", 0)}')
        self.stdout.write(f'Помечено как закрытые: {result.get("archived", 0)}')
        self.stdout.write(f'Всё ещё активны: {result.get("still_active", 0)}')
        self.stdout.write(f'Ошибок: {result.get("errors", 0)}')
        
        metrics = result.get('metrics', {})
        if metrics:
            self.stdout.write('')
            self.stdout.write('Метрики:')
            self.stdout.write(f'  Время выполнения: {metrics.get("duration_seconds", 0):.1f} сек')
            self.stdout.write(f'  Запросов к API: {metrics.get("requests_total", 0)}')
            self.stdout.write(f'  Rate limits: {metrics.get("rate_limits_hit", 0)}')

