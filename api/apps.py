import logging
from django.apps import AppConfig

logger = logging.getLogger('celery.module.vacancies_parser')

# Флаг на уровне модуля для предотвращения повторного логирования
_module_initialized = False


class VacanciesParserConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'modules.vacancies_parser.api'
    label = 'vacancies_parser'
    
    def ready(self):
        """Инициализация модуля при загрузке"""
        global _module_initialized
        
        # Импорт парсеров для гарантированной регистрации в ParserFactory
        # Регистрация происходит автоматически при импорте модулей
        from .core.parsers import api_parsers, html_parsers  # noqa
        
        # Импорт задач для гарантированной регистрации в Celery
        # Задачи должны быть импортированы, чтобы Celery их обнаружил через autodiscover_tasks
        from . import tasks  # noqa: F401
        
        # Логируем итоговое состояние регистрации только один раз
        # (Django может создавать несколько экземпляров AppConfig)
        if not _module_initialized:
            from .core.parsers.base import ParserFactory
            available_parsers = ParserFactory.get_available_parsers()
            if available_parsers:
                parsers_list = ', '.join([f"{p['source']}/{p['mode']}" for p in available_parsers])
                # DEBUG уровень, так как это не критичная информация и может дублироваться при перезагрузке
                logger.debug(f"Модуль vacancies_parser инициализирован. Доступные парсеры: {parsers_list}")
            _module_initialized = True