from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, ListView

from apps.core.permissions import CallerRequiredMixin, CoordinatorRequiredMixin

from . import services
from .forms import DecisionForm, RaiseRequestForm
from .models import CallerRequest, RequestStatus


class MyRequestsView(CallerRequiredMixin, FormView):
    """A caller's own requests, with the form to raise a new one."""

    template_name = "caller_requests/my_requests.html"
    form_class = RaiseRequestForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["saints"] = services.my_saints(self.request.user)
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        contact = self.request.GET.get("contact", "")
        if contact.isdigit():
            initial["contact"] = int(contact)
            initial["kind"] = "unable_to_attend"
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["my_requests"] = CallerRequest.objects.filter(raised_by=self.request.user)[:50]
        return context

    def form_valid(self, form):
        try:
            services.raise_request(
                self.request.user,
                form.cleaned_data["kind"],
                form.cleaned_data["reason"],
                form.cleaned_data["contact"],
            )
        except services.RequestError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Request sent. Your coordinator will look at it.")
        return redirect("caller_requests:mine")


class ManageRequestsView(CoordinatorRequiredMixin, ListView):
    template_name = "caller_requests/manage.html"
    paginate_by = 30

    def get_queryset(self):
        qs = CallerRequest.objects.select_related("raised_by", "contact", "decided_by")
        self.show = self.request.GET.get("show", "pending")
        if self.show == "pending":
            qs = qs.filter(status=RequestStatus.PENDING)
        return qs.order_by("-created_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(show=self.show, decision_form=DecisionForm())
        return context


class DecideRequestView(CoordinatorRequiredMixin, View):
    def post(self, request, pk, decision):
        if decision not in {"approve", "reject"}:
            raise Http404
        item = get_object_or_404(CallerRequest, pk=pk)
        form = DecisionForm(request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        try:
            services.decide(item, request.user, approve=decision == "approve", note=note)
        except services.RequestError as exc:
            messages.error(request, str(exc))
        else:
            item.refresh_from_db()
            messages.success(request, f"{item.get_status_display()}: {item}.")
        return redirect("caller_requests:manage")
