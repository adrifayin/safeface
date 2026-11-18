"""Celery configuration: two queues, ``gpu`` and ``cpu``.

Workers acknowledge late and fetch one task at a time so a crashed worker
does not silently lose a job; hard time limits stop runaway parsers.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("safeface", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_default_queue="cpu",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=settings.job_soft_time_limit_s,
    task_time_limit=settings.job_time_limit_s,
    task_always_eager=settings.celery_eager,
    task_eager_propagates=False,
    task_serializer="json",
    accept_content=["json"],
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    worker_send_task_events=False,
    task_send_sent_event=False,
)
celery_app.autodiscover_tasks(["app.workers"], related_name="tasks", force=True)

QUEUE_GPU = "gpu"
QUEUE_CPU = "cpu"
