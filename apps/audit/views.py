from django.views.generic import ListView

from apps.core.permissions import CoordinatorRequiredMixin

from .models import AuditEvent


class AuditLogView(CoordinatorRequiredMixin, ListView):
    template_name = "audit/event_list.html"
    paginate_by = 50

    def get_queryset(self):
        qs = AuditEvent.objects.select_related("actor")
        action = self.request.GET.get("action", "").strip()
        if action:
            qs = qs.filter(action__startswith=action)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["actions"] = AuditEvent.objects.order_by().values_list("action", flat=True).distinct()
        context["selected_action"] = self.request.GET.get("action", "")
        return context
