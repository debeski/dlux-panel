"""
Generated with django-lux 1.4.15.
Project name: dlux_control.
Generated on: 2026-07-23.
"""
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", include("health_check.urls")),
    path("api/agent/v1/", include("fleet.agent_urls")),
    path("", include("dlux.urls")),
    # DjangoLux generated routes start
    path("fleet/", include(("fleet.urls", "fleet"), namespace="fleet")),
    # DjangoLux generated routes end
]
