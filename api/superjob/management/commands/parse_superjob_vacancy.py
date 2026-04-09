import os
import traceback

from django.core.management.base import BaseCommand

from ...scripts import get_vacancy_details, parse_vacancy_data, save_vacancy_to_db


class Command(BaseCommand):
    help = 'Получение и сохранение детальной информации о вакансии SuperJob по ID'

    def add_arguments(self, parser):
        parser.add_argument(
            'vacancy_id',
            type=str,
            help='ID вакансии на SuperJob',
        )
        parser.add_argument(
            '--api-key',
            type=str,
            help='API ключ SuperJob (по умолчанию берется из env)',
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='Сохранить вакансию в базу данных',
        )

    def handle(self, *args, **options):
        vacancy_id = options['vacancy_id']
        api_key = options.get('api_key') or os.environ.get('SUPERJOB_API_KEY')

        if not api_key:
            self.stdout.write(
                self.style.ERROR(
                    'Ошибка: Не указан API ключ SuperJob. '
                    'Используйте --api-key или переменную SUPERJOB_API_KEY'
                )
            )
            return

        self.stdout.write(f"Получаем данные вакансии {vacancy_id}...")

        try:
            details = get_vacancy_details(vacancy_id, api_key)

            if not details:
                self.stdout.write(
                    self.style.ERROR(f'Вакансия {vacancy_id} не найдена или недоступна')
                )
                return

            self.stdout.write(self.style.SUCCESS(f'Вакансия найдена: {details.get("profession", "N/A")}'))
            self.stdout.write(f'   Компания: {details.get("firm_name", "N/A")}')
            self.stdout.write(f'   Зарплата: {details.get("payment_from", 0)} - {details.get("payment_to", 0)}')
            self.stdout.write(f'   Город: {details.get("town", {}).get("title", "N/A")}')

            if options.get('save'):
                parsed = parse_vacancy_data(details)
                vacancy = save_vacancy_to_db(parsed)
                if vacancy:
                    self.stdout.write(
                        self.style.SUCCESS(f'Вакансия сохранена в БД (ID: {vacancy.id})')
                    )
                else:
                    self.stdout.write(self.style.ERROR('Ошибка при сохранении вакансии'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка: {e}'))
            traceback.print_exc()
