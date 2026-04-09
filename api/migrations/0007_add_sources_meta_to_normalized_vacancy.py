from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vacancies_parser", "0006_seed_system_parsing_tasks"),
    ]

    operations = [
        migrations.AddField(
            model_name="normalizedvacancy",
            name="sources_meta",
            field=models.JSONField(
                default=list,
                blank=True,
                verbose_name="Источники",
                help_text="Список площадок, на которых размещена вакансия",
            ),
        ),
    ]

