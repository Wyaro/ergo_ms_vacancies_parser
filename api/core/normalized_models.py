"""
Нормализованная модель Vacancy для всех источников.

Унифицирует данные из HeadHunter, Habr Career, SuperJob в общую схему.
"""

import hashlib
import json

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class NormalizedVacancy(models.Model):
    """
    Унифицированная модель вакансии для всех источников.
    
    Содержит:
    - Общие поля (title, company, salary и т.д.)
    - Специфичные для источника данные в JSONField
    - Связь с TaskItem для отслеживания источника данных
    - Версионность и история изменений
    """
    
    # ============================================================
    # ИСТОЧНИК ДАННЫХ
    # ============================================================
    
    SOURCE_CHOICES = [
        ('headhunter', 'HeadHunter'),
        ('habr_career', 'Habr Career'),
        ('superjob', 'SuperJob'),
    ]
    source = models.CharField(
        max_length=50,
        choices=SOURCE_CHOICES,
        verbose_name="Источник",
        db_index=True
    )
    
    source_id = models.CharField(
        max_length=100,
        verbose_name="ID на источнике",
        help_text="Оригинальный ID вакансии (hh_id, habr_id, superjob_id)"
    )
    
    source_url = models.URLField(
        verbose_name="URL вакансии на источнике",
        max_length=512
    )
    
    PARSING_MODE_CHOICES = [
        ('api', 'API режим'),
        ('html', 'HTML режим'),
    ]
    parsing_mode = models.CharField(
        max_length=10,
        choices=PARSING_MODE_CHOICES,
        verbose_name="Режим парсинга",
        db_index=True,
        help_text="Каким способом была получена вакансия"
    )
    
    task_item = models.ForeignKey(
        'vacancies_parser.TaskItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parsed_vacancies',
        verbose_name="Элемент задачи",
        help_text="Связь с TaskItem для отслеживания источника парсинга"
    )
    
    # ============================================================
    # ОСНОВНЫЕ ПОЛЯ (ОБЩИЕ ДЛЯ ВСЕХ ИСТОЧНИКОВ)
    # ============================================================
    
    title = models.CharField(
        max_length=255,
        verbose_name="Название вакансии",
        db_index=True
    )
    
    company_name = models.CharField(
        max_length=255,
        verbose_name="Название компании",
        db_index=True
    )
    
    company_url = models.URLField(
        null=True,
        blank=True,
        max_length=512,
        verbose_name="URL компании"
    )
    
    description = models.TextField(
        verbose_name="Описание вакансии"
    )
    
    # ============================================================
    # ЗАРПЛАТА
    # ============================================================
    
    salary_from = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="Зарплата от"
    )
    
    salary_to = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name="Зарплата до"
    )
    
    CURRENCY_CHOICES = [
        ('RUR', 'Рубли'),
        ('USD', 'Доллары'),
        ('EUR', 'Евро'),
        ('KZT', 'Тенге'),
        ('UAH', 'Гривны'),
        ('BYR', 'Белорусские рубли'),
    ]
    salary_currency = models.CharField(
        max_length=3,
        choices=CURRENCY_CHOICES,
        null=True,
        blank=True,
        verbose_name="Валюта"
    )
    
    salary_gross = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="До вычета налогов",
        help_text="True = gross (до налогов), False = net (на руки)"
    )
    
    # ============================================================
    # ЛОКАЦИЯ
    # ============================================================
    
    area_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Город/регион",
        db_index=True
    )
    
    area_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="ID города на источнике"
    )
    
    address = models.TextField(
        null=True,
        blank=True,
        verbose_name="Адрес"
    )
    
    # ============================================================
    # ОПЫТ И ЗАНЯТОСТЬ
    # ============================================================
    
    EXPERIENCE_CHOICES = [
        ('noExperience', 'Нет опыта'),
        ('between1And3', 'От 1 до 3 лет'),
        ('between3And6', 'От 3 до 6 лет'),
        ('moreThan6', 'Более 6 лет'),
    ]
    experience = models.CharField(
        max_length=20,
        choices=EXPERIENCE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Требуемый опыт"
    )
    
    EMPLOYMENT_CHOICES = [
        ('full', 'Полная занятость'),
        ('part', 'Частичная занятость'),
        ('project', 'Проектная работа'),
        ('volunteer', 'Волонтерство'),
        ('probation', 'Стажировка'),
    ]
    employment_type = ArrayField(
        models.CharField(max_length=20, choices=EMPLOYMENT_CHOICES),
        null=True,
        blank=True,
        verbose_name="Типы занятости"
    )
    
    SCHEDULE_CHOICES = [
        ('fullDay', 'Полный день'),
        ('shift', 'Сменный график'),
        ('flexible', 'Гибкий график'),
        ('remote', 'Удаленная работа'),
        ('flyInFlyOut', 'Вахтовый метод'),
    ]
    schedule = ArrayField(
        models.CharField(max_length=20, choices=SCHEDULE_CHOICES),
        null=True,
        blank=True,
        verbose_name="Графики работы"
    )
    
    # ============================================================
    # НАВЫКИ И ТРЕБОВАНИЯ
    # ============================================================
    
    key_skills = ArrayField(
        models.CharField(max_length=100),
        null=True,
        blank=True,
        verbose_name="Ключевые навыки"
    )
    
    professional_roles = ArrayField(
        models.CharField(max_length=100),
        null=True,
        blank=True,
        verbose_name="Профессиональные роли"
    )
    
    # ============================================================
    # КОНТАКТЫ
    # ============================================================
    
    contacts = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Контакты",
        help_text="JSON с контактами (name, email, phones)"
    )
    
    # ============================================================
    # СТАТУС ВАКАНСИИ
    # ============================================================
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активна",
        db_index=True
    )
    
    archived = models.BooleanField(
        default=False,
        verbose_name="Архивная",
        db_index=True
    )
    
    published_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Дата публикации на источнике"
    )
    
    # ============================================================
    # ДОПОЛНИТЕЛЬНЫЕ ДАННЫЕ
    # ============================================================
    
    has_test = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Есть тестовое задание"
    )
    
    accepts_handicapped = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Доступна для людей с ОВЗ"
    )
    
    response_letter_required = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="Требуется сопроводительное письмо"
    )
    
    # ============================================================
    # СПЕЦИФИЧНЫЕ ДЛЯ ИСТОЧНИКА ДАННЫЕ
    # ============================================================
    
    source_specific_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Специфичные данные источника",
        help_text="JSON с полями, уникальными для источника"
    )
    
    raw_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Сырые данные",
        help_text="Полный ответ от источника для отладки/reprocessing"
    )
    
    sources_meta = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Источники",
        help_text="Список площадок, на которых размещена вакансия"
    )
    
    # ============================================================
    # МЕТАДАННЫЕ
    # ============================================================
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания",
        db_index=True
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Дата обновления"
    )
    
    last_checked_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="Дата последней проверки"
    )
    
    version = models.IntegerField(
        default=1,
        verbose_name="Версия"
    )
    
    # ============================================================
    # ДЕДУПЛИКАЦИЯ
    # ============================================================
    
    # Хэш для дедупликации (агрегированный критерий)
    deduplication_hash = models.CharField(
        max_length=64,
        db_index=True,
        default='',
        blank=True,
        verbose_name="Хэш для дедупликации",
        help_text="Агрегированный хэш ключевых полей для поиска дубликатов"
    )
    
    # Связь с оригинальной вакансией (если это дубликат)
    original_vacancy_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="ID оригинальной вакансии",
        help_text="FK на NormalizedVacancy, если это дубликат"
    )
    
    # Статус дедупликации
    DEDUPLICATION_STATUS_CHOICES = [
        ('pending', 'Ожидает проверки'),
        ('original', 'Оригинал'),
        ('duplicate', 'Дубликат'),
    ]
    deduplication_status = models.CharField(
        max_length=20,
        choices=DEDUPLICATION_STATUS_CHOICES,
        default='pending',
        verbose_name="Статус дедупликации",
        db_index=True
    )
    
    class Meta:
        verbose_name = "Нормализованная вакансия"
        verbose_name_plural = "Нормализованные вакансии"
        ordering = ['-created_at']
        db_table = 'vpm_vacancy'
        
        unique_together = [['source', 'source_id']]
        
        indexes = [
            # Поиск по источнику и статусу
            models.Index(fields=['source', 'is_active']),
            models.Index(fields=['source', 'archived']),
            # Поиск по компании
            models.Index(fields=['company_name', 'is_active']),
            # Поиск по городу
            models.Index(fields=['area_name', 'is_active']),
            # Поиск по режиму парсинга
            models.Index(fields=['parsing_mode', 'created_at']),
            # Поиск по дате публикации
            models.Index(fields=['published_at', 'is_active']),
            # Для дедупликации
            models.Index(fields=['title', 'company_name']),
            models.Index(fields=['title', 'area_name']),
            models.Index(fields=['salary_from', 'salary_to']),
            models.Index(fields=['deduplication_hash']),
        ]
    
    def save(self, *args, **kwargs):
        """Переопределение save для генерации хэша дедупликации и заполнения sources_meta"""
        if not self.deduplication_hash:
            self.deduplication_hash = self.generate_deduplication_hash()
        # Автозаполнение sources_meta для одиночных записей
        if not self.sources_meta:
            self.sources_meta = [{
                'source': self.source,
                'source_id': self.source_id,
                'url': self.source_url,
            }]
        super().save(*args, **kwargs)
    
    def clean(self):
        """Валидация поля contacts"""
        if self.contacts and not isinstance(self.contacts, dict):
            raise ValidationError({
                'contacts': 'Поле contacts должно быть JSON объектом или null'
            })
        
        if self.contacts:
            required_keys = ['name', 'email']
            for key in required_keys:
                if key not in self.contacts:
                    raise ValidationError({
                        f'contacts.{key}': f'Отсутствует обязательное поле: {key}'
                    })
    
    def __str__(self):
        return f"[{self.source}] {self.title} - {self.company_name}"
    
    # ============================================================
    # МЕТОДЫ
    # ============================================================
    
    def generate_deduplication_hash(self) -> str:
        """Генерация хэша для дедупликации на основе ключевых полей"""
        key_fields = [
            self.title.lower() if self.title else '',
            self.company_name.lower() if self.company_name else '',
            str(self.salary_from or ''),
            str(self.salary_to or ''),
            self.area_name.lower() if self.area_name else '',
        ]
        hash_string = '|'.join(key_fields)
        return hashlib.sha256(hash_string.encode()).hexdigest()
    
    def update_deduplication_hash(self):
        """Обновление хэша для дедупликации"""
        self.deduplication_hash = self.generate_deduplication_hash()
        self.save(update_fields=['deduplication_hash'])
    
    @classmethod
    def upsert_from_normalized(cls, normalized_data: dict, *, task_item=None) -> "NormalizedVacancy":
        """
        Upsert вакансии по deduplication_hash с агрегированием источников.
        
        normalized_data должен содержать как минимум:
        - source, source_id, source_url, title, company_name, area_name/salary_*
        """
        temp = cls(**{
            k: v for k, v in normalized_data.items()
            if k in {f.name for f in cls._meta.get_fields() if hasattr(f, "column")}
        })
        dedup_hash = temp.generate_deduplication_hash()
        
        vacancy = (
            cls.objects
            .select_for_update()
            .filter(deduplication_hash=dedup_hash)
            .first()
        )
        
        if vacancy is None:
            # normalized_data может уже содержать deduplication_hash (например, после маппинга),
            # поэтому передаем его ровно один раз.
            normalized_data = {k: v for k, v in normalized_data.items() if k != 'deduplication_hash'}
            vacancy = cls.objects.create(
                **normalized_data,
                deduplication_hash=dedup_hash,
            )
            return vacancy
        
        sources_meta = vacancy.sources_meta or []
        current_source = normalized_data.get("source")
        current_source_id = normalized_data.get("source_id")
        current_url = normalized_data.get("source_url")
        
        if current_source and current_source_id:
            exists = any(
                s.get("source") == current_source and s.get("source_id") == current_source_id
                for s in sources_meta
            )
            if not exists:
                sources_meta.append({
                    "source": current_source,
                    "source_id": current_source_id,
                    "url": current_url,
                })
                vacancy.sources_meta = sources_meta
        
        return vacancy
    
    def get_salary_display(self) -> str:
        """Форматированная зарплата для отображения"""
        if not self.salary_from and not self.salary_to:
            return "Не указана"
        
        currency_symbol = {
            'RUR': '₽',
            'USD': '$',
            'EUR': '€',
            'KZT': '₸',
            'UAH': '₴',
            'BYR': 'Br',
        }.get(self.salary_currency, self.salary_currency or '')
        
        gross_text = " до вычета налогов" if self.salary_gross else ""
        
        if self.salary_from and self.salary_to:
            return f"{self.salary_from:,} - {self.salary_to:,} {currency_symbol}{gross_text}"
        elif self.salary_from:
            return f"от {self.salary_from:,} {currency_symbol}{gross_text}"
        else:
            return f"до {self.salary_to:,} {currency_symbol}{gross_text}"
    
    def archive(self):
        """Архивировать вакансию"""
        self.archived = True
        self.is_active = False
        self.save(update_fields=['archived', 'is_active', 'updated_at'])
    
    def activate(self):
        """Активировать вакансию"""
        self.is_active = True
        self.archived = False
        self.save(update_fields=['is_active', 'archived', 'updated_at'])
    
    def is_complete(self) -> bool:
        """
        Проверка полноты записи вакансии.
        
        Запись считается полной, если содержит:
        1. Все обязательные поля (source, source_id, source_url, title, company_name, description)
        2. Локацию (area_name или address)
        3. Хотя бы одну из следующих категорий:
           - Зарплата (salary_from или salary_to)
           - Требования (experience, employment_type или schedule)
           - Навыки (key_skills или professional_roles)
        
        Returns:
            bool: True если запись полная
        """
        # Проверка обязательных полей (проверяем, что они не пустые)
        required_fields = [
            self.source,
            self.source_id,
            self.source_url,
            self.title,
            self.company_name,
            self.description
        ]
        if not all(field and str(field).strip() for field in required_fields):
            return False
        
        # Проверка локации (хотя бы одно поле должно быть заполнено)
        has_location = bool(
            (self.area_name and str(self.area_name).strip()) or
            (self.address and str(self.address).strip())
        )
        if not has_location:
            return False
        
        # Проверка дополнительной информации (хотя бы одна категория должна быть заполнена)
        has_salary = bool(self.salary_from or self.salary_to)
        
        # Проверка требований (employment_type и schedule - это ArrayField)
        has_requirements = bool(
            self.experience or
            (self.employment_type and isinstance(self.employment_type, list) and len(self.employment_type) > 0) or
            (self.schedule and isinstance(self.schedule, list) and len(self.schedule) > 0)
        )
        
        # Проверка навыков (key_skills и professional_roles - это ArrayField)
        has_skills = bool(
            (self.key_skills and isinstance(self.key_skills, list) and len(self.key_skills) > 0) or
            (self.professional_roles and isinstance(self.professional_roles, list) and len(self.professional_roles) > 0)
        )
        
        # Запись полная, если есть хотя бы одна категория дополнительной информации
        return has_salary or has_requirements or has_skills


