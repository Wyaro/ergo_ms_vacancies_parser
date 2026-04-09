import json
import os
import traceback

from celery.exceptions import TimeoutError as CeleryTimeoutError
from django.core.management.base import BaseCommand
from ...tasks import (
    parse_habr_vacancies_task,
    parse_habr_archived_vacancies_task,
    parse_habr_all_vacancies_task,
)


class Command(BaseCommand):
    help = 'Парсинг вакансий с Хабр Карьеры'

    @staticmethod
    def _normalize_search_text(raw_value):
        if raw_value is None:
            return None
        value = str(raw_value).strip()
        return value or None

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            default='config.json',
            help='Путь к JSON конфигурационному файлу (по умолчанию config.json)'
        )
        parser.add_argument(
            '--pages',
            type=int,
            help='Количество страниц для парсинга (переопределяет config)'
        )
        parser.add_argument(
            '--delay',
            type=float,
            help='Задержка между запросами в секундах (переопределяет config)'
        )
        parser.add_argument(
            '--no-details',
            action='store_true',
            help='Не получать детальную информацию о вакансиях (быстрее)'
        )
        parser.add_argument(
            '--archived',
            action='store_true',
            help='Парсить только архивные вакансии'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Парсить все вакансии (активные и архивные)'
        )
        parser.add_argument(
            '--search-text',
            type=str,
            help='Текстовый фильтр вакансий (например: "Python Django")'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Дождаться завершения задачи Celery и вывести результат'
        )
        parser.add_argument(
            '--wait-timeout',
            type=int,
            default=None,
            help='Таймаут ожидания результата в секундах для --wait'
        )

    def load_config(self, config_path):
        """Загрузка конфигурации из JSON файла"""
        try:
            if not os.path.isabs(config_path):
                current_dir = os.path.dirname(os.path.abspath(__file__))
                config_path = os.path.join(current_dir, config_path)

            if not os.path.exists(config_path):
                self.stdout.write(
                    self.style.WARNING(
                        f'Конфигурационный файл {config_path} не найден. '
                        'Используем значения по умолчанию.'
                    )
                )
                return {}

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            self.stdout.write(
                self.style.SUCCESS(f'Конфигурация загружена из {config_path}')
            )
            return config

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Ошибка при загрузке конфигурации: {e}')
            )
            return {}

    def print_formatted_result(self, result):
        """Вывод результата в удобном формате"""
        if not isinstance(result, dict):
            self.stdout.write(f"Результат: {result}")
            return

        status = result.get('status')
        if status == 'SUCCESS':
            self.stdout.write(
                self.style.SUCCESS(result.get('message', 'Задача выполнена успешно'))
            )
            stats = result.get('result')
            if isinstance(stats, dict):
                self.stdout.write("Статистика:")
                self.stdout.write(f"   Всего обработано: {stats.get('total', 0)}")
                self.stdout.write(f"   Новых вакансий: {stats.get('new', 0)}")
                self.stdout.write(f"   Обновлено вакансий: {stats.get('updated', 0)}")
                self.stdout.write(f"   Ошибок: {stats.get('errors', 0)}")
        elif status == 'ERROR':
            self.stdout.write(
                self.style.ERROR(result.get('message', 'Произошла ошибка'))
            )
            if 'error' in result:
                self.stdout.write(f"Детали ошибки: {result['error']}")
        else:
            self.stdout.write(f"Результат: {result}")

    def handle(self, *args, **options):
        config = self.load_config(options['config'])

        pages = options.get('pages') or config.get('pages', 5)
        delay = options.get('delay') or config.get('delay', 1.0)
        get_details = not options.get('no_details', False) and config.get('get_details', True)
        parse_archived = options.get('archived', False) or config.get('parse_archived', False)
        parse_all = options.get('all', False) or config.get('parse_all', False)
        search_text = self._normalize_search_text(
            options.get('search_text') or config.get('search_text')
        )
        wait_for_result = options.get('wait', False)
        wait_timeout = options.get('wait_timeout')

        self.stdout.write("Параметры парсинга:")
        self.stdout.write(f"   Страниц: {pages}")
        self.stdout.write(f"   Задержка: {delay}с")
        self.stdout.write(f"   Детали: {'Да' if get_details else 'Нет'}")
        self.stdout.write(f"   Архивные: {'Да' if parse_archived else 'Нет'}")
        self.stdout.write(f"   Все вакансии: {'Да' if parse_all else 'Нет'}")
        self.stdout.write(f"   Поиск: {search_text if search_text else 'без фильтра'}")
        self.stdout.write("   Celery: Да")

        try:
            task = self._run_celery_task(
                pages, delay, get_details,
                parse_all, parse_archived, search_text
            )
            self.stdout.write(f"Задача Celery запущена с ID: {task.id}")

            if wait_for_result:
                try:
                    if wait_timeout is not None:
                        self.stdout.write(f"Ожидаем завершения задачи (таймаут: {wait_timeout}с)...")
                        result = task.get(timeout=wait_timeout)
                    else:
                        self.stdout.write("Ожидаем завершения задачи...")
                        result = task.get()
                    self.print_formatted_result(result)
                except CeleryTimeoutError:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Таймаут ожидания результата ({wait_timeout}с). "
                            f"Задача {task.id} продолжает выполняться в Celery."
                        )
                    )
            else:
                self.stdout.write(
                    self.style.SUCCESS("Задача отправлена в очередь Celery")
                )

        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING("\nПарсинг прерван пользователем")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Ошибка при выполнении парсинга: {e}")
            )
            self.stdout.write("Детали ошибки:")
            traceback.print_exc()

    def _run_celery_task(self, pages, delay, get_details,
                         parse_all, parse_archived, search_text):
        """Запуск задачи через Celery"""
        if parse_all:
            return parse_habr_all_vacancies_task.delay(
                pages=pages, delay=delay, get_details=get_details, search_text=search_text
            )
        if parse_archived:
            return parse_habr_archived_vacancies_task.delay(
                pages=pages, delay=delay, search_text=search_text
            )
        return parse_habr_vacancies_task.delay(
            pages=pages, delay=delay, get_details=get_details, search_text=search_text
        )
