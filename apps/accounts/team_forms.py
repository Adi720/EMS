from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import SetPasswordForm

from apps.core.forms import BootstrapFormMixin
from apps.core.text import clean_text

from .models import User


class CallerProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"email": "Email (for Saturday reminders)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True

    def clean_first_name(self):
        return clean_text(self.cleaned_data["first_name"])

    def clean_last_name(self):
        return clean_text(self.cleaned_data["last_name"])


class CallerCreateForm(CallerProfileForm):
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 10 characters, not common or all numbers. Share it with the caller privately.",
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta(CallerProfileForm.Meta):
        fields = ["first_name", "last_name", "username", "email"]
        help_texts = {"username": "Used to log in. Letters, digits and @ . + - _ only."}

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            candidate = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            try:
                password_validation.validate_password(p1, candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class CallerPasswordForm(BootstrapFormMixin, SetPasswordForm):
    """New password chosen by the coordinator (validated with the site's password rules)."""
