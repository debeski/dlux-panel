import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AgentEnrollmentToken,
    ComposerAgent,
    FleetBatch,
    FleetBatchMember,
    FleetOperation,
    ManagedProject,
    OperationEvent,
    ProjectSnapshot,
)
from .protocol import (
    SCHEMA_VERSION,
    TERMINAL_STATES,
    sanitize_mapping,
    sanitize_text,
    serialize_command,
    utc_iso,
    validate_action_payload,
    validate_event,
    validate_snapshot,
)


ACTIVE_STATES = ("delivered", "accepted", "running")


class ProtocolConflict(ValidationError):
    pass


def create_enrollment_token(project, actor=None):
    raw_secret = secrets.token_urlsafe(32)
    record = AgentEnrollmentToken.objects.create(
        project=project,
        secret_hash=make_password(raw_secret),
        expires_at=timezone.now() + timedelta(minutes=15),
        created_by=actor,
    )
    return record, f"{record.id}.{raw_secret}"


@transaction.atomic
def enroll_agent(raw_token, capabilities):
    try:
        token_id, raw_secret = str(raw_token or "").split(".", 1)
        token_uuid = uuid.UUID(token_id)
    except (ValueError, AttributeError) as exc:
        raise PermissionDenied("Enrollment token is invalid.") from exc
    token = AgentEnrollmentToken.objects.select_for_update().select_related("project").filter(pk=token_uuid).first()
    now = timezone.now()
    if (
        token is None
        or token.used_at is not None
        or token.expires_at <= now
        or not check_password(raw_secret, token.secret_hash)
    ):
        raise PermissionDenied("Enrollment token is invalid, expired, or already used.")
    if not isinstance(capabilities, dict):
        raise ValidationError("Agent capabilities must be an object.")
    protocol_versions = capabilities.get("protocol_versions") or []
    if SCHEMA_VERSION not in protocol_versions:
        raise ValidationError("Agent does not support protocol schema v1.")
    raw_agent_secret = secrets.token_urlsafe(48)
    agent, _created = ComposerAgent.objects.select_for_update().get_or_create(
        project=token.project,
        defaults={"secret_hash": make_password(raw_agent_secret)},
    )
    agent.secret_hash = make_password(raw_agent_secret)
    agent.pending_secret_hash = ""
    agent.pending_rotation_id = None
    agent.pending_rotation_expires_at = None
    agent.capabilities = sanitize_mapping(capabilities)
    agent.agent_version = sanitize_text(capabilities.get("agent_version"), 64)
    agent.protocol_version = SCHEMA_VERSION
    agent.enrolled_at = now
    agent.last_seen_at = now
    agent.revoked_at = None
    agent.credential_version += 1 if not _created else 0
    agent.save()
    token.used_at = now
    token.save(update_fields=("used_at",))
    return agent, raw_agent_secret


def authenticate_agent(agent_id, bearer_secret, *, allow_pending=False):
    try:
        agent_uuid = uuid.UUID(str(agent_id or ""))
    except ValueError as exc:
        raise PermissionDenied("Agent credentials are invalid.") from exc
    agent = ComposerAgent.objects.select_related("project", "project__scope").filter(pk=agent_uuid).first()
    if not agent or agent.revoked_at is not None:
        raise PermissionDenied("Agent credentials are invalid or revoked.")
    valid_active = check_password(str(bearer_secret or ""), agent.secret_hash)
    valid_pending = bool(
        allow_pending
        and agent.pending_secret_hash
        and agent.pending_rotation_expires_at
        and agent.pending_rotation_expires_at > timezone.now()
        and check_password(str(bearer_secret or ""), agent.pending_secret_hash)
    )
    if not valid_active and not valid_pending:
        raise PermissionDenied("Agent credentials are invalid or revoked.")
    ComposerAgent.objects.filter(pk=agent.pk).update(last_seen_at=timezone.now())
    agent.last_seen_at = timezone.now()
    agent.authenticated_with_pending = valid_pending
    return agent


def revoke_agent(agent):
    now = timezone.now()
    ComposerAgent.objects.filter(pk=agent.pk).update(
        revoked_at=now,
        pending_secret_hash="",
        pending_rotation_id=None,
        pending_rotation_expires_at=None,
    )


