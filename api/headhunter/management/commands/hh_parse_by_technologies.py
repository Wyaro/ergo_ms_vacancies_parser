"""
Команда для парсинга вакансий HeadHunter по технологиям из базы данных.

Автоматически генерирует поисковые запросы на основе технологий
и запускает парсинг через Celery.
"""

import logging
import time
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from django.core.management.base import BaseCommand, CommandParser

from modules.vacancies_parser.api.headhunter.tasks import (
    parse_vacancies_by_technologies,
    parse_vacancies_by_category
)
from modules.vacancies_parser.api.core.utils.task_runner import safe_task_run
from modules.vacancies_parser.api.core.utils.celery_broker import BrokerUnavailableError

logger = logging.getLogger('modules.vacancies_parser.headhunter')

TEXT: Dict[str, str] = {
    'line_sep': '=' * 70,
    'header': 'Парсинг вакансий по технологиям',
    'params_header': 'Параметры парсинга:',
    'task_sent': 'Задача Celery отправлена',
    'task_id': 'Task ID',
    'waiting': 'Ожидание завершения задачи',
    'completed': 'Задача завершена',
    'check_status': 'Проверьте статус задачи через Celery Flower или Django shell',
    'results_header': 'РЕЗУЛЬТАТЫ ПАРСИНГА',
    'sync_mode': 'Синхронный запуск (без Celery worker)',
    'sync_completed': 'Синхронная задача завершена',
    'no_results': 'Результаты не получены',
}


