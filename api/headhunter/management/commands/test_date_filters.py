from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple, Any
from ...scripts import HeadHunterParser


class Command(BaseCommand):
    """
    Команда для тестирования фильтров по дате парсера HeadHunter.
    
    Позволяет протестировать различные сценарии работы с датами:
    - Базовый поиск без фильтров
    - Поиск с фильтрами по дате
    - Работу с пагинацией и "хвостом" данных
    - Сегментированный сбор данных по временным интервалам
    """
    
    help = 'Тестирование фильтров по дате для парсера HeadHunter'
    
    # Константы API HeadHunter
    HH_MAX_RESULTS = 2000
    HH_MAX_PAGES = 20
    MAX_PER_PAGE = 100
    DEFAULT_AREA = 113  # Россия

    def add_arguments(self, parser):
        """Определение аргументов команды."""
        parser.add_argument(
            '--date-from',
            type=str,
            help='Дата начала периода (формат YYYY-MM-DD)'
        )
        parser.add_argument(
            '--date-to', 
            type=str,
            help='Дата окончания периода (формат YYYY-MM-DD)'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Количество дней для тестирования (если не указаны даты)'
        )
        parser.add_argument(
            '--text',
            type=str,
            default='Python разработчик',
            help='Текст для поиска'
        )
        parser.add_argument(
            '--per-page',
            type=int,
            default=50,
            help=f'Количество вакансий на странице (1-{self.MAX_PER_PAGE})'
        )
        parser.add_argument(
            '--max-records',
            type=int,
            default=0,
            help='Дополнительный лимит для сегментированного сбора (0 — без ограничений)'
        )
        parser.add_argument(
            '--segment-days',
            type=int,
            default=14,
            help='Длина одного сегмента в днях при сборе хвоста'
        )
        parser.add_argument(
            '--segments-count',
            type=int,
            default=5,
            help='Количество сегментов для проверки'
        )
        parser.add_argument(
            '--area',
            type=int,
            default=113,
            help='Регион поиска (по умолчанию 113 - Россия)'
        )
        parser.add_argument(
            '--show-vacancies',
            action='store_true',
            help='Показывать информацию о вакансиях'
        )

    def handle(self, *args, **options):
        """Основной метод выполнения команды."""
        try:
            self._validate_arguments(options)
            self._run_tests(options)
        except ValueError as e:
            self.stdout.write(f'[ERROR] Ошибка валидации: {e}')
        except Exception as e:
            self.stdout.write(f'[ERROR] Непредвиденная ошибка: {e}')

    def _validate_arguments(self, options: Dict[str, Any]) -> None:
        """Валидация входных параметров."""
        # Проверка per_page
        per_page = options['per_page']
        if not 1 <= per_page <= self.MAX_PER_PAGE:
            raise ValueError(f'per_page должен быть между 1 и {self.MAX_PER_PAGE}')
        
        # Проверка дат
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        
        if date_from and date_to:
            try:
                start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                
                if start_date > end_date:
                    raise ValueError('Дата начала не может быть больше даты окончания')
                
                if start_date > datetime.now().date():
                    raise ValueError('Дата начала не может быть в будущем')
                    
            except ValueError as e:
                raise ValueError(f'Неверный формат дат: {e}. Используйте YYYY-MM-DD')
        
        # Проверка дней
        if options['days'] <= 0:
            raise ValueError('Количество дней должно быть положительным числом')
        
        # Проверка сегментов
        if options['segment_days'] <= 0:
            raise ValueError('Длина сегмента должна быть положительным числом')
        
        if options['segments_count'] <= 0:
            raise ValueError('Количество сегментов должно быть положительным числом')

    def _run_tests(self, options: Dict[str, Any]) -> None:
        """Запуск всех тестов."""
        # Подготовка параметров
        test_params = self._prepare_test_parameters(options)
        
        self.stdout.write(f'\n[OK] Тестирование фильтров по дате ({test_params["period_desc"]})')
        self._print_test_parameters(test_params)
        self._print_collection_capabilities(test_params)
        
        # Создаем парсер
        parser = HeadHunterParser()
        
        # Запуск тестов
        self._test_basic_search(parser, test_params)
        self._test_date_filter_search(parser, test_params)
        self._test_segmented_search(parser, test_params)
        
        self.stdout.write('\n[OK] Все тесты завершены успешно!')

    def _prepare_test_parameters(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """Подготовка параметров для тестирования."""
        date_from = options.get('date_from')
        date_to = options.get('date_to')
        days = options['days']
        
        if date_from and date_to:
            period_desc = f'период {date_from} - {date_to}'
        else:
            date_to = datetime.now().strftime('%Y-%m-%d')
            date_from = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            period_desc = f'последние {days} дней'
        
        return {
            'date_from': date_from,
            'date_to': date_to,
            'period_desc': period_desc,
            'search_text': options['text'],
            'per_page': options['per_page'],
            'area': options['area'],
            'max_records': options['max_records'],
            'segment_days': options['segment_days'],
            'segments_count': options['segments_count'],
            'show_vacancies': options['show_vacancies']
        }

    def _print_test_parameters(self, params: Dict[str, Any]) -> None:
        """Вывод параметров тестирования."""
        info_table = [
            ('Период', params['period_desc']),
            ('Текст поиска', params['search_text']),
            ('Вакансий на странице', params['per_page']),
            ('Регион', params['area']),
            ('Доп. лимит сбора (0 — без ограничений)', params['max_records']),
            ('Длина сегмента', f"{params['segment_days']} дней"),
            ('Количество сегментов', params['segments_count'])
        ]
        
        self.stdout.write('')
        self._print_table(info_table)
        self.stdout.write('')

    def _print_collection_capabilities(self, params: Dict[str, Any]) -> None:
        """Выводит теоретические ограничения и максимум выгрузки."""
        per_page = max(params['per_page'], 1)
        max_per_request = min(self.HH_MAX_RESULTS, per_page * self.HH_MAX_PAGES)
        available_pages = min(self.HH_MAX_PAGES, (max_per_request + per_page - 1) // per_page)
        theoretical_segment_capacity = params['segments_count'] * max_per_request
        max_records = params['max_records']
        achievable_limit = (
            min(max_records, theoretical_segment_capacity)
            if max_records and max_records > 0
            else theoretical_segment_capacity
        )
        max_records_label = max_records if max_records and max_records > 0 else 'без ограничений'

        capability_table = [
            ('Максимум на один запрос HH', max_per_request),
            ('Доступных страниц HH', available_pages),
            ('Теоретический максимум по сегментам', theoretical_segment_capacity),
            ('Размер страницы сегментов', self.MAX_PER_PAGE),
            ('Лимит параметра max_records', max_records_label),
            ('Достижимый максимум выгрузки', achievable_limit)
        ]

        self.stdout.write('   Ограничения и потенциал выгрузки:')
        self._print_table(capability_table)
        self.stdout.write('')

    def _test_basic_search(self, parser: HeadHunterParser, params: Dict[str, Any]) -> None:
        """Тестирование базового поиска без фильтров по дате."""
        self.stdout.write('\n1. ПОИСК БЕЗ ФИЛЬТРОВ ПО ДАТЕ')
        
        result = self._safe_api_call(
            parser.search_vacancies,
            text=params['search_text'],
            area=params['area'],
            per_page=params['per_page'],
            page=0
        )
        
        if not result:
            self.stdout.write('   [WARN] Пустой результат или ошибка API')
            return
        
        self._print_search_results(result, 'Без фильтров даты')
        
        if params['show_vacancies'] and result.get('items'):
            self._print_vacancies_dates(result['items'], 'Первые вакансии без фильтров')

    def _test_date_filter_search(self, parser: HeadHunterParser, params: Dict[str, Any]) -> None:
        """Тестирование поиска с фильтрами по дате."""
        self.stdout.write('\n2. ПОИСК С ФИЛЬТРАМИ ПО ДАТЕ')
        
        result = self._safe_api_call(
            parser.search_vacancies,
            text=params['search_text'],
            area=params['area'],
            per_page=params['per_page'],
            page=0,
            date_from=params['date_from'],
            date_to=params['date_to']
        )
        
        if not result:
            self.stdout.write('   [WARN] Пустой результат или ошибка API')
            return
        
        self._print_search_results(result, 'С фильтрами даты')
        
        if not result.get('items'):
            self.stdout.write('   [WARN] Вакансии не найдены в указанный период')
            return
        
        # Анализ первых вакансий
        first_page_items = result['items']
        if params['show_vacancies']:
            self._print_vacancies_dates(first_page_items, 'Первые вакансии с фильтрами')
        
        # Анализ распределения дат
        self._analyze_date_distribution(first_page_items, 'на первой странице')
        
        # Получение и анализ "хвоста" данных
        self._analyze_tail_data(parser, result, params)

    def _analyze_tail_data(self, parser: HeadHunterParser, result: Dict[str, Any], params: Dict[str, Any]) -> None:
        """Анализ конечных данных (хвоста) результатов."""
        total_count = result.get('found', 0)
        items_count = len(result.get('items', []))
        
        if total_count <= items_count:
            self.stdout.write('   [INFO] Все данные поместились на одну страницу')
            return
        
        self.stdout.write('   [INFO] Анализ конечных данных...')
        
        tail_page = self._calculate_tail_page(total_count, params['per_page'])
        max_tail_page = self._hh_max_page_index(params['per_page'])
        effective_tail_page = min(tail_page, max_tail_page)
        
        if tail_page > max_tail_page:
            self.stdout.write(
                f'   [WARN] HH API ограничивает выдачу {self.HH_MAX_RESULTS} записей '
                f'(страница {effective_tail_page + 1} из {tail_page + 1})'
            )
        
        last_page_result, used_page = self._fetch_tail_page(
            parser=parser,
            desired_page=effective_tail_page,
            search_text=params['search_text'],
            per_page=params['per_page'],
            date_from=params['date_from'],
            date_to=params['date_to']
        )
        
        if last_page_result and used_page is not None:
            last_items = last_page_result.get('items', [])
            start_idx = used_page * params['per_page'] + 1
            
            self._print_vacancies_dates(
                last_items, 
                f'Последние вакансии (страница {used_page + 1})',
                tail=True
            )
            
            self._analyze_date_distribution(last_items, 'на последней странице')
            
            if used_page != tail_page:
                self.stdout.write(
                    f'   [WARN] Использована страница {used_page + 1} вместо {tail_page + 1}'
                )

    def _test_segmented_search(self, parser: HeadHunterParser, params: Dict[str, Any]) -> None:
        """Тестирование сегментированного поиска."""
        self.stdout.write(
            f'\n3. СЕГМЕНТИРОВАННЫЙ ПОИСК ({params["segment_days"]} дней на сегмент)'
        )
        
        segment_per_page = self.MAX_PER_PAGE
        segments_summary = self._collect_segmented_results(
            parser=parser,
            search_text=params['search_text'],
            segment_per_page=segment_per_page,
            date_from=params['date_from'],
            date_to=params['date_to'],
            max_records=params['max_records'],
            segment_days=params['segment_days'],
            segments_count=params['segments_count']
        )
        
        if not segments_summary:
            self.stdout.write('   [WARN] Не удалось собрать данные по сегментам')
            return
        
        self._print_segments_statistics(segments_summary, params['max_records'])

    def _safe_api_call(self, api_method, **kwargs) -> Optional[Dict[str, Any]]:
        """Безопасный вызов API с обработкой ошибок."""
        try:
            result = api_method(**kwargs)
            if result and result.get('errors'):
                self.stdout.write(f'   [ERROR] API ошибка: {result["errors"]}')
                return None
            return result
        except Exception as e:
            self.stdout.write(f'   [ERROR] Ошибка при вызове API: {e}')
            return None

    def _print_search_results(self, result: Dict[str, Any], title: str) -> None:
        """Вывод результатов поиска."""
        items_count = len(result.get('items', []))
        total_count = result.get('found', 0)
        pages_count = result.get('pages', 0)
        
        stats_table = [
            ('Найдено на странице', items_count),
            ('Всего найдено', total_count),
            ('Страниц', pages_count),
            ('Заполнение страницы', f'{(items_count/max(result.get("per_page", 1), 1)*100):.1f}%')
        ]
        
        self.stdout.write(f'   {title}:')
        self._print_table(stats_table)

    def _print_vacancies_dates(self, items: List[Dict], title: str, tail: bool = False, limit: int = 5) -> None:
        """Вывод дат вакансий."""
        if not items:
            self.stdout.write(f'   {title}: вакансии отсутствуют')
            return
        
        subset = items[-limit:] if tail else items[:limit]
        start_index = 1 if not tail else len(items) - len(subset) + 1
        
        date_table = []
        for i, item in enumerate(subset):
            published = item.get('published_at', '')
            date_str = published[:10] if published else 'нет даты'
            date_table.append((f'Вакансия {start_index + i}', date_str))
        
        self.stdout.write(f'   {title}:')
        self._print_table(date_table)
        
        if len(items) > limit:
            self.stdout.write(f'   ... показано {len(subset)} из {len(items)} вакансий')

    def _analyze_date_distribution(self, items: List[Dict], context: str) -> None:
        """Анализ распределения дат публикации."""
        if not items:
            return
        
        dates = []
        for item in items:
            published = item.get('published_at', '')
            if published:
                try:
                    date_str = published[:10]
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                    dates.append(date_obj)
                except ValueError:
                    continue
        
        if dates:
            earliest = min(dates)
            latest = max(dates)
            date_range = (latest - earliest).days
            
            distribution_table = [
                ('Самая ранняя', earliest),
                ('Самая поздняя', latest),
                ('Разброс дней', date_range)
            ]
            
            self.stdout.write(f'   Распределение дат {context}:')
            self._print_table(distribution_table)

    def _print_segments_statistics(self, segments_summary: List[Dict], max_records: int) -> None:
        """Вывод статистики по сегментам."""
        total_collected = sum(segment['count'] for segment in segments_summary)
        total_found = sum(segment['found'] for segment in segments_summary)
        
        # Детальная таблица по сегментам
        segments_table = []
        for idx, segment in enumerate(segments_summary, 1):
            segments_table.append(
                (
                    idx,
                    segment['start'],
                    segment['end'],
                    segment['count'],
                    segment['found'],
                    segment.get('first_date', '—'),
                    segment.get('last_date', '—')
                )
            )
        
        headers = ('#', 'Начало', 'Конец', 'Получено', 'Всего в HH', 'Первая дата', 'Последняя дата')
        self.stdout.write('\n   Детальная статистика сегментов:')
        self._print_table(segments_table, headers=headers)
        
        # Итоговая статистика
        limit_label = max_records if max_records and max_records > 0 else 'без ограничений'
        summary_table = [
            ('Всего сегментов', len(segments_summary)),
            ('Всего собрано вакансий', total_collected),
            ('Всего найдено в HH', total_found),
            ('Эффективность сбора', f'{(total_collected/total_found*100):.1f}%' if total_found > 0 else 'N/A'),
            ('Лимит сбора', limit_label)
        ]
        
        self.stdout.write('\n   Итоги сегментированного сбора:')
        self._print_table(summary_table)

    def _print_table(self, rows: List[Tuple], headers: Optional[Tuple] = None, indent: str = '   ') -> None:
        """Простая текстовая табличка без внешних зависимостей."""
        if not rows:
            self.stdout.write(indent + '—')
            return
        if headers:
            rows = [headers] + rows
        col_widths = []
        for row in rows:
            for idx, cell in enumerate(row):
                cell_str = str(cell)
                if len(col_widths) <= idx:
                    col_widths.append(len(cell_str))
                else:
                    col_widths[idx] = max(col_widths[idx], len(cell_str))
        for idx, row in enumerate(rows):
            formatted = ' | '.join(str(cell).ljust(col_widths[col_idx]) for col_idx, cell in enumerate(row))
            if headers and idx == 1:
                separator = '-+-'.join('-' * w for w in col_widths)
                self.stdout.write(indent + separator)
            self.stdout.write(indent + formatted)

    def _calculate_tail_page(self, total_count: int, per_page: int) -> int:
        """Вычисление номера страницы для получения хвоста данных."""
        if per_page <= 0:
            return 0
        
        # Простая логика: берем последнюю страницу
        pages = (total_count + per_page - 1) // per_page
        return max(pages - 1, 0)

    def _hh_max_page_index(self, per_page: int) -> int:
        """Максимальный индекс страницы согласно ограничениям HH API."""
        if per_page <= 0:
            return 0
        
        max_pages = self.HH_MAX_RESULTS // per_page
        return min(max_pages - 1, self.HH_MAX_PAGES - 1)

    def _fetch_tail_page(self, parser: HeadHunterParser, desired_page: int, search_text: str, 
                        per_page: int, date_from: str, date_to: str) -> Tuple[Optional[Dict], Optional[int]]:
        """Получение конечной страницы результатов."""
        page = min(desired_page, self._hh_max_page_index(per_page))
        
        while page >= 0:
            result = self._safe_api_call(
                parser.search_vacancies,
                text=search_text,
                area=self.DEFAULT_AREA,
                per_page=per_page,
                page=page,
                date_from=date_from,
                date_to=date_to
            )
            
            if result and result.get('items'):
                return result, page
            page -= 1
        
        return None, None

    def _collect_segmented_results(self, parser: HeadHunterParser, search_text: str, segment_per_page: int,
                                 date_from: str, date_to: str, max_records: int, 
                                 segment_days: int, segments_count: int) -> List[Dict[str, Any]]:
        """Сбор данных по временным сегментам."""
        segments = []
        max_per_segment = max(1, min(self.HH_MAX_RESULTS, segment_per_page * self.HH_MAX_PAGES))
        total_limit = max_records if max_records and max_records > 0 else None
        collected_total = 0
        current_end = self._parse_date(date_to)
        min_date = self._parse_date(date_from)
        
        segment_num = 0
        
        while current_end >= min_date and segment_num < segments_count:
            if total_limit is not None and collected_total >= total_limit:
                break
            
            segment_num += 1
            segment_start = max(min_date, current_end - timedelta(days=segment_days - 1))
            
            segment_limit = max_per_segment
            if total_limit is not None:
                remaining_for_limit = total_limit - collected_total
                if remaining_for_limit <= 0:
                    break
                segment_limit = min(segment_limit, remaining_for_limit)
            
            self.stdout.write(f'   Сегмент {segment_num}: {segment_start} - {current_end}')
            
            # Сбор данных сегмента
            segment_items, segment_found = self._fetch_segment_items(
                parser=parser,
                search_text=search_text,
                per_page=segment_per_page,
                date_from=segment_start,
                date_to=current_end,
                limit=segment_limit
            )
            
            segment_info = {
                'start': segment_start.strftime('%Y-%m-%d'),
                'end': current_end.strftime('%Y-%m-%d'),
                'count': len(segment_items),
                'found': segment_found,
                'first_date': self._extract_date(segment_items[0]) if segment_items else None,
                'last_date': self._extract_date(segment_items[-1]) if segment_items else None
            }
            
            segments.append(segment_info)
            collected_total += len(segment_items)
            
            # Переход к следующему сегменту
            current_end = segment_start - timedelta(days=1)
            
            # Прерывание если в сегменте нет данных и мы достигли минимальной даты
            if not segment_items and current_end < min_date:
                break
        
        return segments

    def _fetch_segment_items(self, parser: HeadHunterParser, search_text: str, per_page: int,
                           date_from: date, date_to: date, limit: int) -> Tuple[List[Dict], int]:
        """Сбор вакансий для временного сегмента."""
        collected_items = []
        page = 0
        total_found = 0
        date_from_str = date_from.strftime('%Y-%m-%d')
        date_to_str = date_to.strftime('%Y-%m-%d')
        
        max_pages = min(self.HH_MAX_PAGES, (limit + per_page - 1) // per_page)
        
        while len(collected_items) < limit and page < max_pages:
            result = self._safe_api_call(
                parser.search_vacancies,
                text=search_text,
                area=self.DEFAULT_AREA,
                per_page=per_page,
                page=page,
                date_from=date_from_str,
                date_to=date_to_str
            )
            
            if not result:
                break
            
            items = result.get('items', [])
            total_found = result.get('found', total_found)
            
            if not items:
                break
            
            collected_items.extend(items)
            
            # Прерываем если получено меньше запрошенного (конец данных)
            if len(items) < per_page:
                break
            
            page += 1
        
        return collected_items[:limit], total_found

    def _extract_date(self, vacancy: Dict) -> Optional[str]:
        """Извлечение даты из вакансии."""
        published = vacancy.get('published_at', '')
        return published[:10] if published else None

    def _parse_date(self, date_str: str) -> date:
        """Парсинг строки даты."""
        return datetime.strptime(date_str, '%Y-%m-%d').date()