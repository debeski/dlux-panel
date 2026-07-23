from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import OperationEvent


def prune_operation_logs(days=None):
    retention_days = int(
        days
        if days is not None
        else getattr(settings, "FLEET_OPERATION_LOG_RETENTION_DAYS", 90)
    )
    cutoff = timezone.now() - timedelta(days=max(1, retention_days))
    return OperationEvent.objects.filter(received_at__lt=cutoff).exclude(log="").update(log="")
