from django.apps import AppConfig


class VacanciesParserHeadhunterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'modules.vacancies_parser.api.headhunter'
    label = 'vacancies_parser_headhunter'

    def ready(self):
        self._register_parser_overrides()

    @staticmethod
    def _register_parser_overrides():
        from ..core.parsers.base import ParserFactory

        try:
            from .parsers.html_parser import HeadHunterHTMLParserOverride
            ParserFactory.register('headhunter', 'html', HeadHunterHTMLParserOverride)
        except Exception:
            pass

        try:
            from .parsers.api_parser import HeadHunterAPIParserOverride
            ParserFactory.register('headhunter', 'api', HeadHunterAPIParserOverride)
        except Exception:
            pass