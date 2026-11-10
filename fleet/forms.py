from django import forms

from dlux.translations import get_strings
from dlux.utils import set_field_attrs

from .models import ManagedProject


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)


class ManagedProjectForm(StyledFormMixin, forms.ModelForm):
    # The add/edit modal is form-only (no embedded list), so on save the modal
    # manager reloads the underlying overview instead of a non-existent inner
    # table — the new/edited project appears in the fleet table immediately.
    refresh_parent = True

    class Meta:
        model = ManagedProject
        fields = ("name", "slug", "environment", "base_url", "scope", "is_active")


class ImageUpdateForm(StyledFormMixin, forms.Form):
    backup_mode = forms.ChoiceField(initial="data")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        s = get_strings()
        self.fields["backup_mode"].choices = (
            ("data", s.get("fleet_backup_data", "Data backup")),
            ("full", s.get("fleet_backup_full", "Full backup")),
            ("skip", s.get("fleet_backup_skip", "Skip backup")),
        )


class BackupCreateForm(StyledFormMixin, forms.Form):
    backup_mode = forms.ChoiceField(initial="data")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        s = get_strings()
        self.fields["backup_mode"].choices = (
            ("data", s.get("fleet_backup_data", "Data backup")),
            ("full", s.get("fleet_backup_full_media", "Full backup with media")),
        )


class RestartForm(StyledFormMixin, forms.Form):
    service = forms.ChoiceField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        s = get_strings()
        self.fields["service"].choices = (
            ("", s.get("fleet_restart_all", "All allowlisted application services")),
            ("web", "Web"),
            ("worker", "Worker"),
            ("celery", "Celery"),
            ("smtp-relay", "SMTP relay"),
            ("caddy", "Caddy"),
        )
        self.fields["service"].help_text = s.get(
            "fleet_restart_service_help",
            "Worker runs DjangoLux tasks from DjangoLux 1.16 on; Celery runs project tasks, or "
            "DjangoLux tasks on older stacks. A service outside the project's restart allowlist "
            "fails with the agent's reason.",
        )


class RecoveryDeployForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    current_password = forms.CharField(widget=forms.PasswordInput)
    backup_bypass_ack = forms.BooleanField()

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        s = get_strings()
        self.fields["reason"].label = s.get("fleet_recovery_reason", "Reason")
        self.fields["current_password"].label = s.get("fleet_recovery_password", "Current password")
        self.fields["backup_bypass_ack"].label = s.get(
            "fleet_recovery_ack",
            "I understand that recovery deployment may bypass the normal DLUX backup workflow",
        )

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user or not self.user.check_password(password):
            raise forms.ValidationError(
                get_strings().get("fleet_recovery_bad_password", "Current password is incorrect.")
            )
        return password


class FleetBatchForm(StyledFormMixin, forms.Form):
    projects = forms.ModelMultipleChoiceField(queryset=ManagedProject.objects.none())
    backup_mode = forms.ChoiceField(initial="data")
    concurrency = forms.IntegerField(min_value=1, max_value=3, initial=1)
    continue_on_failure = forms.BooleanField(required=False, initial=False)
    name = forms.CharField(max_length=160, required=False)

    def __init__(self, *args, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        s = get_strings()
        if projects is not None:
            self.fields["projects"].queryset = projects
        self.fields["backup_mode"].choices = (
            ("data", s.get("fleet_backup_data", "Data backup")),
            ("full", s.get("fleet_backup_full", "Full backup")),
            ("skip", s.get("fleet_backup_skip", "Skip backup")),
        )
        self.fields["projects"].label = s.get("fleet_batch_projects", "Projects")
        self.fields["concurrency"].label = s.get("fleet_batch_concurrency", "Concurrency")
        self.fields["continue_on_failure"].label = s.get("fleet_batch_continue", "Continue on failure")
        self.fields["name"].label = s.get("fleet_batch_name", "Batch name")
