from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, TemplateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from dlux.utils import (
    get_user_scope,
    is_scope_enabled,
    log_audit_event,
    log_user_action,
    setup_filter_helper,
)

from .filters import ManagedProjectFilter
from .forms import (
    BackupCreateForm,
    FleetBatchForm,
    ImageUpdateForm,
    RecoveryDeployForm,
    RestartForm,
)
from .models import BreakGlassAudit, FleetBatch, FleetOperation, ManagedProject
from .protocol import utc_iso
from .services import (
    ProtocolConflict,
    cancel_operation,
    create_batch,
    create_enrollment_token,
    queue_operation,
    revoke_agent,
    scoped_projects_for_user,
)
from .tables import ManagedProjectTable

ACTIVE_OPERATION_STATES = ("queued", "delivered", "accepted", "running")


def _control_panel_url(request):
    configured_url = str(getattr(settings, "BASE_URL", "") or "").strip().rstrip("/")
    parsed = urlparse(configured_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return configured_url
    return request.build_absolute_uri("/").rstrip("/")


def _wants_json(request):
    """The Dlux dynamic modal always fetches with this header. Plain navigation
    keeps the classic page/redirect behaviour so every route works without JS."""
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _modal(request, template, context):
    return JsonResponse({"html": render_to_string(template, context, request=request)})


def _modal_done(request, message, level=messages.SUCCESS):
    messages.add_message(request, level, message)
    return JsonResponse({"success": True, "refresh_parent": True})


class ScopedFleetMixin(LoginRequiredMixin):
    raise_exception = True

    def project_queryset(self):
        return scoped_projects_for_user(self.request.user)


class FleetOverviewView(
    ScopedFleetMixin, PermissionRequiredMixin, SingleTableMixin, FilterView
):
    """The panel's single page: a Dlux data table whose row context menu opens a
    dynamic modal for every project operation, plus a live in-flight strip."""

    permission_required = "fleet.view_managedproject"
    model = ManagedProject
    table_class = ManagedProjectTable
    filterset_class = ManagedProjectFilter
    template_name = "fleet/overview.html"

    def get_queryset(self):
        return self.project_queryset().select_related("agent", "latest_snapshot")

    def get_filterset(self, filterset_class):
        filterset = super().get_filterset(filterset_class)
        setup_filter_helper(filterset, request=self.request)
        return filterset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_operations"] = (
            FleetOperation.objects.filter(
                project__in=self.project_queryset(),
                state__in=ACTIVE_OPERATION_STATES,
            )
            .select_related("project")
            .order_by("-created_at")[:20]
        )
        context["open_project"] = self._deep_linked_project()
        return context

    def _deep_linked_project(self):
        """`?project=<uuid>` opens that project's modal over the table. Resolved
        through the scoped queryset so the parameter cannot probe other scopes."""
        requested = (self.request.GET.get("project") or "").strip()
        if not requested:
            return None
        try:
            return self.project_queryset().filter(pk=requested).first()
        except (ValidationError, ValueError):
            return None


class ManagedProjectDetailView(ScopedFleetMixin, PermissionRequiredMixin, DetailView):
    permission_required = "fleet.view_managedproject"
    model = ManagedProject
    template_name = "fleet/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        return self.project_queryset().select_related("agent", "latest_snapshot")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["operations"] = self.object.operations.prefetch_related("events")[:30]
        return context

    def render_to_response(self, context, **response_kwargs):
        if _wants_json(self.request):
            return _modal(self.request, "fleet/partials/project_detail.html", context)
        return super().render_to_response(context, **response_kwargs)


