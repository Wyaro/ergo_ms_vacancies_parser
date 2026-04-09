from django.core.management.base import BaseCommand
from django.db.models import Q

from ...models import SuperJobVacancy


class Command(BaseCommand):
    help = 'Просмотр вакансий SuperJob из базы данных'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            type=int,
            help='ID записи в базе данных',
        )
        parser.add_argument(
            '--superjob-id',
            type=str,
            help='ID вакансии на SuperJob',
        )
        parser.add_argument(
            '--search',
            type=str,
            help='Поиск по названию, компании, описанию',
        )
        parser.add_argument(
            '--city',
            type=str,
            help='Фильтр по городу',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Количество записей (по умолчанию 20)',
        )
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Смещение от начала (для пагинации)',
        )
        parser.add_argument(
            '--salary-min',
            type=int,
            help='Минимальная зарплата',
        )
        parser.add_argument(
            '--active',
            action='store_true',
            help='Только активные вакансии',
        )
        parser.add_argument(
            '--count',
            action='store_true',
            help='Только количество вакансий (без вывода списка)',
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='Полный вывод (с описанием)',
        )

    def handle(self, *args, **options):
        record_id = options.get('id')
        superjob_id = options.get('superjob_id')

        if record_id:
            self._show_single(pk=record_id, full=True)
            return

        if superjob_id:
            self._show_single(superjob_id=superjob_id, full=True)
            return

        queryset = SuperJobVacancy.objects.all()

        search = options.get('search')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(company_name__icontains=search)
                | Q(description__icontains=search)
            )

        city = options.get('city')
        if city:
            queryset = queryset.filter(city__icontains=city)

        salary_min = options.get('salary_min')
        if salary_min:
            queryset = queryset.filter(
                Q(salary_from__gte=salary_min) | Q(salary_to__gte=salary_min)
            )

        if options.get('active'):
            queryset = queryset.filter(is_active=True)

        total = queryset.count()

        if options.get('count'):
            self.stdout.write(f"Всего вакансий: {total}")
            return

        limit = options['limit']
        offset = options['offset']
        vacancies = queryset[offset:offset + limit]

        self.stdout.write(f"\nВакансии SuperJob ({offset + 1}-{min(offset + limit, total)} из {total}):\n")
        self.stdout.write("-" * 90)

        full = options.get('full', False)

        for vac in vacancies:
            self._print_vacancy(vac, full)
            self.stdout.write("-" * 90)

        if offset + limit < total:
            next_offset = offset + limit
            self.stdout.write(
                f"\nСледующая страница: --offset {next_offset} --limit {limit}"
            )

    def _show_single(self, pk=None, superjob_id=None, full=True):
        try:
            if pk:
                vac = SuperJobVacancy.objects.get(pk=pk)
            else:
                vac = SuperJobVacancy.objects.get(superjob_id=superjob_id)
        except SuperJobVacancy.DoesNotExist:
            lookup = f"ID={pk}" if pk else f"superjob_id={superjob_id}"
            self.stdout.write(self.style.ERROR(f"Вакансия не найдена: {lookup}"))
            return

        self.stdout.write("")
        self._print_vacancy(vac, full)

    def _print_vacancy(self, vac, full=False):
        salary = self._format_salary(vac)

        self.stdout.write(f"  [{vac.id}] {vac.title}")
        self.stdout.write(f"  Компания:  {vac.company_name}")
        self.stdout.write(f"  Город:     {vac.city or '-'}")
        self.stdout.write(f"  Зарплата:  {salary}")
        self.stdout.write(f"  Опыт:      {vac.experience_level or '-'}")
        self.stdout.write(f"  Занятость: {vac.employment_type or '-'}")
        self.stdout.write(f"  Дата:      {vac.published_at.strftime('%d.%m.%Y') if vac.published_at else '-'}")
        self.stdout.write(f"  SJ ID:     {vac.superjob_id}")
        self.stdout.write(f"  URL:       {vac.url}")

        if full:
            self.stdout.write(f"  Роль:      {vac.professional_role or '-'}")
            self.stdout.write(f"  График:    {vac.schedule_type or '-'}")
            self.stdout.write(f"  Активна:   {'Да' if vac.is_active else 'Нет'}")
            self.stdout.write(f"  Версия:    {vac.current_version}")

            if vac.skills:
                self.stdout.write(f"  Навыки:    {', '.join(vac.skills[:10])}")

            if vac.description:
                desc = vac.description[:500]
                if len(vac.description) > 500:
                    desc += '...'
                self.stdout.write(f"\n  Описание:\n  {desc}\n")

    @staticmethod
    def _format_salary(vac):
        if not vac.salary_from and not vac.salary_to:
            return 'Не указана'

        currency = vac.salary_currency or 'RUB'
        gross = ' (до вычета)' if vac.salary_gross else ''

        if vac.salary_from and vac.salary_to:
            return f"{vac.salary_from} - {vac.salary_to} {currency}{gross}"
        if vac.salary_from:
            return f"от {vac.salary_from} {currency}{gross}"
        return f"до {vac.salary_to} {currency}{gross}"
