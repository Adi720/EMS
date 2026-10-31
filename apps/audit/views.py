from datetime import date

from django.db.models import Q
from django.views.generic import ListView

from apps.accounts.models import User
from apps.core.permissions import CoordinatorRequiredMixin

from .models import AuditEvent
from .presentation import CATEGORIES, describe


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class AuditLogView(CoordinatorRequiredMixin, ListView):
    template_name = "audit/event_list.html"
    paginate_by = 50

    def get_queryset(self):
        params = self.request.GET
        qs = AuditEvent.objects.select_related("actor")
        category = params.get("type", "")
        if category in CATEGORIES:
            condition = Q()
            for prefix in CATEGORIES[category][1]:
                condition |= Q(action__startswith=prefix)
            qs = qs.filter(condition)
        action = params.get("action", "").strip()  # exact action (older links)
        if action:
            qs = qs.filter(action__startswith=action)
        actor = params.get("person", "")
        if actor == "system":
            qs = qs.filter(actor__isnull=True)
        elif actor.isdigit():
            qs = qs.filter(actor_id=int(actor))
        if date_from := _parse_date(params.get("from")):
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to := _parse_date(params.get("to")):
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for event in context["object_list"]:
            describe(event)
        params = self.request.GET.copy()
        params.pop("page", None)
        context.update(
            categories=[(key, label) for key, (label, _) in CATEGORIES.items()],
            people=User.objects.filter(pk__in=AuditEvent.objects.values("actor")).order_by(
                "first_name", "username"
            ),
            selected=self.request.GET,
            querystring=params.urlencode(),
            has_filters=any(self.request.GET.get(k) for k in ("type", "action", "person", "from", "to")),
        )
        return context
