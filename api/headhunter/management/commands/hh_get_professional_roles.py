"""
Команда Django для получения списка профессиональных ролей с API HeadHunter.

Использование:
    python manage.py get_professional_roles [--output-file OUTPUT_FILE] [--format FORMAT]

Примеры:
    python manage.py get_professional_roles
    python manage.py get_professional_roles --output-file roles.json --format json
    python manage.py get_professional_roles --output-file roles.csv --format csv
"""

import json
import csv
import logging
from pathlib import Path
from typing import Any, Dict, List

from django.core.management.base import BaseCommand, CommandParser

from ...tasks import get_professional_roles_task

logger = logging.getLogger('modules.vacancies_parser.headhunter.management.commands')


class Command(BaseCommand):
    """
    Команда для получения списка профессиональных ролей с API HeadHunter.

    Позволяет сохранить результаты в файл в различных форматах.
    """

    help = 'Получение списка профессиональных ролей с API HeadHunter'

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Добавляет аргументы командной строки.

        Args:
            parser: Парсер аргументов командной строки
        """
        parser.add_argument(
            '--output-file',
            '-o',
            type=str,
            help='Путь к файлу для сохранения результатов'
        )

        parser.add_argument(
            '--format',
            '-f',
            choices=['json', 'csv'],
            default='json',
            help='Формат выходного файла (по умолчанию: json)'
        )

        parser.add_argument(
            '--pretty',
            action='store_true',
            help='Форматировать JSON с отступами (только для формата json)'
        )

    def handle(self, *args: tuple, **options: Dict[str, Any]) -> None:
        """
        Выполняет команду получения профессиональных ролей.

        Args:
            *args: Позиционные аргументы
            **options: Именованные аргументы
        """
        logger.info('Запуск команды получения профессиональных ролей')
        self.stdout.write(self.style.SUCCESS('Начинаем получение профессиональных ролей...'))  # type: ignore[attr-defined]

        try:
            # Выполняем задачу Celery синхронно
            logger.debug('Выполнение задачи get_professional_roles_task')
            result = get_professional_roles_task()

            if not result.get('success', False):
                error_msg = result.get('error', 'Неизвестная ошибка')
                logger.error(f'Ошибка при получении ролей: {error_msg}')
                self.stderr.write(self.style.ERROR(f'Ошибка при получении ролей: {error_msg}'))  # type: ignore[attr-defined]
                return

            roles: List[Dict[str, Any]] = result.get('roles', [])
            categories_count = result.get('categories_count', 0)
            total_roles = result.get('total_roles', 0)

            logger.info(f'Получено {total_roles} ролей из {categories_count} категорий')

            # Выводим статистику
            self.stdout.write(self.style.SUCCESS(  # type: ignore[attr-defined]
                f'Успешно получено {total_roles} профессиональных ролей из {categories_count} категорий'
            ))

            # Сохраняем в файл если указан путь
            output_file = options.get('output_file')
            if output_file:
                format_type: str = str(options.get('format', 'json'))
                pretty: bool = bool(options.get('pretty', False))
                try:
                    self._save_to_file(roles, str(output_file), format_type, pretty)
                    logger.info(f'Результаты сохранены в файл: {output_file}')
                    self.stdout.write(self.style.SUCCESS(  # type: ignore[attr-defined]
                        f'Результаты сохранены в файл: {output_file}'
                    ))
                except (IOError, OSError) as e:
                    error_msg = f'Ошибка при сохранении файла: {str(e)}'
                    logger.error(error_msg, exc_info=True)
                    self.stderr.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]
            else:
                # Выводим первые несколько ролей в консоль
                self._print_sample_roles(roles)

        except Exception as e:
            error_msg = f'Неожиданная ошибка: {str(e)}'
            logger.error(error_msg, exc_info=True)
            self.stderr.write(self.style.ERROR(error_msg))  # type: ignore[attr-defined]

    def _save_to_file(
        self,
        roles: List[Dict[str, Any]],
        file_path: str,
        format_type: str,
        pretty: bool
    ) -> None:
        """
        Сохраняет роли в файл.

        Args:
            roles: Список ролей (словари)
            file_path: Путь к файлу
            format_type: Формат файла ('json' или 'csv')
            pretty: Форматировать JSON с отступами

        Raises:
            IOError: При ошибках записи файла
            OSError: При ошибках создания директории
            ValueError: При неверном формате файла
        """
        if not roles:
            logger.warning('Список ролей пуст, файл не будет создан')
            return

        # Если путь относительный, сохраняем в директорию config модуля
        if not Path(file_path).is_absolute():
            config_dir = Path(__file__).parent.parent.parent / 'config'
            path = config_dir / file_path
        else:
            path = Path(file_path)

        # Создаем директорию если её нет
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f'Ошибка при создании директории {path.parent}: {e}')
            raise

        # Валидация формата
        if format_type not in ['json', 'csv']:
            raise ValueError(f'Неподдерживаемый формат: {format_type}')

        logger.debug(f'Сохранение {len(roles)} ролей в файл {path} (формат: {format_type})')

        if format_type == 'json':
            indent = 2 if pretty else None
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(roles, f, ensure_ascii=False, indent=indent)
                logger.info(f'Успешно сохранено {len(roles)} ролей в JSON файл: {path}')
            except (IOError, OSError) as e:
                logger.error(f'Ошибка при записи JSON файла {path}: {e}')
                raise

        elif format_type == 'csv':
            # Определяем поля из первой роли
            if not roles:
                logger.warning('Список ролей пуст, CSV файл не будет создан')
                return

            fieldnames = list(roles[0].keys()) if roles else []

            try:
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(roles)
                logger.info(f'Успешно сохранено {len(roles)} ролей в CSV файл: {path}')
            except (IOError, OSError) as e:
                logger.error(f'Ошибка при записи CSV файла {path}: {e}')
                raise

    def _print_sample_roles(self, roles: List[Dict[str, Any]], limit: int = 50) -> None:
        """
        Выводит пример ролей в консоль.

        Args:
            roles: Список ролей (словари)
            limit: Максимальное количество для вывода
        """
        if not roles:
            self.stdout.write('Роли не найдены.')
            return

        self.stdout.write('\nПримеры ролей:')
        self.stdout.write('-' * 50)

        for i, role in enumerate(roles[:limit], 1):
            role_id = role.get('id', 'N/A')
            name = role.get('name', 'N/A')
            self.stdout.write(f'{i:2d}. [{role_id}] {name}')

        if len(roles) > limit:
            self.stdout.write(f'... и ещё {len(roles) - limit} ролей')
        self.stdout.write(f'\nВсего ролей: {len(roles)}')
