from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView

from apps.accounts.models import User
from apps.calling.models import CallTask, EmsSession, SessionStatus, TaskStatus
from apps.contacts.models import Contact, ContactStatus
from apps.contacts.views import caller_label, contact_queryset, filter_contacts
from apps.core.permissions import CoordinatorRequiredMixin

from . import services
from .forms import BulkChangeForm, BulkKind, CycleForm
from .models import AllocationCycle, AllocationOperation, ChangeType

KIND_TO_CHANGE_TYPE = {
    BulkKind.ASSIGN: ChangeType.ASSIGN,
    BulkKind.MOVE_ALL: ChangeType.MOVE_ALL,
    BulkKind.SWAP: ChangeType.SWAP,
    BulkKind.ROTATE: ChangeType.ROTATE,
}


class AllocationHomeView(CoordinatorRequiredMixin, TemplateView):
    template_name = "allocations/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        counts = services.caller_list_counts()
        session = EmsSession.objects.filter(status=SessionStatus.OPEN).order_by("session_date").first()
        pending = {}
        if session:
            pending = dict(
                CallTask.objects.filter(session=session, status=TaskStatus.OPEN, attempt_count=0)
                .values_list("caller")
                .annotate(n=Count("id"))
            )
        largest = max((n for _, n in counts), default=0)
        total = sum(n for _, n in counts)
        context.update(
            caller_cards=[
                {
                    "user": user,
                    "count": n,
                    "share": round(100 * n / largest) if largest else 0,
                    "pending": pending.get(user.pk, 0) if session else None,
                }
                for user, n in counts
            ],
            average=round(total / len(counts), 1) if counts else 0,
            session=session,
            unallocated=services.unallocated_active_contacts().order_by("full_name"),
            cycle=services.active_cycle(),
            cycles=AllocationCycle.objects.all()[:12],
            operations=AllocationOperation.objects.select_related("performed_by", "cycle")[:15],
            rotation_due=services.rotation_due(),
        )
        return context


def build_plan(cleaned):
    kind = cleaned["kind"]
    if kind == BulkKind.ASSIGN:
        return services.plan_assign(cleaned["contacts"], cleaned["to_caller"])
    if kind == BulkKind.MOVE_ALL:
        return services.plan_move_all(cleaned["from_caller"], cleaned["to_caller"])
    if kind == BulkKind.SWAP:
        return services.plan_swap(cleaned["caller_a"], cleaned["caller_b"])
    callers = sorted(cleaned["rotation_callers"], key=lambda u: (u.first_name, u.last_name, u.username))
    return services.plan_rotate(callers)


class BulkChangeView(CoordinatorRequiredMixin, View):
    """GET: choose a change. POST action=preview: show the plan. POST action=apply: apply it atomically."""

    template_name = "allocations/bulk_change.html"

    def selection_context(self, request):
        qs, filter_form = filter_contacts(contact_queryset(), request.GET)
        contacts = list(qs.order_by("full_name", "id")[:500])
        for contact in contacts:
            contact.caller_label = caller_label(contact)
        params = request.GET.copy()
        return {
            "selectable": contacts,
            "filter_form": filter_form,
            "callers": services.callers_queryset(),
            "statuses": ContactStatus.choices,
            "querystring": params.urlencode(),
        }

    def get(self, request):
        initial = {"kind": request.GET.get("kind", BulkKind.ASSIGN)}
        for field in ("from_caller", "to_caller", "caller_a", "caller_b"):
            if request.GET.get(field, "").isdigit():
                initial[field] = int(request.GET[field])
        if request.GET.get("cycle"):
            cycle = AllocationCycle.objects.filter(pk=request.GET["cycle"]).first()
            if cycle:
                initial.update(cycle=cycle, effective_date=cycle.start_date)
        form = BulkChangeForm(initial=initial)
        return render(request, self.template_name, {"form": form, **self.selection_context(request)})

    def post(self, request):
        form = BulkChangeForm(request.POST)
        selected_ids = request.POST.getlist("contacts")
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "selected_ids": selected_ids, **self.selection_context(request)},
            )
        cleaned = form.cleaned_data
        try:
            changes = build_plan(cleaned)
        except services.AllocationError as exc:
            form.add_error(None, str(exc))
            return render(request, self.template_name, {"form": form, **self.selection_context(request)})

        if request.POST.get("action") == "apply":
            try:
                operation = services.apply_plan(
                    changes,
                    kind=KIND_TO_CHANGE_TYPE[cleaned["kind"]],
                    effective_date=cleaned["effective_date"],
                    actor=request.user,
                    reason=cleaned["reason"],
                    cycle=cleaned.get("cycle"),
                    expected_fingerprint=request.POST.get("fingerprint", ""),
                )
            except services.AllocationError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"Applied: {operation.change_count} contact(s) reallocated.")
                return redirect("allocations:operation", pk=operation.pk)

        errors, warnings = services.check_plan(changes, cleaned["effective_date"])
        return render(
            request,
            "allocations/preview.html",
            {
                "form": form,
                "changes": changes,
                "counts": services.count_changes(changes),
                "errors": errors,
                "warnings": warnings,
                "fingerprint": services.plan_fingerprint(changes),
                "post_items": [
                    (k, v)
                    for k, values in request.POST.lists()
                    for v in values
                    if k not in {"csrfmiddlewaretoken", "action", "fingerprint"}
                ],
                "kind_label": dict(BulkKind.CHOICES)[cleaned["kind"]],
            },
        )


class CycleCreateView(CoordinatorRequiredMixin, FormView):
    template_name = "allocations/cycle_form.html"
    form_class = CycleForm

    def form_valid(self, form):
        try:
            cycle = services.create_cycle(actor=self.request.user, **form.cleaned_data)
        except services.AllocationError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(
            self.request,
            f"Cycle {cycle} created ({cycle.get_status_display()}). Now plan the rotation for it.",
        )
        return redirect(f"{reverse('allocations:change')}?kind={BulkKind.SWAP}&cycle={cycle.pk}")


class OperationDetailView(CoordinatorRequiredMixin, DetailView):
    model = AllocationOperation
    template_name = "allocations/operation_detail.html"
    context_object_name = "operation"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        moves = self.object.summary.get("moves", [])
        users = User.objects.in_bulk(
            {m["from"] for m in moves if m["from"]} | {m["to"] for m in moves if m["to"]}
        )
        contacts = Contact.objects.in_bulk([m["contact"] for m in moves])
        context["moves"] = [
            {"contact": contacts.get(m["contact"]), "from": users.get(m["from"]), "to": users.get(m["to"])}
            for m in moves
        ]
        context["tasks"] = self.object.summary.get("tasks", {})
        return context