class ProjectActionView(ScopedFleetMixin, View):
    """One modal endpoint per typed action: GET renders the form, POST queues it."""

    action = ""
    permission_required = ""
    form_class = None
    title = ""
    description = ""
    submit_label = "Queue"
    submit_class = "btn btn-primary"

    def form_kwargs(self, request):
        return {}

    def get_project(self, pk):
        return get_object_or_404(self.project_queryset(), pk=pk)

    def check(self, request):
        if not request.user.has_perm(self.permission_required):
            raise PermissionDenied

    def render_form(self, request, project, form):
        return _modal(
            request,
            "fleet/partials/action_form.html",
            {
                "project": project,
                "form": form,
                "action_url": request.path,
                "description": self.description,
                "submit_label": self.submit_label,
                "submit_class": self.submit_class,
            },
        )

    def get(self, request, pk):
        self.check(request)
        project = self.get_project(pk)
        form = self.form_class(**self.form_kwargs(request))
        return self.render_form(request, project, form)

    def perform(self, request, project, form):
        payload = dict(form.cleaned_data)
        operation = queue_operation(project, self.action, payload, request.user)
        log_user_action(
            request,
            "QUEUE",
            instance=operation,
            details={"action": self.action, "project": str(project.pk)},
        )
        return f"Queued {self.action} as {operation.operation_id}."

    def post(self, request, pk):
        self.check(request)
        project = self.get_project(pk)
        form = self.form_class(request.POST, **self.form_kwargs(request))
        if not form.is_valid():
            if _wants_json(request):
                return self.render_form(request, project, form)
            messages.error(request, "; ".join(sum(form.errors.values(), [])))
            return redirect("fleet:overview")
        message = self.perform(request, project, form)
        if _wants_json(request):
            return _modal_done(request, message)
        messages.success(request, message)
        return redirect("fleet:overview")


class ProjectUpdateActionView(ProjectActionView):
    action = "dlux.image_update"
    permission_required = "fleet.run_image_update"
    form_class = ImageUpdateForm
    description = "Queues a DLUX image update through the project's own update queue."
    submit_label = "Queue update"


class ProjectBackupActionView(ProjectActionView):
    action = "dlux.backup.create"
    permission_required = "fleet.create_project_backup"
    form_class = BackupCreateForm
    description = "The project-local DLUX backup engine owns the artifact."
    submit_label = "Create backup"


class ProjectRestartActionView(ProjectActionView):
    action = "composer.restart"
    permission_required = "fleet.restart_managed_project"
    form_class = RestartForm
    description = "Stateful services stay protected by the generated allowlist."
    submit_label = "Queue restart"


class ProjectRecoveryActionView(ProjectActionView):
    action = "composer.recovery_deploy"
    permission_required = "fleet.run_recovery_deploy"
    form_class = RecoveryDeployForm
    description = (
        "This bypasses the normal DLUX backup gate. A reason and current-password "
        "step-up are mandatory, and the recorded event is immutable."
    )
    submit_label = "Queue audited recovery"
    submit_class = "btn btn-danger"

    def form_kwargs(self, request):
        return {"user": request.user}

    def check(self, request):
        if not request.user.is_superuser or not request.user.has_perm(self.permission_required):
            raise PermissionDenied

    def perform(self, request, project, form):
        reason = form.cleaned_data["reason"]
        operation = queue_operation(
            project,
            self.action,
            {"force": True, "reason": reason},
            request.user,
        )
        BreakGlassAudit.objects.create(
            operation=operation,
            project=project,
            actor=request.user,
            reason=reason,
            source_ip=request.META.get("REMOTE_ADDR") or None,
        )
        log_audit_event(
            request,
            "break_glass_deploy",
            "BREAK_GLASS",
            instance=operation,
            details={"reason": reason, "project": str(project.pk)},
        )
        return f"Break-glass deployment {operation.operation_id} was queued and audited."


