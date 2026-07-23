from django.urls import path

from . import agent_api


urlpatterns = [
    path("enroll/", agent_api.enroll, name="agent_enroll"),
    path("commands/next/", agent_api.next_command, name="agent_next_command"),
    path("operations/<uuid:operation_id>/events/", agent_api.operation_event, name="agent_operation_event"),
    path("snapshot/", agent_api.snapshot, name="agent_snapshot"),
    path("local-operations/", agent_api.local_operation, name="agent_local_operation"),
    path("capabilities/", agent_api.capabilities, name="agent_capabilities"),
    path("credentials/rotate/", agent_api.rotate_credentials, name="agent_rotate_credentials"),
    path("credentials/rotate/confirm/", agent_api.confirm_rotation, name="agent_confirm_rotation"),
]
