from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VacancyViewSet, ParsingControlViewSet

router = DefaultRouter()
router.register(r'vacancies', VacancyViewSet, basename='vacancy')
router.register(r'parsing', ParsingControlViewSet, basename='parsing')

urlpatterns = [
    path('', include(router.urls)),
]
