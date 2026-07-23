import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Permission
from django.test import AsyncClient, Client, TestCase, TransactionTestCase
from django.utils import timezone

from dlux.models import Profile, Scope, ScopeSettings, SystemSettings

from fleet.models import (
    BreakGlassAudit,
    ComposerAgent,
    FleetOperation,
    ManagedProject,
    OperationEvent,
    ProjectSnapshot,
)
from fleet.services import (
    create_batch,
    create_enrollment_token,
    queue_operation,
    scoped_projects_for_user,
)
from fleet.protocol import validate_action_payload, validate_snapshot
from fleet.retention import prune_operation_logs


CAPABILITIES = {
    "agent_version": "1.2.0",
    "protocol_versions": [1],
    "capabilities": [
        "dlux.image_update",
        "dlux.backup.create",
        "composer.restart",
        "composer.recovery_deploy",
        "agent.rotate_credentials",
    ],
}


class AgentApiTests(TestCase):
    def setUp(self):
        self.project = ManagedProject.objects.create(name="Alpha", slug="alpha")
        self.client = Client()

    def test_shared_protocol_fixtures(self):
        fixture_root = Path(__file__).parent / "fixtures" / "agent-protocol-v1"
        command = json.loads((fixture_root / "command.image_update.json").read_text(encoding="utf-8"))
        snapshot = json.loads((fixture_root / "snapshot.json").read_text(encoding="utf-8"))
        invalid = json.loads((fixture_root / "invalid.command.shell.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_action_payload(command["action"], command["payload"]), {"backup_mode": "data"})
        self.assertEqual(validate_snapshot(snapshot)["versions"]["application"], "2.4.0")
        with self.assertRaisesMessage(Exception, "Unsupported remote action"):
            validate_action_payload(invalid["action"], invalid["payload"])

    def enroll(self):
        token_record, raw_token = create_enrollment_token(self.project)
        response = self.client.post(
            "/api/agent/v1/enroll/",
            data=json.dumps({"schema_version": 1, "enrollment_token": raw_token, **CAPABILITIES}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        self.agent = ComposerAgent.objects.get(pk=payload["agent_id"])
        self.secret = payload["agent_secret"]
        self.headers = {
            "HTTP_X_COMPOSER_AGENT_ID": str(self.agent.pk),
            "HTTP_AUTHORIZATION": f"Bearer {self.secret}",
        }
        return token_record, raw_token

    def event(self, operation, sequence, state, detail=None, observed_at=None, **headers):
        return self.client.post(
            f"/api/agent/v1/operations/{operation.pk}/events/",
            data=json.dumps(
                {
                    "schema_version": 1,
                    "operation_id": str(operation.pk),
                    "sequence": sequence,
                    "state": state,
                    "observed_at": observed_at or timezone.now().isoformat(),
                    "detail": detail or {},
                }
            ),
            content_type="application/json",
            **(headers or self.headers),
        )

    def test_enrollment_is_one_use_hashed_and_expires(self):
        token_record, raw_token = self.enroll()
        token_record.refresh_from_db()
        self.assertIsNotNone(token_record.used_at)
        self.assertNotEqual(token_record.secret_hash, raw_token.split(".", 1)[1])
        self.assertNotEqual(self.agent.secret_hash, self.secret)

        reused = self.client.post(
            "/api/agent/v1/enroll/",
            data=json.dumps({"schema_version": 1, "enrollment_token": raw_token, **CAPABILITIES}),
            content_type="application/json",
        )
        self.assertEqual(reused.status_code, 403)

        expired, expired_raw = create_enrollment_token(self.project)
        expired.expires_at = timezone.now() - timedelta(seconds=1)
        expired.save(update_fields=("expires_at",))
        response = self.client.post(
            "/api/agent/v1/enroll/",
            data=json.dumps({"schema_version": 1, "enrollment_token": expired_raw, **CAPABILITIES}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_command_delivery_deduplicated_events_and_single_operation_gate(self):
        self.enroll()
        first = queue_operation(self.project, "dlux.image_update", {"backup_mode": "full"})
        second = queue_operation(self.project, "composer.restart", {"service": "web"})
        response = self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["command"]["operation_id"], str(first.pk))
        self.assertEqual(response.json()["command"]["payload"], {"backup_mode": "full"})

        accepted = self.event(first, 1, "accepted")
        self.assertEqual(accepted.status_code, 201, accepted.content)
        blocked = self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers)
        self.assertEqual(blocked.status_code, 204)
        self.assertEqual(self.event(first, 2, "running", {"phase": "composer_deploy"}).status_code, 201)
        terminal_time = timezone.now().isoformat()
        terminal = self.event(
            first,
            3,
            "succeeded",
            {"message": "done"},
            observed_at=terminal_time,
        )
        self.assertEqual(terminal.status_code, 201)
        duplicate = self.event(
            first,
            3,
            "succeeded",
            {"message": "done"},
            observed_at=terminal_time,
        )
        self.assertEqual(duplicate.status_code, 200)
        conflict = self.event(first, 3, "failed", {"message": "different"})
        self.assertEqual(conflict.status_code, 409)
        out_of_order = self.event(first, 5, "running")
        self.assertEqual(out_of_order.status_code, 409)

        next_response = self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers)
        self.assertEqual(next_response.json()["command"]["operation_id"], str(second.pk))
        self.assertEqual(OperationEvent.objects.filter(operation=first).count(), 3)

        replay_with_changed_log = self.event(
            first,
            3,
            "succeeded",
            {"message": "done", "log": "different"},
            observed_at=terminal_time,
        )
        self.assertEqual(replay_with_changed_log.status_code, 409)

    def test_snapshot_redaction_local_results_capabilities_and_revocation(self):
        self.enroll()
        snapshot = {
            "schema_version": 1,
            "observed_at": timezone.now().isoformat(),
            "project": {"name": "Alpha"},
            "versions": {"application": "2.4.0", "dlux": "1.5.0"},
            "updates": {"status": "idle"},
            "backup": {"status": "ready"},
            "health": {"status": "healthy"},
            "resources": {"cpu_percent": 10},
            "agent": {"agent_version": "1.2.0", "password": "must-not-store"},
        }
        response = self.client.put(
            "/api/agent/v1/snapshot/",
            data=json.dumps(snapshot),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        stored = ProjectSnapshot.objects.get(project=self.project)
        self.assertEqual(stored.agent_report["password"], "[REDACTED]")

        stale_snapshot = dict(snapshot)
        stale_snapshot["observed_at"] = (timezone.now() - timedelta(days=1)).isoformat()
        stale_snapshot["versions"] = {"application": "stale"}
        stale = self.client.put(
            "/api/agent/v1/snapshot/",
            data=json.dumps(stale_snapshot),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(stale.status_code, 200)
        stored.refresh_from_db()
        self.assertEqual(stored.versions["application"], "2.4.0")

        capability_response = self.client.put(
            "/api/agent/v1/capabilities/",
            data=json.dumps({"schema_version": 1, **CAPABILITIES}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(capability_response.status_code, 200)

        local_id = uuid.uuid4()
        local = self.client.post(
            "/api/agent/v1/local-operations/",
            data=json.dumps(
                {
                    "schema_version": 1,
                    "operation_id": str(local_id),
                    "action": "dlux.image_update",
                    "source": "local",
                    "state": "succeeded",
                    "exit_code": 0,
                    "observed_at": timezone.now().isoformat(),
                }
            ),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(local.status_code, 201)
        self.assertEqual(FleetOperation.objects.get(pk=local_id).source, "local")

        self.agent.revoked_at = timezone.now()
        self.agent.save(update_fields=("revoked_at",))
        denied = self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers)
        self.assertEqual(denied.status_code, 403)

    def test_two_phase_rotation_promotes_new_secret_and_revokes_old(self):
        self.enroll()
        begin = self.client.post(
            "/api/agent/v1/credentials/rotate/",
            data=json.dumps({"schema_version": 1}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(begin.status_code, 200, begin.content)
        rotation = begin.json()
        new_headers = {
            "HTTP_X_COMPOSER_AGENT_ID": str(self.agent.pk),
            "HTTP_AUTHORIZATION": f"Bearer {rotation['agent_secret']}",
        }
        confirm = self.client.post(
            "/api/agent/v1/credentials/rotate/confirm/",
            data=json.dumps({"schema_version": 1, "rotation_id": rotation["rotation_id"]}),
            content_type="application/json",
            **new_headers,
        )
        self.assertEqual(confirm.status_code, 200, confirm.content)
        self.assertEqual(self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers).status_code, 403)
        self.assertEqual(self.client.get("/api/agent/v1/commands/next/?wait=0", **new_headers).status_code, 204)
        repeated = self.client.post(
            "/api/agent/v1/credentials/rotate/confirm/",
            data=json.dumps({"schema_version": 1, "rotation_id": rotation["rotation_id"]}),
            content_type="application/json",
            **new_headers,
        )
        self.assertEqual(repeated.status_code, 200)

    def test_payload_limit_and_arbitrary_actions_are_rejected(self):
        self.enroll()
        too_large = self.client.put(
            "/api/agent/v1/snapshot/",
            data=json.dumps({"schema_version": 1, "padding": "x" * 66000}),
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(too_large.status_code, 400)
        with self.assertRaisesMessage(Exception, "Unsupported remote action"):
            queue_operation(self.project, "shell", {"command": "id"})
        with self.assertRaisesMessage(Exception, "Unsupported payload field"):
            queue_operation(
                self.project,
                "dlux.image_update",
                {"backup_mode": "data", "command": "id"},
            )

    def test_backup_creation_is_typed_and_remote_restore_is_rejected(self):
        self.enroll()
        operation = queue_operation(self.project, "dlux.backup.create", {"backup_mode": "full"})
        response = self.client.get("/api/agent/v1/commands/next/?wait=0", **self.headers)
        self.assertEqual(response.json()["command"]["operation_id"], str(operation.pk))
        self.assertEqual(response.json()["command"]["payload"], {"backup_mode": "full"})
        with self.assertRaisesMessage(Exception, "Unsupported remote action"):
            queue_operation(self.project, "dlux.backup.restore", {})


class BatchAndAuthorizationTests(TestCase):
    def setUp(self):
        settings = SystemSettings.load()
        settings.is_configured = True
        settings.save(update_fields=("is_configured",))
        self.user = get_user_model().objects.create_user(username="operator", password="correct-pass")
        self.scope_a = Scope.objects.create(name="A")
        self.scope_b = Scope.objects.create(name="B")
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.scope = self.scope_a
        profile.save(update_fields=("scope",))
        self.user.refresh_from_db()
        scope_settings = ScopeSettings.load()
        scope_settings.is_enabled = True
        scope_settings.save(update_fields=("is_enabled",))
        self.a = ManagedProject.objects.create(name="A", slug="a", scope=self.scope_a)
        self.b = ManagedProject.objects.create(name="B", slug="b", scope=self.scope_b)

    def make_agent(self, project):
        return ComposerAgent.objects.create(
            project=project,
            secret_hash=make_password("agent-secret"),
            capabilities=CAPABILITIES,
        )

    def test_native_scope_filters_projects_and_direct_ui_access(self):
        permission = Permission.objects.get(codename="view_managedproject")
        self.user.user_permissions.add(permission)
        self.assertEqual(list(scoped_projects_for_user(self.user)), [self.a])
        client = Client()
        client.force_login(self.user)
        self.assertEqual(client.get("/fleet/").status_code, 200)
        self.assertEqual(client.get(f"/fleet/projects/{self.a.pk}/").status_code, 200)
        self.assertEqual(client.get(f"/fleet/projects/{self.b.pk}/").status_code, 404)

    def test_batch_concurrency_one_and_halt_after_failure(self):
        agent_a = self.make_agent(self.a)
        agent_b = self.make_agent(self.b)
        batch = create_batch([self.a, self.b], self.user, concurrency=1)
        from fleet.services import claim_next_command, record_operation_event

        first = claim_next_command(agent_a)
        self.assertIsNotNone(first)
        self.assertIsNone(claim_next_command(agent_b))
        operation = FleetOperation.objects.get(pk=first["operation_id"])
        for sequence, state in ((1, "accepted"), (2, "running"), (3, "failed")):
            record_operation_event(
                agent_a,
                operation.pk,
                {
                    "schema_version": 1,
                    "operation_id": str(operation.pk),
                    "sequence": sequence,
                    "state": state,
                    "observed_at": timezone.now().isoformat(),
                    "detail": {},
                },
            )
        batch.refresh_from_db()
        self.assertEqual(batch.state, "failed")
        self.assertEqual(batch.operations.exclude(pk=operation.pk).get().state, "cancelled")

    def test_three_wide_batch_continues_after_a_mixed_failure(self):
        projects = [self.a, self.b]
        for index in range(2):
            projects.append(
                ManagedProject.objects.create(
                    name=f"Extra {index}",
                    slug=f"extra-{index}",
                    scope=self.scope_a,
                )
            )
        agents = [self.make_agent(project) for project in projects]
        batch = create_batch(
            projects,
            self.user,
            concurrency=3,
            continue_on_failure=True,
        )
        from fleet.services import claim_next_command, record_operation_event

        first_three = [claim_next_command(agent) for agent in agents[:3]]
        self.assertTrue(all(first_three))
        self.assertIsNone(claim_next_command(agents[3]))

        failed = FleetOperation.objects.get(pk=first_three[0]["operation_id"])
        for sequence, state in ((1, "accepted"), (2, "running"), (3, "failed")):
            record_operation_event(
                agents[0],
                failed.pk,
                {
                    "schema_version": 1,
                    "operation_id": str(failed.pk),
                    "sequence": sequence,
                    "state": state,
                    "observed_at": timezone.now().isoformat(),
                    "detail": {},
                },
            )

        fourth = claim_next_command(agents[3])
        self.assertIsNotNone(fourth)
        self.assertEqual(FleetOperation.objects.get(pk=fourth["operation_id"]).project, projects[3])
        batch.refresh_from_db()
        self.assertEqual(batch.state, "running")

    def test_break_glass_requires_step_up_and_creates_immutable_audit(self):
        superuser = get_user_model().objects.create_superuser(
            username="root",
            password="step-up-pass",
            email="root@example.com",
        )
        client = Client()
        client.force_login(superuser)
        url = f"/fleet/projects/{self.a.pk}/recovery/"
        rejected = client.post(url, {"reason": "database recovery", "backup_bypass_ack": "on"})
        self.assertEqual(rejected.status_code, 302)
        self.assertFalse(BreakGlassAudit.objects.exists())
        accepted = client.post(
            url,
            {
                "reason": "database recovery",
                "current_password": "step-up-pass",
                "backup_bypass_ack": "on",
            },
        )
        self.assertEqual(accepted.status_code, 302)
        audit = BreakGlassAudit.objects.get()
        self.assertEqual(audit.operation.action, "composer.recovery_deploy")
        with self.assertRaisesMessage(Exception, "immutable"):
            audit.delete()
        with self.assertRaisesMessage(Exception, "immutable"):
            BreakGlassAudit.objects.filter(pk=audit.pk).update(reason="changed")
        with self.assertRaisesMessage(Exception, "immutable"):
            BreakGlassAudit.objects.filter(pk=audit.pk).delete()

    def test_log_retention_clears_console_but_keeps_event_metadata(self):
        operation = queue_operation(self.a, "composer.restart", {"service": "web"}, self.user)
        event = OperationEvent.objects.create(
            operation=operation,
            sequence=1,
            state="running",
            detail={"phase": "restart"},
            log="sanitized console",
            observed_at=timezone.now() - timedelta(days=100),
        )
        OperationEvent.objects.filter(pk=event.pk).update(received_at=timezone.now() - timedelta(days=100))

        self.assertEqual(prune_operation_logs(90), 1)

        event.refresh_from_db()
        self.assertEqual(event.log, "")
        self.assertEqual(event.detail, {"phase": "restart"})


class FiftyAgentLongPollTests(TransactionTestCase):
    reset_sequences = True

    def test_fifty_asgi_long_polls_complete_concurrently(self):
        credentials = []
        for index in range(50):
            project = ManagedProject.objects.create(name=f"Project {index}", slug=f"project-{index}")
            secret = f"secret-{index}"
            agent = ComposerAgent.objects.create(
                project=project,
                secret_hash=make_password(secret),
                capabilities=CAPABILITIES,
            )
            credentials.append((agent, secret))

        async def run_requests():
            clients = [AsyncClient() for _ in credentials]
            calls = [
                client.get(
                    "/api/agent/v1/commands/next/?wait=1",
                    headers={
                        "X-Composer-Agent-ID": str(agent.pk),
                        "Authorization": f"Bearer {secret}",
                    },
                )
                for client, (agent, secret) in zip(clients, credentials)
            ]
            return await asyncio.gather(*calls)

        started = timezone.now()
        responses = async_to_sync(run_requests)()
        elapsed = (timezone.now() - started).total_seconds()
        self.assertTrue(all(response.status_code == 204 for response in responses))
        self.assertLess(elapsed, 8)
