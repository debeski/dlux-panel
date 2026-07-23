import json
import re
import uuid
from datetime import datetime, timezone as datetime_timezone

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime


SCHEMA_VERSION = 1
MAX_DOCUMENT_BYTES = 65536
MAX_EVENT_LOG = 32768
REMOTE_ACTIONS = frozenset(
    {
        "dlux.image_update",
        "dlux.backup.create",
        "composer.restart",
        "composer.recovery_deploy",
        "agent.rotate_credentials",
    }
)
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled"})
EVENT_STATES = frozenset({"accepted", "running", "succeeded", "failed"})
_SENSITIVE_KEY = re.compile(r"(?i)(authorization|password|passwd|secret|api[_-]?key)")
_SENSITIVE_VALUE = re.compile(
    r"(?i)(authorization|password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)([^\s,;]+)"
)


def utc_iso(value=None):
    moment = value or timezone.now()
    return moment.astimezone(datetime_timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value, label):
    parsed = parse_datetime(str(value or ""))
    if parsed is None:
        raise ValidationError(f"{label} must be an ISO-8601 timestamp.")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime_timezone.utc)
    return parsed


def bounded_json_bytes(value):
    try:
        encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("Document must be valid JSON.") from exc
    if len(encoded) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Document exceeds the 64 KiB limit.")
    return encoded


def sanitize_text(value, limit=MAX_EVENT_LOG):
    text = str(value or "").replace("\x00", "").strip()[:limit]
    return _SENSITIVE_VALUE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )


def sanitize_mapping(value, *, depth=0):
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        clean = {}
        for raw_key, item in list(value.items())[:100]:
            key = str(raw_key)[:100]
            if _SENSITIVE_KEY.search(key):
                clean[key] = "[REDACTED]"
            else:
                clean[key] = sanitize_mapping(item, depth=depth + 1)
        return clean
    if isinstance(value, list):
        return [sanitize_mapping(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return sanitize_text(value, 4096)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return sanitize_text(value, 4096)


def validate_action_payload(action, payload):
    if action not in REMOTE_ACTIONS:
        raise ValidationError("Unsupported remote action.")
    if not isinstance(payload, dict):
        raise ValidationError("Command payload must be an object.")
    if action == "dlux.image_update":
        _reject_payload_fields(payload, {"backup_mode"})
        mode = str(payload.get("backup_mode") or "data").strip().lower()
        if mode not in {"data", "full", "skip"}:
            raise ValidationError("backup_mode must be data, full, or skip.")
        return {"backup_mode": mode}
    if action == "dlux.backup.create":
        _reject_payload_fields(payload, {"backup_mode"})
        mode = str(payload.get("backup_mode") or "data").strip().lower()
        if mode not in {"data", "full"}:
            raise ValidationError("backup_mode must be data or full.")
        return {"backup_mode": mode}
    if action == "composer.restart":
        _reject_payload_fields(payload, {"service"})
        service = str(payload.get("service") or "").strip()
        if service and not re.fullmatch(r"[A-Za-z0-9_-]+", service):
            raise ValidationError("Restart service name is invalid.")
        return {"service": service}
    if action == "composer.recovery_deploy":
        _reject_payload_fields(payload, {"force", "reason"})
        reason = sanitize_text(payload.get("reason"), 1000)
        if not reason:
            raise ValidationError("A recovery deployment requires a reason.")
        return {"force": bool(payload.get("force", False)), "reason": reason}
    _reject_payload_fields(payload, set())
    return {}


def _reject_payload_fields(payload, allowed):
    unexpected = set(payload) - allowed
    if unexpected:
        raise ValidationError(f"Unsupported payload field: {sorted(unexpected)[0]}.")


def serialize_command(operation):
    return {
        "schema_version": SCHEMA_VERSION,
        "operation_id": str(operation.operation_id),
        "action": operation.action,
        "created_at": utc_iso(operation.created_for_agent_at),
        "deadline_at": utc_iso(operation.deadline_at),
        "actor": {
            "id": operation.actor_id,
            "display": operation.actor_display,
        },
        "payload": operation.payload,
    }


def validate_event(value, operation_id):
    bounded_json_bytes(value)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported event schema version.")
    try:
        supplied_id = uuid.UUID(str(value.get("operation_id") or ""))
    except ValueError as exc:
        raise ValidationError("Event operation_id must be a UUID.") from exc
    if supplied_id != operation_id:
        raise ValidationError("Event operation_id does not match the URL.")
    state = str(value.get("state") or "").strip()
    if state not in EVENT_STATES:
        raise ValidationError("Unsupported event state.")
    try:
        sequence = int(value.get("sequence"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Event sequence must be an integer.") from exc
    if sequence < 1:
        raise ValidationError("Event sequence must be positive.")
    detail = value.get("detail") or {}
    if not isinstance(detail, dict):
        raise ValidationError("Event detail must be an object.")
    clean_detail = sanitize_mapping(detail)
    return {
        "sequence": sequence,
        "state": state,
        "phase": sanitize_text(clean_detail.get("phase"), 100),
        "detail": clean_detail,
        "log": sanitize_text(clean_detail.pop("log", ""), MAX_EVENT_LOG),
        "observed_at": parse_timestamp(value.get("observed_at"), "observed_at"),
    }


def validate_snapshot(value):
    bounded_json_bytes(value)
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError("Unsupported snapshot schema version.")
    allowed = {"versions", "updates", "backup", "health", "resources", "agent", "project"}
    clean = {}
    for key in allowed:
        item = value.get(key) or {}
        if not isinstance(item, dict):
            raise ValidationError(f"Snapshot {key} must be an object.")
        clean[key] = sanitize_mapping(item)
    clean["observed_at"] = parse_timestamp(value.get("observed_at"), "observed_at")
    return clean
