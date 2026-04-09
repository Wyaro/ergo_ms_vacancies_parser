from django.db import models
from django.utils import timezone


class Vacancy(models.Model):
    """Модель для хранения вакансий с HeadHunter"""
    
    # Основная информация
    title = models.CharField(max_length=255, verbose_name="Название вакансии")
    company_name = models.CharField(max_length=255, verbose_name="Название компании")
    salary_from = models.IntegerField(null=True, blank=True, verbose_name="Зарплата от")
    salary_to = models.IntegerField(null=True, blank=True, verbose_name="Зарплата до")
    salary_currency = models.CharField(max_length=10, null=True, blank=True, verbose_name="Валюта зарплаты")
    salary_gross = models.BooleanField(null=True, blank=True, default=True, verbose_name="Зарплата до вычета налогов")
    
    # Локация
    city = models.CharField(max_length=100, null=True, blank=True, verbose_name="Город")
    address = models.TextField(null=True, blank=True, verbose_name="Адрес")
    
    # Описание и требования
    description = models.TextField(verbose_name="Описание вакансии")
    requirements = models.TextField(null=True, blank=True, verbose_name="Требования")
    responsibilities = models.TextField(null=True, blank=True, verbose_name="Обязанности")
    
    # Тип занятости и опыт
    employment_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="Тип занятости")
    experience_level = models.CharField(max_length=50, null=True, blank=True, verbose_name="Уровень опыта")
    
    # Навыки и ключевые слова
    skills = models.JSONField(default=list, verbose_name="Навыки")
    key_skills = models.JSONField(default=list, verbose_name="Ключевые навыки")
    
    # Ссылки и идентификаторы
    hh_id = models.CharField(max_length=50, unique=True, verbose_name="ID вакансии на HH")
    url = models.URLField(verbose_name="Ссылка на вакансию")
    company_url = models.URLField(null=True, blank=True, verbose_name="Ссылка на компанию")
    
    # Дополнительные поля для полного парсинга
    schedule_type = models.CharField(max_length=50, null=True, blank=True, verbose_name="График работы")
    professional_role = models.CharField(max_length=100, null=True, blank=True, verbose_name="Профессиональная роль")
    alternate_url = models.URLField(null=True, blank=True, verbose_name="Альтернативная ссылка")
    apply_alternate_url = models.URLField(null=True, blank=True, verbose_name="Ссылка для отклика")
    
    # Информация о работодателе
    employer_id = models.CharField(max_length=50, null=True, blank=True, verbose_name="ID работодателя")
    employer_name = models.CharField(max_length=255, null=True, blank=True, verbose_name="Название работодателя")
    employer_trusted = models.BooleanField(default=False, verbose_name="Проверенный работодатель")
    employer_blacklisted = models.BooleanField(default=False, verbose_name="Работодатель в черном списке")
    
    # Дополнительная информация
    premium = models.BooleanField(default=False, verbose_name="Премиум вакансия")
    has_test = models.BooleanField(default=False, verbose_name="Есть тестовое задание")
    response_letter_required = models.BooleanField(default=False, verbose_name="Требуется сопроводительное письмо")
    
    # Метаданные
    published_at = models.DateTimeField(verbose_name="Дата публикации")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания записи")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления записи")
    
    # Статус
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    
    # Версионность
    current_version = models.IntegerField(default=1, verbose_name="Текущая версия")
    
    class Meta:
        verbose_name = "Вакансия"
        verbose_name_plural = "Вакансии"
        ordering = ['-published_at']
        db_table = 'vpm_hh_vacancy'
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['company_name']),
            models.Index(fields=['city']),
            models.Index(fields=['published_at']),
            models.Index(fields=['hh_id']),
            models.Index(fields=['employer_id']),
            models.Index(fields=['current_version']),
            # Для быстрого поиска по критериям
            models.Index(fields=['title', 'city']),
            models.Index(fields=['salary_from', 'salary_to']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.company_name}"
    
    @property
    def salary_display(self):
        """Отображение зарплаты в удобном формате"""
        if not self.salary_from and not self.salary_to:
            return "Не указана"
        
        if self.salary_from and self.salary_to:
            salary_str = f"{self.salary_from} - {self.salary_to}"
        elif self.salary_from:
            salary_str = f"от {self.salary_from}"
        else:
            salary_str = f"до {self.salary_to}"
        
        if self.salary_currency:
            salary_str += f" {self.salary_currency}"
        
        if self.salary_gross is False:
            salary_str += " на руки"
        
        return salary_str
    
    def _normalize_json_field_value(self, value):
        """Нормализует значение JSON поля (список) для строкового представления"""
        if not value:
            return ''
        
        if not isinstance(value, list):
            return str(value) if value is not None else ''
        
        normalized_items = []
        for item in value:
            if isinstance(item, str):
                normalized_items.append(item)
            elif isinstance(item, dict):
                # Извлекаем значение из словаря (обычно 'name' для навыков)
                name = item.get('name') or item.get('value') or str(item)
                if name:
                    normalized_items.append(str(name))
            else:
                normalized_items.append(str(item))
        
        return ', '.join(normalized_items)
    
    def create_version(self, new_data=None):
        """Создает новую версию вакансии с текущими данными"""
        self.current_version += 1
        self.save()
        
        version = VacancyVersion.objects.create(
            vacancy=self,
            version_number=self.current_version,
            created_at=timezone.now()
        )
        
        # Если переданы новые данные, создаем историю изменений
        if new_data:
            changes = []
            for field, new_value in new_data.items():
                if hasattr(self, field):
                    old_value = getattr(self, field)
                    
                    # Специальная обработка для JSON полей
                    if field in ['key_skills', 'skills']:
                        old_value_str = self._normalize_json_field_value(old_value)
                        new_value_str = self._normalize_json_field_value(new_value)
                    else:
                        old_value_str = str(old_value) if old_value is not None else ''
                        new_value_str = str(new_value) if new_value is not None else ''
                    
                    if old_value_str != new_value_str:
                        changes.append({
                            'field_name': field,
                            'old_value': old_value_str,
                            'new_value': new_value_str
                        })
            
            # Создаем записи истории изменений
            for change in changes:
                VacancyChangeHistory.objects.create(
                    vacancy=self,
                    version=version,
                    field_name=change['field_name'],
                    old_value=change['old_value'],
                    new_value=change['new_value']
                )
            
            # Обновляем описание изменений в версии
            if changes:
                change_summary = f"Изменено полей: {len(changes)}"
                version.change_summary = change_summary
                version.save()
        
        return version
    
    def has_changes(self, new_data):
        """Проверяет, есть ли изменения в вакансии"""
        significant_fields = [
            'title', 'company_name', 'salary_from', 'salary_to', 'salary_currency', 'salary_gross',
            'city', 'address', 'description', 'requirements', 'responsibilities',
            'employment_type', 'experience_level', 'key_skills', 'schedule_type',
            'professional_role', 'employer_name', 'premium', 'has_test',
            'response_letter_required'
        ]
        
        for field in significant_fields:
            if field in new_data:
                current_value = getattr(self, field)
                new_value = new_data[field]
                
                # Специальная обработка для JSON полей
                if field in ['key_skills', 'skills']:
                    if set(current_value or []) != set(new_value or []):
                        return True
                else:
                    # Специальная обработка для boolean полей с возможностью None
                    if field == 'salary_gross':
                        if current_value is not new_value:
                            return True
                    else:
                        if current_value != new_value:
                            return True
        
        return False


