from django import forms
from django.utils import timezone

from apps.accounts.models import User
from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.phones import normalize_phone
from apps.core.text import clean_text

from .models import Contact, ContactStatus, StatusReason
from .services import find_possible_duplicates

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
            "collected_by_name",
            "notes",
        ]
        widgets = {
            "registration_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "phone_primary": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
            "phone_secondary": forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
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
            if self.duplicates and not cleaned.get("confirm_duplicate"):
                raise forms.ValidationError(
                    "Another contact already uses this phone number. Check the list below; "
                    "tick the confirmation box only if this is a different person (e.g. a shared family phone)."
                )
        return cleaned

    def contact_data(self):
        return {field: self.cleaned_data[field] for field in self.Meta.fields}


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
        label="Review date (temporarily unavailable only)", required=False, widget=DateInput()
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

    def clean(self):
        cleaned = super().clean()
        new_status = cleaned.get("new_status")
        effective = cleaned.get("effective_date")
        review = cleaned.get("review_date")
        if review and new_status != ContactStatus.TEMP_UNAVAILABLE:
            self.add_error("review_date", "Only used for temporarily unavailable contacts.")
        if review and effective and review < effective:
            self.add_error("review_date", "Review date must be on or after the effective date.")
        if self.contact.status == ContactStatus.DO_NOT_CALL and not cleaned.get("reason_text", "").strip():
            self.add_error("reason_text", "Required: confirm that the person agreed to be contacted again.")
        if cleaned.get("reactivation_caller") and new_status != ContactStatus.ACTIVE:
            self.add_error("reactivation_caller", "Only used when reactivating.")
        return cleaned


class ContactFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Search")
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *ContactStatus.choices])
    area = forms.CharField(required=False)
    caller = forms.CharField(required=False)
