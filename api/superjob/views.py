from pathlib import Path

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Min, Max, Q
from django.utils import timezone
from datetime import timedelta
from kombu.exceptions import OperationalError
import logging
import os

from src.core.utils.mixins import SwaggerSafeMixin
from .models import SuperJobVacancy, SuperJobVacancyVersion
from ..core.models import ParsingTask
from .serializers import (
    VacancyListSerializer, VacancyDetailSerializer, VacancyVersionSerializer,
    VacancyChangeHistorySerializer, VacancyStatsSerializer, ParsingTaskStatusSerializer
)
from .tasks import (
    parse_superjob_vacancies_task,
    parse_all_superjob_vacancies_task,
    get_superjob_vacancy_details_task,
    parse_superjob_vacancies_by_config_task,
    parse_superjob_by_catalogues_task,
    parse_superjob_batch_task,
    check_superjob_vacancies_status_task,
)
from .parsers.discovery import get_catalogues_list
from celery.result import AsyncResult
from ..core.celery_tasks import create_parsing_task
from modules.vacancies_parser.api.core.views import StandardResultsSetPagination

logger = logging.getLogger('modules.vacancies_parser.superjob')

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


def _resolve_api_key(request):
    """Получает API ключ SuperJob: из запроса, env или .env файла модуля."""
    api_key = request.data.get('api_key')
    if api_key:
        return api_key, None

    api_key = os.environ.get('SUPERJOB_API_KEY')
    if api_key:
        return api_key, None

    env_path = Path(__file__).resolve().parent / '.env'
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('SUPERJOB_API_KEY=') and not line.startswith('#'):
                    val = line.split('=', 1)[1].strip()
                    if val:
                        return val, None
        except OSError:
            pass

    return None, Response(
        {
            'error': 'Нет API ключа SuperJob. Передайте его в запросе (api_key) '
                     'или укажите в переменной окружения SUPERJOB_API_KEY.'
        },
        status=status.HTTP_401_UNAUTHORIZED,
    )


