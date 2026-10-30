from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from apps.accounts.models import User
from apps.core.permissions import CallerRequiredMixin, CoordinatorRequiredMixin, RoleRequiredMixin
from apps.reports import metrics

from . import services
from .forms import AttemptForm, QuickAttemptForm, SessionForm
from .models import OUTCOME_HELP, CallTask, EmsSession, Outcome, ReportCategory, SessionStatus, TaskStatus


def visible_tasks(user):
    """Tasks a user may see: coordinators all; callers only their own, not withdrawn ones."""
    if user.is_coordinator:
        return CallTask.objects.all()
    if user.is_caller:
        return CallTask.objects.filter(caller=user, status=TaskStatus.OPEN)
    return CallTask.objects.none()


def default_session(sessions):
    """Nearest open session on/after today, else the latest open, else the latest."""
    today = timezone.localdate()
    open_sessions = [s for s in sessions if s.status == SessionStatus.OPEN]
    upcoming = sorted((s for s in open_sessions if s.session_date >= today), key=lambda s: s.session_date)
    if upcoming:
        return upcoming[0]
    if open_sessions:
        return max(open_sessions, key=lambda s: s.session_date)
    return max(sessions, key=lambda s: s.session_date) if sessions else None


TASK_FILTERS = {
    "pending": Q(attempt_count=0),
    "completed": Q(attempt_count__gt=0),
    "not_connected": Q(latest_outcome=Outcome.NOT_CONNECTED),
    "callback": Q(callback_at__isnull=False) & ~Q(latest_outcome__in=[Outcome.YES, Outcome.NOT_POSSIBLE]),
}


class CallerDashboardView(CallerRequiredMixin, TemplateView):
    template_name = "calling/caller_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        own = CallTask.objects.filter(caller=user, status=TaskStatus.OPEN)
        sessions = list(EmsSession.objects.filter(tasks__in=own).distinct().order_by("-session_date"))
        session = None
        requested = self.request.GET.get("session", "")
        if requested:
            session = next((s for s in sessions if str(s.pk) == requested), None)
            if session is None:
                raise Http404
        session = session or default_session(sessions)
        context.update(
            sessions=sessions, session=session, outcomes=Outcome.choices, outcome_help=OUTCOME_HELP
        )
        if session is None:
            return context
        session_tasks = own.filter(session=session)
        show = self.request.GET.get("show", "")
        tasks = session_tasks.filter(TASK_FILTERS[show]) if show in TASK_FILTERS else session_tasks
        tasks = tasks.select_related("contact").order_by(
            "attempt_count" if show == "" else "contact__full_name", "contact__full_name"
        )
        context.update(tasks=tasks, show=show, summary=metrics.summarize(session_tasks))
        return context


class TaskDetailView(RoleRequiredMixin, FormView):
    """A caller's own task (404 for anyone else's) or any task for coordinators."""

    template_name = "calling/task_detail.html"
    form_class = AttemptForm

    def has_role(self, user):
        return user.is_caller or user.is_coordinator

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            self.task = get_object_or_404(
                visible_tasks(request.user).select_related("contact", "session", "caller"), pk=kwargs["pk"]
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        task = self.task
        context = super().get_context_data(**kwargs)
        context.update(
            task=task,
            contact=task.contact,
            attempts=task.attempts.select_related("recorded_by"),
            can_record=self.can_record(),
            outcome_help=OUTCOME_HELP,
            # Earlier sessions for the same contact, limited to what this user may see.
            previous=visible_tasks(self.request.user)
            .filter(contact=task.contact, attempt_count__gt=0)
            .exclude(pk=task.pk)
            .select_related("session")
            .order_by("-session__session_date")[:5],
        )
        return context

    def can_record(self):
        task = self.task
        return (
            services.can_record(self.request.user, task)
            and task.session.status == SessionStatus.OPEN
            and task.status == TaskStatus.OPEN
            and not task.contact.is_do_not_call
        )

    def form_valid(self, form):
        try:
            attempt = services.record_attempt(
                self.task,
                outcome=form.cleaned_data["outcome"],
                notes=form.cleaned_data["notes"],
                callback_at=form.cleaned_data["callback_at"],
                actor=self.request.user,
            )
        except services.CallingError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, f"Saved: {self.task.contact} — {attempt.get_outcome_display()}.")
        return redirect(next_url(self.request, self.task))


def next_url(request, task):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    if request.user.is_caller and task.caller_id == request.user.pk:
        return f"{reverse('core:caller_dashboard')}?session={task.session_id}"
    return reverse("calling:session_detail", args=[task.session_id])


class QuickAttemptView(RoleRequiredMixin, View):
    """One-tap outcome from the call list."""

    def has_role(self, user):
        return user.is_caller or user.is_coordinator

    def post(self, request, pk):
        task = get_object_or_404(visible_tasks(request.user).select_related("contact"), pk=pk)
        form = QuickAttemptForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose one of the four outcomes.")
        else:
            try:
                attempt = services.record_attempt(
                    task, outcome=form.cleaned_data["outcome"], actor=request.user
                )
            except services.CallingError as exc:
                messages.error(request, str(exc))
            except PermissionDenied:
                raise
            else:
                messages.success(request, f"Saved: {task.contact} — {attempt.get_outcome_display()}.")
        return redirect(f"{next_url(request, task)}#task-{task.pk}")


