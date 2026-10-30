from django import forms
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.forms import BootstrapFormMixin, DateInput

from .models import AllocationCycle, CycleStatus
from .services import active_cycle, callers_queryset, default_cycle_dates


class BulkKind:
    ASSIGN = "assign"
    MOVE_ALL = "move_all"
    SWAP = "swap"
    ROTATE = "rotate"

    CHOICES = [
        (ASSIGN, "Assign or move selected contacts to one caller"),
        (MOVE_ALL, "Move a caller's whole list to another caller"),
        (SWAP, "Swap the complete lists of two callers"),
        (ROTATE, "Rotate lists among several callers (each list moves to the next caller)"),
    ]


class BulkChangeForm(BootstrapFormMixin, forms.Form):
    kind = forms.ChoiceField(label="Change", choices=BulkKind.CHOICES)
    contacts = forms.ModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, widget=forms.MultipleHiddenInput
    )
    to_caller = forms.ModelChoiceField(label="To caller", queryset=callers_queryset(), required=False)
    from_caller = forms.ModelChoiceField(label="From caller", queryset=callers_queryset(), required=False)
    caller_a = forms.ModelChoiceField(label="Caller A", queryset=callers_queryset(), required=False)
    caller_b = forms.ModelChoiceField(label="Caller B", queryset=callers_queryset(), required=False)
    rotation_callers = forms.ModelMultipleChoiceField(
        label="Callers in the rotation",
        queryset=callers_queryset(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Lists rotate in the order shown (alphabetical): 1st → 2nd → … → last → 1st.",
    )
    effective_date = forms.DateField(widget=DateInput())
    cycle = forms.ModelChoiceField(
        label="Allocation cycle",
        queryset=AllocationCycle.objects.exclude(status=CycleStatus.CLOSED),
        required=False,
    )
    reason = forms.CharField(max_length=500, widget=forms.TextInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        callers = callers_queryset().order_by("first_name", "last_name", "username")
        for name in ("to_caller", "from_caller", "caller_a", "caller_b", "rotation_callers"):
            self.fields[name].queryset = callers
        self.fields["cycle"].queryset = AllocationCycle.objects.exclude(status=CycleStatus.CLOSED)
        cycle = active_cycle()
        self.initial.setdefault("cycle", cycle)
        self.initial.setdefault("effective_date", timezone.localdate())

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        required = {
            BulkKind.ASSIGN: ["contacts", "to_caller"],
            BulkKind.MOVE_ALL: ["from_caller", "to_caller"],
            BulkKind.SWAP: ["caller_a", "caller_b"],
            BulkKind.ROTATE: ["rotation_callers"],
        }.get(kind, [])
        for name in required:
            if not cleaned.get(name):
                self.add_error(
                    name if name != "contacts" else None,
                    "Select at least one contact." if name == "contacts" else "Required for this change.",
                )
        if (
            kind == BulkKind.MOVE_ALL
            and cleaned.get("from_caller")
            and cleaned.get("from_caller") == cleaned.get("to_caller")
        ):
            self.add_error("to_caller", "Choose a different caller.")
        if (
            kind == BulkKind.SWAP
            and cleaned.get("caller_a")
            and cleaned.get("caller_a") == cleaned.get("caller_b")
        ):
            self.add_error("caller_b", "Choose a different caller.")
        if kind == BulkKind.ROTATE and len(cleaned.get("rotation_callers") or []) < 2:
            self.add_error("rotation_callers", "Choose at least two callers.")
        return cleaned


class CycleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = AllocationCycle
        fields = ["name", "start_date", "planned_end_date", "notes"]
        widgets = {
            "start_date": DateInput(),
            "planned_end_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        start, end = default_cycle_dates()
        self.initial.setdefault("start_date", start)
        self.initial.setdefault("planned_end_date", end)
        self.initial.setdefault("name", f"{start:%b %Y} – {end:%b %Y}")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("planned_end_date")
        if start and end and end < start:
            self.add_error("planned_end_date", "Must be on or after the start date.")
        return cleaned