@transaction.atomic
def begin_credential_rotation(agent):
    agent = ComposerAgent.objects.select_for_update().get(pk=agent.pk)
    if agent.revoked_at is not None:
        raise PermissionDenied("Agent is revoked.")
    secret = secrets.token_urlsafe(48)
    rotation_id = uuid.uuid4()
    agent.pending_secret_hash = make_password(secret)
    agent.pending_rotation_id = rotation_id
    agent.pending_rotation_expires_at = timezone.now() + timedelta(minutes=10)
    agent.save(
        update_fields=(
            "pending_secret_hash",
            "pending_rotation_id",
            "pending_rotation_expires_at",
            "updated_at",
        )
    )
    return rotation_id, secret


@transaction.atomic
def confirm_credential_rotation(agent, rotation_id):
    authenticated_with_pending = getattr(agent, "authenticated_with_pending", False)
    agent = ComposerAgent.objects.select_for_update().get(pk=agent.pk)
    if str(agent.last_rotation_id or "") == str(rotation_id):
        return
    if (
        not agent.pending_rotation_id
        or str(agent.pending_rotation_id) != str(rotation_id)
        or not agent.pending_secret_hash
        or not agent.pending_rotation_expires_at
        or agent.pending_rotation_expires_at <= timezone.now()
    ):
        raise ProtocolConflict("Credential rotation is invalid or expired.")
    if not authenticated_with_pending:
        raise PermissionDenied("Rotation confirmation requires the pending credential.")
    agent.secret_hash = agent.pending_secret_hash
    agent.pending_secret_hash = ""
    agent.pending_rotation_id = None
    agent.pending_rotation_expires_at = None
    agent.last_rotation_id = rotation_id
    agent.last_rotation_confirmed_at = timezone.now()
    agent.credential_version += 1
    agent.save(
        update_fields=(
            "secret_hash",
            "pending_secret_hash",
            "pending_rotation_id",
            "pending_rotation_expires_at",
            "last_rotation_id",
            "last_rotation_confirmed_at",
            "credential_version",
            "updated_at",
        )
    )


def queue_operation(project, action, payload, actor=None, *, batch=None, deadline_minutes=60):
    clean_payload = validate_action_payload(action, payload)
    now = timezone.now()
    actor_id = str(getattr(actor, "pk", "") or "")
    actor_display = ""
    if actor is not None:
        actor_display = actor.get_full_name() or actor.get_username()
    return FleetOperation.objects.create(
        project=project,
        scope=project.scope,
        batch=batch,
        action=action,
        payload=clean_payload,
        actor_id=actor_id,
        actor_display=sanitize_text(actor_display, 200),
        created_by=actor,
        updated_by=actor,
        created_for_agent_at=now,
        deadline_at=now + timedelta(minutes=max(1, min(1440, int(deadline_minutes)))),
        break_glass_reason=clean_payload.get("reason", "") if action == "composer.recovery_deploy" else "",
    )


@transaction.atomic
def create_batch(projects, actor, *, backup_mode="data", concurrency=1, continue_on_failure=False, name=""):
    concurrency = int(concurrency)
    if concurrency < 1 or concurrency > 3:
        raise ValidationError("Batch concurrency must be between 1 and 3.")
    projects = list(projects)
    if not projects:
        raise ValidationError("Select at least one project.")
    scope_ids = {project.scope_id for project in projects}
    scope = projects[0].scope if len(scope_ids) == 1 else None
    batch = FleetBatch.objects.create(
        name=sanitize_text(name, 160) or f"Fleet update {timezone.now():%Y-%m-%d %H:%M}",
        action="dlux.image_update",
        payload={"backup_mode": backup_mode},
        concurrency=concurrency,
        continue_on_failure=bool(continue_on_failure),
        scope=scope,
        created_by=actor,
        updated_by=actor,
    )
    for position, project in enumerate(projects, start=1):
        operation = queue_operation(
            project,
            "dlux.image_update",
            {"backup_mode": backup_mode},
            actor,
            batch=batch,
        )
        FleetBatchMember.objects.create(
            batch=batch,
            project=project,
            operation=operation,
            position=position,
        )
    return batch


