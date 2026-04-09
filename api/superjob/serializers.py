from rest_framework import serializers

from .models import SuperJobVacancy, SuperJobVacancyVersion, SuperJobVacancyChangeHistory


class VacancyChangeHistorySerializer(serializers.ModelSerializer):

    class Meta:
        model = SuperJobVacancyChangeHistory
        ref_name = 'SuperJobVacancyChangeHistory'
        fields = ['id', 'field_name', 'old_value', 'new_value', 'created_at', 'change_description']
        read_only_fields = ['id', 'created_at', 'change_description']


class VacancyVersionSerializer(serializers.ModelSerializer):
    changes_count = serializers.SerializerMethodField()
    changes = VacancyChangeHistorySerializer(many=True, read_only=True, source='changes.all')

    class Meta:
        model = SuperJobVacancyVersion
        ref_name = 'SuperJobVacancyVersion'
        fields = ['id', 'version_number', 'created_at', 'change_summary', 'changes_count', 'changes']
        read_only_fields = ['id', 'version_number', 'created_at']

    def get_changes_count(self, obj):
        return obj.changes.count()


class VacancyListSerializer(serializers.ModelSerializer):
    salary_display = serializers.CharField(read_only=True)

    class Meta:
        model = SuperJobVacancy
        ref_name = 'SuperJobVacancyList'
        fields = [
            'id', 'title', 'company_name', 'salary_from', 'salary_to',
            'salary_currency', 'salary_display', 'city', 'employment_type',
            'experience_level', 'key_skills', 'published_at', 'url',
            'premium', 'is_active', 'current_version', 'professional_role',
        ]
        read_only_fields = ['id', 'salary_display']


class VacancyDetailSerializer(serializers.ModelSerializer):
    salary_display = serializers.CharField(read_only=True)
    versions_count = serializers.SerializerMethodField()
    latest_version = serializers.SerializerMethodField()

    class Meta:
        model = SuperJobVacancy
        ref_name = 'SuperJobVacancyDetail'
        fields = [
            'id', 'title', 'company_name', 'salary_from', 'salary_to',
            'salary_currency', 'salary_gross', 'salary_display', 'city', 'address',
            'description', 'requirements', 'responsibilities', 'employment_type',
            'experience_level', 'schedule_type', 'skills', 'key_skills',
            'superjob_id', 'url', 'company_url', 'alternate_url', 'apply_alternate_url',
            'employer_id', 'employer_name', 'employer_trusted', 'employer_blacklisted',
            'professional_role', 'premium', 'has_test', 'response_letter_required',
            'published_at', 'created_at', 'updated_at', 'is_active',
            'current_version', 'versions_count', 'latest_version',
        ]
        read_only_fields = [
            'id', 'salary_display', 'created_at', 'updated_at',
            'versions_count', 'latest_version',
        ]

    def get_versions_count(self, obj):
        return obj.versions.count()

    def get_latest_version(self, obj):
        latest = obj.versions.first()
        if latest:
            return VacancyVersionSerializer(latest).data
        return None


class VacancyStatsSerializer(serializers.Serializer):

    class Meta:
        ref_name = 'SuperJobVacancyStats'

    total_vacancies = serializers.IntegerField()
    active_vacancies = serializers.IntegerField()
    avg_salary_from = serializers.FloatField(allow_null=True)
    avg_salary_to = serializers.FloatField(allow_null=True)
    min_salary_from = serializers.IntegerField(allow_null=True)
    max_salary_to = serializers.IntegerField(allow_null=True)
    vacancies_by_city = serializers.DictField()
    vacancies_by_role = serializers.DictField()
    vacancies_by_experience = serializers.DictField()
    recent_vacancies_count = serializers.IntegerField()
    premium_vacancies_count = serializers.IntegerField()


class ParsingTaskStatusSerializer(serializers.Serializer):

    class Meta:
        ref_name = 'SuperJobParsingTaskStatus'

    task_id = serializers.CharField()
    status = serializers.CharField()
    progress = serializers.DictField(allow_null=True)
    result = serializers.DictField(allow_null=True)
    error = serializers.CharField(allow_null=True)