class Command(BaseCommand):
    help = 'Парсинг вакансий HeadHunter по технологиям из базы данных'

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Добавляет аргументы командной строки.

        Args:
            parser: Парсер аргументов командной строки
        """
        parser.add_argument(
            '--category',
            type=str,
            help='Категория технологий (LANG, FRAMEWORK, DB, TOOL, PLATFORM, PROTOCOL, LIBRARY, SERVICE)'
        )
        parser.add_argument(
            '--categories',
            type=str,
            nargs='+',
            help='Список категорий технологий'
        )
        parser.add_argument(
            '--top',
            type=int,
            default=50,
            help='Количество топовых технологий (по умолчанию 50)'
        )
        parser.add_argument(
            '--use-aliases',
            action='store_true',
            help='Использовать алиасы технологий как отдельные запросы'
        )
        parser.add_argument(
            '--area',
            type=int,
            default=113,
            help='ID региона (по умолчанию 113 = Россия)'
        )
        parser.add_argument(
            '--pages',
            type=int,
            default=2,
            help='Количество страниц для парсинга на запрос (по умолчанию 2)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.5,
            help='Задержка между запросами в секундах (по умолчанию 1.5)'
        )
        parser.add_argument(
            '--no-details',
            action='store_true',
            help='Не получать детальную информацию (быстрее)'
        )
        parser.add_argument(
            '--max-queries',
            type=int,
            help='Максимальное количество поисковых запросов'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Дождаться завершения задачи Celery и вывести результат'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Выполнить синхронно без Celery (apply)'
        )
        parser.add_argument(
            '--save-results',
            type=str,
            metavar='FILE',
            help='Сохранить результаты в JSON файл'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Минимальный вывод (только важная информация)'
        )
        parser.add_argument(
            '--json-output',
            action='store_true',
            help='Вывести результат в JSON формате (stdout)'
        )

    def handle(self, *args: tuple, **options: Dict[str, Any]) -> None:
        """
        Выполняет команду парсинга вакансий по технологиям.

        Args:
            *args: Позиционные аргументы
            **options: Именованные аргументы
        """
        logger.info('Запуск команды парсинга вакансий по технологиям')
        
        # Парсим и валидируем параметры
        category_raw = options.get('category')
        category: Optional[str] = str(category_raw) if category_raw else None
        categories_raw = options.get('categories')
        categories: Optional[list] = list(categories_raw) if categories_raw else None
        top_n: int = int(options.get('top', 50))  # type: ignore[arg-type]
        use_aliases: bool = bool(options.get('use_aliases', False))
        area: int = int(options.get('area', 113))  # type: ignore[arg-type]
        pages: int = int(options.get('pages', 2))  # type: ignore[arg-type]
        delay: float = float(options.get('delay', 1.5))  # type: ignore[arg-type]
        get_details: bool = not bool(options.get('no_details', False))
        max_queries_raw = options.get('max_queries')
        max_queries: Optional[int] = int(max_queries_raw) if max_queries_raw is not None else None  # type: ignore[arg-type]
        wait: bool = bool(options.get('wait', False))
        sync_mode: bool = bool(options.get('sync', False))
        save_results_raw = options.get('save_results')
        save_results: Optional[str] = str(save_results_raw) if save_results_raw else None
        quiet: bool = bool(options.get('quiet', False))
        json_output: bool = bool(options.get('json_output', False))
        
        ctx: Dict[str, Any] = {
            'quiet': quiet,
            'json_output': json_output,
            'save_results': save_results,
        }
        
        # Валидация параметров
        validation_error = self._validate_parameters(
            category, categories, top_n, area, pages, delay, max_queries
        )
        if validation_error:
            if not quiet and not json_output:
                self.stdout.write(self.style.ERROR(validation_error))  # type: ignore[attr-defined]
            logger.error(f'Валидация не пройдена: {validation_error}')
            if json_output:
                self.stdout.write(json.dumps({'error': validation_error}, ensure_ascii=False))
            return
        
        # Вывод заголовка и параметров
        self._print_header(ctx)
        self._print_parameters(category, categories, top_n, use_aliases, area, pages, delay, get_details, max_queries, ctx)
        
        try:
            logger.debug(f'Параметры: category={category}, categories={categories}, top_n={top_n}, '
                        f'area={area}, pages={pages}, delay={delay}, get_details={get_details}')

            if category:
                task_kwargs: Dict[str, Any] = {
                    'category': category,
                    'use_aliases': use_aliases,
                    'area': area,
                    'pages': pages,
                    'delay': delay,
                    'get_details': get_details,
                    'max_queries': max_queries or 50
                }
                if sync_mode:
                    self._run_task_sync(parse_vacancies_by_category, task_kwargs, ctx)
                    return
                logger.info(f'Запуск парсинга по категории: {category}')
                if not quiet:
                    self.stdout.write(self.style.SUCCESS(f'Запуск парсинга по категории: {category}'))  # type: ignore[attr-defined]
                try:
                    result = safe_task_run(
                        parse_vacancies_by_category,
                        task_kwargs,
                        prefer_async=not sync_mode,
                        fallback_to_sync=True
                    )
                    task = result if hasattr(result, 'id') else None
                except BrokerUnavailableError as e:
                    self.stdout.write(self.style.ERROR(f'Ошибка: {e}'))  # type: ignore[attr-defined]
                    self.stdout.write('Решения:')
                    self.stdout.write('  1. Запустите Celery worker: ergoms start-worker')
                    self.stdout.write('  2. Используйте синхронный режим (--sync)')
                    raise
            else:
                task_kwargs = {
                    'categories': categories,
                    'top_n': top_n,
                    'use_aliases': use_aliases,
                    'area': area,
                    'pages': pages,
                    'delay': delay,
                    'get_details': get_details,
                    'max_queries': max_queries
                }
                if sync_mode:
                    self._run_task_sync(parse_vacancies_by_technologies, task_kwargs, ctx)
                    return
                logger.info('Запуск парсинга по технологиям')
                if not quiet:
                    self.stdout.write(self.style.SUCCESS('Запуск парсинга по технологиям'))  # type: ignore[attr-defined]
                try:
                    result = safe_task_run(
                        parse_vacancies_by_technologies,
                        task_kwargs,
                        prefer_async=not sync_mode,
                        fallback_to_sync=True
                    )
                    task = result if hasattr(result, 'id') else None
                except BrokerUnavailableError as e:
                    self.stdout.write(self.style.ERROR(f'Ошибка: {e}'))  # type: ignore[attr-defined]
                    self.stdout.write('Решения:')
                    self.stdout.write('  1. Запустите Celery worker: ergoms start-worker')
                    self.stdout.write('  2. Используйте синхронный режим (--sync)')
                    raise
            
            if task and hasattr(task, 'id'):
                logger.info(f'Задача Celery отправлена: Task ID={task.id}')
                if not quiet:
                    self.stdout.write('')
                    self.stdout.write(self.style.SUCCESS(f'{TEXT["task_sent"]}! {TEXT["task_id"]}: {task.id}'))  # type: ignore[attr-defined]
                elif json_output:
                    self.stdout.write(json.dumps({'task_id': str(task.id), 'status': 'queued'}, ensure_ascii=False))

                if wait:
                    self._wait_for_task(task, ctx)
            else:
                logger.info('Задача выполнена синхронно')
                if not quiet:
                    self.stdout.write(self.style.WARNING('Задача выполнена синхронно (брокер недоступен)'))  # type: ignore[attr-defined]
            else:
                if not quiet:
                    self.stdout.write('')
                    self.stdout.write(f'{TEXT["check_status"]}')
                elif json_output:
                    self.stdout.write(json.dumps({'message': TEXT['check_status']}, ensure_ascii=False))
        
        except Exception as e:
            error_msg = f'Ошибка при запуске парсинга: {e}'
            self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
            logger.exception('Ошибка при запуске парсинга по технологиям')
    
    def _validate_parameters(
        self,
        category: Optional[str],
        categories: Optional[list],
        top_n: int,
        area: int,
        pages: int,
        delay: float,
        max_queries: Optional[int]
    ) -> str:
        """
        Валидирует параметры команды.

        Args:
            category: Категория технологий
            categories: Список категорий
            top_n: Количество топовых технологий
            area: ID региона
            pages: Количество страниц
            delay: Задержка между запросами
            max_queries: Максимальное количество запросов

        Returns:
            Сообщение об ошибке или пустая строка если всё ок
        """
        if top_n < 1:
            return 'Параметр --top должен быть положительным числом'
        if area < 1:
            return 'Параметр --area должен быть положительным числом'
        if pages < 1:
            return 'Параметр --pages должен быть положительным числом'
        if delay < 0:
            return 'Параметр --delay не может быть отрицательным'
        if max_queries is not None and max_queries < 1:
            return 'Параметр --max-queries должен быть положительным числом'
        return ''

    def _print_header(self, ctx: Dict[str, Any]) -> None:
        """
        Выводит заголовок команды.

        Args:
            ctx: Контекст с опциями
        """
        if ctx['quiet'] or ctx['json_output']:
            return
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(f'=== {TEXT["header"]} ===')
        self.stdout.write(TEXT['line_sep'])

    def _print_parameters(
        self,
        category: Optional[str],
        categories: Optional[list],
        top_n: int,
        use_aliases: bool,
        area: int,
        pages: int,
        delay: float,
        get_details: bool,
        max_queries: Optional[int],
        ctx: Dict[str, Any]
    ) -> None:
        """
        Выводит параметры парсинга в удобном формате.

        Args:
            category: Категория технологий
            categories: Список категорий
            top_n: Количество топовых технологий
            use_aliases: Использовать алиасы
            area: ID региона
            pages: Количество страниц
            delay: Задержка
            get_details: Получать детали
            max_queries: Максимум запросов
            ctx: Контекст с опциями
        """
        if ctx['quiet'] or ctx['json_output']:
            return

        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'{TEXT["params_header"]}'))  # type: ignore[attr-defined]
        
        # Определяем режим парсинга
        if category:
            mode_text = f'Категория: {self.style.SUCCESS(category)}'  # type: ignore[attr-defined]
        elif categories:
            cats_str = ', '.join(categories)
            mode_text = f'Категории: {self.style.SUCCESS(cats_str)}'  # type: ignore[attr-defined]
        else:
            mode_text = f'Топ технологий: {self.style.SUCCESS(str(top_n))}'  # type: ignore[attr-defined]
        
        self.stdout.write(f'   {mode_text}')
        self.stdout.write(f'   Регион: {self.style.SUCCESS(str(area))} (Россия)')  # type: ignore[attr-defined]
        self.stdout.write(f'   Страниц на запрос: {self.style.SUCCESS(str(pages))}')  # type: ignore[attr-defined]
        self.stdout.write(f'   Задержка: {self.style.SUCCESS(f"{delay} сек")}')  # type: ignore[attr-defined]
        self.stdout.write(f'   Детальная информация: {self.style.SUCCESS("Да" if get_details else "Нет")}')  # type: ignore[attr-defined]
        self.stdout.write(f'   Алиасы: {self.style.SUCCESS("Да" if use_aliases else "Нет")}')  # type: ignore[attr-defined]
        if max_queries:
            self.stdout.write(f'   Макс. запросов: {self.style.SUCCESS(str(max_queries))}')  # type: ignore[attr-defined]
        
        # Предупреждение о долгом выполнении
        estimated_time = self._estimate_time(pages, delay, max_queries or 50, get_details)
        if estimated_time > 300:  # Больше 5 минут
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(  # type: ignore[attr-defined]
                f'Предупреждение: Ожидаемое время выполнения ~{estimated_time // 60} мин {estimated_time % 60} сек'
            ))
        
        self.stdout.write('')
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write('')

    def _estimate_time(self, pages: int, delay: float, max_queries: int, get_details: bool) -> int:
        """
        Оценивает время выполнения парсинга в секундах.

        Args:
            pages: Количество страниц
            delay: Задержка между запросами
            max_queries: Максимум запросов
            get_details: Получать детали

        Returns:
            Оценка времени в секундах
        """
        base_time = pages * delay * max_queries
        if get_details:
            # Детализация добавляет примерно 0.5 сек на вакансию
            # Предполагаем ~20 вакансий на страницу
            base_time += pages * max_queries * 20 * 0.5
        return int(base_time)

    def _run_task_sync(
        self,
        task_func: Any,
        task_kwargs: Dict[str, Any],
        ctx: Dict[str, Any]
    ) -> None:
        """
        Запускает задачу синхронно (без Celery worker).

        Args:
            task_func: Функция задачи Celery
            task_kwargs: Параметры задачи
            ctx: Контекст с опциями
        """
        logger.info('Синхронный запуск задачи (без Celery worker)')
        if not ctx['quiet']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(f'{TEXT["sync_mode"]}...'))  # type: ignore[attr-defined]
        
        start_time = time.time()
        try:
            res = task_func.apply(kwargs=task_kwargs)
            elapsed_time = time.time() - start_time
            
            if res.successful():
                result = res.get()
                if isinstance(result, dict):
                    result['execution_time_seconds'] = round(elapsed_time, 2)
                    logger.info(f'Синхронная задача завершена успешно за {elapsed_time:.2f} сек')
                    if not ctx['quiet']:
                        self.stdout.write('')
                        self.stdout.write(self.style.SUCCESS(  # type: ignore[attr-defined]
                            f'{TEXT["sync_completed"]} за {elapsed_time:.1f} сек'
                        ))
                    self._print_result(result, ctx)
                else:
                    logger.warning(f'Неожиданный тип результата: {type(result)}')
                    if not ctx['quiet']:
                        self.stdout.write(f'Результат: {result}')
            else:
                error_msg = f'Ошибка при выполнении: {res.result}'
                logger.error(error_msg)
                if not ctx['quiet']:
                    self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
                elif ctx['json_output']:
                    self.stdout.write(json.dumps({'error': str(res.result)}, ensure_ascii=False))
        except Exception as e:
            error_msg = f'Ошибка при синхронном выполнении: {e}'
            logger.exception(error_msg)
            if not ctx['quiet']:
                self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
            elif ctx['json_output']:
                self.stdout.write(json.dumps({'error': error_msg}, ensure_ascii=False))

    def _wait_for_task(self, task: Any, ctx: Dict[str, Any]) -> None:
        """
        Ожидает завершения задачи Celery и выводит результат.

        Args:
            task: Объект задачи Celery
            ctx: Контекст с опциями
        """
        logger.info('Ожидание завершения задачи Celery')
        if not ctx['quiet']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(f'{TEXT["waiting"]}...'))  # type: ignore[attr-defined]
        
        start_time = time.time()
        spinner = ['|', '/', '-', '\\']
        i = 0
        last_status_check = 0

        try:
            while not task.ready():
                elapsed = int(time.time() - start_time)
                
                if not ctx['quiet']:
                    # Обновляем статус каждые 2 секунды
                    if elapsed - last_status_check >= 2:
                        minutes = elapsed // 60
                        seconds = elapsed % 60
                        time_str = f'{minutes:02d}:{seconds:02d}'
                        sys.stdout.write(f'\r{spinner[i % len(spinner)]} Выполняется... {time_str}')
                        sys.stdout.flush()
                        last_status_check = elapsed
                
                time.sleep(0.5)
                i += 1

            if not ctx['quiet']:
                sys.stdout.write('\r')
            
            elapsed_time = time.time() - start_time

            if task.successful():
                result = task.get()
                if isinstance(result, dict):
                    result['execution_time_seconds'] = round(elapsed_time, 2)
                    logger.info(f'Задача Celery завершена успешно за {elapsed_time:.2f} сек')
                    if not ctx['quiet']:
                        self.stdout.write('')
                        self.stdout.write(self.style.SUCCESS(  # type: ignore[attr-defined]
                            f'{TEXT["completed"]} за {elapsed_time:.1f} сек'
                        ))
                    self._print_result(result, ctx)
                else:
                    logger.warning(f'Неожиданный тип результата: {type(result)}')
                    if not ctx['quiet']:
                        self.stdout.write(f'Результат: {result}')
                    elif ctx['json_output']:
                        self.stdout.write(json.dumps({'result': str(result)}, ensure_ascii=False))
            else:
                error_result = task.result
                error_msg = f'Ошибка при выполнении задачи: {error_result}'
                logger.error(error_msg)
                if not ctx['quiet']:
                    self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
                elif ctx['json_output']:
                    self.stdout.write(json.dumps({'error': str(error_result)}, ensure_ascii=False))
        except KeyboardInterrupt:
            if not ctx['quiet']:
                self.stdout.write('\n')
                self.stdout.write(self.style.WARNING('Прервано пользователем'))  # type: ignore[attr-defined]
            logger.warning('Ожидание задачи прервано пользователем')
        except Exception as e:
            error_msg = f'Ошибка при ожидании задачи: {e}'
            logger.exception(error_msg)
            if not ctx['quiet']:
                self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
            elif ctx['json_output']:
                self.stdout.write(json.dumps({'error': error_msg}, ensure_ascii=False))

    def _print_result(self, result: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        """
        Выводит результаты парсинга.

        Args:
            result: Словарь с результатами парсинга
            ctx: Контекст с опциями
        """
        if not isinstance(result, dict):
            logger.warning(f'Неожиданный формат результата: {type(result)}')
            if not ctx['quiet']:
                self.stdout.write(f'Результат: {result}')
            elif ctx['json_output']:
                self.stdout.write(json.dumps({'result': str(result)}, ensure_ascii=False))
            return

        if result.get('error'):
            error_msg = result['error']
            logger.error(f'Ошибка в результате парсинга: {error_msg}')
            if not ctx['quiet']:
                self.stdout.write(self.style.ERROR(f'Ошибка: {error_msg}'))  # type: ignore[attr-defined]
            elif ctx['json_output']:
                self.stdout.write(json.dumps({'error': error_msg}, ensure_ascii=False))
            return

        # Сохраняем результаты в файл если нужно
        if ctx['save_results']:
            self._save_results_to_file(result, ctx['save_results'], ctx)

        # JSON вывод
        if ctx['json_output']:
            self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            return

        if ctx['quiet']:
            # Минимальный вывод
            total = result.get('total_vacancies', 0)
            new = result.get('new_vacancies', 0)
            updated = result.get('updated_vacancies', 0)
            self.stdout.write(f'{total} обработано, {new} новых, {updated} обновлено')
            return

        # Полный вывод с форматированием
        self.stdout.write('')
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(f'=== {TEXT["results_header"]} ===')
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write('')

        mode = result.get('mode', 'unknown')
        execution_time = result.get('execution_time_seconds', 0)

        # Информация о режиме парсинга
        if mode == 'by_technologies':
            tech_count = result.get('technologies_count', 0)
            queries_count = result.get('search_queries_count', 0)
            self.stdout.write(self.style.SUCCESS(f'Использовано технологий: {tech_count}'))  # type: ignore[attr-defined]
            self.stdout.write(self.style.SUCCESS(f'Поисковых запросов: {queries_count}'))  # type: ignore[attr-defined]

            if result.get('search_queries'):
                self.stdout.write('')
                self.stdout.write('   Примеры запросов:')
                for i, query in enumerate(result['search_queries'][:10], 1):
                    self.stdout.write(f'   {i:2d}. {query}')
                if len(result['search_queries']) > 10:
                    self.stdout.write(f'   ... и ещё {len(result["search_queries"]) - 10} запросов')

        elif mode == 'by_category':
            category = result.get('category', 'N/A')
            queries_count = result.get('search_queries_count', 0)
            self.stdout.write(self.style.SUCCESS(f'Категория: {category}'))  # type: ignore[attr-defined]
            self.stdout.write(self.style.SUCCESS(f'Поисковых запросов: {queries_count}'))  # type: ignore[attr-defined]

            if result.get('search_queries'):
                self.stdout.write('')
                self.stdout.write('   Запросы:')
                for i, query in enumerate(result['search_queries'][:10], 1):
                    self.stdout.write(f'   {i:2d}. {query}')
                if len(result['search_queries']) > 10:
                    self.stdout.write(f'   ... и ещё {len(result["search_queries"]) - 10} запросов')

        # Статистика по вакансиям
        self.stdout.write('')
        self.stdout.write('Статистика по вакансиям:')
        total_vacancies = result.get('total_vacancies', 0)
        new_vacancies = result.get('new_vacancies', 0)
        updated_vacancies = result.get('updated_vacancies', 0)
        total_in_db = result.get('total_in_db', 0)

        self.stdout.write(f'   Всего обработано: {self.style.SUCCESS(str(total_vacancies))}')  # type: ignore[attr-defined]
        if new_vacancies > 0:
            self.stdout.write(f'   Новых вакансий: {self.style.SUCCESS(str(new_vacancies))}')  # type: ignore[attr-defined]
        if updated_vacancies > 0:
            self.stdout.write(f'   Обновлено вакансий: {self.style.SUCCESS(str(updated_vacancies))}')  # type: ignore[attr-defined]
        self.stdout.write(f'   Всего в базе данных: {self.style.SUCCESS(str(total_in_db))}')  # type: ignore[attr-defined]

        # Время выполнения
        if execution_time > 0:
            minutes = int(execution_time // 60)
            seconds = int(execution_time % 60)
            if minutes > 0:
                time_str = f'{minutes} мин {seconds} сек'
            else:
                time_str = f'{seconds} сек'
            self.stdout.write('')
            self.stdout.write(f'Время выполнения: {self.style.SUCCESS(time_str)}')  # type: ignore[attr-defined]

        self.stdout.write('')
        self.stdout.write(TEXT['line_sep'])

    def _save_results_to_file(
        self,
        result: Dict[str, Any],
        file_path: str,
        ctx: Dict[str, Any]
    ) -> None:
        """
        Сохраняет результаты парсинга в JSON файл.

        Args:
            result: Словарь с результатами
            file_path: Путь к файлу
            ctx: Контекст с опциями
        """
        try:
            # Если путь относительный, сохраняем в директорию config модуля
            if not Path(file_path).is_absolute():
                config_dir = Path(__file__).parent.parent.parent / 'config'
                path = config_dir / file_path
            else:
                path = Path(file_path)

            # Создаем директорию если её нет
            path.parent.mkdir(parents=True, exist_ok=True)

            # Добавляем метаданные
            result_with_meta = {
                'timestamp': datetime.now().isoformat(),
                'results': result
            }

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(result_with_meta, f, ensure_ascii=False, indent=2)

            logger.info(f'Результаты сохранены в файл: {path}')
            if not ctx['quiet']:
                self.stdout.write('')
                self.stdout.write(self.style.SUCCESS(  # type: ignore[attr-defined]
                    f'Результаты сохранены в файл: {path}'
                ))
        except (IOError, OSError) as e:
            error_msg = f'Ошибка при сохранении результатов: {e}'
            logger.error(error_msg, exc_info=True)
            if not ctx['quiet']:
                self.stdout.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]

