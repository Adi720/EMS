from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.allocations.models import Allocation
from apps.allocations.services import (
    AllocationError,
    assign_individual,
    callers_queryset,
    current_allocation,
    unallocated_active_contacts,
)
from apps.audit.services import events_for, log_event
from apps.calling.models import CallTask
from apps.core.exports import export_response
from apps.core.forms import BootstrapFormMixin, DateInput
from apps.core.permissions import CoordinatorRequiredMixin
from apps.core.phones import display_phone, phone_digits

from . import services
from .forms import ContactFilterForm, ContactForm, StatusChangeForm
from .models import Contact, ContactStatus


def contact_queryset():
    open_alloc = Allocation.objects.filter(contact=OuterRef("pk"), effective_to__isnull=True)
    return Contact.objects.annotate(
        current_caller_id=Subquery(open_alloc.values("caller_id")[:1]),
        current_caller_first=Subquery(open_alloc.values("caller__first_name")[:1]),
        current_caller_last=Subquery(open_alloc.values("caller__last_name")[:1]),
        current_caller_username=Subquery(open_alloc.values("caller__username")[:1]),
    )


def filter_contacts(qs, params):
    form = ContactFilterForm(params)
    form.is_valid()
    data = form.cleaned_data if form.is_bound else {}
    q = data.get("q", "").strip()
    if q:
        condition = Q(full_name__icontains=q) | Q(area__icontains=q)
        digits = phone_digits(q)
        if len(digits) >= 4:
            condition |= Q(phone_primary__contains=digits) | Q(phone_secondary__contains=digits)
        qs = qs.filter(condition)
    if data.get("status"):
        qs = qs.filter(status=data["status"])
    if data.get("area", "").strip():
        qs = qs.filter(area__icontains=data["area"].strip())
    caller = data.get("caller", "")
    if caller == "none":
        qs = qs.filter(current_caller_id__isnull=True)
    elif caller.isdigit():
        qs = qs.filter(current_caller_id=int(caller))
    return qs, form


def caller_label(contact):
    name = f"{contact.current_caller_first or ''} {contact.current_caller_last or ''}".strip()
    return name or contact.current_caller_username or ""


