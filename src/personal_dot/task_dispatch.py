import uuid

from personal_dot.config import get_settings
from personal_dot.jobs import execute_task
from personal_dot.queue import get_queue


def enqueue_task(task_id: uuid.UUID | str) -> None:
    normalized_id = str(task_id)
    settings = get_settings()
    # Database task claiming is the duplicate-execution guard. RQ delivery IDs
    # must remain unique so an approval can resume the same task in a new job.
    get_queue().enqueue(
        execute_task,
        normalized_id,
        job_timeout=settings.rq_job_timeout_seconds,
        result_ttl=settings.rq_result_ttl_seconds,
        failure_ttl=settings.rq_failure_ttl_seconds,
    )