class VacancyChangeHistory(models.Model):
    """
    История изменений нормализованной вакансии.
    
    Отслеживает:
    - Изменения в полях вакансии
    - Источник изменений (TaskItem)
    - Diff между версиями
    """
    
    vacancy = models.ForeignKey(
        NormalizedVacancy,
        on_delete=models.CASCADE,
        related_name='change_history',
        verbose_name="Вакансия"
    )
    
    version = models.IntegerField(
        verbose_name="Версия"
    )
    
    task_item = models.ForeignKey(
        'vacancies_parser.TaskItem',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vacancy_changes',
        verbose_name="Элемент задачи"
    )
    
    changed_fields = models.JSONField(
        verbose_name="Измененные поля",
        help_text="JSON с diff: {field: {old: value, new: value}}"
    )
    
    changed_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата изменения",
        db_index=True
    )
    
    parsing_mode = models.CharField(
        max_length=10,
        choices=NormalizedVacancy.PARSING_MODE_CHOICES,
        verbose_name="Режим парсинга"
    )
    
    class Meta:
        verbose_name = "История изменений вакансии"
        verbose_name_plural = "История изменений вакансий"
        ordering = ['-changed_at']
        db_table = 'vpm_vacancy_change_history'
        
        unique_together = [['vacancy', 'version']]
        
        indexes = [
            models.Index(fields=['vacancy', 'changed_at']),
            models.Index(fields=['changed_at']),
        ]
    
    def __str__(self):
        return f"[v{self.version}] {self.vacancy.title} - {self.changed_at.strftime('%Y-%m-%d %H:%M')}"