def _resolve_parsing_mode(request):
    raw_mode = request.data.get('parsing_mode', 'api')
    mode = str(raw_mode).strip().lower()
    if mode not in ('api', 'html'):
        return None, Response(
            {'error': 'Некорректный parsing_mode. Допустимые значения: api, html'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return mode, None


class VacancyViewSet(SwaggerSafeMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet для работы с вакансиями SuperJob"""
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # description может быть очень большим и сильно замедляет icontains-поиск
    search_fields = ['title', 'company_name', 'city', 'professional_role']
    ordering_fields = ['published_at', 'created_at', 'salary_from', 'salary_to', 'title']
    ordering = ['-published_at']
    filterset_fields = {
        'city': ['exact', 'icontains'],
        'employment_type': ['exact'],
        'experience_level': ['exact'],
        'professional_role': ['exact', 'icontains'],
        'is_active': ['exact'],
        'premium': ['exact'],
        'employer_trusted': ['exact'],
        'published_at': ['gte', 'lte', 'exact'],
        'salary_from': ['gte'],
        'salary_to': ['lte'],
    }

    def get_queryset(self):
        if self.is_swagger_fake_view():
            return SuperJobVacancy.objects.none()

        queryset = SuperJobVacancy.objects.all().defer(
            'description',
            'requirements',
            'responsibilities',
            'skills',
        )

        key_skills = self.request.query_params.getlist('key_skills')
        if key_skills:
            for skill in key_skills:
                queryset = queryset.filter(key_skills__icontains=skill)

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
        except SuperJobVacancyVersion.DoesNotExist:
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
            except SuperJobVacancyVersion.DoesNotExist:
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
            max_salary_to=Max('salary_to'),
        )

        vacancies_by_city = dict(
            queryset.values('city').annotate(count=Count('id')).values_list('city', 'count')
        )

        vacancies_by_role = dict(
            queryset.exclude(professional_role__isnull=True)
            .exclude(professional_role='')
            .values('professional_role')
            .annotate(count=Count('id'))
            .values_list('professional_role', 'count')
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
        premium_vacancies_count = queryset.filter(premium=True).count()

        stats_data = {
            'total_vacancies': total_vacancies,
            'active_vacancies': active_vacancies,
            'avg_salary_from': salary_stats['avg_salary_from'],
            'avg_salary_to': salary_stats['avg_salary_to'],
            'min_salary_from': salary_stats['min_salary_from'],
            'max_salary_to': salary_stats['max_salary_to'],
            'vacancies_by_city': vacancies_by_city,
            'vacancies_by_role': vacancies_by_role,
            'vacancies_by_experience': vacancies_by_experience,
            'recent_vacancies_count': recent_vacancies_count,
            'premium_vacancies_count': premium_vacancies_count,
        }

        serializer = VacancyStatsSerializer(stats_data)
        return Response(serializer.data)

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
            normalized_result = None
            status_data = {
                'task_id': task_id,
                'status': task_result.status,
                'progress': None,
                'result': normalized_result,
                'error': None,
            }

            if task_result.ready():
                if task_result.successful():
                    raw_result = task_result.result

                    # create_parsing_task возвращает int (ID ParsingTask),
                    # а сериализатор ожидает объект.
                    if isinstance(raw_result, int):
                        parsing_task = (
                            ParsingTask.objects.filter(id=raw_result)
                            .values(
                                'id',
                                'status',
                                'source',
                                'parsing_mode',
                                'total_items',
                                'processed_items',
                                'completed_items',
                                'failed_items',
                                'progress_percent',
                            )
                            .first()
                        )
                        normalized_result = {
                            'parsing_task_id': raw_result,
                            'parsing_task': parsing_task,
                        }
                    elif isinstance(raw_result, dict):
                        normalized_result = raw_result
                    else:
                        normalized_result = {'value': str(raw_result)}

                    status_data['result'] = normalized_result
                else:
                    status_data['error'] = str(task_result.info)
            elif hasattr(task_result, 'info') and isinstance(task_result.info, dict):
                status_data['progress'] = task_result.info

            serializer = ParsingTaskStatusSerializer(status_data)
            return Response(serializer.data)
        except Exception as e:
            logger.error('Ошибка при получении статуса задачи %s: %s', task_id, e, exc_info=True)
            return Response(
                {'error': f'Ошибка при получении статуса: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ParsingControlViewSet(SwaggerSafeMixin, viewsets.ViewSet):
    """ViewSet для управления парсингом вакансий SuperJob"""
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['post'])
    def parse_by_text(self, request):
        """Запустить парсинг вакансий по текстовому запросу"""
        parsing_mode, mode_err = _resolve_parsing_mode(request)
        if mode_err:
            return mode_err

        api_key = None
        if parsing_mode == 'api':
            api_key, err = _resolve_api_key(request)
            if err:
                return err

        text = request.data.get('text')
        if not text:
            return Response(
                {'error': 'Не указан текст для поиска (text)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        town = request.data.get('town')
        experience = request.data.get('experience')
        employment = request.data.get('employment')
        schedule = request.data.get('schedule')
        max_pages = request.data.get('max_pages', 5)
        delay = request.data.get('delay', 1.0)

        try:
            if parsing_mode == 'html':
                task_name = f'SuperJob HTML: {text}'
                html_config = {
                    'keywords': text,
                    'max_pages': max_pages,
                    'delay': delay,
                }
                result = _launch_task(create_parsing_task, {
                    'source': 'superjob',
                    'parsing_mode': 'html',
                    'config': html_config,
                    'name': task_name,
                    'created_by_id': request.user.id if request.user.is_authenticated else None,
                })
                return Response({
                    'task_id': result.id,
                    'status': 'started',
                    'message': f'HTML-парсинг SuperJob по запросу "{text}" запущен',
                }, status=status.HTTP_202_ACCEPTED)

            result = _launch_task(parse_superjob_vacancies_task, {
                'text': text,
                'town': town,
                'experience': experience,
                'employment': employment,
                'schedule': schedule,
                'max_pages': max_pages,
                'delay': delay,
                'api_key': api_key,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': f'Парсинг вакансий по запросу "{text}" запущен',
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error('Ошибка брокера при запуске парсинга по тексту: %s', e)
            return _broker_error_response(e)
        except Exception as e:
            logger.error('Ошибка при запуске парсинга по тексту: %s', e, exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'])
    def parse_all(self, request):
        """Запустить универсальный парсинг всех вакансий"""
        api_key, err = _resolve_api_key(request)
        if err:
            return err

        max_pages_per_query = request.data.get('max_pages_per_query', 3)
        delay = request.data.get('delay', 1.0)

        try:
            result = _launch_task(parse_all_superjob_vacancies_task, {
                'max_pages_per_query': max_pages_per_query,
                'delay': delay,
                'api_key': api_key,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': 'Универсальный парсинг вакансий SuperJob запущен',
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error('Ошибка брокера при запуске универсального парсинга: %s', e)
            return _broker_error_response(e)
        except Exception as e:
            logger.error('Ошибка при запуске универсального парсинга: %s', e, exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'])
    def parse_by_config(self, request):
        """Запустить парсинг по переданной конфигурации"""
        api_key, err = _resolve_api_key(request)
        if err:
            return err

        config = request.data.get('config', {})
        config['api_key'] = api_key

        try:
            result = _launch_task(parse_superjob_vacancies_by_config_task, {'config': config})
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': 'Парсинг вакансий по конфигурации запущен',
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error('Ошибка брокера при запуске парсинга по конфигу: %s', e)
            return _broker_error_response(e)
        except Exception as e:
            logger.error('Ошибка при запуске парсинга по конфигу: %s', e, exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['post'])
    def parse_by_catalogues(self, request):
        """Запустить парсинг вакансий по каталогам (отраслям) SuperJob"""
        api_key, err = _resolve_api_key(request)
        if err:
            return err

        catalogue_ids = request.data.get('catalogue_ids')
        max_pages = request.data.get('max_pages_per_catalogue', 10)
        delay = request.data.get('delay', 1.0)

        try:
            result = _launch_task(parse_superjob_by_catalogues_task, {
                'catalogue_ids': catalogue_ids,
                'max_pages_per_catalogue': max_pages,
                'delay': delay,
                'api_key': api_key,
            })
            mode = f"{len(catalogue_ids)} выбранных" if catalogue_ids else "всех"
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': f'Парсинг вакансий по каталогам ({mode}) запущен',
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error('Ошибка брокера при парсинге по каталогам: %s', e)
            return _broker_error_response(e)
        except Exception as e:
            logger.error('Ошибка при запуске парсинга по каталогам: %s', e, exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=['get'])
    def catalogues(self, request):
        """Получить список каталогов (отраслей) SuperJob"""
        api_key = os.environ.get('SUPERJOB_API_KEY')
        if not api_key:
            return Response(
                {'error': 'SUPERJOB_API_KEY не указан в переменных окружения'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            result = get_catalogues_list(api_key)
            return Response({
                'total': len(result),
                'catalogues': result,
            })
        except Exception as e:
            logger.error('Ошибка при получении каталогов: %s', e, exc_info=True)
            return Response(
                {'error': f'Ошибка при получении каталогов: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def get_details(self, request):
        """Получить детальную информацию о конкретной вакансии"""
        api_key, err = _resolve_api_key(request)
        if err:
            return err

        vacancy_id = request.data.get('vacancy_id')
        if not vacancy_id:
            return Response(
                {'error': 'Не указан vacancy_id'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = _launch_task(get_superjob_vacancy_details_task, {
                'vacancy_id': str(vacancy_id),
                'api_key': api_key,
            })
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': f'Получение деталей вакансии {vacancy_id} запущено',
            }, status=status.HTTP_202_ACCEPTED)
        except _BROKER_ERRORS as e:
            logger.error('Ошибка брокера при получении деталей вакансии %s: %s', vacancy_id, e)
            return _broker_error_response(e)
        except Exception as e:
            logger.error('Ошибка при получении деталей вакансии %s: %s', vacancy_id, e, exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
