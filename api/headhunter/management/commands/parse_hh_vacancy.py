from django.core.management.base import BaseCommand
from modules.vacancies_parser.api.headhunter.models import Vacancy
import sys
import time
from modules.vacancies_parser.api.headhunter.tasks import (
    parse_single_vacancy_task,
    parse_vacancies_batch_task,
)


class Command(BaseCommand):
    """
    Команда для парсинга вакансий HeadHunter:
    - одиночная вакансия по ID;
    - массовая детализация вакансий, взятых из БД.
    """

    help = 'Парсинг вакансий с HeadHunter: одна вакансия по ID или массово из БД'

    def add_arguments(self, parser):
        # ID вакансии делаем необязательным, чтобы поддержать режим --from-db
        parser.add_argument(
            'vacancy_id',
            type=str,
            nargs='?',
            help='ID вакансии на HeadHunter'
        )

        parser.add_argument(
            '--force-update',
            action='store_true',
            help='Принудительно обновить существующую вакансию'
        )

        parser.add_argument(
            '--wait',
            action='store_true',
            help='Дождаться завершения задачи Celery и вывести результат'
        )

        # Режим массовой детализации вакансий из БД
        parser.add_argument(
            '--from-db',
            action='store_true',
            help='Детализировать вакансии, выбранные из базы данных (черновики и т.п.)'
        )

        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Максимальное количество вакансий для обработки в режиме --from-db (по умолчанию 100)'
        )

    def print_formatted_result(self, result):
        if not isinstance(result, dict):
            self.stdout.write(f'Результат: {result}')
            return
        status = result.get('status')
        message = result.get('message', '')
        self.stdout.write(f'\nСтатус: {status}')
        if message:
            self.stdout.write(f'   - {message}')
        # Если есть ключевые поля вакансии, выводим их
        for key in ['title', 'company_name', 'city', 'salary_from', 'salary_to', 'salary_currency', 'url']:
            if key in result:
                self.stdout.write(f'   - {key}: {result[key]}')

    def _run_single_vacancy(self, vacancy_id: str, force_update: bool, wait: bool) -> None:
        """Обработка одной вакансии по ID через Celery-задачу."""
        task = parse_single_vacancy_task.delay(vacancy_id, force_update)  # type: ignore[call-arg]
        self.stdout.write(f'Задача Celery отправлена! Task ID: {task.id}')

        if not wait:
            self.stdout.write('Проверьте статус задачи через Celery Flower или Django shell.')
            return

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

    def _run_from_db(self, force_update: bool, wait: bool, limit: int) -> None:
        """
        Массовая детализация вакансий, выбранных из БД.

        Базовый критерий: вакансии с hh_id, помеченные как неактивные (черновики),
        которые, например, были созданы командой parse_hh_by_text_and_date.
        При необходимости фильтр можно уточнить.
        """
        queryset = Vacancy.objects.filter(  # type: ignore[attr-defined]
            is_active=False,
            hh_id__isnull=False,
        )

        if limit > 0:
            queryset = queryset[:limit]

        hh_ids = list(
            queryset.values_list('hh_id', flat=True)  # type: ignore[attr-defined]
        )

        if not hh_ids:
            self.stdout.write(
                'Нет вакансий для детализации (фильтр is_active=False, hh_id не пустой).'
            )
            return

        self.stdout.write(
            f'Найдено {len(hh_ids)} вакансий для детализации. Запуск batch-задачи Celery...'
        )

        task = parse_vacancies_batch_task.delay(
            [str(hh_id) for hh_id in hh_ids],
            bool(force_update),
        )  # type: ignore[call-arg]
        self.stdout.write(f'   Batch Task ID = {task.id}')

        if not wait:
            self.stdout.write(
                'Задача отправлена. Для отслеживания используйте Celery Flower или Django shell.'
            )
            return

        self.stdout.write('Ожидание завершения batch-задачи...')
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
            self.stdout.write('Batch-задача завершена!')
            # Краткое резюме
            if isinstance(result, dict):
                self.stdout.write(
                    f"   Всего: {result.get('total', '-')} | "
                    f"создано: {result.get('created', '-')} | "
                    f"обновлено: {result.get('updated', '-')} | "
                    f"без изменений: {result.get('no_changes', '-')} | "
                    f"ошибок: {result.get('errors', '-')}"
                )
        else:
            self.stdout.write(f'Ошибка при выполнении batch-задачи: {task.result}')

    def handle(self, *args, **options):
        from_db = options.get('from_db')
        force_update = options.get('force_update', False)
        wait = options.get('wait', False)

        if from_db:
            limit = options.get('limit') or 0
            self._run_from_db(force_update=force_update, wait=wait, limit=limit)
            return

        vacancy_id = options.get('vacancy_id')
        if not vacancy_id:
            self.stdout.write(
                'Не указан vacancy_id и не задан флаг --from-db. Нечего обрабатывать.'
            )
            return

        self._run_single_vacancy(vacancy_id=vacancy_id, force_update=force_update, wait=wait)