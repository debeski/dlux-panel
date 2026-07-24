import django_filters
from django.db.models import Q

from .models import ManagedProject

AGENT_STATE_CHOICES = (
    ("online", "Online"),
    ("offline", "Offline"),
    ("revoked", "Revoked"),
    ("unenrolled", "Not enrolled"),
)


class ManagedProjectFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search", label="Search")
    agent_state = django_filters.ChoiceFilter(
        choices=AGENT_STATE_CHOICES,
        method="filter_agent_state",
        label="Agent",
    )

    class Meta:
        model = ManagedProject
        fields = ("search", "environment", "agent_state", "is_active")

    def filter_search(self, queryset, name, value):
        value = (value or "").strip()
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(slug__icontains=value) | Q(base_url__icontains=value)
        )

    def filter_agent_state(self, queryset, name, value):
        if value == "unenrolled":
            return queryset.filter(agent__isnull=True)
        if value == "revoked":
            return queryset.filter(agent__revoked_at__isnull=False)
        if value in {"online", "offline"}:
            candidates = queryset.filter(agent__isnull=False, agent__revoked_at__isnull=True)
            online_pks = [
                project.pk for project in candidates.select_related("agent")
                if project.agent.is_online
            ]
            if value == "online":
                return candidates.filter(pk__in=online_pks)
            return candidates.exclude(pk__in=online_pks)
        return queryset
