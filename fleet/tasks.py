from celery import shared_task

from .retention import prune_operation_logs as prune


@shared_task(name="fleet.tasks.prune_operation_logs", ignore_result=True)
def prune_operation_logs():
    return prune()
