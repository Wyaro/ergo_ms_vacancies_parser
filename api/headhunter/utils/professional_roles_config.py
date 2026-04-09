"""
Утилита для работы с конфигурацией профессиональных ролей IT.

Загружает настройки из JSON конфига и предоставляет методы для работы с ролями.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from ..tasks import get_professional_roles_task

logger = logging.getLogger('modules.vacancies_parser.headhunter.utils.professional_roles')


@dataclass
class ProfessionalRole:
    """Модель профессиональной роли"""
    id: str
    name: str
    accept_incomplete_resumes: bool
    is_default: bool
    select_deprecated: bool
    search_deprecated: bool


@dataclass
class ProfessionalRolesConfig:
    """Конфигурация для парсинга профессиональных ролей"""
    enabled: bool
    target_category_id: str
    area: int
    pages: int
    delay: float
    get_details: bool
    max_concurrent_roles: int
    batch_size: int
    exclude_roles: List[str]
    include_only: Optional[List[str]]
    use_static_file: bool = False
    static_file: Optional[str] = None
    it_roles_file: Optional[Path] = None


class ProfessionalRolesManager:
    """
    Менеджер для работы с профессиональными ролями IT.

    Загружает конфигурацию и предоставляет актуальный список ролей.
    """

    CONFIG_FILE = Path(__file__).parent.parent / 'config' / 'professional_roles_config.json'

    def __init__(self):
        self.config = self._load_config()
        self._roles_cache: Optional[List[ProfessionalRole]] = None

    def _load_config(self) -> ProfessionalRolesConfig:
        """Загружает конфигурацию из JSON файла"""
        try:
            with open(self.CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            role_filters = data.get('role_filters', {})
            use_static_file = role_filters.get('use_static_file', False)
            static_file = role_filters.get('static_file', 'it_professional_roles.json')

            if use_static_file:
                it_roles_file = Path(__file__).parent.parent / 'config' / static_file
            else:
                it_roles_file = None

            return ProfessionalRolesConfig(
            enabled=data.get('enabled', False),
            target_category_id=data['target_category']['id'],
            area=data['parsing_settings']['area'],
            pages=data['parsing_settings']['pages'],
            delay=data['parsing_settings']['delay'],
            get_details=data['parsing_settings']['get_details'],
            max_concurrent_roles=data['parsing_settings']['max_concurrent_roles'],
            batch_size=data['parsing_settings']['batch_size'],
            exclude_roles=role_filters.get('exclude_roles', []),
                include_only=role_filters.get('include_only'),
                use_static_file=use_static_file,
                static_file=static_file,
                it_roles_file=it_roles_file
            )

        except Exception as e:
            logger.error(f'Ошибка загрузки конфига профессиональных ролей: {e}')
            raise

    def get_it_roles(self, force_refresh: bool = False) -> List[ProfessionalRole]:
        """
        Получает список IT ролей из API HeadHunter.

        Всегда получает актуальные роли из API, игнорируя статические файлы.

        Args:
            force_refresh: Принудительно обновить кэш (получить из API)

        Returns:
            Список профессиональных ролей IT
        """
        if force_refresh:
            self._roles_cache = None

        if self._roles_cache is None:
            try:
                # Всегда получаем роли из API
                roles_data = self._fetch_roles_from_api()
                if roles_data:
                    self._roles_cache = roles_data
                    logger.info(f'Загружено {len(self._roles_cache)} IT ролей из API HeadHunter')
                else:
                    logger.error('Не удалось получить IT роли из API')
                    self._roles_cache = []
            except Exception as e:
                logger.error(f'Ошибка получения IT ролей из API: {e}', exc_info=True)
                self._roles_cache = []

        return self._roles_cache

    def _load_it_roles_from_file(self) -> Optional[List[ProfessionalRole]]:
        """Загружает IT роли из статического файла"""
        try:
            if not self.config.it_roles_file or not self.config.it_roles_file.exists():
                logger.error(f'Файл IT ролей не найден: {self.config.it_roles_file}')
                return None

            with open(self.config.it_roles_file, 'r', encoding='utf-8') as f:
                roles_data = json.load(f)

            roles = []
            for role_data in roles_data:
                role = ProfessionalRole(
                    id=str(role_data['id']),
                    name=role_data['name'],
                    accept_incomplete_resumes=role_data.get('accept_incomplete_resumes', False),
                    is_default=role_data.get('is_default', False),
                    select_deprecated=role_data.get('select_deprecated', False),
                    search_deprecated=role_data.get('search_deprecated', False)
                )
                # Применяем фильтры из конфига
                if self._should_include_role(role):
                    roles.append(role)

            return roles

        except Exception as e:
            logger.error(f'Ошибка чтения файла IT ролей: {e}')
            return None

    def _save_roles_to_file(self, roles: List[ProfessionalRole]) -> None:
        """Сохраняет роли в кэш-файл"""
        try:
            roles_data = [
                {
                    'id': role.id,
                    'name': role.name,
                    'accept_incomplete_resumes': role.accept_incomplete_resumes,
                    'is_default': role.is_default,
                    'select_deprecated': role.select_deprecated,
                    'search_deprecated': role.search_deprecated
                }
                for role in roles
            ]

            with open(self.ROLES_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(roles_data, f, ensure_ascii=False, indent=2)

            logger.info(f'Роли сохранены в файл: {self.ROLES_CACHE_FILE}')

        except Exception as e:
            logger.error(f'Ошибка сохранения файла ролей: {e}')

    def _fetch_roles_from_api(self) -> Optional[List[ProfessionalRole]]:
        """Получает роли из API HeadHunter"""
        try:
            # Получаем полные данные ролей из API
            parser = HeadHunterParser()
            raw_data = parser._make_request(f"{parser.base_url}/professional_roles")

            if not raw_data or 'categories' not in raw_data:
                logger.error('Некорректный ответ от API профессиональных ролей')
                return None

            # Находим категорию IT
            it_category = None
            for category in raw_data['categories']:
                if str(category.get('id')) == str(self.config.target_category_id):
                    it_category = category
                    break

            if not it_category:
                logger.error(f'Категория IT с ID {self.config.target_category_id} не найдена')
                return None

            # Преобразуем роли в объекты
            roles = []
            for role_data in it_category.get('roles', []):
                role = ProfessionalRole(
                    id=str(role_data['id']),
                    name=role_data['name'],
                    accept_incomplete_resumes=role_data.get('accept_incomplete_resumes', False),
                    is_default=role_data.get('is_default', False),
                    select_deprecated=role_data.get('select_deprecated', False),
                    search_deprecated=role_data.get('search_deprecated', False)
                )

                # Применяем фильтры
                if self._should_include_role(role):
                    roles.append(role)

            return roles

        except Exception as e:
            logger.error(f'Ошибка получения ролей из API: {e}')
            return None

    def _should_include_role(self, role: ProfessionalRole) -> bool:
        """
        Определяет, должна ли роль быть включена в парсинг.

        Args:
            role: Профессиональная роль

        Returns:
            True если роль должна быть включена
        """
        # Исключаем deprecated роли
        if role.select_deprecated or role.search_deprecated:
            return False

        # Исключаем роли из списка исключений
        if role.id in self.config.exclude_roles:
            return False

        # Если есть список include_only, проверяем вхождение
        if self.config.include_only:
            return role.id in self.config.include_only

        return True

    def get_roles_for_parsing(self) -> List[Dict[str, Any]]:
        """
        Получает список ролей в формате, подходящем для парсинга.

        Returns:
            Список словарей с ID и названием ролей
        """
        roles = self.get_it_roles()
        return [
            {
                'id': role.id,
                'name': role.name,
                'professional_role': role.id  # Для использования в API запросах
            }
            for role in roles
        ]

    def get_config(self) -> ProfessionalRolesConfig:
        """Получает текущую конфигурацию"""
        return self.config


# Импорт здесь, чтобы избежать циклических зависимостей
from ..scripts import HeadHunterParser
