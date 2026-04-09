"""
Команда для очистки таблицы вакансий HeadHunter.
"""

import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Tuple, cast

from django.core.management.base import BaseCommand, CommandParser
from django.core.management.color import no_style
from django.utils import timezone
from django.db import transaction, connection, DatabaseError

from modules.vacancies_parser.api.headhunter.models import (
    Vacancy,
    VacancyVersion,
    VacancyChangeHistory,
)

logger = logging.getLogger('modules.vacancies_parser.headhunter')
VacancyModel = cast(Any, Vacancy)
VacancyVersionModel = cast(Any, VacancyVersion)
VacancyChangeHistoryModel = cast(Any, VacancyChangeHistory)
transaction = cast(Any, transaction)

TEXT: Dict[str, str] = {
    'line_sep': '-' * 64,
    'header': 'Очистка таблицы вакансий HeadHunter',
    'need_filter': 'Необходимо указать хотя бы один параметр фильтрации.',
    'no_items': 'Нет вакансий для удаления.',
    'dry_run': '[DRY RUN] Удаление не выполнено.',
    'confirm_prompt': 'Удалить {count} вакансий? (yes/no): ',
    'aborted': 'Операция отменена.',
    'delete_start': 'Удаление...',
    'delete_done': 'Удаление завершено.',
    'reset_seq': 'Сброс секвенций...',
    'state': 'Текущее состояние базы:',
}


