from django import forms

from dlux.utils import set_field_attrs

from .models import ManagedProject


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_field_attrs(self)


class ManagedProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ManagedProject
        fields = ("name", "slug", "environment", "base_url", "scope", "is_active")


class ImageUpdateForm(StyledFormMixin, forms.Form):
    backup_mode = forms.ChoiceField(
        choices=(("data", "Data backup"), ("full", "Full backup"), ("skip", "Skip backup")),
        initial="data",
    )


class BackupCreateForm(StyledFormMixin, forms.Form):
    backup_mode = forms.ChoiceField(
        choices=(("data", "Data backup"), ("full", "Full backup with media")),
        initial="data",
    )


class RestartForm(StyledFormMixin, forms.Form):
    service = forms.ChoiceField(
        required=False,
        choices=(
            ("", "All allowlisted application services"),
            ("web", "Web"),
            ("celery", "Celery"),
            ("smtp-relay", "SMTP relay"),
            ("caddy", "Caddy"),
        ),
    )


class RecoveryDeployForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    current_password = forms.CharField(widget=forms.PasswordInput)
    backup_bypass_ack = forms.BooleanField(
        label="I understand that recovery deployment may bypass the normal DLUX backup workflow"
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.user or not self.user.check_password(password):
            raise forms.ValidationError("Current password is incorrect.")
        return password


class FleetBatchForm(StyledFormMixin, forms.Form):
    projects = forms.ModelMultipleChoiceField(queryset=ManagedProject.objects.none())
    backup_mode = forms.ChoiceField(
        choices=(("data", "Data backup"), ("full", "Full backup"), ("skip", "Skip backup")),
        initial="data",
    )
    concurrency = forms.IntegerField(min_value=1, max_value=3, initial=1)
    continue_on_failure = forms.BooleanField(required=False, initial=False)
    name = forms.CharField(max_length=160, required=False)

    def __init__(self, *args, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        if projects is not None:
            self.fields["projects"].queryset = projects
