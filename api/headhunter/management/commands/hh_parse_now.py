"""
Команда для немедленного запуска парсинга вне очереди.
"""

import json
import logging
from typing import Any, Dict

from django.core.management.base import BaseCommand, CommandError

from modules.vacancies_parser.api.headhunter.tasks import (
    parse_vacancies_by_technologies,
    parse_vacancies_by_category,
)
from modules.vacancies_parser.api.core.utils.task_runner import safe_task_run
from modules.vacancies_parser.api.core.utils.celery_broker import BrokerUnavailableError

logger = logging.getLogger('modules.vacancies_parser.headhunter')

TEXT: Dict[str, str] = {
    'line_sep': '-' * 64,
    'header': 'Немедленный запуск парсинга',
    'queued': 'Задача запущена в фоне.',
    'started': 'Запуск парсинга (ожидайте)...',
    'finished': 'Парсинг завершён.',
}


class Command(BaseCommand):
    help = 'Немедленный запуск парсинга вне очереди'

    def add_arguments(self, parser):
        parser.add_argument(
            '--preset',
            type=str,
            choices=['quick', 'normal', 'full', 'test'],
            default='quick',
            help='Пресет парсинга: quick (быстро), normal (обычный), full (полный), test (тест)'
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Конкретная категория (LANG, FRAMEWORK, DB, TOOL, PLATFORM)'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Запустить асинхронно (в фоне), иначе с ожиданием'
        )
        parser.add_argument(
            '--json-output',
            action='store_true',
            help='Вывести результат в JSON'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Минимальный вывод'
        )

    def handle(self, *args, **options):
        ctx = self._parse_options(options)
        self._print_header(ctx)

        params, task_func = self._resolve_params(ctx)

        try:
            if ctx['is_async']:
                self._run_async(task_func, params, ctx)
            else:
                self._run_sync(task_func, params, ctx)
        except Exception as e:
            if ctx['json_output']:
                self.stdout.write(json.dumps({'error': str(e)}, ensure_ascii=False))
            else:
                self.stdout.write(f'Ошибка при запуске: {e}')
            logger.exception('Ошибка при немедленном запуске парсинга')
    
    def _get_preset_params(self, preset):
        """Получение параметров для пресета."""
        presets = {
            'test': {
                'categories': None,
                'top_n': 5,
                'use_aliases': False,
                'area': 113,
                'pages': 1,
                'delay': 1.0,
                'get_details': False,
                'max_queries': 5
            },
            'quick': {
                'categories': None,
                'top_n': 10,
                'use_aliases': False,
                'area': 113,
                'pages': 1,
                'delay': 1.0,
                'get_details': False,
                'max_queries': 10
            },
            'normal': {
                'categories': ['LANG', 'FRAMEWORK'],
                'top_n': 20,
                'use_aliases': False,
                'area': 113,
                'pages': 2,
                'delay': 1.5,
                'get_details': True,
                'max_queries': 25
            },
            'full': {
                'categories': ['LANG', 'FRAMEWORK', 'DB'],
                'top_n': 40,
                'use_aliases': True,
                'area': 113,
                'pages': 3,
                'delay': 2.0,
                'get_details': True,
                'max_queries': 50
            }
        }
        return presets.get(preset, presets['quick'])
    
    def _get_category_params(self, category):
        """Получение параметров для конкретной категории."""
        return {
            'category': category,
            'use_aliases': False,
            'area': 113,
            'pages': 2,
            'delay': 1.5,
            'get_details': True,
            'max_queries': 20
        }
    
    def _print_results(self, result):
        """Вывод результатов парсинга."""
        mode = result.get('mode', 'unknown')

        if mode == 'by_technologies':
            self.stdout.write(f"Технологий использовано: {result.get('technologies_count', 0)}")
            self.stdout.write(f"Поисковых запросов: {result.get('search_queries_count', 0)}")
        elif mode == 'by_category':
            self.stdout.write(f"Категория: {result.get('category', 'N/A')}")
            self.stdout.write(f"Поисковых запросов: {result.get('search_queries_count', 0)}")

        self.stdout.write('')
        self.stdout.write(f"Всего обработано: {result.get('total_vacancies', 0)}")
        self.stdout.write(f"Новых вакансий: {result.get('new_vacancies', 0)}")
        self.stdout.write(f"Обновлено: {result.get('updated_vacancies', 0)}")
        self.stdout.write(f"Всего в базе: {result.get('total_in_db', 0)}")

    def _parse_options(self, options) -> Dict[str, Any]:
        return {
            'preset': options.get('preset'),
            'category': options.get('category'),
            'is_async': bool(options.get('async')),
            'json_output': bool(options.get('json_output')),
            'quiet': bool(options.get('quiet')),
        }

    def _print_header(self, ctx: Dict[str, Any]):
        if ctx['json_output'] or ctx['quiet']:
            return
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(TEXT['header'])
        self.stdout.write(TEXT['line_sep'])

    def _resolve_params(self, ctx: Dict[str, Any]):
        if ctx['category']:
            params = self._get_category_params(ctx['category'])
            task_func = parse_vacancies_by_category
        else:
            params = self._get_preset_params(ctx['preset'])
            task_func = parse_vacancies_by_technologies
        return params, task_func

    def _run_async(self, task_func, params: Dict[str, Any], ctx: Dict[str, Any]):
        try:
            result = safe_task_run(
                task_func,
                params,
                prefer_async=True,
                fallback_to_sync=True
            )
            
            if hasattr(result, 'id'):
                task_id = result.id
                if ctx['json_output']:
                    self.stdout.write(json.dumps({'task_id': str(task_id), 'status': 'queued'}, ensure_ascii=False))
                elif ctx['quiet']:
                    self.stdout.write(f'Task ID: {task_id}')
                else:
                    self.stdout.write(TEXT['queued'])
                    self.stdout.write(f'Task ID: {task_id}')
                    self.stdout.write('Проверьте статус через логи или Django shell')
            else:
                if ctx['json_output']:
                    self.stdout.write(json.dumps({'status': 'completed', 'result': result}, ensure_ascii=False))
                elif ctx['quiet']:
                    self.stdout.write('Задача выполнена синхронно')
                else:
                    self.stdout.write(self.style.WARNING('Брокер недоступен, задача выполнена синхронно'))
                    self._print_results(result)
                    
        except BrokerUnavailableError as e:
            error_msg = str(e)
            if ctx['json_output']:
                self.stdout.write(json.dumps({
                    'error': error_msg,
                    'suggestions': [
                        'Запустите Celery worker: ergoms start-worker',
                        'Используйте синхронный режим (без --async)'
                    ]
                }, ensure_ascii=False))
            else:
                self.stdout.write(self.style.ERROR(f'Ошибка: {error_msg}'))
                self.stdout.write('')
                self.stdout.write('Решения:')
                self.stdout.write('  1. Запустите Celery worker: ergoms start-worker')
                self.stdout.write('  2. Используйте синхронный режим (без --async)')
            raise CommandError(error_msg)

    def _run_sync(self, task_func, params: Dict[str, Any], ctx: Dict[str, Any]):
        if not ctx['quiet'] and not ctx['json_output']:
            self.stdout.write(TEXT['started'])
        result = task_func(**params)
        if ctx['json_output']:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if not ctx['quiet']:
            self.stdout.write(TEXT['finished'])
        if result.get('error'):
            self.stdout.write(f'Ошибка: {result["error"]}')
        else:
            self._print_results(result)



