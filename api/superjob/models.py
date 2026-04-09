from django.db import models
from django.utils import timezone


class SuperJobVacancy(models.Model):
    """Модель для хранения вакансий с SuperJob"""
    
    # Основная информация
    title = models.CharField(max_length=255, verbose_name="Название вакансии")
    company_name = models.CharField(max_length=255, verbose_name="Название компании")
    salary_from = models.IntegerField(null=True, blank=True, verbose_name="Зарплата от")
    salary_to = models.IntegerField(null=True, blank=True, verbose_name="Зарплата до")
    salary_currency = models.CharField(max_length=10, null=True, blank=True, verbose_name="Валюта зарплаты")
    salary_gross = models.BooleanField(default=True, verbose_name="Зарплата до вычета налогов")
    
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
    superjob_id = models.CharField(max_length=50, unique=True, verbose_name="ID вакансии на SuperJob")
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
        verbose_name = "Вакансия SuperJob"
        verbose_name_plural = "Вакансии SuperJob"
        ordering = ['-published_at']
        db_table = 'vpm_sj_vacancy'
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['company_name']),
            models.Index(fields=['city']),
            models.Index(fields=['published_at']),
            models.Index(fields=['superjob_id']),
            models.Index(fields=['employer_id']),
            models.Index(fields=['current_version']),
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
        
        if not self.salary_gross:
            salary_str += " на руки"
        
        return salary_str
    
    def create_version(self, new_data=None, auto_save=True):
        """
        Создание новой версии вакансии.

        Args:
            new_data: Новые данные для сравнения с текущими.
            auto_save: Сохранить вакансию после создания версии.
                       False при bulk-операциях (вызывающая сторона сохраняет через bulk_update).
        """
        self.current_version += 1
        
        version = SuperJobVacancyVersion.objects.create(
            vacancy=self,
            version_number=self.current_version
        )
        
        if new_data:
            changes = []
            for field_name, new_value in new_data.items():
                if hasattr(self, field_name):
                    old_value = getattr(self, field_name)
                    if old_value != new_value:
                        changes.append({
                            'field_name': field_name,
                            'old_value': str(old_value) if old_value is not None else '',
                            'new_value': str(new_value) if new_value is not None else ''
                        })
            
            if changes:
                SuperJobVacancyChangeHistory.objects.bulk_create([
                    SuperJobVacancyChangeHistory(vacancy=self, version=version, **change)
                    for change in changes
                ])
                version.change_summary = f"Изменено полей: {len(changes)}"
                version.save()
        
        if auto_save:
            self.save()
        return version
    
    def has_changes(self, new_data):
        """Проверка наличия изменений в данных"""
        for field_name, new_value in new_data.items():
            if hasattr(self, field_name):
                old_value = getattr(self, field_name)
                if old_value != new_value:
                    return True
        return False


class SuperJobVacancyVersion(models.Model):
    """Модель для хранения версий вакансий (только метаданные)"""
    
    vacancy = models.ForeignKey(SuperJobVacancy, on_delete=models.CASCADE, related_name='versions', verbose_name="Вакансия")
    version_number = models.IntegerField(verbose_name="Номер версии")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания версии")
    
    # Дополнительные метаданные версии
    change_summary = models.TextField(null=True, blank=True, verbose_name="Описание изменений")
    
    class Meta:
        verbose_name = "Версия вакансии SuperJob"
        verbose_name_plural = "Версии вакансий SuperJob"
        ordering = ['-version_number']
        db_table = 'vpm_sj_vacancy_version'
        unique_together = ['vacancy', 'version_number']
        indexes = [
            models.Index(fields=['vacancy', 'version_number']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Версия {self.version_number} вакансии {self.vacancy.title}"
    
    @property
    def salary_display(self):
        """Отображение зарплаты в удобном формате"""
        return self.vacancy.salary_display
    
    def get_changes_from_previous(self):
        """Получение изменений относительно предыдущей версии"""
        previous_version = self.vacancy.versions.filter(
            version_number__lt=self.version_number
        ).order_by('-version_number').first()
        
        if previous_version:
            return self.changes.all()
        return []


class SuperJobVacancyChangeHistory(models.Model):
    """Модель для хранения истории изменений полей вакансий"""
    
    vacancy = models.ForeignKey(SuperJobVacancy, on_delete=models.CASCADE, related_name='change_history', verbose_name="Вакансия")
    version = models.ForeignKey(SuperJobVacancyVersion, on_delete=models.CASCADE, related_name='changes', verbose_name="Версия")
    
    field_name = models.CharField(max_length=100, verbose_name="Название поля")
    old_value = models.TextField(null=True, blank=True, verbose_name="Старое значение")
    new_value = models.TextField(null=True, blank=True, verbose_name="Новое значение")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата изменения")
    
    class Meta:
        verbose_name = "История изменений вакансии SuperJob"
        verbose_name_plural = "История изменений вакансий SuperJob"
        ordering = ['-created_at']
        db_table = 'vpm_sj_vacancy_change_history'
        indexes = [
            models.Index(fields=['vacancy', 'created_at']),
            models.Index(fields=['field_name']),
        ]
    
    def __str__(self):
        return f"Изменение {self.field_name} в вакансии {self.vacancy.title}"
    
    @property
    def change_description(self):
        """Описание изменения"""
        return f"{self.field_name}: {self.old_value} → {self.new_value}" 