# -*- coding: utf-8 -*-
"""
Миграция данных: добавление меню модуля vacancies_parser в боковую панель.

Создаёт элементы меню для управления парсингом вакансий.
"""

from django.db import migrations


def populate_vacancies_parser_menu(apps, schema_editor):
    """Создаёт элементы меню модуля vacancies_parser."""
    from src.core.cms.adp.menu.migration_utils import MenuMigrationHelper
    
    # Инициализация helper для модуля
    helper = MenuMigrationHelper(apps, 'modules/vacancies_parser')
    
    # Очистка существующих элементов модуля (если есть)
    helper.clear_module_items()
    
    # Создание группы меню "Парсинг вакансий" с подпунктами
    # order=40 размещает после AI Hub (order=30)
    # Группа ведет на страницу со списком задач (главная страница модуля)
    parser_menu = helper.create_group(
        'Парсинг вакансий',
        'VacanciesParserMain',  # Главная страница модуля
        icon='FileText',
        order=40
    )
    
    # Создание подпунктов меню с разными маршрутами
    helper.create_routes_batch([
        ('Задачи парсинга', 'VacanciesParser', 'ListChecks'),
        ('Результаты (вакансии)', 'VacanciesParserResults', 'Briefcase'),
    ], parent=parser_menu)


def reverse_populate_vacancies_parser_menu(apps, schema_editor):
    """Удаляет элементы меню модуля vacancies_parser."""
    MenuItem = apps.get_model('cms_adp', 'MenuItem')
    
    # Удаление всех элементов меню модуля
    MenuItem.objects.filter(module_source='modules/vacancies_parser').delete()


class Migration(migrations.Migration):
    
    dependencies = [
        ('vacancies_parser', '0002_create_normalized_vacancy_models'),
        ('cms_adp', '0007_populate_core_menu'),  # Зависимость от core меню
    ]
    
    operations = [
        migrations.RunPython(
            populate_vacancies_parser_menu,
            reverse_populate_vacancies_parser_menu
        ),
    ]
