from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Avg, Min, Max, Q, F
from django.utils import timezone
from datetime import timedelta
import logging

from src.core.utils.mixins import SwaggerSafeMixin
from .models import Vacancy, VacancyVersion, VacancyChangeHistory
from .serializers import (
    VacancyListSerializer, VacancyDetailSerializer, VacancyVersionSerializer,
    VacancyChangeHistorySerializer, VacancyStatsSerializer, ParsingTaskStatusSerializer
)
from .tasks import (
    parse_vacancies_by_professional_roles, parse_vacancies_by_technologies,
    parse_single_vacancy_task
)
from celery.result import AsyncResult
from modules.vacancies_parser.api.core.utils.task_runner import safe_task_run
from modules.vacancies_parser.api.core.utils.celery_broker import BrokerUnavailableError
from modules.vacancies_parser.api.core.views import StandardResultsSetPagination

logger = logging.getLogger('modules.vacancies_parser.headhunter')


class VacancyViewSet(SwaggerSafeMixin, viewsets.ReadOnlyModelViewSet):
    """ViewSet для работы с вакансиями"""
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
        """Получение queryset с учетом фильтрации"""
        if self.is_swagger_fake_view():
            return Vacancy.objects.none()

        queryset = Vacancy.objects.all().defer(
            'description',
            'requirements',
            'responsibilities',
            'skills',
        )
        
        # Фильтрация по навыкам (key_skills содержит)
        key_skills = self.request.query_params.getlist('key_skills')
        if key_skills:
            for skill in key_skills:
                queryset = queryset.filter(key_skills__icontains=skill)
        
        # Фильтрация по диапазону зарплаты
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
        """Выбор сериализатора в зависимости от действия"""
        if self.action == 'list':
            return VacancyListSerializer
        return VacancyDetailSerializer
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """Получить все версии вакансии"""
        vacancy = self.get_object()
        # Оптимизация: prefetch_related для обратной связи
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
                # Оптимизация: select_related для ForeignKey
                version = vacancy.versions.select_related('vacancy').get(version_number=int(version_number))
                changes = version.changes.all().select_related('vacancy', 'version')
            except VacancyVersion.DoesNotExist:
                return Response(
                    {'error': 'Версия не найдена'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            # Оптимизация: select_related для ForeignKey
            changes = vacancy.change_history.all().select_related('vacancy', 'version')
        
        serializer = VacancyChangeHistorySerializer(changes, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Получить статистику по вакансиям"""
        if self.is_swagger_fake_view():
            return Response(VacancyStatsSerializer({}).data)
        
        queryset = self.get_queryset()
        
        # Базовая статистика
        total_vacancies = queryset.count()
        active_vacancies = queryset.filter(is_active=True).count()
        
        # Статистика по зарплатам
        salary_stats = queryset.filter(
            Q(salary_from__isnull=False) | Q(salary_to__isnull=False)
        ).aggregate(
            avg_salary_from=Avg('salary_from'),
            avg_salary_to=Avg('salary_to'),
            min_salary_from=Min('salary_from'),
            max_salary_to=Max('salary_to')
        )
        
        # Статистика по городам
        vacancies_by_city = dict(
            queryset.values('city').annotate(count=Count('id')).values_list('city', 'count')
        )
        
        # Статистика по ролям
        vacancies_by_role = dict(
            queryset.exclude(professional_role__isnull=True)
            .values('professional_role')
            .annotate(count=Count('id'))
            .values_list('professional_role', 'count')
        )
        
        # Статистика по опыту
        vacancies_by_experience = dict(
            queryset.exclude(experience_level__isnull=True)
            .values('experience_level')
            .annotate(count=Count('id'))
            .values_list('experience_level', 'count')
        )
        
        # Недавние вакансии (за последние 7 дней)
        recent_date = timezone.now() - timedelta(days=7)
        recent_vacancies_count = queryset.filter(published_at__gte=recent_date).count()
        
        # Премиум вакансии
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
    
    @action(detail=False, methods=['post'])
    def parse_single(self, request):
        """Запустить парсинг одной вакансии по ID"""
        vacancy_id = request.data.get('vacancy_id')
        force_update = request.data.get('force_update', False)
        
        if not vacancy_id:
            return Response(
                {'error': 'Не указан vacancy_id'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = safe_task_run(
                parse_single_vacancy_task,
                {'vacancy_id': vacancy_id, 'force_update': force_update},
                prefer_async=True,
                fallback_to_sync=False
            )
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': 'Задача парсинга запущена'
            }, status=status.HTTP_202_ACCEPTED)
        except BrokerUnavailableError as e:
            logger.error(f'Ошибка брокера при запуске парсинга вакансии {vacancy_id}: {str(e)}')
            return Response({
                'error': f'Celery брокер недоступен: {str(e)}',
                'broker_error': True,
                'suggestion': 'Запустите Celery worker: ergoms start-worker'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f'Ошибка при запуске парсинга вакансии {vacancy_id}: {str(e)}', exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
            else:
                # Пытаемся получить прогресс из состояния задачи
                if hasattr(task_result, 'info') and isinstance(task_result.info, dict):
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
    """ViewSet для управления парсингом вакансий"""
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['post'])
    def parse_by_roles(self, request):
        """Запустить парсинг по профессиональным ролям"""
        area = request.data.get('area', 113)
        pages = request.data.get('pages', 20)
        delay = request.data.get('delay', 1.5)
        get_details = request.data.get('get_details', True)
        max_concurrent_roles = request.data.get('max_concurrent_roles', 5)
        batch_size = request.data.get('batch_size', 25)
        force_refresh_roles = request.data.get('force_refresh_roles', False)
        incremental = request.data.get('incremental', False)
        
        try:
            result = safe_task_run(
                parse_vacancies_by_professional_roles,
                {
                    'area': area,
                    'pages': pages,
                    'delay': delay,
                    'get_details': get_details,
                    'max_concurrent_roles': max_concurrent_roles,
                    'batch_size': batch_size,
                    'force_refresh_roles': force_refresh_roles,
                    'incremental': incremental
                },
                prefer_async=True,
                fallback_to_sync=False
            )
            
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': 'Парсинг по профессиональным ролям запущен'
            }, status=status.HTTP_202_ACCEPTED)
        except BrokerUnavailableError as e:
            logger.error(f'Ошибка брокера при запуске парсинга по ролям: {str(e)}')
            return Response({
                'error': f'Celery брокер недоступен: {str(e)}',
                'broker_error': True,
                'suggestion': 'Запустите Celery worker: ergoms start-worker'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f'Ошибка при запуске парсинга по ролям: {str(e)}', exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['post'])
    def parse_by_technologies(self, request):
        """Запустить парсинг по технологиям"""
        technologies = request.data.get('technologies', [])
        area = request.data.get('area', 113)
        pages = request.data.get('pages', 10)
        delay = request.data.get('delay', 1.5)
        get_details = request.data.get('get_details', True)
        
        if not technologies:
            return Response(
                {'error': 'Не указаны технологии для парсинга'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            result = safe_task_run(
                parse_vacancies_by_technologies,
                {
                    'technologies': technologies,
                    'area': area,
                    'pages': pages,
                    'delay': delay,
                    'get_details': get_details
                },
                prefer_async=True,
                fallback_to_sync=False
            )
            
            return Response({
                'task_id': result.id,
                'status': 'started',
                'message': 'Парсинг по технологиям запущен'
            }, status=status.HTTP_202_ACCEPTED)
        except BrokerUnavailableError as e:
            logger.error(f'Ошибка брокера при запуске парсинга по технологиям: {str(e)}')
            return Response({
                'error': f'Celery брокер недоступен: {str(e)}',
                'broker_error': True,
                'suggestion': 'Запустите Celery worker: ergoms start-worker'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as e:
            logger.error(f'Ошибка при запуске парсинга по технологиям: {str(e)}', exc_info=True)
            return Response(
                {'error': f'Ошибка при запуске задачи: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

