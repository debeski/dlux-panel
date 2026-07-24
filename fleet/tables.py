import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html

from dlux.tables import DluxTable

from .models import ManagedProject


def _badge(css_class, label):
    return format_html('<span class="badge {}">{}</span>', css_class, label)


class ManagedProjectTable(DluxTable):
    name = tables.Column(verbose_name="Project")
    agent = tables.Column(verbose_name="Agent", orderable=False, empty_values=())
    versions = tables.Column(accessor="pk", verbose_name="Versions", orderable=False)
    update_state = tables.Column(accessor="pk", verbose_name="Update", orderable=False)
    backup_state = tables.Column(accessor="pk", verbose_name="Backup", orderable=False)
    observed = tables.Column(accessor="pk", verbose_name="Observed", orderable=False)

    class Meta(DluxTable.Meta):
        model = ManagedProject
        fields = ("name", "agent", "versions", "update_state", "backup_state", "observed")
        order_by = ("name",)
        dlux_actions = True

    def render_name(self, record):
        return format_html(
            '<span class="fw-semibold">{}</span><div class="small text-muted">{}</div>',
            record.name,
            record.environment,
        )

    def render_agent(self, record):
        agent = getattr(record, "agent", None)
        if agent is None:
            return _badge("text-bg-warning", "Not enrolled")
        if agent.revoked_at:
            return _badge("text-bg-danger", "Revoked")
        if agent.is_online:
            return _badge("text-bg-success", "Online")
        return _badge("text-bg-secondary", "Offline")

    def render_versions(self, record):
        snapshot = getattr(record, "latest_snapshot", None)
        versions = (snapshot.versions if snapshot else None) or {}
        return format_html(
            '{}<div class="small text-muted">DLUX {}</div>',
            versions.get("application") or "—",
            versions.get("dlux") or "—",
        )

    def render_update_state(self, record):
        snapshot = getattr(record, "latest_snapshot", None)
        state = ((snapshot.update_state if snapshot else None) or {}).get("active_status")
        return state or "—"

    def render_backup_state(self, record):
        snapshot = getattr(record, "latest_snapshot", None)
        state = ((snapshot.backup_summary if snapshot else None) or {}).get("status")
        return state or "—"

    def render_observed(self, record):
        snapshot = getattr(record, "latest_snapshot", None)
        if snapshot is None or not snapshot.observed_at:
            return "—"
        return snapshot.observed_at.strftime("%Y-%m-%d %H:%M:%S")

    def _modal_action(self, label, icon, url, title, *, permissions=None, dblclick=False, danger=False):
        action = {
            "label": label,
            "icon": icon,
            "type": "event",
            "event": "dlux:dynamic_modal:open",
            "data": {"url": url, "title": title},
        }
        if permissions:
            action["permissions"] = permissions
        if dblclick:
            action["dblclick"] = True
        if danger:
            action["danger"] = True
        return action

    def get_dlux_row_actions(self, record, base_actions):
        """Every project operation is reachable from the row's context menu, each
        opening a Dlux dynamic modal. Nothing here navigates away from the page."""
        name = record.name
        agent = getattr(record, "agent", None)
        agent_active = bool(agent and not agent.revoked_at)

        actions = [
            self._modal_action(
                "View",
                "bi bi-eye",
                reverse("fleet:project_detail", args=[record.pk]),
                name,
                permissions=["fleet.view_managedproject"],
                dblclick=True,
            ),
            self._modal_action(
                "Edit",
                "bi bi-pencil",
                reverse("modal_manager", args=["fleet", "ManagedProject", record.pk]),
                f"Edit {name}",
                permissions=["fleet.change_managedproject"],
            ),
            {"type": "divider"},
            self._modal_action(
                "Queue update",
                "bi bi-arrow-down-circle",
                reverse("fleet:project_update", args=[record.pk]),
                f"Update {name}",
                permissions=["fleet.run_image_update"],
            ),
            self._modal_action(
                "Create backup",
                "bi bi-archive",
                reverse("fleet:project_backup", args=[record.pk]),
                f"Back up {name}",
                permissions=["fleet.create_project_backup"],
            ),
            self._modal_action(
                "Safe restart",
                "bi bi-arrow-repeat",
                reverse("fleet:project_restart", args=[record.pk]),
                f"Restart {name}",
                permissions=["fleet.restart_managed_project"],
            ),
            {"type": "divider"},
            self._modal_action(
                "Enrollment token",
                "bi bi-key",
                reverse("fleet:project_enrollment", args=[record.pk]),
                f"Enroll {name}",
                permissions=["fleet.manage_composer_agent"],
            ),
        ]

        if agent_active:
            actions += [
                self._modal_action(
                    "Rotate credential",
                    "bi bi-shuffle",
                    reverse("fleet:project_rotate", args=[record.pk]),
                    f"Rotate {name}",
                    permissions=["fleet.manage_composer_agent"],
                ),
                self._modal_action(
                    "Revoke agent",
                    "bi bi-slash-circle",
                    reverse("fleet:project_revoke", args=[record.pk]),
                    f"Revoke {name}",
                    permissions=["fleet.manage_composer_agent"],
                    danger=True,
                ),
            ]

        actions += [
            {"type": "divider"},
            self._modal_action(
                "Recovery deploy",
                "bi bi-exclamation-octagon",
                reverse("fleet:project_recovery", args=[record.pk]),
                f"Break-glass recovery — {name}",
                permissions=["fleet.run_recovery_deploy"],
                danger=True,
            ),
        ]
        return actions
