"""The single-page panel: Dlux table, context-menu actions, and modal endpoints."""

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse

from dlux.models import SystemSettings

from fleet.models import FleetOperation, ManagedProject
from fleet.services import queue_operation

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class PanelUITests(TestCase):
    def setUp(self):
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
        self.assertIn(
            reverse("modal_manager", args=["fleet", "ManagedProject", "new"]), body
        )
        self.assertIn(reverse("fleet:batch_add"), body)

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

    def test_deep_link_opens_a_scoped_project_modal(self):
        response = self.client.get(reverse("fleet:overview"), {"project": str(self.project.pk)})
        self.assertContains(
            response, reverse("fleet:project_detail", args=[self.project.pk])
        )

    def test_deep_link_ignores_an_unresolvable_project(self):
        response = self.client.get(reverse("fleet:overview"), {"project": "not-a-uuid"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-open-project-url")


class PanelPermissionTests(TestCase):
    def setUp(self):
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