class ParsingStatistics(models.Model):
    """
    Статистика парсинга для мониторинга и аналитики.
    
    Агрегирует:
    - Производительность по источникам и режимам
    - Ошибки и их типы
    - Качество извлечения данных
    """
    
    task = models.ForeignKey(
        'ParsingTask',
        on_delete=models.CASCADE,
        related_name='statistics',
        verbose_name="Задача парсинга"
    )
    
    # Временные метрики
    started_at = models.DateTimeField(
        verbose_name="Начало"
    )
    
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Окончание"
    )
    
    duration_seconds = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Длительность (сек)"
    )
    
    # Счетчики
    total_processed = models.IntegerField(
        default=0,
        verbose_name="Всего обработано"
    )
    
    successful_items = models.IntegerField(
        default=0,
        verbose_name="Успешно обработано"
    )
    
    failed_items = models.IntegerField(
        default=0,
        verbose_name="Ошибок"
    )
    
    blocked_items = models.IntegerField(
        default=0,
        verbose_name="Заблокировано"
    )
    
    # Производительность
    avg_item_duration_ms = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Среднее время на элемент (мс)"
    )
    
    items_per_second = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Элементов в секунду"
    )
    
    # Качество данных
    complete_records = models.IntegerField(
        default=0,
        verbose_name="Полных записей",
        help_text="Записи со всеми обязательными полями"
    )
    
    incomplete_records = models.IntegerField(
        default=0,
        verbose_name="Неполных записей"
    )
    
    # Ошибки
    error_breakdown = models.JSONField(
        default=dict,
        verbose_name="Разбивка ошибок",
        help_text="JSON: {error_type: count}"
    )
    
    # Метаданные
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Дата создания"
    )
    
    class Meta:
        verbose_name = "Статистика парсинга"
        verbose_name_plural = "Статистика парсинга"
        ordering = ['-created_at']
        db_table = 'vpm_parsing_statistics'
        
        indexes = [
            models.Index(fields=['task', 'created_at']),
            models.Index(fields=['started_at']),
        ]
    
    def __str__(self):
        return f"Stats for Task {self.task_id}: {self.successful_items}/{self.total_processed} OK"
    
    def calculate_metrics(self):
        """Расчет производственных метрик"""
        if self.finished_at and self.started_at:
            self.duration_seconds = int((self.finished_at - self.started_at).total_seconds())
            
            if self.duration_seconds > 0:
                self.items_per_second = round(self.total_processed / self.duration_seconds, 2)
        
        if self.total_processed > 0 and self.duration_seconds:
            self.avg_item_duration_ms = round(
                (self.duration_seconds * 1000) / self.total_processed,
                2
            )
        
        self.save(update_fields=[
            'duration_seconds',
            'avg_item_duration_ms',
            'items_per_second'
        ])
