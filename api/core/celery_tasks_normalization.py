"""
Celery задачи нормализации вакансий.

Содержит:
- Фоновую дедупликацию нормализованных вакансий
- Пересчёт нормализации для уже обработанных задач
"""

import logging

from celery import shared_task

from .models import ParsingTask, TaskItem

logger = logging.getLogger('celery.module.vacancies_parser.normalization')


@shared_task(
    name='vacancies_parser.tasks.rebuild_normalized_vacancies_for_task',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def rebuild_normalized_vacancies_for_task(self, task_id: int) -> dict:
    """
    Повторная нормализация вакансий для указанной задачи парсинга.

    Полезна при изменении логики нормализации. Использует extracted_data
    из TaskItem для повторной записи в NormalizedVacancy.
    """
    from .tasks.worker import _save_normalized_vacancy

    try:
        task = ParsingTask.objects.get(id=task_id)
    except ParsingTask.DoesNotExist:
        logger.error(f"rebuild_normalized_vacancies: задача {task_id} не найдена")
        return {'error': 'task_not_found', 'task_id': task_id}

    items = TaskItem.objects.filter(
        task_id=task_id,
        status='completed',
        extracted_data__isnull=False,
    ).exclude(extracted_data={})

    total = items.count()
    success = 0
    failed = 0

    for item in items.iterator(chunk_size=100):
        if not isinstance(item.extracted_data, dict) or not item.extracted_data:
            continue
        try:
            _save_normalized_vacancy(item.extracted_data, task, item)
            success += 1
        except Exception as e:
            logger.warning(f"rebuild: ошибка для item {item.id}: {e}")
            failed += 1

    logger.info(
        f"Rebuild task {task_id}: всего={total}, успешно={success}, ошибок={failed}"
    )
    return {'task_id': task_id, 'total': total, 'success': success, 'failed': failed}


@shared_task(name='vacancies_parser.tasks.run_deduplication_task')
def run_deduplication_task() -> dict:
    """
    Фоновая дедупликация нормализованных вакансий.

    Обрабатывает записи с deduplication_status='pending':
    - Группирует по deduplication_hash
    - Самую старую запись в группе помечает как 'original'
    - Остальные помечает как 'duplicate'
    """
    from .normalized_models import NormalizedVacancy

    BATCH_SIZE = 500
    processed = 0
    marked_original = 0
    marked_duplicate = 0

    pending_hashes = (
        NormalizedVacancy.objects
        .filter(deduplication_status='pending')
        .exclude(deduplication_hash='')
        .values_list('deduplication_hash', flat=True)
        .distinct()
    )

    for dedup_hash in pending_hashes.iterator(chunk_size=BATCH_SIZE):
        existing_original = (
            NormalizedVacancy.objects
            .filter(deduplication_hash=dedup_hash, deduplication_status='original')
            .only('id')
            .first()
        )

        group = list(
            NormalizedVacancy.objects
            .filter(deduplication_hash=dedup_hash, deduplication_status='pending')
            .order_by('created_at')
            .only('id', 'created_at')
        )

        if not group:
            continue

        processed += len(group)

        if existing_original:
            NormalizedVacancy.objects.filter(
                id__in=[v.id for v in group]
            ).update(
                deduplication_status='duplicate',
                original_vacancy_id=existing_original.id,
            )
            marked_duplicate += len(group)
        else:
            original = group[0]
            NormalizedVacancy.objects.filter(id=original.id).update(
                deduplication_status='original'
            )
            marked_original += 1

            if len(group) > 1:
                duplicate_ids = [v.id for v in group[1:]]
                NormalizedVacancy.objects.filter(id__in=duplicate_ids).update(
                    deduplication_status='duplicate',
                    original_vacancy_id=original.id,
                )
                marked_duplicate += len(duplicate_ids)

    logger.info(
        f"Дедупликация завершена: обработано={processed}, "
        f"оригинальных={marked_original}, дублей={marked_duplicate}"
    )
    return {
        'processed': processed,
        'marked_original': marked_original,
        'marked_duplicate': marked_duplicate,
    }
