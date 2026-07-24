"""The single-page panel: Dlux table, context-menu actions, and modal endpoints."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from dlux.models import SystemSettings

from fleet.models import FleetOperation, ManagedProject
from fleet.services import queue_operation

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class PanelUITests(TestCase):
    def setUp(self):
        cache.clear()
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=("is_configured",))
        self.user = get_user_model().objects.create_superuser(
            username="root", password="panel-pass", email="root@example.com"
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.project = ManagedProject.objects.create(name="Forms", slug="forms")

    def test_overview_renders_dlux_table_with_context_menu_rows(self):
        response = self.client.get(reverse("fleet:overview"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("dlux-data-table", body)
        self.assertIn('data-dlux-context="true"', body)
        self.assertIn("Forms", body)

    def test_overview_offers_modal_triggers_instead_of_form_pages(self):
        body = self.client.get(reverse("fleet:overview")).content.decode()
        self.assertIn("data-dynamic-modal", body)
        self.assertIn(reverse("fleet:project_modal_add"), body)
        self.assertIn(reverse("fleet:batch_add"), body)

    def test_add_edit_modal_is_form_only(self):
        add = self.client.get(reverse("fleet:project_modal_add"), **AJAX)
        self.assertEqual(add.status_code, 200)
        html = json.loads(add.content)["html"]
        self.assertIn("name", html)
        # A form-only modal must not embed the record listing table.
        self.assertNotIn("dlux-data-table", html)

    def test_adding_a_project_refreshes_the_parent_table(self):
        response = self.client.post(
            reverse("fleet:project_modal_add"),
            {"name": "Newbie", "slug": "newbie", "environment": "production", "is_active": "on"},
            **AJAX,
        )
        payload = json.loads(response.content)
        self.assertTrue(payload["success"])
        # The form-only modal has no inner list, so it must reload the overview
        # for the new row to appear in the fleet table.
        self.assertTrue(payload["refresh_parent"])
        self.assertTrue(ManagedProject.objects.filter(slug="newbie").exists())

    def test_row_actions_all_open_modals(self):
        from fleet.tables import ManagedProjectTable

        table = ManagedProjectTable(ManagedProject.objects.all())
        actions = table.get_dlux_row_actions(self.project, [])
        events = [action for action in actions if action.get("type") == "event"]
        self.assertTrue(events)
        for action in events:
            self.assertEqual(action["event"], "dlux:dynamic_modal:open")
            self.assertIn("url", action["data"])
        self.assertTrue(any(action.get("dblclick") for action in events))

    def test_detail_returns_modal_html_for_ajax_and_a_page_otherwise(self):
        url = reverse("fleet:project_detail", args=[self.project.pk])

        modal = self.client.get(url, **AJAX)
        self.assertEqual(modal.status_code, 200)
        self.assertEqual(modal["Content-Type"], "application/json")
        self.assertIn("modal-body", json.loads(modal.content)["html"])

        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page["Content-Type"])

    def test_action_modal_renders_a_form_then_queues_and_refreshes(self):
        url = reverse("fleet:project_update", args=[self.project.pk])

        form = json.loads(self.client.get(url, **AJAX).content)["html"]
        self.assertIn("backup_mode", form)
        self.assertIn(url, form)

        queued = self.client.post(url, {"backup_mode": "data"}, **AJAX)
        payload = json.loads(queued.content)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["refresh_parent"])
        self.assertEqual(
            FleetOperation.objects.get(project=self.project).action, "dlux.image_update"
        )

    def test_invalid_action_post_rerenders_the_modal_form(self):
        url = reverse("fleet:project_update", args=[self.project.pk])
        response = self.client.post(url, {"backup_mode": "bogus"}, **AJAX)
        payload = json.loads(response.content)
        self.assertNotIn("success", payload)
        self.assertIn("html", payload)
        self.assertFalse(FleetOperation.objects.exists())

    def test_enrollment_modal_explains_then_reveals_the_token_once(self):
        url = reverse("fleet:project_enrollment", args=[self.project.pk])

        intro = json.loads(self.client.get(url, **AJAX).content)["html"]
        self.assertIn("Generate token", intro)

        minted = self.client.post(url, **AJAX)
        self.assertEqual(minted["Cache-Control"], "no-store")
        html = json.loads(minted.content)["html"]
        self.assertIn("Pairing token", html)
        self.assertIn("Control panel URL", html)

    def test_enrollment_values_are_click_to_copy(self):
        url = reverse("fleet:project_enrollment", args=[self.project.pk])
        html = json.loads(self.client.post(url, **AJAX).content)["html"]
        # Both the control URL and the token expose a copy trigger.
        self.assertEqual(html.count("data-fleet-copy="), 2)

    def test_panel_renders_in_arabic(self):
        settings = SystemSettings.load()
        settings.default_language = "ar"
        settings.save(update_fields=("default_language",))
        try:
            profile = self.user.profile
            profile.language = "ar"
            profile.save(update_fields=("language",))
        except Exception:
            pass

        body = self.client.get(reverse("fleet:overview")).content.decode()
        self.assertIn("المشروع", body)      # table header "Project"
        self.assertIn("إضافة مشروع", body)   # "Add project"

        detail = json.loads(
            self.client.get(reverse("fleet:project_detail", args=[self.project.pk]), **AJAX).content
        )["html"]
        self.assertIn("لقطة DLUX", detail)   # "DLUX snapshot"

    def test_confirm_modals_gate_agent_operations(self):
        response = self.client.get(
            reverse("fleet:project_revoke", args=[self.project.pk]), **AJAX
        )
        self.assertIn("Revoke agent", json.loads(response.content)["html"])

    def test_batch_modal_creates_a_batch_and_refreshes(self):
        url = reverse("fleet:batch_add")
        self.assertIn("concurrency", json.loads(self.client.get(url, **AJAX).content)["html"])

        response = self.client.post(
            url,
            {
                "projects": [str(self.project.pk)],
                "backup_mode": "data",
                "concurrency": 1,
                "name": "Nightly",
            },
            **AJAX,
        )
        self.assertTrue(json.loads(response.content)["success"])

    def test_active_operations_feed_drives_the_in_flight_strip(self):
        operation = queue_operation(self.project, "composer.restart", {"service": "web"}, self.user)
        response = self.client.get(reverse("fleet:operations_active"))
        entries = json.loads(response.content)["operations"]
        self.assertEqual(entries[0]["operation_id"], str(operation.operation_id))
        self.assertEqual(entries[0]["project"], "Forms")
        self.assertEqual(
            entries[0]["detail_url"],
            reverse("fleet:project_detail", args=[self.project.pk]),
        )

    def test_feed_reports_live_status_fields(self):
        queue_operation(self.project, "composer.restart", {"service": "web"}, self.user)
        entry = json.loads(self.client.get(reverse("fleet:operations_active")).content)["operations"][0]
        for key in ("phase", "age_seconds", "overdue", "agent_online", "recreate_expected", "deadline_at"):
            self.assertIn(key, entry)
        self.assertFalse(entry["overdue"])
        self.assertFalse(entry["agent_online"])  # no agent enrolled yet

    def test_operation_status_includes_live_status_block(self):
        operation = queue_operation(self.project, "composer.restart", {"service": "web"}, self.user)
        data = json.loads(
            self.client.get(reverse("fleet:operation_status", args=[operation.operation_id])).content
        )
        self.assertIn("status", data)
        self.assertEqual(data["status"]["state"], "queued")

    def test_overdue_operation_is_flagged_before_it_is_swept(self):
        from django.utils import timezone
        from datetime import timedelta

        operation = queue_operation(self.project, "composer.restart", {"service": "web"}, self.user)
        FleetOperation.objects.filter(pk=operation.pk).update(
            state="delivered", deadline_at=timezone.now() - timedelta(minutes=1)
        )
        entry = json.loads(self.client.get(reverse("fleet:operations_active")).content)["operations"][0]
        self.assertTrue(entry["overdue"])

    def test_deep_link_opens_a_scoped_project_modal(self):
        response = self.client.get(reverse("fleet:overview"), {"project": str(self.project.pk)})
        self.assertContains(
            response, reverse("fleet:project_detail", args=[self.project.pk])
        )

    def test_deep_link_ignores_an_unresolvable_project(self):
        response = self.client.get(reverse("fleet:overview"), {"project": "not-a-uuid"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-open-project-url")


class FleetLayoutTests(TestCase):
    def setUp(self):
        cache.clear()
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=("is_configured",))
        self.user = get_user_model().objects.create_superuser(
            username="root", password="panel-pass", email="root@example.com"
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.project = ManagedProject.objects.create(name="Forms", slug="forms", environment="production")

    def test_default_layout_is_the_table(self):
        body = self.client.get(reverse("fleet:overview")).content.decode()
        self.assertIn("dlux-data-table", body)
        self.assertNotIn("data-fleet-cards", body)

    def test_per_user_preference_switches_to_cards(self):
        self.client.post(
            reverse("update_app_preference", args=["fleet.overview_layout"]),
            data=json.dumps("cards"),
            content_type="application/json",
        )
        body = self.client.get(reverse("fleet:overview")).content.decode()
        self.assertIn("data-fleet-cards", body)
        self.assertNotIn("dlux-data-table", body)

    def test_cards_carry_the_same_context_menu_actions(self):
        from fleet.layouts import FLEET_LAYOUT_NS

        profile = self.user.profile
        prefs = profile.preferences or {}
        prefs.setdefault("app", {})[FLEET_LAYOUT_NS] = "cards"
        profile.preferences = prefs
        profile.save(update_fields=("preferences",))

        body = self.client.get(reverse("fleet:overview")).content.decode()
        self.assertIn("data-dlux-context=\"true\"", body)
        self.assertIn("data-dlux-actions", body)
        self.assertIn("dlux:dynamic_modal:open", body)

    def test_global_default_applies_without_a_per_user_pref(self):
        from fleet.layouts import get_default_fleet_layout, FLEET_LAYOUT_NS

        settings = SystemSettings.load()
        extra = settings.extra_config or {}
        extra.setdefault("app", {})[FLEET_LAYOUT_NS] = {"default_layout": "cards"}
        settings.extra_config = extra
        settings.save(update_fields=("extra_config",))
        self.assertEqual(get_default_fleet_layout(), "cards")

    def test_layout_option_card_is_visible_on_the_options_page(self):
        from dlux.options import get_visible_cards

        request = type("Req", (), {"user": self.user})()
        ids = {card.get("id") if isinstance(card, dict) else getattr(card, "id", None)
               for card in get_visible_cards(request)}
        self.assertIn("fleet.overview_layout", ids)


class OperationSweepTests(TestCase):
    def setUp(self):
        cache.clear()
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=("is_configured",))
        self.user = get_user_model().objects.create_superuser(
            username="root", password="panel-pass", email="root@example.com"
        )
        self.project = ManagedProject.objects.create(name="Forms", slug="forms")

    def test_stuck_operation_is_failed_after_grace(self):
        from django.utils import timezone
        from datetime import timedelta
        from fleet.services import expire_stale_operations

        operation = queue_operation(self.project, "dlux.image_update", {"backup_mode": "data"}, self.user)
        FleetOperation.objects.filter(pk=operation.pk).update(
            state="delivered", deadline_at=timezone.now() - timedelta(minutes=30)
        )
        self.assertEqual(expire_stale_operations(grace_minutes=10), 1)
        operation.refresh_from_db()
        self.assertEqual(operation.state, "failed")
        self.assertTrue(operation.result.get("expired"))

    def test_operation_within_grace_is_left_running(self):
        from django.utils import timezone
        from datetime import timedelta
        from fleet.services import expire_stale_operations

        operation = queue_operation(self.project, "dlux.image_update", {"backup_mode": "data"}, self.user)
        # Past its own deadline, but still inside the grace window.
        FleetOperation.objects.filter(pk=operation.pk).update(
            state="running", deadline_at=timezone.now() - timedelta(minutes=2)
        )
        self.assertEqual(expire_stale_operations(grace_minutes=10), 0)
        operation.refresh_from_db()
        self.assertEqual(operation.state, "running")

    def test_terminal_operations_are_untouched(self):
        from django.utils import timezone
        from datetime import timedelta
        from fleet.services import expire_stale_operations

        operation = queue_operation(self.project, "composer.restart", {"service": "web"}, self.user)
        FleetOperation.objects.filter(pk=operation.pk).update(
            state="succeeded", deadline_at=timezone.now() - timedelta(hours=2)
        )
        self.assertEqual(expire_stale_operations(grace_minutes=10), 0)
        operation.refresh_from_db()
        self.assertEqual(operation.state, "succeeded")


class PanelPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=("is_configured",))
        self.user = get_user_model().objects.create_user(
            username="viewer", password="panel-pass", email="viewer@example.com"
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_managedproject")
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.project = ManagedProject.objects.create(name="Archive", slug="archive")

    def test_view_only_user_cannot_open_an_action_modal(self):
        response = self.client.get(
            reverse("fleet:project_update", args=[self.project.pk]), **AJAX
        )
        self.assertEqual(response.status_code, 403)

    def test_view_only_user_cannot_queue_through_the_modal_endpoint(self):
        response = self.client.post(
            reverse("fleet:project_update", args=[self.project.pk]),
            {"backup_mode": "data"},
            **AJAX,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FleetOperation.objects.exists())
