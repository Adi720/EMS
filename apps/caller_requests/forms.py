from django import forms

from apps.core.forms import BootstrapFormMixin

from .models import RequestKind


class RaiseRequestForm(BootstrapFormMixin, forms.Form):
    kind = forms.ChoiceField(label="What is it about?", choices=RequestKind.choices)
    contact = forms.ModelChoiceField(label="Saint", queryset=None, required=False, empty_label="— Choose —")
    reason = forms.CharField(
        label="Reason",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Please type your remarks"}),
    )

    def __init__(self, *args, saints, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].queryset = saints


class DecisionForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(label="Note to the caller", required=False, max_length=1000)
