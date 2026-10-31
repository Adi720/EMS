from django import forms
from django.utils import timezone

from apps.accounts.models import User
from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.phones import normalize_phone
from apps.core.text import clean_text

from .models import CALLABLE_STATUSES, Contact, ContactStatus, StatusReason
from .services import default_hold_until, find_possible_duplicates

PHONE_ERROR = "Enter a valid mobile number (10 digits, or with country code such as +91)."


class ContactForm(BootstrapFormMixin, forms.ModelForm):
    confirm_duplicate = forms.BooleanField(
        required=False,
        label="I have checked the possible duplicates and this is a different person",
    )

    class Meta:
        model = Contact
        fields = [
            "full_name",
            "phone_primary",
            "phone_secondary",
            "area",
            "registration_date",
            "qualification",
            "skills",
            "sewa",
            "collected_by_name",
            "notes",
        ]
        widgets = {
            "registration_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "skills": forms.TextInput(attrs={"placeholder": "e.g. teaching, computers, cooking"}),
            "sewa": forms.TextInput(attrs={"placeholder": "Sewa they do or would like to do"}),
            "phone_primary": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
            "phone_secondary": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
        }
        labels = {"phone_primary": "Mobile number", "phone_secondary": "Second mobile number"}
        help_texts = {"phone_primary": "10 digits, or with the country code (+91…)."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        # The "different person" box only appears once a possible duplicate is found.
        if not self.data.get("confirm_duplicate"):
            self.fields["confirm_duplicate"].widget = forms.HiddenInput()
        if self.instance.pk:
            self.initial["phone_primary"] = self.instance.phone_display
            self.initial["phone_secondary"] = self.instance.phone_secondary_display

    def _clean_phone(self, name, required):
        value = clean_text(self.cleaned_data.get(name))
        if not value:
            if required:
                raise forms.ValidationError("This field is required.")
            return ""
        normalised = normalize_phone(value)
        if normalised is None:
            raise forms.ValidationError(PHONE_ERROR)
        return normalised

    def clean_phone_primary(self):
        return self._clean_phone("phone_primary", required=True)

    def clean_phone_secondary(self):
        return self._clean_phone("phone_secondary", required=False)

    def clean_full_name(self):
        return clean_text(self.cleaned_data["full_name"])

    def clean_area(self):
        return clean_text(self.cleaned_data["area"])

    def clean_registration_date(self):
        value = self.cleaned_data["registration_date"]
        if value and value > timezone.localdate():
            raise forms.ValidationError("Registration date cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        primary, secondary = cleaned.get("phone_primary"), cleaned.get("phone_secondary")
        if primary and secondary and primary == secondary:
            self.add_error("phone_secondary", "Secondary phone is the same as the primary phone.")
        phones_changed = not self.instance.pk or {"phone_primary", "phone_secondary"} & set(self.changed_data)
        if primary and phones_changed:
            self.duplicates = list(
                find_possible_duplicates([primary, secondary], exclude_pk=self.instance.pk)
            )
            if self.duplicates:
                self.fields["confirm_duplicate"].widget = forms.CheckboxInput()
            if self.duplicates and not cleaned.get("confirm_duplicate"):
                raise forms.ValidationError(
                    "Another contact already uses this phone number. Check the list below; "
                    "tick the confirmation box only if this is a different person (e.g. a shared family phone)."
                )
        return cleaned

    def contact_data(self):
        return {field: self.cleaned_data[field] for field in self.Meta.fields}


class StallSaintForm(ContactForm):
    """New Saint from the stall. No caller or start date: coordinators decide those."""

    class Meta(ContactForm.Meta):
        fields = [
            "full_name",
            "phone_primary",
            "phone_secondary",
            "area",
            "registration_date",
            "qualification",
            "skills",
            "sewa",
            "notes",
            "collected_by_name",
        ]
        labels = {
            **ContactForm.Meta.labels,
            "collected_by_name": "Your name",
            "registration_date": "Date met at the stall",
        }
        help_texts = {
            **ContactForm.Meta.help_texts,
            "collected_by_name": "The stall seva member adding this Saint.",
            "registration_date": "",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["collected_by_name"].required = True
        self.initial.setdefault("registration_date", timezone.localdate())

    def clean_collected_by_name(self):
        return clean_text(self.cleaned_data["collected_by_name"])


class StatusChangeForm(BootstrapFormMixin, forms.Form):
    new_status = forms.ChoiceField(label="New status", choices=ContactStatus.choices)
    reason_category = forms.ChoiceField(
        label="Reason",
        choices=[
            c for c in StatusReason.choices if c[0] not in {StatusReason.CREATED, StatusReason.IMPORTED}
        ],
    )
    reason_text = forms.CharField(
        label="Details", required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2})
    )
    effective_date = forms.DateField(label="Effective date", widget=DateInput())
    review_date = forms.DateField(
        label="Next call date (On Hold only)",
        required=False,
        widget=DateInput(),
        help_text="Filled in as 6 months ahead if left empty.",
    )
    reactivation_caller = forms.ModelChoiceField(
        label="Allocate to caller (when reactivating an unallocated contact)",
        queryset=User.objects.none(),
        required=False,
    )

    def __init__(self, *args, contact, callers, **kwargs):
        super().__init__(*args, **kwargs)
        self.contact = contact
        self.fields["new_status"].choices = [c for c in ContactStatus.choices if c[0] != contact.status]
        self.fields["reactivation_caller"].queryset = callers
        self.initial.setdefault("effective_date", timezone.localdate())
        self.initial.setdefault("review_date", default_hold_until())

    def clean(self):
        cleaned = super().clean()
        new_status = cleaned.get("new_status")
        effective = cleaned.get("effective_date")
        review = cleaned.get("review_date")
        if new_status != ContactStatus.ON_HOLD:
            cleaned["review_date"] = None  # only On Hold has a next call date
        elif review and effective and review < effective:
            self.add_error("review_date", "The next call date must be on or after the effective date.")
        if cleaned.get("reactivation_caller") and new_status not in CALLABLE_STATUSES:
            self.add_error("reactivation_caller", "Only used when reactivating.")
        return cleaned


class ContactFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *ContactStatus.choices])
    area = forms.CharField(required=False)
    caller = forms.CharField(required=False)
