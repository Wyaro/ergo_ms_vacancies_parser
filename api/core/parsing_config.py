"""
Конфигурируемые параметры парсинга (чанки, кэш, лимиты).

Чтение из Django settings с подставлением значений по умолчанию.
Для переопределения задайте в настройках проекта или в .env (через django-environ и т.п.):
  VACANCIES_PARSER_SUPERJOB_CHUNK_SIZE = 50
  VACANCIES_PARSER_SUPERJOB_MAX_PARALLEL_CHUNKS = 4
  VACANCIES_PARSER_HABR_CHUNK_SIZE = 25
  VACANCIES_PARSER_HABR_MAX_PARALLEL_CHUNKS = 6
  VACANCIES_PARSER_TECH_QUERIES_CACHE_TTL_SEC = 600
"""


def _get_setting(name: str, default: int) -> int:
    try:
        from django.conf import settings
        return getattr(settings, name, default)
    except Exception:
        return default


def get_superjob_chunk_size() -> int:
    """Размер чанка запросов для параллельного парсинга SuperJob. 0 = последовательный режим."""
    return _get_setting('VACANCIES_PARSER_SUPERJOB_CHUNK_SIZE', 50)


def get_superjob_max_parallel_chunks() -> int:
    """Максимум параллельных чанков SuperJob (учёт лимита API ~120 req/min)."""
    return _get_setting('VACANCIES_PARSER_SUPERJOB_MAX_PARALLEL_CHUNKS', 4)


def get_habr_chunk_size() -> int:
    """Размер чанка запросов для параллельного парсинга Habr. 0 = последовательный режим."""
    return _get_setting('VACANCIES_PARSER_HABR_CHUNK_SIZE', 25)


def get_habr_max_parallel_chunks() -> int:
    """Максимум параллельных чанков Habr."""
    return _get_setting('VACANCIES_PARSER_HABR_MAX_PARALLEL_CHUNKS', 6)


def get_tech_queries_cache_ttl_sec() -> int:
    """TTL кэша списка запросов технологий в секундах. 0 = без кэша."""
    return _get_setting('VACANCIES_PARSER_TECH_QUERIES_CACHE_TTL_SEC', 600)