class VacancyVersion(models.Model):
    """Модель для хранения версий вакансий (только метаданные)"""
    
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name='versions', verbose_name="Вакансия")
    version_number = models.IntegerField(verbose_name="Номер версии")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания версии")
    
    # Дополнительные метаданные версии
    change_summary = models.TextField(null=True, blank=True, verbose_name="Описание изменений")
    
    class Meta:
        verbose_name = "Версия вакансии"
        verbose_name_plural = "Версии вакансий"
        ordering = ['-version_number']
        db_table = 'vpm_hh_vacancy_version'
        unique_together = ['vacancy', 'version_number']
        indexes = [
            models.Index(fields=['vacancy', 'version_number']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.vacancy.title} - версия {self.version_number}"
    
    @property
    def salary_display(self):
        """Отображение зарплаты в удобном формате (берет из основной вакансии)"""
        return self.vacancy.salary_display
    
    def get_changes_from_previous(self):
        """Получает изменения относительно предыдущей версии"""
        if self.version_number <= 1:
            return "Первая версия"
        
        # Здесь можно добавить логику для сравнения с предыдущей версией
        # если нужно будет хранить историю изменений
        return self.change_summary or "Изменения не описаны"


class VacancyChangeHistory(models.Model):
    """Модель для хранения истории изменений полей вакансий"""
    
    vacancy = models.ForeignKey(Vacancy, on_delete=models.CASCADE, related_name='change_history', verbose_name="Вакансия")
    version = models.ForeignKey(VacancyVersion, on_delete=models.CASCADE, related_name='changes', verbose_name="Версия")
    
    field_name = models.CharField(max_length=100, verbose_name="Название поля")
    old_value = models.TextField(null=True, blank=True, verbose_name="Старое значение")
    new_value = models.TextField(null=True, blank=True, verbose_name="Новое значение")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата изменения")
    
    class Meta:
        verbose_name = "История изменений вакансии"
        verbose_name_plural = "История изменений вакансий"
        ordering = ['-created_at']
        db_table = 'vpm_hh_vacancy_change_history'
        indexes = [
            models.Index(fields=['vacancy', 'version']),
            models.Index(fields=['field_name']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.vacancy.title} - {self.field_name} (v{self.version.version_number})"
    
    @property
    def change_description(self):
        """Описание изменения в удобном формате"""
        if self.old_value is None and self.new_value is not None:
            return f"Добавлено: {self.new_value}"
        elif self.old_value is not None and self.new_value is None:
            return f"Удалено: {self.old_value}"
        elif self.old_value != self.new_value:
            return f"Изменено: {self.old_value} → {self.new_value}"
        else:
            return "Без изменений"
