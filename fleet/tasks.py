from celery import shared_task

from .retention import prune_operation_logs as prune
from .services import expire_stale_operations as expire


@shared_task(name="fleet.tasks.prune_operation_logs", ignore_result=True)
def prune_operation_logs():
    return prune()


@shared_task(name="fleet.tasks.expire_stale_operations", ignore_result=True)
def expire_stale_operations():
    return expire()
