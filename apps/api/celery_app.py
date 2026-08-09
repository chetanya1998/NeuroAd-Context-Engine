from __future__ import annotations

import os

from celery import Celery


broker_url = os.getenv("NEUROAD_REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("neuroad", broker=broker_url, backend=broker_url)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_soft_time_limit=int(os.getenv("NEUROAD_TASK_SOFT_LIMIT_SECONDS", "3300")),
    task_time_limit=int(os.getenv("NEUROAD_TASK_LIMIT_SECONDS", "3600")),
    result_expires=86400,
)


@celery_app.task(name="neuroad.process_upload_job", autoretry_for=(OSError,), retry_backoff=True, max_retries=2)
def process_upload_job_task(job_id: str, video_id: str) -> None:
    import main

    main.init_db()
    main.process_upload_job(job_id, video_id)


@celery_app.task(name="neuroad.process_comparison_job", autoretry_for=(OSError,), retry_backoff=True, max_retries=2)
def process_comparison_job_task(comparison_id: str, members: list[dict[str, object]]) -> None:
    import main

    main.init_db()
    main.process_comparison_job(comparison_id, members)
