"""
URL конфигурация для модуля vacancies_parser.

Endpoints:
- /api/vacancies_parser/tasks/ - управление задачами парсинга
- /api/vacancies_parser/items/ - просмотр элементов задач
- /api/vacancies_parser/vacancies/ - просмотр вакансий
- /api/vacancies_parser/statistics/ - просмотр статистики
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .core.views import (
    ParsingTaskViewSet,
    TaskItemViewSet,
    NormalizedVacancyViewSet,
    ParsingStatisticsViewSet,
    TaskRunViewSet,
    ExternalApiEventViewSet,
    SystemJobsViewSet,
)

app_name = 'vacancies_parser'

# Router для автоматической генерации URL
router = DefaultRouter()

# Регистрация ViewSets для главного модуля
router.register(r'tasks', ParsingTaskViewSet, basename='task')
router.register(r'items', TaskItemViewSet, basename='item')
router.register(r'vacancies', NormalizedVacancyViewSet, basename='vacancy')
router.register(r'statistics', ParsingStatisticsViewSet, basename='statistics')
router.register(r'task-runs', TaskRunViewSet, basename='task-run')
router.register(r'external-api-events', ExternalApiEventViewSet, basename='external-api-event')
router.register(r'system-jobs', SystemJobsViewSet, basename='system-job')

# Прямое подключение router.urls (без вложенного include)
urlpatterns = router.urls

"""
Доступные endpoints:

ЗАДАЧИ ПАРСИНГА (ParsingTaskViewSet):
- GET    /api/vacancies_parser/tasks/                   - Список задач
- POST   /api/vacancies_parser/tasks/                   - Создание задачи
- GET    /api/vacancies_parser/tasks/{id}/              - Детали задачи
- PATCH  /api/vacancies_parser/tasks/{id}/              - Обновление задачи
- DELETE /api/vacancies_parser/tasks/{id}/              - Удаление задачи
- GET    /api/vacancies_parser/tasks/{id}/progress/     - Прогресс выполнения
- POST   /api/vacancies_parser/tasks/{id}/pause/        - Приостановка задачи
- POST   /api/vacancies_parser/tasks/{id}/resume/       - Возобновление задачи
- POST   /api/vacancies_parser/tasks/{id}/stop/         - Остановка задачи
- GET    /api/vacancies_parser/tasks/{id}/items/        - Элементы задачи
- GET    /api/vacancies_parser/tasks/{id}/statistics/   - Статистика задачи
- GET    /api/vacancies_parser/tasks/sources/           - Доступные источники и режимы

ЭЛЕМЕНТЫ ЗАДАЧ (TaskItemViewSet):
- GET    /api/vacancies_parser/items/                   - Список элементов
- GET    /api/vacancies_parser/items/{id}/              - Детали элемента

ВАКАНСИИ (NormalizedVacancyViewSet):
- GET    /api/vacancies_parser/vacancies/               - Список вакансий
- GET    /api/vacancies_parser/vacancies/{id}/          - Детали вакансии
- GET    /api/vacancies_parser/vacancies/{id}/changes/  - История изменений

СТАТИСТИКА (ParsingStatisticsViewSet):
- GET    /api/vacancies_parser/statistics/              - Список статистик
- GET    /api/vacancies_parser/statistics/{id}/         - Детали статистики
"""