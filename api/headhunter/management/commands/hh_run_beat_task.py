"""
Команда для немедленного запуска периодической задачи из Celery Beat.

Позволяет запустить любую задачу из расписания Beat прямо сейчас,
не дожидаясь её по расписанию.
"""

import logging
import time
import sys
from django.core.management.base import BaseCommand
from celery.result import AsyncResult

from modules.vacancies_parser.api.headhunter.celery_beat_config import HeadhunterCeleryBeatConfig
from modules.vacancies_parser.api.headhunter.tasks import (
    parse_vacancies_by_technologies,
    parse_vacancies_by_category
)

logger = logging.getLogger('modules.vacancies_parser.headhunter')


class Command(BaseCommand):
    help = 'Запуск периодической задачи из Celery Beat вне очереди'

    def add_arguments(self, parser):
        parser.add_argument(
            'task_name',
            type=str,
            nargs='?',
            help='Название задачи из Beat расписания'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='Показать список доступных задач'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Дождаться завершения задачи и вывести результат'
        )

    def handle(self, *args, **options):
        # Получаем конфигурацию Beat
        beat_config = HeadhunterCeleryBeatConfig('headhunter')
        schedule = beat_config.get_beat_schedule()
        
        # Показать список задач
        if options.get('list') or not options.get('task_name'):
            self._show_task_list(schedule)
            return
        
        task_name = options.get('task_name')
        wait = options.get('wait')
        
        # Проверяем существование задачи
        if task_name not in schedule:
            self.stdout.write(
                self.style.ERROR(f'Задача "{task_name}" не найдена в расписании!')
            )
            self.stdout.write('Используйте --list для просмотра доступных задач')
            return
        
        # Получаем конфигурацию задачи
        task_config = schedule[task_name]
        task_path = task_config.get('task')
        task_kwargs = task_config.get('kwargs', {})
        task_options = task_config.get('options', {})
        
        self.stdout.write(f'=== ЗАПУСК ЗАДАЧИ: {task_name} ===')

        # Выводим информацию о задаче
        self.stdout.write(f'Задача: {task_path}')
        self.stdout.write('Параметры:')
        for key, value in task_kwargs.items():
            self.stdout.write(f'   - {key}: {value}')

        if task_options:
            self.stdout.write('Опции:')
            for key, value in task_options.items():
                self.stdout.write(f'   - {key}: {value}')

        self.stdout.write()
        
        try:
            # Определяем функцию задачи
            if 'parse_vacancies_by_category' in task_path:
                task_func = parse_vacancies_by_category
            elif 'parse_vacancies_by_technologies' in task_path:
                task_func = parse_vacancies_by_technologies
            else:
                self.stdout.write(
                    self.style.ERROR(f'Неизвестный тип задачи: {task_path}')
                )
                return
            
            # Запускаем задачу
            if wait:
                self.stdout.write('Запуск задачи с ожиданием...')

                # Запускаем в Celery с обработкой ошибок брокера
                from modules.vacancies_parser.api.core.utils.task_runner import safe_task_run
                from modules.vacancies_parser.api.core.utils.celery_broker import BrokerUnavailableError
                
                try:
                    result = safe_task_run(
                        task_func.apply_async,
                        {'kwargs': task_kwargs, **task_options},
                        prefer_async=True,
                        fallback_to_sync=False
                    )
                    task = result
                except BrokerUnavailableError as e:
                    self.stdout.write(self.style.ERROR(f'Ошибка: {e}'))  # type: ignore[attr-defined]
                    self.stdout.write('Решения:')
                    self.stdout.write('  1. Запустите Celery worker: ergoms start-worker')
                    self.stdout.write('  2. Запустите Celery beat: ergoms start-beat')
                    raise

                self.stdout.write(f'Task ID: {task.id}')
                self.stdout.write('Ожидание завершения...')
                
                # Ожидание с анимацией
                spinner = ['|', '/', '-', '\\']
                i = 0
                
                while not task.ready():
                    sys.stdout.write(f'\rВыполняется... {spinner[i % 4]}')
                    sys.stdout.flush()
                    time.sleep(2)
                    i += 1
                
                sys.stdout.write('\r')
                
                if task.successful():
                    result = task.get()
                    self.stdout.write('\n=== ЗАДАЧА ЗАВЕРШЕНА! ===')
                    self._print_result(result)
                else:
                    self.stdout.write(f'Ошибка: {task.result}')
            else:
                # Асинхронный запуск
                from modules.vacancies_parser.api.core.utils.task_runner import safe_task_run
                from modules.vacancies_parser.api.core.utils.celery_broker import BrokerUnavailableError
                
                try:
                    result = safe_task_run(
                        task_func.apply_async,
                        {'kwargs': task_kwargs, **task_options},
                        prefer_async=True,
                        fallback_to_sync=False
                    )
                    task = result
                except BrokerUnavailableError as e:
                    self.stdout.write(self.style.ERROR(f'Ошибка: {e}'))  # type: ignore[attr-defined]
                    self.stdout.write('Решения:')
                    self.stdout.write('  1. Запустите Celery worker: ergoms start-worker')
                    self.stdout.write('  2. Запустите Celery beat: ergoms start-beat')
                    raise

                self.stdout.write('Задача запущена асинхронно!')
                self.stdout.write(f'Task ID: {task.id}')
                self.stdout.write('Проверьте статус через логи или используйте --wait')
        
        except Exception as e:
            self.stdout.write(f'Ошибка при запуске: {e}')
            logger.exception(f'Ошибка при запуске задачи {task_name}')
    
    def _show_task_list(self, schedule):
        """Показать список доступных задач."""
        self.stdout.write('=== ДОСТУПНЫЕ ЗАДАЧИ ДЛЯ ЗАПУСКА ===')
        
        for i, (task_name, task_config) in enumerate(schedule.items(), 1):
            kwargs = task_config.get('kwargs', {})
            
            # Определяем тип задачи
            if 'category' in kwargs:
                task_type = f"Категория: {kwargs['category']}"
            elif 'top_n' in kwargs:
                task_type = f"Топ-{kwargs['top_n']} технологий"
            else:
                task_type = "Универсальный парсинг"
            
            self.stdout.write(f'{i}. {task_name}')
            self.stdout.write(f'   {task_type}')
            self.stdout.write(f'   Страниц: {kwargs.get("pages", "N/A")}')
            self.stdout.write('')

        self.stdout.write('Для запуска используйте:')
        self.stdout.write('   python src/manage.py hh_run_beat_task <название_задачи> --wait')
        self.stdout.write('Пример:')
        
        if schedule:
            first_task = list(schedule.keys())[0]
            self.stdout.write(f'   python src/manage.py hh_run_beat_task {first_task} --wait')
        
        self.stdout.write('')
    
    def _print_result(self, result):
        """Вывод результатов выполнения задачи."""
        if result.get('error'):
            self.stdout.write(f'Ошибка: {result["error"]}')
            return

        mode = result.get('mode', 'unknown')

        if mode == 'by_technologies':
            self.stdout.write(f"Технологий: {result.get('technologies_count', 0)}")
            self.stdout.write(f"Запросов: {result.get('search_queries_count', 0)}")

            if result.get('search_queries'):
                self.stdout.write('   Примеры запросов:')
                for query in result['search_queries'][:10]:
                    self.stdout.write(f'     - {query}')

        elif mode == 'by_category':
            self.stdout.write(f"Категория: {result.get('category', 'N/A')}")
            self.stdout.write(f"Запросов: {result.get('search_queries_count', 0)}")

        self.stdout.write('')
        self.stdout.write(f"Всего обработано: {result.get('total_vacancies', 0)}")
        self.stdout.write(f"Новых вакансий: {result.get('new_vacancies', 0)}")
        self.stdout.write(f"Обновлено: {result.get('updated_vacancies', 0)}")
        self.stdout.write(f"Всего в базе: {result.get('total_in_db', 0)}")



