"""
Конфигурация Celery для модуля headhunter.
Настройки задач парсинга вакансий с HeadHunter.
"""

from typing import Dict, Any

from ..core.celery_config_base import VacanciesParserCeleryConfigBase

class HeadhunterCeleryConfig(VacanciesParserCeleryConfigBase):
    """
    Конфигурация Celery для модуля парсинга HeadHunter.
    """
    
    def __init__(self, module_name: str):
        super().__init__(module_name)
    
    def get_task_routes(self) -> Dict[str, Dict[str, Any]]:
        """Маршруты задач для парсинга HeadHunter"""
        return {
            'modules.vacancies_parser.api.headhunter.tasks.*': {'queue': 'headhunter'},
        }
    
    def get_task_queues(self) -> Dict[str, Dict[str, Any]]:
        """Очереди задач для парсинга HeadHunter"""
        return {
            'headhunter': {
                'exchange': 'headhunter',
                'routing_key': 'headhunter',
            }
        }
    
    def get_task_annotations(self) -> Dict[str, Dict[str, Any]]:
        """Аннотации задач для парсинга HeadHunter"""
        return {
            'modules.vacancies_parser.api.headhunter.tasks.parse_hh_vacancies_task': {
                'time_limit': 7200,   # Таймаут 2 часа
                'soft_time_limit': 6900,  # Мягкий таймаут 1 час 55 минут
                'rate_limit': '100/h',   # Максимум 100 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_single_vacancy_task': {
                'time_limit': 1800,   # Таймаут 30 минут
                'soft_time_limit': 1500,  # Мягкий таймаут 25 минут
                'rate_limit': '100/h',  # Максимум 100 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_technologies': {
                'time_limit': 5400,   # Таймаут 1.5 часа
                'soft_time_limit': 5100,  # Мягкий таймаут 1 час 25 минут
                'rate_limit': '60/h',  # Максимум 60 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_category': {
                'time_limit': 3600,   # Таймаут 1 час
                'soft_time_limit': 3300,  # Мягкий таймаут 55 минут
                'rate_limit': '60/h',  # Максимум 60 задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_time_period': {
                'time_limit': 7500,   # Таймаут 2 часа 5 минут
                'soft_time_limit': 7200,  # Мягкий таймаут 2 часа
                'rate_limit': '20/h',  # Максимум 20 задач в час (ресурсоемкая)
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_vacancies_by_time_period_parallel': {
                'time_limit': 10800,  # Таймаут 3 часа (мастер задача)
                'soft_time_limit': 10200,  # Мягкий таймаут 2 часа 50 минут
                'rate_limit': '10/h',  # Максимум 10 мастер задач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_single_query_segment_task': {
                'time_limit': 7200,   # Таймаут 2 часа (подзадача)
                'soft_time_limit': 6900,  # Мягкий таймаут 1 час 55 минут
                'rate_limit': '50/h',  # Максимум 50 подзадач в час
            },
            'modules.vacancies_parser.api.headhunter.tasks.parse_single_role_batch': {
                'time_limit': 10800,  # Подзадача парсинга ролей (3 часа)
                'soft_time_limit': 9000,
                'rate_limit': '15/h',
            },
            'modules.vacancies_parser.api.headhunter.tasks.finalize_role_fragments': {
                'time_limit': 1200,   # Агрегация быстрый коллбек
                'soft_time_limit': 900,
                'rate_limit': '60/h',
            },
            # Daily parsing - ежедневный парсинг за вчера и сегодня
            'modules.vacancies_parser.api.headhunter.tasks.parse_daily_vacancies_yesterday_today': {
                'time_limit': 18000,  # Таймаут 5 часов
                'soft_time_limit': 14400,  # Мягкий таймаут 4 часа
                # rate_limit не нужен - задача управляется через Beat расписание (1 раз в день)
            },
            # Monthly parsing - месячный парсинг с рекурсивной сегментацией
            'modules.vacancies_parser.api.headhunter.tasks.parse_monthly_vacancies_recursive': {
                'time_limit': 36000,  # Таймаут 10 часов
                'soft_time_limit': 28800,  # Мягкий таймаут 8 часов
                # rate_limit не нужен - задача управляется через Beat расписание (1 раз в месяц)
            },
            'modules.vacancies_parser.api.headhunter.tasks._parse_single_day_recursive': {
                'time_limit': 9000,   # Таймаут 2.5 часа на день
                'soft_time_limit': 7200,  # Мягкий таймаут 2 часа
                'rate_limit': '50/h',  # Максимум 50 дней в час (для параллельной обработки)
            },
        }
    
    def get_module_loggers(self) -> Dict[str, Any]:
        """Специализированные логгеры для модуля парсинга HeadHunter"""
        loggers = super().get_module_loggers()
        
        # Добавляем специализированные логгеры
        loggers.update({
            'parsing': self._get_logger('parsing'),
            'api': self._get_logger('api'),
        })
        
        return loggers
    
    def _get_logger(self, logger_name: str):
        """Создает специализированный логгер для модуля"""
        import logging
        return logging.getLogger(f'celery.module.{self.module_name}.{logger_name}')

    def get_max_concurrent_tasks(self) -> int:
        return 3  # Максимум 3 одновременных задачи
