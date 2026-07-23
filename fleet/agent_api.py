import asyncio
import json
import uuid

from asgiref.sync import sync_to_async
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .protocol import MAX_DOCUMENT_BYTES, SCHEMA_VERSION
from .services import (
    ProtocolConflict,
    authenticate_agent,
    begin_credential_rotation,
    claim_next_command,
    confirm_credential_rotation,
    enroll_agent,
    record_local_operation,
    record_operation_event,
    store_snapshot,
    update_capabilities,
)


def _error(message, status):
    if isinstance(message, ValidationError):
        detail = "; ".join(message.messages)
    else:
        detail = str(message)
    return JsonResponse({"error": detail}, status=status)


def _document(request):
    content_length = request.META.get("CONTENT_LENGTH")
    try:
        if content_length and int(content_length) > MAX_DOCUMENT_BYTES:
            raise ValidationError("Document exceeds the 64 KiB limit.")
    except ValueError as exc:
        raise ValidationError("Content-Length is invalid.") from exc
    raw = request.body
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValidationError("Document exceeds the 64 KiB limit.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationError("Request body must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValidationError("Request body must be a JSON object.")
    return value


def _credentials(request):
    agent_id = request.headers.get("X-Composer-Agent-ID", "")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, bearer = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not bearer:
        raise PermissionDenied("Agent credentials are required.")
    return agent_id, bearer


async def _authenticate(request, *, allow_pending=False):
    agent_id, bearer = _credentials(request)
    return await sync_to_async(authenticate_agent, thread_sensitive=True)(
        agent_id,
        bearer,
        allow_pending=allow_pending,
    )


@csrf_exempt
async def enroll(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        document = _document(request)
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError("Unsupported enrollment schema version.")
        capabilities = {
            "agent_version": document.get("agent_version"),
            "protocol_versions": document.get("protocol_versions"),
            "capabilities": document.get("capabilities"),
        }
        agent, secret = await sync_to_async(enroll_agent, thread_sensitive=True)(
            document.get("enrollment_token"),
            capabilities,
        )
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse(
        {
            "schema_version": SCHEMA_VERSION,
            "agent_id": str(agent.id),
            "agent_secret": secret,
        },
        status=201,
    )


@csrf_exempt
async def next_command(request):
    if request.method != "GET":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        wait_seconds = max(0, min(25, int(request.GET.get("wait", "25"))))
    except (PermissionDenied, ValueError) as exc:
        return _error(exc, 403 if isinstance(exc, PermissionDenied) else 400)
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        command = await sync_to_async(claim_next_command, thread_sensitive=True)(agent)
        if command:
            return JsonResponse({"command": command})
        if asyncio.get_running_loop().time() >= deadline:
            return HttpResponse(status=204)
        await asyncio.sleep(0.25)


@csrf_exempt
async def operation_event(request, operation_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        event, created = await sync_to_async(record_operation_event, thread_sensitive=True)(
            agent,
            operation_id,
            _document(request),
        )
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ProtocolConflict as exc:
        return _error(exc, 409)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse(
        {"operation_id": str(operation_id), "sequence": event.sequence},
        status=201 if created else 200,
    )


@csrf_exempt
async def snapshot(request):
    if request.method != "PUT":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        await sync_to_async(store_snapshot, thread_sensitive=True)(agent, _document(request))
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse({"status": "stored"})


@csrf_exempt
async def local_operation(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        operation, created = await sync_to_async(record_local_operation, thread_sensitive=True)(
            agent,
            _document(request),
        )
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ProtocolConflict as exc:
        return _error(exc, 409)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse(
        {"operation_id": str(operation.operation_id)},
        status=201 if created else 200,
    )


@csrf_exempt
async def capabilities(request):
    if request.method != "PUT":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        await sync_to_async(update_capabilities, thread_sensitive=True)(agent, _document(request))
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse({"status": "stored"})


@csrf_exempt
async def rotate_credentials(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request)
        document = _document(request)
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError("Unsupported rotation schema version.")
        rotation_id, secret = await sync_to_async(begin_credential_rotation, thread_sensitive=True)(agent)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ValidationError as exc:
        return _error(exc, 400)
    return JsonResponse(
        {
            "schema_version": SCHEMA_VERSION,
            "rotation_id": str(rotation_id),
            "agent_secret": secret,
        }
    )


@csrf_exempt
async def confirm_rotation(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        agent = await _authenticate(request, allow_pending=True)
        document = _document(request)
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError("Unsupported rotation schema version.")
        rotation_id = uuid.UUID(str(document.get("rotation_id") or ""))
        await sync_to_async(confirm_credential_rotation, thread_sensitive=True)(agent, rotation_id)
    except PermissionDenied as exc:
        return _error(exc, 403)
    except ProtocolConflict as exc:
        return _error(exc, 409)
    except (ValidationError, ValueError) as exc:
        return _error(exc, 400)
    return JsonResponse({"status": "confirmed"})
