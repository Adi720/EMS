from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.allocations.models import Allocation
from apps.calling.models import CallAttempt, CallTask, EmsSession, SessionStatus, TaskStatus
from apps.calling.services import next_sunday
from apps.core.permissions import CoordinatorRequiredMixin

from . import performance, team
from .models import User
from .roles import Role
from .team_forms import CallerCreateForm, CallerPasswordForm, CallerProfileForm


def current_session():
    return EmsSession.objects.filter(status=SessionStatus.OPEN).order_by("session_date").first() or (
        EmsSession.objects.filter(session_date=next_sunday(), venue="").first()
    )


class TeamListView(CoordinatorRequiredMixin, TemplateView):
    template_name = "accounts/team_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = current_session()
        members = (
            team.team_members()
            .annotate(
                saints=Count("allocations", filter=Q(allocations__effective_to__isnull=True), distinct=True)
            )
            .order_by("-is_active", "first_name", "last_name", "username")
        )
        last_calls = dict(
            CallAttempt.objects.filter(recorded_by__in=members.values("pk"))
            .values_list("recorded_by")
            .annotate(last=Max("attempted_at"))
        )
        pending = {}
        if session:
            pending = dict(
                CallTask.objects.filter(session=session, status=TaskStatus.OPEN, attempt_count=0)
                .values_list("caller")
                .annotate(n=Count("id"))
            )
        perf = performance.performance(callers=members.values("pk"))
        rows = []
        for member in members:
            row = perf.get(member.pk)
            rows.append(
                {
                    "user": member,
                    "status": performance.team_status(member, row),
                    "rate": row["completion_rate"] if row else None,
                    "saints": member.saints,
                    "pending": pending.get(member.pk, 0) if session else None,
                    "last_call": last_calls.get(member.pk),
                    "manageable": team.can_manage(self.request.user, member),
                    "is_coordinator": member.groups.filter(name=Role.COORDINATOR).exists()
                    or member.is_superuser,
                }
            )
        context.update(
            rows=rows,
            session=session,
            active_count=sum(1 for r in rows if r["user"].is_active),
            inactive_count=sum(1 for r in rows if not r["user"].is_active),
        )
        return context


