"""
Вывод количества записей о вакансиях по площадкам и по нормализованной таблице.

Использование:
    ergoms api vacancy_stats
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from modules.vacancies_parser.api.core.normalized_models import NormalizedVacancy


class Command(BaseCommand):
    help = 'Количество записей о вакансиях по площадкам (таблицы vpm_*) и по нормализованной таблице vpm_vacancy'

    def handle(self, *args, **options):
        self.stdout.write('')
        self.stdout.write('=== Таблицы по площадкам (сырые данные) ===')
        self.stdout.write('')

        hh_count = hc_count = sj_count = 0
        try:
            from modules.vacancies_parser.api.headhunter.models import Vacancy as HH
            hh_count = HH.objects.count()
            self.stdout.write(f'  vpm_hh_vacancy (HeadHunter):     {hh_count}')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  vpm_hh_vacancy (HeadHunter):     ошибка — {e}'))

        try:
            from modules.vacancies_parser.api.habr_career.models import Vacancy as HC
            hc_count = HC.objects.count()
            self.stdout.write(f'  vpm_hc_vacancy (Habr Career):   {hc_count}')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  vpm_hc_vacancy (Habr Career):   ошибка — {e}'))

        try:
            from modules.vacancies_parser.api.superjob.models import SuperJobVacancy as SJ
            sj_count = SJ.objects.count()
            self.stdout.write(f'  vpm_sj_vacancy (SuperJob):      {sj_count}')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'  vpm_sj_vacancy (SuperJob):      ошибка — {e}'))

        self.stdout.write('')
        self.stdout.write('=== Нормализованная таблица (итоговая) ===')
        self.stdout.write('')

        total = NormalizedVacancy.objects.count()
        self.stdout.write(f'  vpm_vacancy (всего):             {total}')

        by_source = (
            NormalizedVacancy.objects
            .values('source')
            .annotate(c=Count('id'))
            .order_by('source')
        )
        for row in by_source:
            self.stdout.write(f"  vpm_vacancy по source={row['source']}: {row['c']}")

        self.stdout.write('')
        if hh_count > 0 and (hc_count == 0 or sj_count == 0):
            self.stdout.write(self.style.WARNING('Подсказка: при ненулевом HH и нулях по другим площадкам проверьте:'))
            if sj_count == 0:
                self.stdout.write(self.style.WARNING('  - SUPERJOB_API_KEY в .env (задачи по расписанию берут ключ из env)'))
            self.stdout.write(self.style.WARNING('  - воркер слушает очереди habr_career и superjob (ergoms start-worker без --worker или с конфигом all)'))
            self.stdout.write('')
