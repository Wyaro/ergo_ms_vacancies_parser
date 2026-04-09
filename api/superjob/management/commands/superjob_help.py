from django.core.management.base import BaseCommand


COMMANDS = [
    {
        'name': 'parse_superjob_vacancies',
        'description': 'Парсинг вакансий с SuperJob (основная команда)',
        'args': [
            ('--text <str>', 'Текст для поиска вакансий'),
            ('--town <str>', 'Город для поиска'),
            ('--max-pages <int>', 'Максимум страниц (по умолчанию 5)'),
            ('--delay <float>', 'Задержка между запросами в секундах'),
            ('--all', 'Универсальный парсинг по набору популярных запросов'),
            ('--catalogues', 'Парсинг по каталогам (отраслям) SuperJob'),
            ('--catalogue-ids <str>', 'ID каталогов через запятую (33,76,381)'),
            ('--max-pages-per-catalogue <int>', 'Максимум страниц на каталог (по умолчанию 10)'),
            ('--list-catalogues', 'Вывести список всех каталогов и выйти'),
            ('--max', 'Максимальный режим: 500 страниц (до 50 000 вакансий)'),
            ('--vacancy-id <str>', 'Получить детали конкретной вакансии по ID'),
            ('--config <path>', 'Путь к JSON-конфигурации (по умолчанию config.json)'),
            ('--api-key <str>', 'API ключ SuperJob (переопределяет env)'),
            ('--celery', 'Запустить задачу через Celery (асинхронно)'),
            ('--wait', 'Дождаться завершения Celery-задачи'),
        ],
        'examples': [
            'ergoms api parse_superjob_vacancies --text "Python"',
            'ergoms api parse_superjob_vacancies --text "Django" --town "Москва" --max',
            'ergoms api parse_superjob_vacancies --catalogues',
            'ergoms api parse_superjob_vacancies --catalogues --catalogue-ids 33,381 --max',
            'ergoms api parse_superjob_vacancies --all --celery --wait',
            'ergoms api parse_superjob_vacancies --list-catalogues',
        ],
    },
    {
        'name': 'parse_superjob_vacancy',
        'description': 'Получение одной вакансии с SuperJob по ID (с возможностью сохранения)',
        'args': [
            ('vacancy_id', 'ID вакансии на SuperJob (обязательный)'),
            ('--api-key <str>', 'API ключ SuperJob (переопределяет env)'),
            ('--save', 'Сохранить вакансию в базу данных'),
        ],
        'examples': [
            'ergoms api parse_superjob_vacancy 12345678',
            'ergoms api parse_superjob_vacancy 12345678 --save',
        ],
    },
    {
        'name': 'show_superjob_vacancies',
        'description': 'Просмотр вакансий SuperJob из базы данных',
        'args': [
            ('--id <int>', 'ID записи в базе данных'),
            ('--superjob-id <str>', 'ID вакансии на SuperJob'),
            ('--search <str>', 'Поиск по названию, компании, описанию'),
            ('--city <str>', 'Фильтр по городу'),
            ('--salary-min <int>', 'Минимальная зарплата'),
            ('--active', 'Только активные вакансии'),
            ('--limit <int>', 'Количество записей (по умолчанию 20)'),
            ('--offset <int>', 'Смещение от начала (пагинация)'),
            ('--count', 'Только количество вакансий'),
            ('--full', 'Полный вывод с описанием'),
        ],
        'examples': [
            'ergoms api show_superjob_vacancies',
            'ergoms api show_superjob_vacancies --id 42',
            'ergoms api show_superjob_vacancies --search "Python" --city "Москва"',
            'ergoms api show_superjob_vacancies --salary-min 150000 --active',
            'ergoms api show_superjob_vacancies --count',
        ],
    },
    {
        'name': 'superjob_help',
        'description': 'Справка по всем командам SuperJob (эта команда)',
        'args': [],
        'examples': [
            'ergoms api superjob_help',
        ],
    },
]


class Command(BaseCommand):
    help = 'Справка по всем командам парсинга SuperJob'

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write("  SuperJob - Парсер вакансий | Справка по командам")
        self.stdout.write("=" * 80)
        self.stdout.write("")

        for cmd in COMMANDS:
            self.stdout.write(f"  ergoms api {cmd['name']}")
            self.stdout.write(f"  {cmd['description']}")
            self.stdout.write("")

            if cmd['args']:
                self.stdout.write("  Параметры:")
                max_arg_len = max(len(a[0]) for a in cmd['args'])
                for arg_name, arg_desc in cmd['args']:
                    padding = ' ' * (max_arg_len - len(arg_name) + 2)
                    self.stdout.write(f"    {arg_name}{padding}{arg_desc}")
                self.stdout.write("")

            if cmd['examples']:
                self.stdout.write("  Примеры:")
                for ex in cmd['examples']:
                    self.stdout.write(f"    {ex}")
                self.stdout.write("")

            self.stdout.write("-" * 80)
            self.stdout.write("")

        self.stdout.write("  API эндпоинты (требуют авторизации):")
        self.stdout.write("    GET  /api/vacancies_parser/superjob/vacancies/          Список вакансий")
        self.stdout.write("    GET  /api/vacancies_parser/superjob/vacancies/{id}/      Одна вакансия")
        self.stdout.write("    GET  /api/vacancies_parser/superjob/vacancies/stats/     Статистика")
        self.stdout.write("    POST /api/vacancies_parser/superjob/parsing/parse_by_text/        По тексту")
        self.stdout.write("    POST /api/vacancies_parser/superjob/parsing/parse_all/            Универсальный")
        self.stdout.write("    POST /api/vacancies_parser/superjob/parsing/parse_by_catalogues/  По каталогам")
        self.stdout.write("    GET  /api/vacancies_parser/superjob/parsing/catalogues/           Список каталогов")
        self.stdout.write("")
        self.stdout.write("=" * 80)
