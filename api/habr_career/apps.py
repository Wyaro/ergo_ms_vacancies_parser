from django.apps import AppConfig


class VacanciesParserHabrCareerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'modules.vacancies_parser.api.habr_career'
    label = 'vacancies_parser_habr_career'

    def ready(self):
        # Ensure module parser overrides are registered on app init.
        from . import parsers  # noqa: F401