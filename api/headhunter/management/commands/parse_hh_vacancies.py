import json
import os
import time
import sys
from pathlib import Path
from django.core.management.base import BaseCommand
from modules.vacancies_parser.api.headhunter.scripts import parse_vacancies_by_text, parse_all_vacancies
from modules.vacancies_parser.api.headhunter.tasks import parse_hh_vacancies_task
from celery.result import AsyncResult


class Command(BaseCommand):
    help = 'Парсинг вакансий с HeadHunter'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            default='config.json',
            help='Путь к JSON конфигурационному файлу (по умолчанию config.json)'
        )
        parser.add_argument(
            '--text',
            type=str,
            nargs='+',  # Позволяет указывать несколько слов
            help='Текст для поиска вакансий (можно указать несколько слов, переопределяет config)'
        )
        parser.add_argument(
            '--area',
            type=int,
            help='ID региона (переопределяет config)'
        )
        parser.add_argument(
            '--experience',
            type=str,
            choices=['noExperience', 'between1And3', 'between3And6', 'moreThan6'],
            help='Уровень опыта'
        )
        parser.add_argument(
            '--employment',
            type=str,
            choices=['full', 'part', 'project', 'volunteer', 'probation'],
            help='Тип занятости'
        )
        parser.add_argument(
            '--schedule',
            type=str,
            choices=['fullDay', 'shift', 'flexible', 'remote', 'flyInFlyOut'],
            help='График работы'
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
            '--universal',
            action='store_true',
            help='Универсальный парсинг всех вакансий по регионам и ролям'
        )
        parser.add_argument(
            '--pages-per-area',
            type=int,
            help='Количество страниц для каждого региона (переопределяет config)'
        )
        parser.add_argument(
            '--max-total-pages',
            type=int,
            help='Максимальное общее количество страниц (переопределяет config)'
        )
        parser.add_argument(
            '--areas-only',
            action='store_true',
            help='Парсить только по регионам (без профессиональных ролей)'
        )
        parser.add_argument(
            '--use-config-only',
            action='store_true',
            help='Использовать только настройки из конфигурационного файла'
        )
        parser.add_argument(
            '--wait',
            action='store_true',
            help='Дождаться завершения задачи Celery и вывести результат'
        )
    
    def load_config(self, config_path):
        """Загрузка конфигурации из JSON файла"""
        try:
            # Получаем абсолютный путь к конфигурационному файлу
            if os.path.isabs(config_path):
                # Абсолютный путь - используем как есть
                config_file = Path(config_path)
            else:
                # Относительный путь - ищем в папке config модуля
                # Путь относительно корня модуля: modules/vacancies_parser/api/headhunter/
                module_dir = Path(__file__).parent.parent.parent
                config_dir = module_dir / 'config'
                config_file = config_dir / config_path
            
            if not config_file.exists():
                self.stdout.write(
                    f'Конфигурационный файл не найден: {config_file}'
                )
                return None
            
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.stdout.write(
                f'Конфигурация загружена из: {config_file}'
            )
            return config
            
        except json.JSONDecodeError as e:
            self.stdout.write(
                f'Ошибка парсинга JSON файла: {e}'
            )
            return None
        except Exception as e:
            self.stdout.write(
                f'Ошибка загрузки конфигурации: {e}'
            )
            return None
    
    def print_formatted_result(self, result):
        if not isinstance(result, dict):
            self.stdout.write(f'Результат: {result}')
            return
        if result.get('error'):
            self.stdout.write(f'Ошибка: {result["error"]}')
            return
        if result.get('mode') == 'universal':
            self.stdout.write('\nИтоги универсального парсинга:')
            self.stdout.write(f'   - Обработано регионов: {result.get("areas_processed", "-")}')
            self.stdout.write(f'   - Обработано ролей: {result.get("roles_processed", "-")}')
            self.stdout.write(f'   - Обработано страниц: {result.get("pages_processed", "-")}')
            self.stdout.write(f'   - Всего вакансий: {result.get("total_vacancies", "-")}')
            self.stdout.write(f'   - Новых вакансий: {result.get("new_vacancies", "-")}')
            self.stdout.write(f'   - Обновлено вакансий: {result.get("updated_vacancies", "-")}')
            self.stdout.write(f'   - Всего в базе: {result.get("total_in_db", "-")}')
        elif result.get('mode') == 'by_text':
            self.stdout.write('\nИтоги парсинга по запросам:')
            self.stdout.write(f'   - Всего вакансий: {result.get("total_vacancies", "-")}')
            self.stdout.write(f'   - Новых вакансий: {result.get("new_vacancies", "-")}')
            self.stdout.write(f'   - Обновлено вакансий: {result.get("updated_vacancies", "-")}')
            self.stdout.write(f'   - Всего в базе: {result.get("total_in_db", "-")}')
        else:
            self.stdout.write(f'Результат: {result}')

    def handle(self, *args, **options):
        # Загружаем конфигурацию
        config = self.load_config(options.get('config'))
        if not config and options.get('use_config_only'):
            self.stdout.write(
                'Не удалось загрузить конфигурацию, а флаг --use-config-only установлен'
            )
            return
        # Определяем параметры парсинга
        if options.get('use_config_only') and config:
            text_list = config.get('search_queries', [])
            area = config.get('area_code', 113)
            pages = config.get('parsing_settings', {}).get('pages_per_query', 2)
            delay = config.get('parsing_settings', {}).get('delay_between_queries', 1.0)
            get_details = config.get('parsing_settings', {}).get('get_detailed_info', True)
            universal = config.get('universal_parsing', {}).get('enabled', False)
            pages_per_area = config.get('universal_parsing', {}).get('pages_per_area', 5)
            max_total_pages = config.get('universal_parsing', {}).get('max_total_pages', 100)
            areas_only = config.get('universal_parsing', {}).get('areas_only', False)
        else:
            text_list = options.get('text')
            area = options.get('area') or (config.get('area_code', 113) if config else 113)
            pages = options.get('pages') or (config.get('parsing_settings', {}).get('pages_per_query', 2) if config else 2)
            delay = options.get('delay') or (config.get('parsing_settings', {}).get('delay_between_queries', 1.0) if config else 1.0)
            get_details = not options.get('no_details') if options.get('no_details') is not None else (config.get('parsing_settings', {}).get('get_detailed_info', True) if config else True)
            universal = options.get('universal') or (config.get('universal_parsing', {}).get('enabled', False) if config else False)
            pages_per_area = options.get('pages_per_area') or (config.get('universal_parsing', {}).get('pages_per_area', 5) if config else 5)
            max_total_pages = options.get('max_total_pages') or (config.get('universal_parsing', {}).get('max_total_pages', 100) if config else 100)
            areas_only = options.get('areas_only') or (config.get('universal_parsing', {}).get('areas_only', False) if config else False)
        if not text_list and not universal and config:
            text_list = config.get('search_queries', [])
            universal = config.get('universal_parsing', {}).get('enabled', False)
        # Запуск задачи Celery
        task = parse_hh_vacancies_task.delay(
            text_list=text_list,
            area=area,
            pages=pages,
            delay=delay,
            get_details=get_details,
            universal=universal,
            pages_per_area=pages_per_area,
            max_total_pages=max_total_pages,
            areas_only=areas_only,
            config=config
        )
        self.stdout.write(f'Задача Celery отправлена! Task ID: {task.id}')
        if options.get('wait'):
            self.stdout.write('Ожидание завершения задачи...')
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
                self.stdout.write('Задача завершена!')
                self.print_formatted_result(result)
            else:
                self.stdout.write(f'Ошибка при выполнении задачи: {task.result}')
        else:
            self.stdout.write('Проверьте статус задачи через Celery Flower или Django shell.') 