class EnrollmentTokenView(ScopedFleetMixin, View):
    """GET explains the pairing flow; POST mints the one-use token and renders it
    back into the same modal so it is shown exactly once."""

    def check(self, request):
        if not request.user.has_perm("fleet.manage_composer_agent"):
            raise PermissionDenied

    def get(self, request, pk):
        self.check(request)
        project = self.get_project_or_404(pk)
        return _modal(
            request,
            "fleet/partials/enrollment_intro.html",
            {"project": project, "action_url": request.path},
        )

    def get_project_or_404(self, pk):
        return get_object_or_404(self.project_queryset(), pk=pk)

    def post(self, request, pk):
        self.check(request)
        project = self.get_project_or_404(pk)
        record, token = create_enrollment_token(project, request.user)
        log_user_action(
            request, "ENROLL", instance=project, details={"expires_at": utc_iso(record.expires_at)}
        )
        context = {
            "project": project,
            "token": token,
            "expires_at": record.expires_at,
            "control_url": _control_panel_url(request),
        }
        if _wants_json(request):
            response = _modal(request, "fleet/partials/enrollment_token.html", context)
        else:
            response = render(request, "fleet/enrollment_token.html", context)
        response["Cache-Control"] = "no-store"
        return response


class AgentConfirmActionView(ScopedFleetMixin, View):
    """Confirm-only agent operations (no form fields), rendered as a modal."""

    title = ""
    description = ""
    submit_label = "Confirm"
    submit_class = "btn btn-primary"

    def check(self, request):
        if not request.user.has_perm("fleet.manage_composer_agent"):
            raise PermissionDenied

    def get(self, request, pk):
        self.check(request)
        project = get_object_or_404(self.project_queryset(), pk=pk)
        return _modal(
            request,
            "fleet/partials/confirm.html",
            {
                "project": project,
                "action_url": request.path,
                "description": self.description,
                "submit_label": self.submit_label,
                "submit_class": self.submit_class,
            },
        )


class AgentRevokeView(AgentConfirmActionView):
    description = (
        "Revocation blocks central traffic immediately. The project keeps its own "
        "local DLUX updates."
    )
    submit_label = "Revoke agent"
    submit_class = "btn btn-danger"

    def post(self, request, pk):
        self.check(request)
        project = get_object_or_404(self.project_queryset(), pk=pk)
        agent = getattr(project, "agent", None)
        if agent:
            revoke_agent(agent)
            log_audit_event(request, "agent_revoked", "REVOKE", instance=project)
            message = "Agent credential revoked immediately; local DLUX updates remain available."
            if _wants_json(request):
                return _modal_done(request, message, messages.WARNING)
            messages.warning(request, message)
        return redirect("fleet:overview")


class AgentRotateView(AgentConfirmActionView):
    description = (
        "Rotation stages a pending credential; the agent confirms with the new "
        "secret before the old one is revoked."
    )
    submit_label = "Rotate credential"

    def post(self, request, pk):
        self.check(request)
        project = get_object_or_404(self.project_queryset(), pk=pk)
        agent = getattr(project, "agent", None)
        if not agent or agent.revoked_at:
            message = "An active enrolled agent is required."
            if _wants_json(request):
                return JsonResponse({"error": message}, status=400)
            messages.error(request, message)
            return redirect("fleet:overview")
        operation = queue_operation(
            project, "agent.rotate_credentials", {}, request.user, deadline_minutes=15
        )
        log_audit_event(request, "agent_rotation", "ROTATE", instance=operation)
        message = f"Credential rotation {operation.operation_id} was queued."
        if _wants_json(request):
            return _modal_done(request, message)
        messages.success(request, message)
        return redirect("fleet:overview")