class Command(BaseCommand):
    help = 'Очистка таблицы вакансий HeadHunter'

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Добавляет аргументы командной строки.

        Args:
            parser: Парсер аргументов командной строки
        """
        parser.add_argument(
            '--all',
            action='store_true',
            help='Удалить ВСЕ вакансии (требует подтверждения)'
        )
        parser.add_argument(
            '--older-than',
            type=int,
            metavar='DAYS',
            help='Удалить вакансии старше указанного количества дней (должно быть положительным числом)'
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

    def handle(self, *args: tuple, **options: Dict[str, Any]) -> None:
        """
        Выполняет команду очистки вакансий.

        Args:
            *args: Позиционные аргументы
            **options: Именованные аргументы
        """
        logger.info('Запуск команды очистки вакансий')
        ctx = self._parse_options(options)
        self._print_header(ctx)

        # Валидация параметров
        validation_error = self._validate_parameters(ctx)
        if validation_error:
            self._out(validation_error, ctx)
            logger.warning(f'Валидация не пройдена: {validation_error}')
            return

        valid, filters_applied = self._validate_filters(ctx)
        if not valid:
            logger.warning('Фильтры не указаны')
            return

        logger.debug(f'Применённые фильтры: {filters_applied}')
        queryset = self._build_queryset(ctx)
        summary = self._collect_summary(queryset, filters_applied)
        logger.info(f'Найдено для удаления: {summary["vacancy_count"]} вакансий, '
                   f'{summary["version_count"]} версий, {summary["history_count"]} записей истории')

        if ctx['json_output']:
            self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        self._print_summary(summary, ctx)

        if summary['vacancy_count'] == 0:
            return

        if ctx['dry_run']:
            self._print_dry_run(queryset, summary, ctx)
            return

        if not ctx['force']:
            if not self._confirm(summary['vacancy_count']):
                self._out(TEXT['aborted'], ctx)
                return

        self._perform_deletion(queryset, summary, ctx, filters_applied)

    def _parse_options(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Парсит и нормализует опции командной строки.

        Args:
            options: Словарь опций из командной строки

        Returns:
            Нормализованный словарь опций
        """
        return {
            'delete_all': bool(options.get('all')),
            'older_than_days': options.get('older_than'),
            'city': options.get('city'),
            'company': options.get('company'),
            'inactive_only': bool(options.get('inactive')),
            'force': bool(options.get('force')),
            'dry_run': bool(options.get('dry_run')),
            'json_output': bool(options.get('json_output')),
            'quiet': bool(options.get('quiet')),
        }

    def _validate_parameters(self, ctx: Dict[str, Any]) -> str:
        """
        Валидирует параметры команды.

        Args:
            ctx: Контекст с опциями

        Returns:
            Сообщение об ошибке или пустая строка если всё ок
        """
        if ctx['older_than_days'] is not None and ctx['older_than_days'] <= 0:
            return 'Параметр --older-than должен быть положительным числом'
        return ''

    def _print_header(self, ctx: Dict[str, Any]) -> None:
        """
        Выводит заголовок команды.

        Args:
            ctx: Контекст с опциями
        """
        if ctx['json_output'] or ctx['quiet']:
            return
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(TEXT['header'])
        self.stdout.write(TEXT['line_sep'])

    def _validate_filters(self, ctx: Dict[str, Any]) -> Tuple[bool, List[str]]:
        filters_applied: List[str] = []
        if ctx['delete_all']:
            filters_applied.append('ВСЕ ВАКАНСИИ')
            return True, filters_applied

        if any([ctx['older_than_days'], ctx['city'], ctx['company'], ctx['inactive_only']]):
            return True, filters_applied

        self._out(TEXT['need_filter'], ctx)
        return False, filters_applied

    def _build_queryset(self, ctx: Dict[str, Any]):
        """
        Строит queryset на основе фильтров.

        Args:
            ctx: Контекст с опциями

        Returns:
            QuerySet для удаления
        """
        queryset = VacancyModel.objects.all()
        if ctx['delete_all']:
            logger.debug('Режим удаления: ВСЕ ВАКАНСИИ')
            return queryset

        filters_applied = []
        if ctx['older_than_days']:
            cutoff_date = timezone.now() - timedelta(days=ctx['older_than_days'])
            queryset = queryset.filter(published_at__lt=cutoff_date)
            filters_applied.append(f'старше {ctx["older_than_days"]} дней')
        if ctx['city']:
            queryset = queryset.filter(city__icontains=ctx['city'])
            filters_applied.append(f'город: {ctx["city"]}')
        if ctx['company']:
            queryset = queryset.filter(company_name__icontains=ctx['company'])
            filters_applied.append(f'компания: {ctx["company"]}')
        if ctx['inactive_only']:
            queryset = queryset.filter(is_active=False)
            filters_applied.append('неактивные')

        if filters_applied:
            logger.debug(f'Применены фильтры: {", ".join(filters_applied)}')

        return queryset

    def _collect_summary(self, queryset, filters_applied: List[str]) -> Dict[str, Any]:
        """
        Собирает статистику по объектам для удаления.

        Args:
            queryset: QuerySet вакансий для удаления
            filters_applied: Список применённых фильтров

        Returns:
            Словарь со статистикой
        """
        logger.debug('Сбор статистики для удаления')
        vacancy_count = queryset.count()
        vacancy_ids = list(queryset.values_list('id', flat=True)) if vacancy_count > 0 else []

        version_count = 0
        history_count = 0
        if vacancy_ids:
            version_count = VacancyVersionModel.objects.filter(vacancy_id__in=vacancy_ids).count()
            history_count = VacancyChangeHistoryModel.objects.filter(vacancy_id__in=vacancy_ids).count()

        return {
            'filters': filters_applied,
            'vacancy_count': vacancy_count,
            'version_count': version_count,
            'history_count': history_count,
        }

    def _print_summary(self, summary: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        """
        Выводит сводку по объектам для удаления.

        Args:
            summary: Статистика удаления
            ctx: Контекст с опциями
        """
        if ctx['quiet']:
            return
        self.stdout.write('Применённые фильтры:')
        if summary['filters']:
            for f in summary['filters']:
                self.stdout.write(f'  - {f}')
        else:
            self.stdout.write('  - (указаны выборочные фильтры)')
        self.stdout.write('')
        self.stdout.write('Будет удалено:')
        self.stdout.write(f'  - Вакансий: {summary["vacancy_count"]}')
        self.stdout.write(f'  - Версий вакансий: {summary["version_count"]}')
        self.stdout.write(f'  - Записей истории изменений: {summary["history_count"]}')
        self.stdout.write('')
        if summary['vacancy_count'] == 0:
            self.stdout.write(TEXT['no_items'])

    def _print_dry_run(self, queryset, summary: Dict[str, Any], ctx: Dict[str, Any]) -> None:
        """
        Выводит примеры вакансий для удаления в режиме dry-run.

        Args:
            queryset: QuerySet вакансий для удаления
            summary: Статистика удаления
            ctx: Контекст с опциями
        """
        logger.info('Режим dry-run: показ примеров без удаления')
        if not ctx['quiet']:
            self.stdout.write(TEXT['dry_run'])
        sample_vacancies = list(queryset[:10])
        if not sample_vacancies:
            logger.debug('Нет примеров для показа')
            return
        if ctx['json_output']:
            self.stdout.write(json.dumps({
                'vacancy_count': summary['vacancy_count'],
                'samples': [
                    {'hh_id': v.hh_id, 'title': v.title, 'company': v.company_name, 'city': v.city}
                    for v in sample_vacancies
                ],
            }, ensure_ascii=False, indent=2))
            return
        if ctx['quiet']:
            return
        self.stdout.write('Примеры вакансий для удаления:')
        for v in sample_vacancies:
            self.stdout.write(f'  - [{v.hh_id}] {v.title} ({v.company_name}, {v.city})')
        if summary['vacancy_count'] > 10:
            self.stdout.write(f'  ... и ещё {summary["vacancy_count"] - 10} вакансий')

    def _confirm(self, vacancy_count: int) -> bool:
        """
        Запрашивает подтверждение у пользователя.

        Args:
            vacancy_count: Количество вакансий для удаления

        Returns:
            True если пользователь подтвердил, False иначе
        """
        try:
            confirm = input(TEXT['confirm_prompt'].format(count=vacancy_count))
            result = confirm.lower() in ['yes', 'y', 'да']
            logger.info(f'Подтверждение удаления: {"подтверждено" if result else "отменено"}')
            return result
        except (EOFError, KeyboardInterrupt):
            logger.warning('Прервано пользователем при подтверждении')
            return False

    def _perform_deletion(
        self,
        queryset,
        summary: Dict[str, Any],
        ctx: Dict[str, Any],
        filters_applied: List[str]
    ) -> None:
        """
        Выполняет удаление вакансий и связанных данных.

        Args:
            queryset: QuerySet вакансий для удаления
            summary: Статистика удаления
            ctx: Контекст с опциями
            filters_applied: Список применённых фильтров

        Raises:
            DatabaseError: При ошибках работы с БД
        """
        logger.info(f'Начало удаления: {summary["vacancy_count"]} вакансий')
        try:
            with transaction.atomic():  # type: ignore[misc]
                self._out(TEXT['delete_start'], ctx)

                vacancy_ids = list(queryset.values_list('id', flat=True))
                if not vacancy_ids:
                    logger.warning('Список ID вакансий пуст')
                    self._out(TEXT['no_items'], ctx)
                    return

                logger.debug(f'Удаление истории изменений для {len(vacancy_ids)} вакансий')
                history_deleted = VacancyChangeHistoryModel.objects.filter(
                    vacancy_id__in=vacancy_ids
                ).delete()
                logger.debug(f'Удалено записей истории: {history_deleted[0]}')

                logger.debug(f'Удаление версий для {len(vacancy_ids)} вакансий')
                versions_deleted = VacancyVersionModel.objects.filter(
                    vacancy_id__in=vacancy_ids
                ).delete()
                logger.debug(f'Удалено версий: {versions_deleted[0]}')

                batch_size = 1000
                total_deleted = 0
                total_batches = (len(vacancy_ids) + batch_size - 1) // batch_size
                logger.debug(f'Удаление вакансий батчами: {total_batches} батчей по {batch_size}')

                for i in range(0, len(vacancy_ids), batch_size):
                    batch_ids = vacancy_ids[i:i + batch_size]
                    batch_num = (i // batch_size) + 1
                    logger.debug(f'Удаление батча {batch_num}/{total_batches} ({len(batch_ids)} вакансий)')

                    try:
                        deleted_count, _ = VacancyModel.objects.filter(
                            id__in=batch_ids
                        ).delete()
                        total_deleted += deleted_count
                        logger.debug(f'Батч {batch_num}: удалено {deleted_count} вакансий')

                        if len(vacancy_ids) > batch_size and not ctx['quiet'] and not ctx['json_output']:
                            self.stdout.write(f'  - Удалено {total_deleted} из {len(vacancy_ids)} вакансий...')
                    except DatabaseError as e:
                        logger.error(f'Ошибка при удалении батча {batch_num}: {e}')
                        raise

                if not ctx['json_output']:
                    self._out(TEXT['delete_done'], ctx)
                    self.stdout.write(f'Всего удалено объектов: {total_deleted + history_deleted[0] + versions_deleted[0]}')
                    self.stdout.write(f'  - Вакансий: {total_deleted}')
                    self.stdout.write(f'  - Версий: {versions_deleted[0]}')
                    self.stdout.write(f'  - Записей истории: {history_deleted[0]}')

                remaining_vacancies = VacancyModel.objects.filter(id__in=vacancy_ids).count()
                if remaining_vacancies > 0:
                    logger.warning(f'Осталось {remaining_vacancies} вакансий, которые не были удалены через ORM')
                    if not ctx['json_output']:
                        self.stdout.write(
                            f'ВНИМАНИЕ: Осталось {remaining_vacancies} вакансий, которые не были удалены.'
                        )

                    remaining_ids = list(
                        VacancyModel.objects.filter(id__in=vacancy_ids).values_list('id', flat=True)
                    )
                    if remaining_ids:
                        logger.debug(f'Попытка удаления {len(remaining_ids)} вакансий через прямой SQL')
                        try:
                            with connection.cursor() as cursor:
                                placeholders = ','.join(['%s'] * len(remaining_ids))
                                table_name = VacancyModel._meta.db_table
                                cursor.execute(
                                    f'DELETE FROM {table_name} WHERE id IN ({placeholders})',
                                    remaining_ids
                                )
                                sql_deleted = cursor.rowcount
                                logger.info(f'Удалено через SQL: {sql_deleted} вакансий')
                                if sql_deleted > 0 and not ctx['json_output']:
                                    self.stdout.write(f'Удалено через SQL: {sql_deleted} вакансий')
                        except DatabaseError as e:
                            logger.error(f'Ошибка при удалении через SQL: {e}')
                            if not ctx['json_output']:
                                self.stdout.write(f'Ошибка при удалении через SQL: {e}')

                self._out(TEXT['reset_seq'], ctx)
                self._reset_sequences(ctx)

                if not ctx['json_output'] and not ctx['quiet']:
                    self._out(TEXT['state'], ctx)
                    self.stdout.write(f'  - Вакансий: {VacancyModel.objects.count()}')
                    self.stdout.write(f'  - Версий: {VacancyVersionModel.objects.count()}')
                    self.stdout.write(f'  - Записей истории: {VacancyChangeHistoryModel.objects.count()}')

                logger.info(
                    'Очистка вакансий выполнена: удалено %d вакансий, %d версий, %d записей истории, фильтры: %s',
                    total_deleted,
                    versions_deleted[0],
                    history_deleted[0],
                    ', '.join(filters_applied) if filters_applied else '(выборочные фильтры)'
                )

                if ctx['json_output']:
                    self.stdout.write(json.dumps({
                        'deleted_total': total_deleted,
                        'history_deleted': history_deleted[0],
                        'versions_deleted': versions_deleted[0],
                    }, ensure_ascii=False, indent=2))

        except DatabaseError as e:
            error_msg = f'Ошибка базы данных при удалении: {e}'
            self._out(error_msg, ctx)
            logger.exception('Ошибка базы данных при очистке вакансий')
            raise
        except Exception as e:
            error_msg = f'Неожиданная ошибка при удалении: {e}'
            self._out(error_msg, ctx)
            logger.exception('Неожиданная ошибка при очистке вакансий')
            raise

    def _reset_sequences(self, ctx: Dict[str, Any]) -> None:
        """
        Сбрасывает секвенции для моделей.

        Args:
            ctx: Контекст с опциями
        """
        logger.debug('Сброс секвенций БД')
        models_to_reset = [VacancyModel, VacancyVersionModel, VacancyChangeHistoryModel]
        sql_statements = connection.ops.sequence_reset_sql(no_style(), models_to_reset)
        if not sql_statements:
            logger.debug('Нет секвенций для сброса')
            return

        try:
            with connection.cursor() as cursor:
                for statement in sql_statements:
                    logger.debug(f'Выполнение SQL: {statement[:100]}...')
                    cursor.execute(statement)
            logger.info(f'Сброшено {len(sql_statements)} секвенций')
            if not ctx['quiet'] and not ctx['json_output']:
                self.stdout.write('Секвенции успешно сброшены.')
        except DatabaseError as e:
            logger.error(f'Ошибка при сбросе секвенций: {e}')
            if not ctx['quiet'] and not ctx['json_output']:
                self.stdout.write(f'ВНИМАНИЕ: Ошибка при сбросе секвенций: {e}')

    def _out(self, message: str, ctx: Dict[str, Any]) -> None:
        """
        Выводит сообщение с учётом режимов quiet и json-output.

        Args:
            message: Текст сообщения
            ctx: Контекст с опциями
        """
        if ctx['json_output'] or ctx['quiet']:
            return
        self.stdout.write(message)
