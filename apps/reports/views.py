from datetime import date

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.models import User
from apps.allocations.services import rotation_due, unallocated_active_contacts
from apps.audit.services import log_event
from apps.calling import reminders
from apps.calling.models import CallTask, EmsSession, Outcome, TaskStatus, congregation_label
from apps.calling.services import next_sunday
from apps.calling.views import default_session
from apps.contacts.models import Contact, ContactStatus
from apps.core.exports import export_response
from apps.core.permissions import CoordinatorRequiredMixin

from . import metrics
from .overview import build_overview


def parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class CoordinatorDashboardView(CoordinatorRequiredMixin, TemplateView):
    template_name = "reports/coordinator_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        sessions = list(EmsSession.objects.all())
        session = None
        if params.get("session", "").isdigit():
            session = next((s for s in sessions if s.pk == int(params["session"])), None)
        session = session or default_session(sessions)

        caller = params.get("caller", "")
        tasks = CallTask.objects.all()
        if caller.isdigit():
            tasks = tasks.filter(caller_id=int(caller))

        date_from, date_to = parse_date(params.get("from")), parse_date(params.get("to"))
        history_tasks = tasks
        if date_from:
            history_tasks = history_tasks.filter(session__session_date__gte=date_from)
        if date_to:
            history_tasks = history_tasks.filter(session__session_date__lte=date_to)

        today = timezone.localdate()
        sunday = next_sunday(today)
        week_session = next((s for s in sessions if s.session_date == sunday and s.venue == ""), None)
        if week_session and week_session.is_open:
            message = reminders.group_message(
                week_session, reminders.my_calls_url(self.request.build_absolute_uri("/"))
            )
            context.update(whatsapp_message=message, whatsapp_url=reminders.whatsapp_share_url(message))
        context.update(
            overview=build_overview(self.request.user, week_session),
            week_label=congregation_label(sunday),
            week_session=week_session,
            older_open=[s for s in sessions if s.is_open and s.session_date < sunday],
            sessions=sessions,
            session=session,
            callers=User.objects.filter(call_tasks__isnull=False)
            .distinct()
            .order_by("first_name", "username"),
            selected_caller=caller,
            date_from=params.get("from", ""),
            date_to=params.get("to", ""),
            history=metrics.by_session(history_tasks)[:26],
            unallocated_count=unallocated_active_contacts().count(),
            review_due=Contact.objects.filter(
                status=ContactStatus.TEMP_UNAVAILABLE, review_date__lte=today
            ).order_by("review_date"),
            rotation_due=rotation_due(),
        )
        if session:
            session_tasks = tasks.filter(session=session)
            context.update(
                summary=metrics.summarize(session_tasks),
                by_caller=metrics.by_caller(session_tasks),
                withdrawn_count=session_tasks.filter(status=TaskStatus.WITHDRAWN).count(),
            )
        return context


def month_bounds(value):
    today = timezone.localdate()
    try:
        year, month = (int(p) for p in value.split("-"))
        start = date(year, month, 1)
    except (ValueError, AttributeError):
        start = today.replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


def monthly_data(month_param):
    start, end = month_bounds(month_param)
    tasks = CallTask.objects.filter(session__session_date__gte=start, session__session_date__lt=end)
    return {
        "month_start": start,
        "month_value": f"{start:%Y-%m}",
        "summary": metrics.summarize(tasks),
        "by_session": sorted(metrics.by_session(tasks), key=lambda r: r["session_obj"].session_date),
        "by_caller": metrics.by_caller(tasks),
        "unique_yes": metrics.unique_contacts(tasks, Outcome.YES),
        "session_count": EmsSession.objects.filter(session_date__gte=start, session_date__lt=end).count(),
    }


class MonthlyReportView(CoordinatorRequiredMixin, TemplateView):
    template_name = "reports/monthly.html"

    def get_context_data(self, **kwargs):
        return super().get_context_data(**monthly_data(self.request.GET.get("month", "")), **kwargs)


METRIC_HEADERS = [metrics.METRIC_LABELS[f] for f in metrics.METRIC_FIELDS] + ["Completion %", "Connection %"]


def metric_cells(row):
    return [row[f] for f in metrics.METRIC_FIELDS] + [row["completion_rate"], row["connection_rate"]]


def export_format(request):
    return "xlsx" if request.GET.get("format") == "xlsx" else "csv"


class SessionExportView(CoordinatorRequiredMixin, View):
    """kind=summary: per-caller metrics. kind=tasks: one row per task (no phone numbers)."""

    def get(self, request, pk):
        session = get_object_or_404(EmsSession, pk=pk)
        kind = request.GET.get("kind", "summary")
        fmt = export_format(request)
        tasks = CallTask.objects.filter(session=session)
        if kind == "summary":
            headers = ["Caller", *METRIC_HEADERS]
            rows = [[str(r["caller_obj"]), *metric_cells(r)] for r in metrics.by_caller(tasks)]
            rows.append(["TOTAL", *metric_cells(metrics.summarize(tasks))])
        elif kind == "tasks":
            include_dnc = request.GET.get("include_dnc") == "1"
            qs = tasks.select_related("contact", "caller").order_by(
                "caller__first_name", "contact__full_name"
            )
            if not include_dnc:
                qs = qs.exclude(contact__status=ContactStatus.DO_NOT_CALL)
            headers = [
                "Contact",
                "Area",
                "Caller",
                "Task status",
                "Latest outcome",
                "Report category",
                "Attempts",
                "Last attempt",
                "Call back at",
            ]
            rows = [
                [
                    t.contact.full_name,
                    t.contact.area,
                    str(t.caller),
                    t.get_status_display(),
                    t.get_latest_outcome_display(),
                    t.report_category.label if t.status == TaskStatus.OPEN else "",
                    t.attempt_count,
                    t.last_attempt_at,
                    t.callback_at,
                ]
                for t in qs
            ]
        else:
            raise Http404
        log_event(
            request.user,
            f"export.session_{kind}",
            f"Exported {session} {kind} ({fmt})",
            session,
            rows=len(rows),
        )
        return export_response(fmt, f"ems-{session.session_date:%Y%m%d}-{kind}", headers, rows, kind.title())


class MonthlyExportView(CoordinatorRequiredMixin, View):
    def get(self, request):
        data = monthly_data(request.GET.get("month", ""))
        fmt = export_format(request)
        headers = ["Session", *METRIC_HEADERS]
        rows = [[str(r["session_obj"]), *metric_cells(r)] for r in data["by_session"]]
        rows.append(["TOTAL", *metric_cells(data["summary"])])
        log_event(
            request.user,
            "export.monthly",
            f"Exported monthly report {data['month_value']} ({fmt})",
            rows=len(rows),
        )
        return export_response(fmt, f"ems-monthly-{data['month_value']}", headers, rows, "Monthly")
