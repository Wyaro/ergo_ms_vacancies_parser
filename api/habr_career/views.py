from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Min, Max, Q
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from datetime import timedelta
from kombu.exceptions import OperationalError
import logging

from src.core.utils.mixins import SwaggerSafeMixin
from .models import Vacancy, VacancyVersion
from .serializers import (
    VacancyListSerializer, VacancyDetailSerializer, VacancyVersionSerializer,
    VacancyChangeHistorySerializer, VacancyStatsSerializer,
    ParsingTaskStatusSerializer
)
from .tasks import (
    parse_habr_vacancies_task, parse_habr_archived_vacancies_task,
    parse_habr_all_vacancies_task
)
from celery.result import AsyncResult
from modules.vacancies_parser.api.core.views import StandardResultsSetPagination

logger = logging.getLogger('modules.vacancies_parser.habr_career')
_BROKER_ERRORS = (ConnectionRefusedError, OperationalError, ConnectionError, OSError)


def _launch_task(task, kwargs):
    """Отправка Celery-задачи в брокер. Возвращает AsyncResult."""
    return task.apply_async(kwargs=kwargs)


def _broker_error_response(exc):
    return Response(
        {
            'error': f'Celery брокер недоступен: {exc}',
            'broker_error': True,
            'suggestion': 'Запустите Celery worker: ergoms start-worker',
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _normalize_search_text(raw_value):
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


class VacancyViewSet(SwaggerSafeMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet для работы с вакансиями Хабр Карьеры"""
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # description может быть очень большим и сильно замедляет icontains-поиск
    search_fields = ['title', 'company_name', 'city', 'qualification']
    ordering_fields = ['published_at', 'created_at', 'salary_from', 'salary_to', 'title']
    ordering = ['-published_at']
    filterset_fields = {
        'city': ['exact', 'icontains'],
        'employment_type': ['exact'],
        'experience_level': ['exact'],
        'qualification': ['exact', 'icontains'],
        'is_active': ['exact'],
        'premium': ['exact'],
        'schedule_type': ['exact'],
        'published_at': ['gte', 'lte', 'exact'],
        'salary_from': ['gte'],
        'salary_to': ['lte'],
    }

    def get_queryset(self):
        if self.is_swagger_fake_view():
            return Vacancy.objects.none()

        queryset = Vacancy.objects.all().defer(
            'description',
            'requirements',
            'responsibilities',
            'skills',
        )

        skills = self.request.query_params.getlist('skills')
        if skills:
            for skill in skills:
                queryset = queryset.filter(skills__icontains=skill)

        salary_min = self.request.query_params.get('salary_min')
        salary_max = self.request.query_params.get('salary_max')
        if salary_min:
            queryset = queryset.filter(
                Q(salary_to__gte=int(salary_min)) | Q(salary_from__gte=int(salary_min))
            )
        if salary_max:
            queryset = queryset.filter(
                Q(salary_from__lte=int(salary_max)) | Q(salary_to__lte=int(salary_max))
            )

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return VacancyListSerializer
        return VacancyDetailSerializer

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Получить все версии вакансии"""
        vacancy = self.get_object()
        versions = vacancy.versions.all().select_related('vacancy')
        serializer = VacancyVersionSerializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def version_detail(self, request, pk=None):
        """Получить детали конкретной версии"""
        vacancy = self.get_object()
        version_number = request.query_params.get('version')

        if not version_number:
            return Response(
                {'error': 'Не указан номер версии'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            version = vacancy.versions.get(version_number=int(version_number))
            serializer = VacancyVersionSerializer(version)
            return Response(serializer.data)
        except VacancyVersion.DoesNotExist:
            return Response(
                {'error': 'Версия не найдена'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'])
    def changes(self, request, pk=None):
        """Получить историю изменений вакансии"""
        vacancy = self.get_object()
        version_number = request.query_params.get('version')

        if version_number:
            try:
                version = vacancy.versions.select_related('vacancy').get(
                    version_number=int(version_number)
                )
                changes = version.changes.all().select_related('vacancy', 'version')
            except VacancyVersion.DoesNotExist:
                return Response(
                    {'error': 'Версия не найдена'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            changes = vacancy.change_history.all().select_related('vacancy', 'version')

        serializer = VacancyChangeHistorySerializer(changes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Получить статистику по вакансиям"""
        if self.is_swagger_fake_view():
            return Response(VacancyStatsSerializer({}).data)

        queryset = self.get_queryset()

        total_vacancies = queryset.count()
        active_vacancies = queryset.filter(is_active=True).count()

        salary_stats = queryset.filter(
            Q(salary_from__isnull=False) | Q(salary_to__isnull=False)
        ).aggregate(
            avg_salary_from=Avg('salary_from'),
            avg_salary_to=Avg('salary_to'),
            min_salary_from=Min('salary_from'),
            max_salary_to=Max('salary_to')
        )

        vacancies_by_city = dict(
            queryset.values('city').annotate(count=Count('id')).values_list('city', 'count')
        )

        vacancies_by_qualification = dict(
            queryset.exclude(qualification__isnull=True)
            .exclude(qualification='')
            .values('qualification')
            .annotate(count=Count('id'))
            .values_list('qualification', 'count')
        )

        vacancies_by_experience = dict(
            queryset.exclude(experience_level__isnull=True)
            .exclude(experience_level='')
            .values('experience_level')
            .annotate(count=Count('id'))
            .values_list('experience_level', 'count')
        )

        recent_date = timezone.now() - timedelta(days=7)
        recent_vacancies_count = queryset.filter(published_at__gte=recent_date).count()

        stats_data = {
            'total_vacancies': total_vacancies,
            'active_vacancies': active_vacancies,
            'avg_salary_from': salary_stats['avg_salary_from'],
            'avg_salary_to': salary_stats['avg_salary_to'],
            'min_salary_from': salary_stats['min_salary_from'],
            'max_salary_to': salary_stats['max_salary_to'],
            'vacancies_by_city': vacancies_by_city,
            'vacancies_by_qualification': vacancies_by_qualification,
            'vacancies_by_experience': vacancies_by_experience,
            'recent_vacancies_count': recent_vacancies_count,
        }

        serializer = VacancyStatsSerializer(stats_data)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary='Статус Celery-задачи парсинга',
        manual_parameters=[
            openapi.Parameter(
                'task_id',
                openapi.IN_QUERY,
                description='ID Celery-задачи',
                type=openapi.TYPE_STRING,
                required=True,
            ),
        ],
        responses={
            200: ParsingTaskStatusSerializer,
            400: openapi.Response(description='Не указан task_id'),
        },
    )
    @action(detail=False, methods=['get'])
    def task_status(self, request):
        """Получить статус задачи парсинга"""
        task_id = request.query_params.get('task_id')

        if not task_id:
            return Response(
                {'error': 'Не указан task_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            task_result = AsyncResult(task_id)
            status_data = {
                'task_id': task_id,
                'status': task_result.status,
                'progress': None,
                'result': None,
                'error': None
            }

            if task_result.ready():
                if task_result.successful():
                    status_data['result'] = task_result.result
                else:
                    status_data['error'] = str(task_result.info)
            elif hasattr(task_result, 'info') and isinstance(task_result.info, dict):
                status_data['progress'] = task_result.info

            serializer = ParsingTaskStatusSerializer(status_data)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f'Ошибка при получении статуса задачи {task_id}: {str(e)}', exc_info=True)
            return Response(
                {'error': f'Ошибка при получении статуса: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ParsingControlViewSet(SwaggerSafeMixin, viewsets.ViewSet):
    """ViewSet для управления парсингом вакансий Хабр Карьеры"""
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary='Запуск парсинга активных вакансий',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'pages': openapi.Schema(type=openapi.TYPE_INTEGER, default=5),
                'delay': openapi.Schema(type=openapi.TYPE_NUMBER, default=1.0),
                'get_details': openapi.Schema(type=openapi.TYPE_BOOLEAN, default=True),
                'search_text': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='Текстовый фильтр вакансий (например: "Python Django")',
                    default='',
                ),
            },
        ),
        responses={
            202: openapi.Response(
                description='Задача парсинга активных вакансий поставлена в очередь'
            ),
            503: openapi.Response(description='Celery брокер недоступен'),
        },
    )
    @action(detail=False, methods=['post'])
    def parse_active(self, request):
        """Запустить парсинг активных вакансий"""
        pages = request.data.get('pages', 5)
        delay = request.data.get('delay', 1.0)
        get_details = request.data.get('get_details', True)
        search_text = _normalize_search_text(request.data.get('search_text'))

        try:
            result = _launch_task(parse_habr_vacancies_task, {
                'pages': pages,
                'delay': delay,
                'get_details': get_details,
                'search_text': search_text,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': (
                    'Парсинг активных вакансий запущен'
                    if not search_text else f'Парсинг активных вакансий запущен (фильтр: {search_text})'
                ),
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error(f'Ошибка брокера при запуске парсинга активных вакансий: {str(e)}')
            return _broker_error_response(e)
        except Exception as e:
            logger.error(
                f'Ошибка при запуске парсинга активных вакансий: {str(e)}', exc_info=True
            )
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @swagger_auto_schema(
        operation_summary='Запуск парсинга архивных вакансий',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'pages': openapi.Schema(type=openapi.TYPE_INTEGER, default=5),
                'delay': openapi.Schema(type=openapi.TYPE_NUMBER, default=1.0),
                'search_text': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='Текстовый фильтр вакансий (например: "Python Django")',
                    default='',
                ),
            },
        ),
        responses={
            202: openapi.Response(
                description='Задача парсинга архивных вакансий поставлена в очередь'
            ),
            503: openapi.Response(description='Celery брокер недоступен'),
        },
    )
    @action(detail=False, methods=['post'])
    def parse_archived(self, request):
        """Запустить парсинг архивных вакансий"""
        pages = request.data.get('pages', 5)
        delay = request.data.get('delay', 1.0)
        search_text = _normalize_search_text(request.data.get('search_text'))

        try:
            result = _launch_task(parse_habr_archived_vacancies_task, {
                'pages': pages,
                'delay': delay,
                'search_text': search_text,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': (
                    'Парсинг архивных вакансий запущен'
                    if not search_text else f'Парсинг архивных вакансий запущен (фильтр: {search_text})'
                ),
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error(f'Ошибка брокера при запуске парсинга архивных вакансий: {str(e)}')
            return _broker_error_response(e)
        except Exception as e:
            logger.error(
                f'Ошибка при запуске парсинга архивных вакансий: {str(e)}', exc_info=True
            )
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @swagger_auto_schema(
        operation_summary='Запуск парсинга всех вакансий',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'pages': openapi.Schema(type=openapi.TYPE_INTEGER, default=5),
                'delay': openapi.Schema(type=openapi.TYPE_NUMBER, default=1.0),
                'get_details': openapi.Schema(type=openapi.TYPE_BOOLEAN, default=True),
                'search_text': openapi.Schema(
                    type=openapi.TYPE_STRING,
                    description='Текстовый фильтр вакансий (например: "Python Django")',
                    default='',
                ),
            },
        ),
        responses={
            202: openapi.Response(
                description='Задача парсинга всех вакансий поставлена в очередь'
            ),
            503: openapi.Response(description='Celery брокер недоступен'),
        },
    )
    @action(detail=False, methods=['post'])
    def parse_all(self, request):
        """Запустить парсинг всех вакансий (активных и архивных)"""
        pages = request.data.get('pages', 5)
        delay = request.data.get('delay', 1.0)
        get_details = request.data.get('get_details', True)
        search_text = _normalize_search_text(request.data.get('search_text'))

        try:
            result = _launch_task(parse_habr_all_vacancies_task, {
                'pages': pages,
                'delay': delay,
                'get_details': get_details,
                'search_text': search_text,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': (
                    'Парсинг всех вакансий запущен'
                    if not search_text else f'Парсинг всех вакансий запущен (фильтр: {search_text})'
                ),
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error(f'Ошибка брокера при запуске парсинга всех вакансий: {str(e)}')
            return _broker_error_response(e)
        except Exception as e:
            logger.error(
                f'Ошибка при запуске парсинга всех вакансий: {str(e)}', exc_info=True
            )
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
