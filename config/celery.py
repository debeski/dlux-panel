"""
Generated with django-lux 1.4.15.
Project name: dlux_control.
Generated on: 2026-07-23.
"""
import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("dlux_control")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.broker_connection_retry_on_startup = True
app.autodiscover_tasks()
