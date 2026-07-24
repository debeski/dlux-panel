from django.urls import path

from . import views


app_name = "fleet"

urlpatterns = [
    path("", views.FleetOverviewView.as_view(), name="overview"),
    path("projects/<uuid:pk>/", views.ManagedProjectDetailView.as_view(), name="project_detail"),
    path("projects/<uuid:pk>/update/", views.ProjectUpdateActionView.as_view(), name="project_update"),
    path("projects/<uuid:pk>/backup/", views.ProjectBackupActionView.as_view(), name="project_backup"),
    path("projects/<uuid:pk>/restart/", views.ProjectRestartActionView.as_view(), name="project_restart"),
    path("projects/<uuid:pk>/recovery/", views.ProjectRecoveryActionView.as_view(), name="project_recovery"),
    path("projects/<uuid:pk>/enrollment/", views.EnrollmentTokenView.as_view(), name="project_enrollment"),
    path("projects/<uuid:pk>/revoke/", views.AgentRevokeView.as_view(), name="project_revoke"),
    path("projects/<uuid:pk>/rotate/", views.AgentRotateView.as_view(), name="project_rotate"),
    path("batches/new/", views.FleetBatchCreateView.as_view(), name="batch_add"),
    path("batches/<uuid:pk>/", views.FleetBatchDetailView.as_view(), name="batch_detail"),
    path("operations/active/", views.ActiveOperationsView.as_view(), name="operations_active"),
    path("operations/<uuid:operation_id>/status/", views.OperationStatusView.as_view(), name="operation_status"),
    path("operations/<uuid:operation_id>/cancel/", views.OperationCancelView.as_view(), name="operation_cancel"),
]
