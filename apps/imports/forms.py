from django import forms
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.utils import timezone

from apps.accounts.models import User
from apps.allocations.models import AllocationCycle, CycleStatus
from apps.allocations.services import add_months
from apps.contacts.models import Contact
from apps.core.forms import BootstrapFormMixin, DateInput

from . import parsing
from .models import RowAction


class UploadForm(BootstrapFormMixin, forms.Form):
    file = forms.FileField(
        label="Workbook (.xlsx) or CSV",
        validators=[FileExtensionValidator(["xlsx", "csv"])],
    )
    contact_sheet = forms.CharField(
        required=False, max_length=100, help_text="Leave blank to use the 'EMS STALL SEWA' sheet."
    )
    status_sheet = forms.CharField(
        required=False,
        max_length=100,
        help_text="Leave blank to use the '2026 Calling Sewa status' sheet if present.",
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > settings.IMPORT_MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                f"Files must be under {settings.IMPORT_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        return upload


class MappingForm(BootstrapFormMixin, forms.Form):
    def __init__(self, *args, headers, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "— not mapped —"), *[(h, h) for h in headers]]
        for key, label, required, _ in parsing.TARGET_FIELDS:
            self.fields[key] = forms.ChoiceField(label=label, choices=choices, required=required)
        self.apply_bootstrap()

    def apply_bootstrap(self):
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-select"

    def clean(self):
        cleaned = super().clean()
        used = [v for v in cleaned.values() if v]
        if len(used) != len(set(used)):
            raise forms.ValidationError("Each workbook column can be mapped to only one field.")
        return cleaned


class CallerMappingForm(forms.Form):
    name = forms.CharField(required=False, max_length=150)
    choice = forms.CharField(required=False, max_length=20)
    save_alias = forms.BooleanField(required=False)

    def clean_choice(self):
        choice = self.cleaned_data["choice"]
        if choice and choice != "unallocated":
            if not choice.isdigit() or not User.objects.filter(pk=int(choice), is_active=True).exists():
                raise forms.ValidationError("Choose an active user.")
        return choice


class RowForm(BootstrapFormMixin, forms.Form):
    full_name = forms.CharField(required=False, max_length=150, label="Name")
    phone = forms.CharField(required=False, max_length=60, label="Mobile number")
    area = forms.CharField(required=False, max_length=150)
    registration_date = forms.DateField(required=False, widget=DateInput(), label="Registration date")
    action = forms.ChoiceField(choices=RowAction.choices, required=False)
    link_contact = forms.ModelChoiceField(
        queryset=Contact.objects.none(), required=False, label="Existing contact to link"
    )
    skip_reason = forms.CharField(required=False, max_length=300)

    def __init__(self, *args, candidates, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["link_contact"].queryset = candidates

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")
        if action == RowAction.LINK and not cleaned.get("link_contact"):
            self.add_error("link_contact", "Choose the contact to link to.")
        if action == RowAction.SKIP and not cleaned.get("skip_reason", "").strip():
            self.add_error("skip_reason", "A reason is required to skip a row.")
        return cleaned

    def overrides(self):
        data = {k: (self.cleaned_data.get(k) or "") for k in ("full_name", "phone", "area")}
        reg = self.cleaned_data.get("registration_date")
        data["registration_date"] = reg.isoformat() if reg else ""
        return data


class CommitForm(BootstrapFormMixin, forms.Form):
    cycle = forms.ModelChoiceField(
        queryset=AllocationCycle.objects.exclude(status=CycleStatus.CLOSED),
        required=False,
        label="Existing allocation cycle",
    )
    new_cycle_name = forms.CharField(required=False, max_length=100, label="…or new cycle name")
    new_cycle_start = forms.DateField(required=False, widget=DateInput(), label="New cycle start date")
    new_cycle_end = forms.DateField(required=False, widget=DateInput(), label="New cycle planned end date")
    confirm_cycle_start = forms.BooleanField(
        label="I confirm this is the start date of the current allocation cycle (not the stall registration date)."
    )
    confirm_caller_column = forms.BooleanField(
        label="I confirm the mapped caller column holds the caller allocated to each contact."
    )
    acknowledge_discrepancies = forms.BooleanField(
        required=False, label="I have reviewed the discrepancies above and want to import anyway."
    )

    def __init__(self, *args, needs_ack, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cycle"].queryset = AllocationCycle.objects.exclude(status=CycleStatus.CLOSED)
        self.fields["acknowledge_discrepancies"].required = needs_ack
        self.needs_ack = needs_ack

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("cycle") and cleaned.get("new_cycle_name"):
            raise forms.ValidationError("Choose an existing cycle or enter a new one, not both.")
        if not cleaned.get("cycle"):
            if not cleaned.get("new_cycle_name") or not cleaned.get("new_cycle_start"):
                raise forms.ValidationError(
                    "Choose an existing cycle, or enter a new cycle name and start date."
                )
            start = cleaned["new_cycle_start"]
            if start > timezone.localdate():
                self.add_error("new_cycle_start", "The current cycle cannot start in the future.")
            end = cleaned.get("new_cycle_end") or add_months(start, settings.ALLOCATION_CYCLE_MONTHS)
            cleaned["new_cycle_end"] = end
            if end < start:
                self.add_error("new_cycle_end", "Must be after the start date.")
        return cleaned