class TeamCreateView(CoordinatorRequiredMixin, FormView):
    template_name = "accounts/team_form.html"
    form_class = CallerCreateForm

    def form_valid(self, form):
        data = form.cleaned_data
        user = team.create_caller(
            username=data["username"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            password=data["password1"],
            actor=self.request.user,
        )
        messages.success(
            self.request,
            f"Caller account created for {user.get_full_name() or user.username}. "
            "Share the username and password with them privately.",
        )
        return redirect("team:detail", pk=user.pk)


class MemberMixin(CoordinatorRequiredMixin):
    """Loads a team member; ``manage = True`` views also require the right to change them."""

    manage = False

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if not request.user.is_coordinator:
                raise PermissionDenied
            self.member = get_object_or_404(team.team_members(), pk=kwargs["pk"])
            if self.manage and not team.can_manage(request.user, self.member):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class TeamDetailView(MemberMixin, TemplateView):
    template_name = "accounts/team_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        member = self.member
        session = current_session()
        saints = (
            Allocation.objects.filter(caller=member, effective_to__isnull=True)
            .select_related("contact")
            .order_by("contact__full_name")
        )
        week = None
        if session:
            tasks = CallTask.objects.filter(session=session, caller=member, status=TaskStatus.OPEN)
            week = {
                "session": session,
                "assigned": tasks.count(),
                "done": tasks.filter(attempt_count__gt=0).count(),
            }
        context.update(
            member=member,
            saints=saints,
            week=week,
            attempts=CallAttempt.objects.filter(recorded_by=member)
            .select_related("task__contact", "task__session")
            .order_by("-attempted_at")[:15],
            manageable=team.can_manage(self.request.user, member),
            perf=performance.performance(callers=[member]).get(member.pk),
            moved_away=team.saints_moved_during_leave(member),
        )
        context["status"] = performance.team_status(member, context["perf"])
        return context


class TeamEditView(MemberMixin, FormView):
    manage = True
    template_name = "accounts/team_form.html"
    form_class = CallerProfileForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = User.objects.get(pk=self.member.pk)
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(member=self.member, **kwargs)

    def form_valid(self, form):
        changed = team.update_caller(self.member, form.cleaned_data, self.request.user)
        messages.success(self.request, "Details saved." if changed else "No changes to save.")
        return redirect("team:detail", pk=self.member.pk)


class TeamPasswordView(MemberMixin, FormView):
    manage = True
    template_name = "accounts/team_password.html"
    form_class = CallerPasswordForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.member
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(member=self.member, **kwargs)

    def form_valid(self, form):
        team.reset_password(self.member, form.cleaned_data["new_password1"], self.request.user)
        messages.success(self.request, f"Password reset for {self.member}. Share it with them privately.")
        return redirect("team:detail", pk=self.member.pk)


class TeamActiveView(MemberMixin, View):
    manage = True

    def post(self, request, pk, action):
        try:
            if action == "deactivate":
                unassigned = team.deactivate_caller(self.member, request.user)
                text = f"{self.member} is deactivated and can no longer log in."
                if unassigned:
                    text += (
                        f" {unassigned} Saint(s) now have no caller — assign them on the Assignments page."
                    )
                messages.success(request, text)
            elif action == "activate":
                team.activate_caller(self.member, request.user)
                messages.success(
                    request, f"{self.member} can log in again. Assign Saints to them when ready."
                )
            else:
                raise PermissionDenied
        except team.TeamError as exc:
            messages.error(request, str(exc))
        return redirect("team:detail", pk=pk)


class TeamLeaveView(MemberMixin, View):
    """Start leave, then go straight to moving the caller's Saints to someone else."""

    def post(self, request, pk):
        try:
            team.start_leave(self.member, request.user, reason=request.POST.get("reason", ""))
        except team.TeamError as exc:
            messages.error(request, str(exc))
            return redirect("team:detail", pk=pk)
        saints = Allocation.objects.filter(caller=self.member, effective_to__isnull=True).count()
        if not saints:
            messages.success(request, f"{self.member} is On Leave.")
            return redirect("team:detail", pk=pk)
        messages.warning(
            request,
            f"{self.member} is On Leave. Please give their {saints} Saint(s) to another caller.",
        )
        return redirect(f"{reverse('allocations:change')}?kind=move_all&from_caller={pk}")


class TeamReturnView(MemberMixin, TemplateView):
    """Back from leave: Saints stay with their new callers unless ticked to move back."""

    template_name = "accounts/team_return.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(member=self.member, moved_away=team.saints_moved_during_leave(self.member))
        return context

    def post(self, request, pk):
        ids = [int(v) for v in request.POST.getlist("move_back") if v.isdigit()]
        try:
            moved = team.end_leave(self.member, request.user, move_back=ids)
        except team.TeamError as exc:
            messages.error(request, str(exc))
        else:
            text = f"{self.member} is back from leave."
            if moved:
                text += f" {moved} Saint(s) moved back to them."
            messages.success(request, text)
        return redirect("team:detail", pk=pk)


class PerformanceView(CoordinatorRequiredMixin, TemplateView):
    """Callers sorted by calls attempted ÷ assigned over 1, 2 or 3 months."""

    template_name = "accounts/performance.html"
    PERIODS = (1, 2, 3)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        months = self.request.GET.get("months", "")
        months = int(months) if months.isdigit() and int(months) in self.PERIODS else 1
        members = team.team_members().filter(is_active=True)
        perf = performance.performance(months, callers=members.values("pk"))
        rows = []
        for member in members:
            row = perf.get(member.pk)
            if row is None:
                continue
            rows.append({"user": member, "status": performance.team_status(member, row), **row})
        rows.sort(key=lambda r: (-(r["completion_rate"] or 0), -r["assigned"], str(r["user"]).lower()))
        start, today = performance.window(months)
        context.update(
            rows=rows,
            months=months,
            periods=self.PERIODS,
            start=start,
            threshold=settings.PARTIALLY_ACTIVE_BELOW,
            without_calls=[m for m in members if m.pk not in perf],
        )
        return context
