from django import forms

from apps.core.forms import BootstrapFormMixin, DateInput, DateTimeInput
from apps.core.text import clean_text

from .models import EmsSession, Outcome


class SessionForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = EmsSession
        fields = ["session_date", "title", "venue", "notes"]
        widgets = {"session_date": DateInput(), "notes": forms.Textarea(attrs={"rows": 2})}

    def clean_title(self):
        return clean_text(self.cleaned_data["title"])

    def clean_venue(self):
        return clean_text(self.cleaned_data["venue"])


class AttemptForm(BootstrapFormMixin, forms.Form):
    outcome = forms.ChoiceField(choices=Outcome.choices, widget=forms.RadioSelect)
    notes = forms.CharField(
        label="Remarks",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Please type your remarks"}),
    )
    callback_at = forms.DateTimeField(
        label="Call back at",
        required=False,
        widget=DateTimeInput(),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )


class QuickAttemptForm(forms.Form):
    outcome = forms.ChoiceField(choices=Outcome.choices)
