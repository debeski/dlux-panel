import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from dlux.models import ScopedModel


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Break-glass audit records are immutable.")

    def delete(self):
        raise ValidationError("Break-glass audit records are immutable.")


class ManagedProject(ScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    environment = models.CharField(max_length=80, default="production")
    base_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        permissions = (
            ("run_image_update", "Can run managed project image updates"),
            ("create_project_backup", "Can create managed project backups"),
            ("restart_managed_project", "Can safely restart managed project services"),
            ("manage_composer_agent", "Can enroll, rotate, and revoke Composer agents"),
            ("run_fleet_batch", "Can run fleet batches"),
            ("run_recovery_deploy", "Can run break-glass recovery deployments"),
        )

    def __str__(self):
        return f"{self.name} ({self.environment})"


class ComposerAgent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.OneToOneField(
        ManagedProject,
        on_delete=models.CASCADE,
        related_name="agent",
    )
    secret_hash = models.CharField(max_length=255)
    pending_secret_hash = models.CharField(max_length=255, blank=True)
    pending_rotation_id = models.UUIDField(null=True, blank=True, unique=True)
    pending_rotation_expires_at = models.DateTimeField(null=True, blank=True)
    last_rotation_id = models.UUIDField(null=True, blank=True)
    last_rotation_confirmed_at = models.DateTimeField(null=True, blank=True)
    credential_version = models.PositiveIntegerField(default=1)
    capabilities = models.JSONField(default=dict, blank=True)
    agent_version = models.CharField(max_length=64, blank=True)
    protocol_version = models.PositiveSmallIntegerField(default=1)
    enrolled_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_online(self):
        return bool(
            self.revoked_at is None
            and self.last_seen_at
            and self.last_seen_at >= timezone.now() - timedelta(seconds=90)
        )

    def __str__(self):
        return f"{self.project} agent"


class AgentEnrollmentToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        ManagedProject,
        on_delete=models.CASCADE,
        related_name="enrollment_tokens",
    )
    secret_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self):
        return f"Enrollment for {self.project} until {self.expires_at.isoformat()}"


class FleetBatch(ScopedModel):
    STATE_CHOICES = (
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    action = models.CharField(max_length=80, default="dlux.image_update")
    payload = models.JSONField(default=dict)
    concurrency = models.PositiveSmallIntegerField(
        default=1,
        validators=(MinValueValidator(1), MaxValueValidator(3)),
    )
    continue_on_failure = models.BooleanField(default=False)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="queued")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name


class FleetOperation(ScopedModel):
    ACTION_CHOICES = (
        ("dlux.image_update", "DLUX image update"),
        ("dlux.backup.create", "DLUX backup creation"),
        ("composer.restart", "Safe restart"),
        ("composer.recovery_deploy", "Recovery deployment"),
        ("agent.rotate_credentials", "Rotate agent credentials"),
    )
    STATE_CHOICES = (
        ("queued", "Queued"),
        ("delivered", "Delivered"),
        ("accepted", "Accepted"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
    )
    SOURCE_CHOICES = (("central", "Central"), ("local", "Local"))

    operation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schema_version = models.PositiveSmallIntegerField(default=1)
    project = models.ForeignKey(
        ManagedProject,
        on_delete=models.PROTECT,
        related_name="operations",
    )
    batch = models.ForeignKey(
        FleetBatch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operations",
    )
    action = models.CharField(max_length=80, choices=ACTION_CHOICES)
    payload = models.JSONField(default=dict)
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="central")
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="queued", db_index=True)
    actor_id = models.CharField(max_length=150, blank=True)
    actor_display = models.CharField(max_length=200, blank=True)
    created_for_agent_at = models.DateTimeField(default=timezone.now)
    deadline_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_sequence = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    break_glass_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (
            models.Index(fields=("project", "state", "created_for_agent_at")),
            models.Index(fields=("batch", "state")),
        )

    def __str__(self):
        return f"{self.action} {self.operation_id}"


class OperationEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    operation = models.ForeignKey(
        FleetOperation,
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    phase = models.CharField(max_length=100, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    log = models.TextField(blank=True)
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sequence",)
        constraints = (
            models.UniqueConstraint(
                fields=("operation", "sequence"),
                name="fleet_unique_operation_event_sequence",
            ),
        )


class FleetBatchMember(models.Model):
    batch = models.ForeignKey(FleetBatch, on_delete=models.CASCADE, related_name="members")
    project = models.ForeignKey(ManagedProject, on_delete=models.PROTECT, related_name="batch_members")
    operation = models.OneToOneField(
        FleetOperation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="batch_member",
    )
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ("position",)
        constraints = (
            models.UniqueConstraint(fields=("batch", "project"), name="fleet_unique_batch_project"),
            models.UniqueConstraint(fields=("batch", "position"), name="fleet_unique_batch_position"),
        )


class ProjectSnapshot(models.Model):
    project = models.OneToOneField(
        ManagedProject,
        primary_key=True,
        on_delete=models.CASCADE,
        related_name="latest_snapshot",
    )
    schema_version = models.PositiveSmallIntegerField(default=1)
    observed_at = models.DateTimeField()
    versions = models.JSONField(default=dict)
    update_state = models.JSONField(default=dict)
    backup_summary = models.JSONField(default=dict)
    health_summary = models.JSONField(default=dict)
    resource_summary = models.JSONField(default=dict)
    agent_report = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Latest snapshot for {self.project}"


class BreakGlassAudit(models.Model):
    objects = ImmutableAuditQuerySet.as_manager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.OneToOneField(
        FleetOperation,
        on_delete=models.PROTECT,
        related_name="break_glass_audit",
    )
    project = models.ForeignKey(ManagedProject, on_delete=models.PROTECT, related_name="break_glass_audits")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=1000)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Break-glass audit records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Break-glass audit records are immutable.")