def _batch_operation_may_dispatch(operation):
    batch = FleetBatch.objects.select_for_update().get(pk=operation.batch_id)
    operations = FleetOperation.objects.select_for_update().filter(batch=batch)
    if operations.filter(state="failed").exists() and not batch.continue_on_failure:
        now = timezone.now()
        operations.filter(state="queued").update(state="cancelled", finished_at=now)
        batch.state = "failed"
        batch.finished_at = now
        batch.save(update_fields=("state", "finished_at", "updated_at"))
        return False
    active_count = operations.filter(state__in=ACTIVE_STATES).count()
    available = max(0, batch.concurrency - active_count)
    eligible = list(
        FleetBatchMember.objects.filter(batch=batch, operation__state="queued")
        .order_by("position")
        .values_list("operation_id", flat=True)[:available]
    )
    if operation.operation_id not in eligible:
        return False
    if batch.state == "queued":
        batch.state = "running"
        batch.started_at = timezone.now()
        batch.save(update_fields=("state", "started_at", "updated_at"))
    return True


@transaction.atomic
def claim_next_command(agent):
    if FleetOperation.objects.filter(project=agent.project, state__in=("accepted", "running")).exists():
        return None
    operation = (
        FleetOperation.objects.select_for_update()
        .filter(project=agent.project, state__in=("delivered", "queued"))
        .order_by("created_for_agent_at")
        .first()
    )
    if operation is None:
        return None
    if operation.deadline_at <= timezone.now():
        operation.state = "failed"
        operation.finished_at = timezone.now()
        operation.result = {"error": "Command deadline expired before delivery."}
        operation.save(update_fields=("state", "finished_at", "result", "updated_at"))
        _refresh_batch(operation.batch_id)
        return None
    if operation.state == "queued" and operation.batch_id and not _batch_operation_may_dispatch(operation):
        return None
    advertised = set((agent.capabilities or {}).get("capabilities") or [])
    if advertised and operation.action not in advertised:
        operation.state = "failed"
        operation.finished_at = timezone.now()
        operation.result = {"error": "Agent does not advertise this capability."}
        operation.save(update_fields=("state", "finished_at", "result", "updated_at"))
        _refresh_batch(operation.batch_id)
        return None
    if operation.state == "queued":
        operation.state = "delivered"
        operation.delivered_at = timezone.now()
        operation.save(update_fields=("state", "delivered_at", "updated_at"))
    return serialize_command(operation)


@transaction.atomic
def record_operation_event(agent, operation_id, document):
    operation = (
        FleetOperation.objects.select_for_update()
        .filter(operation_id=operation_id, project=agent.project)
        .first()
    )
    if operation is None:
        raise ValidationError("Operation does not belong to this agent.")
    event = validate_event(document, operation.operation_id)
    existing = OperationEvent.objects.filter(operation=operation, sequence=event["sequence"]).first()
    if existing:
        if (
            existing.state == event["state"]
            and existing.phase == event["phase"]
            and existing.detail == event["detail"]
            and existing.log == event["log"]
            and existing.observed_at == event["observed_at"]
        ):
            return existing, False
        raise ProtocolConflict("Sequence was already used by a different event.")
    if event["sequence"] != operation.last_sequence + 1:
        raise ProtocolConflict("Event sequence is out of order.")
    allowed = {
        "delivered": {"accepted"},
        "accepted": {"running"},
        "running": {"running", "succeeded", "failed"},
    }
    if event["state"] not in allowed.get(operation.state, set()):
        raise ProtocolConflict(f"Invalid operation transition {operation.state} to {event['state']}.")
    created = OperationEvent.objects.create(operation=operation, **event)
    now = timezone.now()
    operation.state = event["state"]
    operation.last_sequence = event["sequence"]
    if event["state"] == "accepted" and operation.accepted_at is None:
        operation.accepted_at = now
    elif event["state"] == "running" and operation.started_at is None:
        operation.started_at = now
    elif event["state"] in TERMINAL_STATES:
        operation.finished_at = now
        operation.result = event["detail"]
    operation.save(
        update_fields=(
            "state",
            "last_sequence",
            "accepted_at",
            "started_at",
            "finished_at",
            "result",
            "updated_at",
        )
    )
    _refresh_batch(operation.batch_id)
    return created, True