# --- Coordinator: sessions ---------------------------------------------------


class SessionListView(CoordinatorRequiredMixin, ListView):
    template_name = "calling/session_list.html"
    paginate_by = 20

    def get_queryset(self):
        return EmsSession.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = {
            r["session"]: r
            for r in metrics.grouped(CallTask.objects.filter(session__in=context["object_list"]), "session")
        }
        for session in context["object_list"]:
            session.summary = rows.get(session.pk)
        return context


class SessionCreateView(CoordinatorRequiredMixin, FormView):
    template_name = "calling/session_form.html"
    form_class = SessionForm

    def form_valid(self, form):
        try:
            session = services.create_session(actor=self.request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"{session} created. Click Start calling when ready.")
        return redirect("calling:session_detail", pk=session.pk)


class SessionUpdateView(CoordinatorRequiredMixin, FormView):
    template_name = "calling/session_form.html"
    form_class = SessionForm

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(EmsSession, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = EmsSession.objects.get(pk=self.session.pk)
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(session=self.session, **kwargs)

    def form_valid(self, form):
        try:
            services.update_session(self.session, form.cleaned_data, self.request.user)
        except (services.CallingError, ValidationError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Congregation saved.")
        return redirect("calling:session_detail", pk=self.session.pk)


class SessionDetailView(CoordinatorRequiredMixin, TemplateView):
    """Weekly report for one session: totals, per caller, per area, and the task list."""

    template_name = "calling/session_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = get_object_or_404(EmsSession, pk=kwargs["pk"])
        all_tasks = CallTask.objects.filter(session=session)
        tasks = all_tasks.select_related("contact", "caller").order_by(
            "caller__first_name", "contact__full_name"
        )
        caller = self.request.GET.get("caller", "")
        if caller.isdigit():
            tasks = tasks.filter(caller_id=int(caller))
        show = self.request.GET.get("show", "")
        if show in TASK_FILTERS:
            tasks = tasks.filter(TASK_FILTERS[show], status=TaskStatus.OPEN)
        elif show == "withdrawn":
            tasks = tasks.filter(status=TaskStatus.WITHDRAWN)
        elif show in ReportCategory.values:
            tasks = tasks.filter(status=TaskStatus.OPEN).filter(
                Q(attempt_count=0) | Q(latest_outcome=Outcome.NOT_CONNECTED)
                if show == ReportCategory.UNKNOWN
                else Q(latest_outcome=show)
            )
        context.update(
            session=session,
            summary=metrics.summarize(all_tasks),
            by_caller=metrics.by_caller(all_tasks),
            by_area=metrics.by_area(all_tasks),
            tasks=tasks,
            withdrawn_count=all_tasks.filter(status=TaskStatus.WITHDRAWN).count(),
            callers=User.objects.filter(call_tasks__session=session).distinct(),
            selected_caller=caller,
            show=show,
        )
        return context


class SessionActionView(CoordinatorRequiredMixin, View):
    def post(self, request, pk, action):
        session = get_object_or_404(EmsSession, pk=pk)
        try:
            if action == "open":
                _, totals = services.open_session(session, request.user)
                messages.success(request, f"Calling is open for {session}. Call lists: {describe(totals)}.")
            elif action == "close":
                services.close_session(session, request.user)
                messages.success(request, f"Calling closed for {session}. Counts are now final.")
            elif action == "refresh":
                totals = services.refresh_session(session, request.user)
                messages.success(request, f"Call lists refreshed: {describe(totals)}.")
            else:
                raise Http404
        except services.CallingError as exc:
            messages.error(request, str(exc))
        return redirect("calling:session_detail", pk=pk)


class StartWeeklyCallingView(CoordinatorRequiredMixin, View):
    """One click from the dashboard: create + open the coming Sunday's congregation."""

    def post(self, request):
        try:
            session, totals, closed = services.start_weekly_calling(request.user)
        except services.CallingError as exc:
            messages.error(request, str(exc))
            return redirect("core:coordinator_dashboard")
        text = f"Calling is open for {session}."
        if totals:
            text += f" Call lists: {describe(totals)}."
        if closed:
            text += " Closed calling for " + ", ".join(str(s) for s in closed) + "."
        messages.success(request, text)
        return redirect(f"{reverse('core:coordinator_dashboard')}?session={session.pk}")


def describe(totals):
    labels = {
        "created": "contacts added",
        "moved": "moved to a new caller",
        "reinstated": "reinstated",
        "withdrawn": "withdrawn",
    }
    return ", ".join(f"{n} {labels.get(k, k)}" for k, n in sorted(totals.items())) or "no changes"
