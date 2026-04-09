"""
Команда для просмотра статуса фонового парсинга HeadHunter.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.vacancies_parser.api.headhunter.celery_beat_config import HeadhunterCeleryBeatConfig

# Путь к конфигурационному файлу фонового парсинга
BACKGROUND_PARSING_CONFIG = Path(__file__).parent.parent.parent / 'config' / 'background_parsing.json'


TEXT: Dict[str, str] = {
    'line_sep': '-' * 64,
    'header': 'Статус фонового парсинга HeadHunter',
    'no_config_file': 'Файл конфигурации не найден',
    'config_header': 'Конфигурация из файла',
    'tasks_header': 'Периодические задачи',
    'additional_header': 'Дополнительные настройки',
    'commands_header': 'Полезные команды',
    'beat_start': '   api start_celery_beat',
    'tech_parse': '   api parse_hh_by_technologies --category LANG --wait',
    'beat_logs': '   Get-Content logs/celery_beat.log -Tail 50',
}


class Command(BaseCommand):
    help = 'Просмотр статуса фонового парсинга HeadHunter'

    def add_arguments(self, parser):
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Показать детальную информацию о каждой задаче'
        )
        parser.add_argument(
            '--config',
            action='store_true',
            help='Показать конфигурацию из JSON файла'
        )
        parser.add_argument(
            '--json-output',
            action='store_true',
            help='Вывести результат в JSON (stdout)'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Минимальный текстовый вывод'
        )

    def handle(self, *args, **options):
        quiet = bool(options.get('quiet'))
        as_json = bool(options.get('json_output'))

        beat_config = HeadhunterCeleryBeatConfig('headhunter')
        schedule = beat_config.get_beat_schedule()
        additional_config = beat_config.get_additional_beat_config()
        now_str = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        detailed = bool(options.get('detailed'))

        if as_json:
            payload = {
                'tasks_total': len(schedule),
                'current_time': now_str,
                'tasks': self._collect_tasks(schedule, detailed=detailed),
                'additional': additional_config or {},
            }
            config_json = self._load_json_config()
            if options.get('config') and config_json is not None:
                payload['config'] = config_json
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        self._print_header(quiet)
        if not quiet:
            self.stdout.write(f'Всего настроено задач: {len(schedule)}')
            self.stdout.write(f'Текущее время: {now_str}')

        if options.get('config'):
            self._print_json_config(quiet)

        self._print_tasks(schedule, detailed, quiet)
        self._print_additional(additional_config, quiet)
        self._print_commands(quiet)

    def _print_header(self, quiet: bool):
        if quiet:
            return
        self.stdout.write(TEXT['line_sep'])
        self.stdout.write(TEXT['header'])
        self.stdout.write(TEXT['line_sep'])

    def _collect_tasks(self, schedule: Dict[str, Any], detailed: bool) -> Dict[str, Any]:
        tasks: Dict[str, Any] = {}
        for task_name, task_config in schedule.items():
            tasks[task_name] = self._task_info_dict(task_config, detailed)
        return tasks

    def _task_info_dict(self, task_config: Dict[str, Any], detailed: bool) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        schedule = task_config.get('schedule')
        info['schedule'] = self._format_schedule(schedule)
        if detailed:
            info['task'] = task_config.get('task', 'N/A')
            kwargs = task_config.get('kwargs', {})
            if kwargs:
                info['kwargs'] = kwargs
            options = task_config.get('options', {})
            if options:
                info['options'] = options
        else:
            kwargs = task_config.get('kwargs', {})
            brief: Dict[str, Any] = {}
            for key in ('category', 'top_n', 'pages'):
                if key in kwargs:
                    brief[key] = kwargs[key]
            if brief:
                info['summary'] = brief
        return info

    def _print_tasks(self, schedule: Dict[str, Any], detailed: bool, quiet: bool):
        if not quiet:
            self.stdout.write('\n' + TEXT['tasks_header'])
        rows = []
        for task_name, task_config in schedule.items():
            info = self._task_info_dict(task_config, detailed)
            if quiet:
                continue
            sched = info.get("schedule", "N/A")
            extra_parts = []
            if detailed:
                if info.get('task'):
                    extra_parts.append(f'задача: {info["task"]}')
                if info.get('kwargs'):
                    kwargs_str = '; '.join(f'{k}={v}' for k, v in info['kwargs'].items())
                    extra_parts.append(f'параметры: {kwargs_str}')
                if info.get('options'):
                    opts_str = '; '.join(f'{k}={v}' for k, v in info['options'].items())
                    extra_parts.append(f'опции: {opts_str}')
            else:
                if info.get('summary'):
                    summary_str = '; '.join(f'{k}={v}' for k, v in info['summary'].items())
                    extra_parts.append(summary_str)
            rows.append((task_name, sched, ' | '.join(extra_parts) if extra_parts else ''))

        if quiet:
            return

        name_w = max((len(r[0]) for r in rows), default=0)
        sched_w = max((len(r[1]) for r in rows), default=0)

        for name, sched, extra in rows:
            line = f'{name.ljust(name_w)} | расписание: {sched.ljust(sched_w)}'
            if extra:
                line = f'{line} | {extra}'
            self.stdout.write(line)

    def _print_additional(self, additional_config: Optional[Dict[str, Any]], quiet: bool):
        if not additional_config:
            return
        if quiet:
            return
        self.stdout.write('\n' + TEXT['additional_header'])
        for key, value in additional_config.items():
            self.stdout.write(f'  {key}: {value}')

    def _print_commands(self, quiet: bool):
        if quiet:
            return
        self.stdout.write('\n' + TEXT['commands_header'])
        self.stdout.write('Для запуска Celery Beat:')
        self.stdout.write(TEXT['beat_start'])
        self.stdout.write('\nДля ручного запуска парсинга:')
        self.stdout.write(TEXT['tech_parse'])
        self.stdout.write('\nДля просмотра логов Beat:')
        self.stdout.write(TEXT['beat_logs'])

    def _format_schedule(self, schedule):
        """Форматирование расписания в читаемый формат."""
        if hasattr(schedule, 'run_every'):
            return f'Каждые {schedule.run_every}'

        if hasattr(schedule, 'hour') and hasattr(schedule, 'minute'):
            hour = schedule.hour
            minute = schedule.minute
            day_of_week = getattr(schedule, 'day_of_week', '*')

            if isinstance(hour, set):
                hour_str = ','.join(map(str, sorted(hour)))
            elif hour == '*':
                hour_str = 'каждый час'
            elif isinstance(hour, str) and '/' in hour:
                hour_str = f'каждые {hour.split("/")[1]} ч'
            else:
                hour_str = f'{hour:02d}' if isinstance(hour, int) else str(hour)

            if isinstance(minute, set):
                minute_str = ','.join(map(str, sorted(minute)))
            elif minute == '*':
                minute_str = 'каждую минуту'
            else:
                minute_str = f'{minute:02d}' if isinstance(minute, int) else str(minute)

            if day_of_week and day_of_week != '*' and not isinstance(day_of_week, set):
                day_name = self._get_day_name(day_of_week)
                return f'{day_name} в {hour_str}:{minute_str}'
            elif isinstance(day_of_week, set):
                days = ', '.join([self._get_day_name(d) for d in sorted(day_of_week)])
                return f'{days} в {hour_str}:{minute_str}'
            else:
                if '/' in str(hour):
                    return f'{hour_str}'
                return f'Каждый день в {hour_str}:{minute_str}'

        return str(schedule)

    def _get_day_name(self, day):
        """Получение названия дня недели."""
        days = {
            0: 'Пн', 1: 'Вт', 2: 'Ср', 3: 'Чт', 4: 'Пт', 5: 'Сб', 6: 'Вс',
            'monday': 'Понедельник', 'tuesday': 'Вторник',
            'wednesday': 'Среда', 'thursday': 'Четверг',
            'friday': 'Пятница', 'saturday': 'Суббота',
            'sunday': 'Воскресенье',
        }
        return days.get(day, str(day))

    def _print_json_config(self, quiet: bool):
        config = self._load_json_config()
        if config is None:
            if not quiet:
                self.stdout.write('\n' + TEXT['no_config_file'])
            return
        if quiet:
            return
        self.stdout.write('\n' + TEXT['config_header'])
        self.stdout.write(f'Описание: {config.get("description", "N/A")}')
        self.stdout.write(f'Включено: {"Да" if config.get("enabled") else "Нет"}')

        if 'common_settings' in config:
            self.stdout.write('\nОбщие настройки:')
            for key, value in config['common_settings'].items():
                self.stdout.write(f'   - {key}: {value}')

    def _load_json_config(self) -> Optional[Dict[str, Any]]:
        """
        Загрузка JSON конфигурации фонового парсинга.
        
        Returns:
            Словарь с конфигурацией или None, если файл не найден или произошла ошибка
        """
        if not BACKGROUND_PARSING_CONFIG.exists():
            return None

        try:
            with open(BACKGROUND_PARSING_CONFIG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # Логируем ошибку парсинга JSON, но не прерываем выполнение команды
            return None
        except Exception:
            # Другие ошибки (IOError, PermissionError и т.д.)
            return None