class FleetBatchCreateView(ScopedFleetMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "fleet.run_fleet_batch"
    template_name = "fleet/batch_form.html"

    def build_form(self, data=None):
        return FleetBatchForm(data, projects=self.project_queryset())

    def get(self, request, *args, **kwargs):
        if _wants_json(request):
            return _modal(
                request,
                "fleet/partials/batch_form.html",
                {"form": self.build_form(), "action_url": request.path},
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or self.build_form()
        return context

    def post(self, request):
        form = self.build_form(request.POST)
        if not form.is_valid():
            if _wants_json(request):
                return _modal(
                    request,
                    "fleet/partials/batch_form.html",
                    {"form": form, "action_url": request.path},
                )
            return self.render_to_response(self.get_context_data(form=form))
        batch = create_batch(
            form.cleaned_data["projects"],
            request.user,
            backup_mode=form.cleaned_data["backup_mode"],
            concurrency=form.cleaned_data["concurrency"],
            continue_on_failure=form.cleaned_data["continue_on_failure"],
            name=form.cleaned_data["name"],
        )
        log_user_action(request, "QUEUE", instance=batch, details={"member_count": batch.members.count()})
        if _wants_json(request):
            return _modal_done(request, f"Batch {batch.name} was queued.")
        return redirect("fleet:batch_detail", pk=batch.pk)


class FleetBatchDetailView(ScopedFleetMixin, PermissionRequiredMixin, DetailView):
    permission_required = "fleet.view_fleetbatch"
    model = FleetBatch
    template_name = "fleet/batch_detail.html"
    context_object_name = "batch"

    def get_queryset(self):
        queryset = FleetBatch.objects.all()
        if self.request.user.is_superuser or not is_scope_enabled():
            return queryset
        scope = get_user_scope(self.request.user)
        return queryset.filter(
            Q(scope=scope) | Q(scope__isnull=True, members__project__scope=scope)
        ).distinct()

    def render_to_response(self, context, **response_kwargs):
        if _wants_json(self.request):
            return _modal(self.request, "fleet/partials/batch_detail.html", context)
        return super().render_to_response(context, **response_kwargs)


class OperationStatusView(ScopedFleetMixin, View):
    def get(self, request, operation_id):
        if not request.user.has_perm("fleet.view_fleetoperation"):
            raise PermissionDenied
        operation = get_object_or_404(
            FleetOperation.objects.filter(project__in=self.project_queryset()),
            pk=operation_id,
        )
        return JsonResponse(
            {
                "operation_id": str(operation.operation_id),
                "state": operation.state,
                "result": operation.result,
                "events": [
                    {
                        "sequence": event.sequence,
                        "state": event.state,
                        "phase": event.phase,
                        "detail": event.detail,
                        "log": event.log,
                        "observed_at": utc_iso(event.observed_at),
                    }
                    for event in operation.events.all()
                ],
            }
        )


class ActiveOperationsView(ScopedFleetMixin, View):
    """Feed for the overview's in-flight strip, so a running operation stays
    visible after its modal is closed."""

    def get(self, request):
        if not request.user.has_perm("fleet.view_fleetoperation"):
            raise PermissionDenied
        operations = (
            FleetOperation.objects.filter(
                project__in=self.project_queryset(),
                state__in=ACTIVE_OPERATION_STATES,
            )
            .select_related("project")
            .order_by("-created_at")[:20]
        )
        return JsonResponse(
            {
                "operations": [
                    {
                        "operation_id": str(operation.operation_id),
                        "project": operation.project.name,
                        "detail_url": reverse(
                            "fleet:project_detail", args=[operation.project_id]
                        ),
                        "action": operation.action,
                        "state": operation.state,
                        "created_at": utc_iso(operation.created_at),
                    }
                    for operation in operations
                ]
            }
        )


class OperationCancelView(ScopedFleetMixin, View):
    def post(self, request, operation_id):
        if not request.user.has_perm("fleet.change_fleetoperation"):
            raise PermissionDenied
        operation = get_object_or_404(
            FleetOperation.objects.filter(project__in=self.project_queryset()),
            pk=operation_id,
        )
        try:
            cancel_operation(operation, request.user)
        except ProtocolConflict as exc:
            message = "; ".join(exc.messages)
            if _wants_json(request):
                return JsonResponse({"error": message}, status=409)
            messages.error(request, message)
        else:
            log_user_action(request, "CANCEL", instance=operation)
            if _wants_json(request):
                return _modal_done(request, "Operation cancelled.")
            messages.success(request, "Operation cancelled.")
        return redirect("fleet:overview")