class ContactListView(CoordinatorRequiredMixin, ListView):
    template_name = "contacts/contact_list.html"
    paginate_by = 25

    def get_queryset(self):
        qs, self.filter_form = filter_contacts(contact_queryset(), self.request.GET)
        return qs.order_by("full_name", "id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for contact in context["object_list"]:
            contact.caller_label = caller_label(contact)
        params = self.request.GET.copy()
        params.pop("page", None)
        status_params = params.copy()
        status_params.pop("status", None)
        counts = dict(Contact.objects.order_by().values_list("status").annotate(n=Count("id")))
        context.update(
            filter_form=self.filter_form,
            callers=callers_queryset().order_by("first_name", "last_name", "username"),
            statuses=ContactStatus.choices,
            status_tabs=[("", "All", sum(counts.values()))]
            + [(value, label, counts.get(value, 0)) for value, label in ContactStatus.choices],
            selected_status=self.request.GET.get("status", ""),
            status_querystring=status_params.urlencode(),
            querystring=params.urlencode(),
            total=context["paginator"].count if context.get("paginator") else len(context["object_list"]),
            active_count=counts.get(ContactStatus.ACTIVE, 0),
            unallocated_count=unallocated_active_contacts().count(),
            areas=Contact.objects.order_by("area").values_list("area", flat=True).distinct()[:300],
            has_filters=any(self.request.GET.get(k) for k in ("q", "area", "caller", "status")),
        )
        return context


class ContactCreateForm(ContactForm):
    allocate_to = forms.ModelChoiceField(label="Caller", queryset=callers_queryset(), required=False)
    allocation_start = forms.DateField(
        label="Caller from date",
        required=False,
        widget=DateInput(),
        help_text="When the caller becomes responsible. Not the registration date.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["allocate_to"].queryset = callers_queryset()
        self.initial.setdefault("allocation_start", timezone.localdate())


class ContactCreateView(CoordinatorRequiredMixin, FormView):
    template_name = "contacts/contact_form.html"
    form_class = ContactCreateForm

    def form_valid(self, form):
        contact = services.create_contact(form.contact_data(), self.request.user)
        caller = form.cleaned_data.get("allocate_to")
        if caller:
            assign_individual(
                contact,
                caller,
                effective_date=form.cleaned_data.get("allocation_start") or timezone.localdate(),
                actor=self.request.user,
                reason="Allocated when the contact was created",
            )
        messages.success(self.request, f"{contact} added to the Saints directory.")
        return redirect("contacts:detail", pk=contact.pk)


class ContactUpdateView(CoordinatorRequiredMixin, FormView):
    template_name = "contacts/contact_form.html"
    form_class = ContactForm

    def dispatch(self, request, *args, **kwargs):
        self.contact = get_object_or_404(Contact, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # The form validates against a copy so the service sees the stored values.
        kwargs["instance"] = Contact.objects.get(pk=self.contact.pk)
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(contact=self.contact, **kwargs)

    def form_valid(self, form):
        _, changed = services.update_contact(self.contact, form.contact_data(), self.request.user)
        messages.success(self.request, "Saved." if changed else "No changes to save.")
        return redirect("contacts:detail", pk=self.contact.pk)


class ReassignForm(BootstrapFormMixin, forms.Form):
    caller = forms.ModelChoiceField(label="New caller", queryset=callers_queryset())
    effective_date = forms.DateField(widget=DateInput())
    reason = forms.CharField(max_length=500, widget=forms.TextInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["caller"].queryset = callers_queryset()
        self.initial.setdefault("effective_date", timezone.localdate())


class ContactDetailView(CoordinatorRequiredMixin, DetailView):
    model = Contact
    template_name = "contacts/contact_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contact = self.object
        tasks = (
            CallTask.objects.filter(contact=contact)
            .select_related("session", "caller")
            .prefetch_related("attempts__recorded_by")
            .order_by("-session__session_date")
        )
        context.update(
            current=current_allocation(contact),
            allocations=contact.allocations.select_related("caller", "created_by", "cycle").order_by(
                "-effective_from", "-id"
            ),
            history=contact.status_history.select_related("changed_by"),
            tasks=tasks,
            duplicates=services.find_possible_duplicates(
                [contact.phone_primary, contact.phone_secondary], exclude_pk=contact.pk
            ),
            status_form=kwargs.get("status_form")
            or StatusChangeForm(contact=contact, callers=callers_queryset()),
            reassign_form=kwargs.get("reassign_form") or ReassignForm(),
            events=events_for(contact)[:20],
        )
        return context


class ContactStatusView(CoordinatorRequiredMixin, View):
    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        form = StatusChangeForm(request.POST, contact=contact, callers=callers_queryset())
        if form.is_valid():
            try:
                services.change_status(
                    contact,
                    form.cleaned_data["new_status"],
                    request.user,
                    reason_category=form.cleaned_data["reason_category"],
                    reason_text=form.cleaned_data["reason_text"],
                    effective_date=form.cleaned_data["effective_date"],
                    review_date=form.cleaned_data["review_date"],
                    reactivation_caller=form.cleaned_data["reactivation_caller"],
                )
            except (services.LifecycleError, AllocationError, ValidationError) as exc:
                messages.error(request, str(exc))
            else:
                contact.refresh_from_db()
                messages.success(request, f"Status changed to {contact.get_status_display()}.")
                return redirect("contacts:detail", pk=pk)
        view = ContactDetailView(request=request, kwargs={"pk": pk}, object=contact)
        view.object = contact
        return view.render_to_response(view.get_context_data(status_form=form))


class ContactReassignView(CoordinatorRequiredMixin, View):
    def post(self, request, pk):
        contact = get_object_or_404(Contact, pk=pk)
        form = ReassignForm(request.POST)
        if form.is_valid():
            try:
                assign_individual(
                    contact,
                    form.cleaned_data["caller"],
                    effective_date=form.cleaned_data["effective_date"],
                    actor=request.user,
                    reason=form.cleaned_data["reason"],
                )
            except AllocationError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"{contact} is now with {form.cleaned_data['caller']}.")
                return redirect("contacts:detail", pk=pk)
        view = ContactDetailView(request=request, kwargs={"pk": pk})
        view.object = contact
        return view.render_to_response(view.get_context_data(reassign_form=form))


MAX_DELETE = 200


class ContactDeleteView(CoordinatorRequiredMixin, View):
    """Confirm and delete one or more Saints (``?ids=1,2`` or ``ids`` form values)."""

    template_name = "contacts/contact_delete.html"

    def selected(self, request):
        source = request.POST if request.method == "POST" else request.GET
        ids = []
        for value in source.getlist("ids"):
            ids += [part for part in value.split(",") if part.strip().isdigit()]
        return list(Contact.objects.filter(pk__in=ids[:MAX_DELETE]).order_by("full_name", "id"))

    def get(self, request):
        contacts = self.selected(request)
        if not contacts:
            messages.info(request, "Select at least one Saint to delete.")
            return redirect("contacts:list")
        can, kept = services.deletable(contacts)
        return render(
            request,
            self.template_name,
            {"can": can, "kept": kept, "next": safe_next(request, reverse("contacts:list"))},
        )

    def post(self, request):
        contacts = self.selected(request)
        can, _ = services.deletable(contacts)
        if not can:
            messages.error(request, "None of the selected Saints can be deleted.")
            return redirect("contacts:list")
        names = services.delete_contacts(can, request.user, reason=request.POST.get("reason", "")[:300])
        shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
        messages.success(request, f"Deleted {len(names)} Saint{'s' if len(names) != 1 else ''}: {shown}.")
        return redirect(safe_next(request, reverse("contacts:list")))


def safe_next(request, default):
    """A same-site list URL to return to after deleting, or ``default``."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    list_url = reverse("contacts:list")
    if target.startswith(list_url) and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return default


EXPORT_HEADERS = [
    "Name",
    "Phone",
    "Secondary phone",
    "Area",
    "Registration date",
    "Qualification",
    "Collected by",
    "Status",
    "Current caller",
]


class ContactExportView(CoordinatorRequiredMixin, View):
    """Contact list export. Do-not-call contacts are excluded unless explicitly included."""

    def get(self, request):
        qs, _ = filter_contacts(contact_queryset(), request.GET)
        include_dnc = request.GET.get("include_dnc") == "1"
        if not include_dnc:
            qs = qs.exclude(status=ContactStatus.DO_NOT_CALL)
        qs = qs.order_by("full_name", "id")
        fmt = "xlsx" if request.GET.get("format") == "xlsx" else "csv"
        rows = [
            [
                c.full_name,
                display_phone(c.phone_primary),
                display_phone(c.phone_secondary),
                c.area,
                c.registration_date,
                c.qualification,
                c.collected_by_name,
                c.get_status_display(),
                caller_label(c),
            ]
            for c in qs
        ]
        log_event(
            request.user,
            "export.contacts",
            f"Exported {len(rows)} contacts ({fmt})",
            include_dnc=include_dnc,
            filters={k: v for k, v in request.GET.items() if k != "format"},
        )
        filename = f"contacts-{timezone.localdate():%Y%m%d}"
        return export_response(fmt, filename, EXPORT_HEADERS, rows, "Contacts")
