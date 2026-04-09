"""
Команда для проверки статуса вакансий и деактивации закрытых.
"""

import json
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, cast

from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.vacancies_parser.api.headhunter.models import Vacancy
from modules.vacancies_parser.api.headhunter.tasks import (
    check_vacancies_status_task,
    update_vacancy_details_task,
)

logger = logging.getLogger('modules.vacancies_parser.headhunter')
VacancyModel = cast(Any, Vacancy)

TEXT: Dict[str, str] = {
    'line_sep': '-' * 64,
    'header': 'Проверка статуса вакансий',
    'no_active': 'Нет активных вакансий для проверки.',
    'params_header': 'Параметры проверки:',
    'stats_header': 'Статистика вакансий:',
    'time_header': 'По времени обновления:',
    'started': 'Запуск проверки (ожидайте)...',
    'done': 'Проверка завершена.',
    'queued': 'Задача запущена в фоне.',
    'check_later': 'Проверьте статус задачи через Celery Flower или Django shell.',
    'single_check': 'Проверка вакансии:',
    'single_not_found': 'Вакансия {vacancy_id} не найдена в БД',
    'single_task_started': 'Задача обновления запущена.',
}


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
        parser.add_argument(
            '--json-output',
            action='store_true',
            help='Вывести результат в JSON (stdout)'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Минимальный текстовый вывод'
        )

    def handle(self, *args, **options):
        ctx = self._parse_options(options)
        self._print_header(ctx)

        # Статистика без проверки
        if ctx['show_stats']:
            self._show_statistics(ctx)
            return

        # Проверка одной вакансии
        if ctx['vacancy_id']:
            self._check_single_vacancy(ctx)
            return

        # Массовая проверка
        self._run_bulk_check(ctx)

    def _print_header(self, ctx: Dict[str, Any]):
        if ctx['json_output'] or ctx['quiet']:
            return
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(TEXT['header'])
        self.stdout.write(TEXT['line_sep'])

    def _parse_options(self, options) -> Dict[str, Any]:
        return {
            'batch_size': options.get('batch_size'),
            'delay': options.get('delay'),
            'max_vacancies': options.get('max'),
            'older_than_days': options.get('older_than'),
            'is_async': options.get('async'),
            'show_stats': options.get('stats'),
            'vacancy_id': options.get('vacancy_id'),
            'json_output': bool(options.get('json_output')),
            'quiet': bool(options.get('quiet')),
        }

    def _show_statistics(self, ctx: Dict[str, Any]):
        """Показать статистику по вакансиям"""
        total = VacancyModel.objects.count()
        active = VacancyModel.objects.filter(is_active=True).count()
        inactive = VacancyModel.objects.filter(is_active=False).count()
        
        # По возрасту
        now = timezone.now()
        last_day = VacancyModel.objects.filter(updated_at__gte=now - timedelta(days=1)).count()
        last_week = VacancyModel.objects.filter(updated_at__gte=now - timedelta(days=7)).count()
        last_month = VacancyModel.objects.filter(updated_at__gte=now - timedelta(days=30)).count()
        older = VacancyModel.objects.filter(updated_at__lt=now - timedelta(days=30)).count()
        
        if ctx['json_output']:
            payload = {
                'total': total,
                'active': active,
                'inactive': inactive,
                'last_day': last_day,
                'last_week': last_week,
                'last_month': last_month,
                'older': older,
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        quiet = ctx['quiet']
        if not quiet:
            self.stdout.write(TEXT['stats_header'])
        self.stdout.write(f'  Всего: {total}')
        self.stdout.write(f'  Активных: {active} ({active/total*100:.1f}%)' if total else '  Активных: 0')
        self.stdout.write(f'  Неактивных: {inactive} ({inactive/total*100:.1f}%)' if total else '  Неактивных: 0')
        if not quiet:
            self.stdout.write('')
            self.stdout.write(TEXT['time_header'])
        self.stdout.write(f'  За последние 24 часа: {last_day}')
        self.stdout.write(f'  За последнюю неделю: {last_week}')
        self.stdout.write(f'  За последний месяц: {last_month}')
        self.stdout.write(f'  Старше месяца: {older}')

    def _check_single_vacancy(self, ctx: Dict[str, Any]):
        """Проверить одну вакансию"""
        vacancy_id = ctx['vacancy_id']
        is_async = ctx['is_async']
        quiet = ctx['quiet']
        as_json = ctx['json_output']

        vacancy = VacancyModel.objects.filter(hh_id=vacancy_id).first()
        if not vacancy:
            msg = TEXT['single_not_found'].format(vacancy_id=vacancy_id)
            if as_json:
                self.stdout.write(json.dumps({'error': msg}, ensure_ascii=False))
            else:
                self.stdout.write(msg)
            return

        if as_json:
            self.stdout.write(json.dumps({
                'vacancy_id': vacancy_id,
                'title': vacancy.title,
                'company': vacancy.company_name,
                'status': 'active' if vacancy.is_active else 'inactive',
            }, ensure_ascii=False))
        elif not quiet:
            self.stdout.write(f'{TEXT["single_check"]} {vacancy_id}')
            self.stdout.write(f'  Название: {vacancy.title}')
            self.stdout.write(f'  Компания: {vacancy.company_name}')
            self.stdout.write(f'  Статус: {"Активна" if vacancy.is_active else "Неактивна"}')
            self.stdout.write('')
        
        if is_async:
            task = update_vacancy_details_task.delay(vacancy_id)  # type: ignore[call-arg]
            if as_json:
                self.stdout.write(json.dumps({'task_id': str(task.id), 'status': 'queued'}, ensure_ascii=False))
            elif quiet:
                self.stdout.write(f'Task ID: {task.id}')
            else:
                self.stdout.write(TEXT['single_task_started'])
                self.stdout.write(f'Task ID: {task.id}')
        else:
            result = update_vacancy_details_task(vacancy_id)
            if as_json:
                self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            elif quiet:
                self.stdout.write(result.get("status", ""))
            else:
                self.stdout.write(f'Результат: {result.get("status")}')
                self.stdout.write(f'Сообщение: {result.get("message")}')

    def _run_bulk_check(self, ctx: Dict[str, Any]):
        batch_size = ctx['batch_size']
        delay = ctx['delay']
        max_vacancies = ctx['max_vacancies']
        older_than_days = ctx['older_than_days']
        is_async = ctx['is_async']
        as_json = ctx['json_output']
        quiet = ctx['quiet']

        total_active = VacancyModel.objects.filter(is_active=True).count()
        total_inactive = VacancyModel.objects.filter(is_active=False).count()

        queryset = VacancyModel.objects.filter(is_active=True)
        if older_than_days:
            cutoff_date = timezone.now() - timedelta(days=older_than_days)
            queryset = queryset.filter(updated_at__lt=cutoff_date)
            to_check = queryset.count()
        else:
            to_check = total_active

        if total_active == 0:
            msg = TEXT['no_active']
            if as_json:
                self.stdout.write(json.dumps({'error': msg}, ensure_ascii=False))
            else:
                self.stdout.write(msg)
            return

        if as_json:
            self.stdout.write(json.dumps({
                'active': total_active,
                'inactive': total_inactive,
                'to_check': to_check,
                'batch_size': batch_size,
                'delay': delay,
                'max_vacancies': max_vacancies,
                'mode': 'async' if is_async else 'sync',
            }, ensure_ascii=False, indent=2))
        elif not quiet:
            self.stdout.write(f'Активных вакансий: {total_active}')
            self.stdout.write(f'Неактивных вакансий: {total_inactive}')
            if older_than_days:
                self.stdout.write(f'Фильтр: вакансии старше {older_than_days} дней')
                self.stdout.write(f'К проверке: {to_check}')
            self.stdout.write('')
            self.stdout.write(TEXT['params_header'])
            self.stdout.write(f'  - Размер пакета: {batch_size}')
            self.stdout.write(f'  - Задержка: {delay} сек')
            self.stdout.write(f'  - Максимум вакансий: {max_vacancies}')
            self.stdout.write(f'  - Режим: {"Асинхронный (Celery)" if is_async else "Синхронный"}')
            self.stdout.write('')

        try:
            if is_async:
                task = check_vacancies_status_task.delay(  # type: ignore[call-arg]
                    batch_size=batch_size,
                    delay=delay,
                    max_vacancies=max_vacancies
                )
                if as_json:
                    self.stdout.write(json.dumps({'task_id': str(task.id), 'status': 'queued'}, ensure_ascii=False))
                elif quiet:
                    self.stdout.write(f'Task ID: {task.id}')
                else:
                    self.stdout.write(TEXT['queued'])
                    self.stdout.write(f'Task ID: {task.id}')
            else:
                if not quiet:
                    self.stdout.write(TEXT['started'])
                    self.stdout.write('')
                result = check_vacancies_status_task(
                    batch_size=batch_size,
                    delay=delay,
                    max_vacancies=max_vacancies
                )
                if not quiet and not as_json:
                    self.stdout.write('')
                    self.stdout.write(TEXT['done'])
                self._print_result(result, ctx)
        except Exception as e:
            if as_json:
                self.stdout.write(json.dumps({'error': str(e)}, ensure_ascii=False))
            else:
                self.stdout.write(f'Ошибка при запуске: {e}')
            logger.exception('Ошибка при проверке статуса вакансий')

    def _print_result(self, result, ctx: Dict[str, Any]):
        """Вывод результатов проверки"""
        as_json = ctx['json_output']
        quiet = ctx['quiet']

        if as_json:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return

        self.stdout.write(f'Проверено вакансий: {result.get("checked", 0)}')
        self.stdout.write(f'Помечено как закрытые: {result.get("archived", 0)}')
        self.stdout.write(f'Всё ещё активны: {result.get("still_active", 0)}')
        self.stdout.write(f'Ошибок: {result.get("errors", 0)}')
        
        metrics = result.get('metrics', {})
        if metrics and not quiet:
            self.stdout.write('')
            self.stdout.write('Метрики:')
            self.stdout.write(f'  Время выполнения: {metrics.get("duration_seconds", 0):.1f} сек')
            self.stdout.write(f'  Запросов к API: {metrics.get("requests_total", 0)}')
            self.stdout.write(f'  Rate limits: {metrics.get("rate_limits_hit", 0)}')