def _refresh_batch(batch_id):
    if not batch_id:
        return
    batch = FleetBatch.objects.select_for_update().get(pk=batch_id)
    states = list(FleetOperation.objects.filter(batch=batch).values_list("state", flat=True))
    if not states:
        return
    now = timezone.now()
    if any(state == "failed" for state in states) and not batch.continue_on_failure:
        FleetOperation.objects.filter(batch=batch, state="queued").update(state="cancelled", finished_at=now)
        batch.state = "failed"
        batch.finished_at = now
    elif all(state in TERMINAL_STATES for state in states):
        batch.state = "failed" if any(state == "failed" for state in states) else "succeeded"
        batch.finished_at = now
    elif any(state in ACTIVE_STATES for state in states):
        batch.state = "running"
        batch.started_at = batch.started_at or now
    batch.save(update_fields=("state", "started_at", "finished_at", "updated_at"))


@transaction.atomic
def cancel_operation(operation, actor=None):
    operation = FleetOperation.objects.select_for_update().get(pk=operation.pk)
    if operation.state not in {"queued", "delivered"}:
        raise ProtocolConflict("Only queued or delivered operations can be cancelled.")
    operation.state = "cancelled"
    operation.finished_at = timezone.now()
    operation.updated_by = actor
    operation.result = {"cancelled_by": str(getattr(actor, "pk", "") or "")}
    operation.save(update_fields=("state", "finished_at", "updated_by", "result", "updated_at"))
    _refresh_batch(operation.batch_id)
    return operation


@transaction.atomic
def record_local_operation(agent, document):
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported local operation schema version.")
    try:
        operation_id = uuid.UUID(str(document.get("operation_id") or ""))
    except ValueError as exc:
        raise ValidationError("Local operation_id must be a UUID.") from exc
    if document.get("action") != "dlux.image_update" or document.get("source") != "local":
        raise ValidationError("Only local DLUX image update results are accepted.")
    state = str(document.get("state") or "")
    if state not in {"succeeded", "failed"}:
        raise ValidationError("Local operation must be terminal.")
    existing = FleetOperation.objects.filter(pk=operation_id).first()
    if existing:
        if existing.project_id != agent.project_id or existing.source != "local":
            raise ProtocolConflict("operation_id is already used by another operation.")
        return existing, False
    now = timezone.now()
    detail = sanitize_mapping(
        {
            "exit_code": document.get("exit_code"),
            "observed_at": document.get("observed_at"),
        }
    )
    operation = FleetOperation.objects.create(
        operation_id=operation_id,
        project=agent.project,
        scope=agent.project.scope,
        action="dlux.image_update",
        payload={},
        source="local",
        state=state,
        actor_display="Local DLUX",
        created_for_agent_at=now,
        deadline_at=now,
        started_at=now,
        finished_at=now,
        last_sequence=1,
        result=detail,
    )
    OperationEvent.objects.create(
        operation=operation,
        sequence=1,
        state=state,
        detail=detail,
        observed_at=now,
    )
    return operation, True


@transaction.atomic
def store_snapshot(agent, document):
    snapshot = validate_snapshot(document)
    existing = ProjectSnapshot.objects.select_for_update().filter(project=agent.project).first()
    if existing and existing.observed_at >= snapshot["observed_at"]:
        return existing, False
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": snapshot["observed_at"],
        "versions": snapshot["versions"],
        "update_state": snapshot["updates"],
        "backup_summary": snapshot["backup"],
        "health_summary": snapshot["health"],
        "resource_summary": snapshot["resources"],
        "agent_report": snapshot["agent"],
    }
    if existing:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save(update_fields=(*defaults.keys(), "received_at"))
        return existing, False
    return ProjectSnapshot.objects.create(project=agent.project, **defaults), True


def update_capabilities(agent, document):
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported capabilities schema version.")
    capabilities = document.get("capabilities")
    versions = document.get("protocol_versions")
    if not isinstance(capabilities, list) or SCHEMA_VERSION not in (versions or []):
        raise ValidationError("Capabilities document does not support schema v1.")
    clean = sanitize_mapping(document)
    ComposerAgent.objects.filter(pk=agent.pk).update(
        capabilities=clean,
        agent_version=sanitize_text(document.get("agent_version"), 64),
        protocol_version=SCHEMA_VERSION,
        last_seen_at=timezone.now(),
    )
    return clean


def scoped_projects_for_user(user):
    from dlux.utils import get_user_scope, is_scope_enabled

    queryset = ManagedProject.objects.filter(is_active=True)
    if user.is_superuser or not is_scope_enabled():
        return queryset
    scope = get_user_scope(user)
    if scope is None:
        return queryset.none()
    return queryset.filter(scope=scope)
