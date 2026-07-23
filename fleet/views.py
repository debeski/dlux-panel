from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from dlux.utils import get_user_scope, is_scope_enabled, log_audit_event, log_user_action

from .forms import (
    BackupCreateForm,
    FleetBatchForm,
    ImageUpdateForm,
    ManagedProjectForm,
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


class ScopedFleetMixin(LoginRequiredMixin):
    raise_exception = True

    def project_queryset(self):
        return scoped_projects_for_user(self.request.user)


class FleetOverviewView(ScopedFleetMixin, PermissionRequiredMixin, ListView):
    permission_required = "fleet.view_managedproject"
    model = ManagedProject
    template_name = "fleet/overview.html"
    context_object_name = "projects"

    def get_queryset(self):
        return self.project_queryset().select_related("agent", "latest_snapshot").order_by("name")


class ManagedProjectCreateView(ScopedFleetMixin, PermissionRequiredMixin, CreateView):
    permission_required = "fleet.add_managedproject"
    model = ManagedProject
    form_class = ManagedProjectForm
    template_name = "fleet/project_form.html"

    def form_valid(self, form):
        if is_scope_enabled() and not self.request.user.is_superuser:
            scope = get_user_scope(self.request.user)
            if scope is None:
                raise PermissionDenied
            form.instance.scope = scope
        response = super().form_valid(form)
        log_user_action(self.request, "CREATE", instance=self.object)
        return response

    def get_success_url(self):
        return reverse("fleet:project_detail", kwargs={"pk": self.object.pk})


class ManagedProjectUpdateView(ScopedFleetMixin, PermissionRequiredMixin, UpdateView):
    permission_required = "fleet.change_managedproject"
    model = ManagedProject
    form_class = ManagedProjectForm
    template_name = "fleet/project_form.html"

    def get_queryset(self):
        return self.project_queryset()

    def form_valid(self, form):
        response = super().form_valid(form)
        log_user_action(self.request, "UPDATE", instance=self.object)
        return response

    def get_success_url(self):
        return reverse("fleet:project_detail", kwargs={"pk": self.object.pk})


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
        context["update_form"] = ImageUpdateForm()
        context["backup_form"] = BackupCreateForm()
        context["restart_form"] = RestartForm()
        context["recovery_form"] = RecoveryDeployForm(user=self.request.user)
        return context


class ProjectActionView(ScopedFleetMixin, View):
    action = ""
    permission_required = ""
    form_class = None

    def post(self, request, pk):
        if not request.user.has_perm(self.permission_required):
            raise PermissionDenied
        project = get_object_or_404(self.project_queryset(), pk=pk)
        form = self.form_class(request.POST)
        if not form.is_valid():
            messages.error(request, "; ".join(sum(form.errors.values(), [])))
            return redirect("fleet:project_detail", pk=project.pk)
        payload = dict(form.cleaned_data)
        operation = queue_operation(project, self.action, payload, request.user)
        log_user_action(
            request,
            "QUEUE",
            instance=operation,
            details={"action": self.action, "project": str(project.pk)},
        )
        messages.success(request, f"Queued {self.action} as {operation.operation_id}.")
        return redirect("fleet:project_detail", pk=project.pk)


class ProjectUpdateActionView(ProjectActionView):
    action = "dlux.image_update"
    permission_required = "fleet.run_image_update"
    form_class = ImageUpdateForm


class ProjectBackupActionView(ProjectActionView):
    action = "dlux.backup.create"
    permission_required = "fleet.create_project_backup"
    form_class = BackupCreateForm


class ProjectRestartActionView(ProjectActionView):
    action = "composer.restart"
    permission_required = "fleet.restart_managed_project"
    form_class = RestartForm


class ProjectRecoveryActionView(ScopedFleetMixin, View):
    def post(self, request, pk):
        if not request.user.is_superuser or not request.user.has_perm("fleet.run_recovery_deploy"):
            raise PermissionDenied
        project = get_object_or_404(self.project_queryset(), pk=pk)
        form = RecoveryDeployForm(request.POST, user=request.user)
        if not form.is_valid():
            messages.error(request, "; ".join(sum(form.errors.values(), [])))
            return redirect("fleet:project_detail", pk=project.pk)
        reason = form.cleaned_data["reason"]
        operation = queue_operation(
            project,
            "composer.recovery_deploy",
            {"force": True, "reason": reason},
            request.user,
        )
        source_ip = request.META.get("REMOTE_ADDR") or None
        BreakGlassAudit.objects.create(
            operation=operation,
            project=project,
            actor=request.user,
            reason=reason,
            source_ip=source_ip,
        )
        log_audit_event(
            request,
            "break_glass_deploy",
            "BREAK_GLASS",
            instance=operation,
            details={"reason": reason, "project": str(project.pk)},
        )
        messages.warning(request, f"Break-glass deployment {operation.operation_id} was queued and audited.")
        return redirect("fleet:project_detail", pk=project.pk)


class EnrollmentTokenView(ScopedFleetMixin, View):
    def post(self, request, pk):
        if not request.user.has_perm("fleet.manage_composer_agent"):
            raise PermissionDenied
        project = get_object_or_404(self.project_queryset(), pk=pk)
        record, token = create_enrollment_token(project, request.user)
        log_user_action(request, "ENROLL", instance=project, details={"expires_at": utc_iso(record.expires_at)})
        response = render(
            request,
            "fleet/enrollment_token.html",
            {"project": project, "token": token, "expires_at": record.expires_at},
        )
        response["Cache-Control"] = "no-store"
        return response


class AgentRevokeView(ScopedFleetMixin, View):
    def post(self, request, pk):
        if not request.user.has_perm("fleet.manage_composer_agent"):
            raise PermissionDenied
        project = get_object_or_404(self.project_queryset(), pk=pk)
        agent = getattr(project, "agent", None)
        if agent:
            revoke_agent(agent)
            log_audit_event(request, "agent_revoked", "REVOKE", instance=project)
            messages.warning(request, "Agent credential revoked immediately; local DLUX updates remain available.")
        return redirect("fleet:project_detail", pk=project.pk)


class AgentRotateView(ScopedFleetMixin, View):
    def post(self, request, pk):
        if not request.user.has_perm("fleet.manage_composer_agent"):
            raise PermissionDenied
        project = get_object_or_404(self.project_queryset(), pk=pk)
        agent = getattr(project, "agent", None)
        if not agent or agent.revoked_at:
            messages.error(request, "An active enrolled agent is required.")
            return redirect("fleet:project_detail", pk=project.pk)
        operation = queue_operation(project, "agent.rotate_credentials", {}, request.user, deadline_minutes=15)
        log_audit_event(request, "agent_rotation", "ROTATE", instance=operation)
        messages.success(request, f"Credential rotation {operation.operation_id} was queued.")
        return redirect("fleet:project_detail", pk=project.pk)


class FleetBatchCreateView(ScopedFleetMixin, PermissionRequiredMixin, TemplateView):
    permission_required = "fleet.run_fleet_batch"
    template_name = "fleet/batch_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = kwargs.get("form") or FleetBatchForm(projects=self.project_queryset())
        return context

    def post(self, request):
        form = FleetBatchForm(request.POST, projects=self.project_queryset())
        if not form.is_valid():
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
        return queryset.filter(Q(scope=scope) | Q(scope__isnull=True, members__project__scope=scope)).distinct()


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
            messages.error(request, "; ".join(exc.messages))
        else:
            log_user_action(request, "CANCEL", instance=operation)
            messages.success(request, "Operation cancelled.")
        return redirect("fleet:project_detail", pk=operation.project_id)
