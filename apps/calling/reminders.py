"""Weekly calling reminders: a WhatsApp share link and Saturday emails to callers.

The email reminder is run once a day by the host's scheduler (``manage.py weekly_reminders``);
it acts only on the reminder weekday (Saturday by default). No reminder service, queue or
paid messaging API is used.
"""

from urllib.parse import quote

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.audit.services import log_event

from .models import CallTask, EmsSession, SessionStatus, TaskStatus
from .services import next_sunday, start_weekly_calling


def my_calls_url(base_url=None):
    return (base_url or settings.SITE_URL).rstrip("/") + reverse("core:caller_dashboard")


def group_message(session, link):
    return (
        f"🙏 Calling is open for {session}.\n"
        f"Please call your contacts today and record each result: {link}\n"
        "After each call tap Yes, Not Possible, Will Try or Call Not Connected."
    )


def whatsapp_share_url(text):
    """wa.me link that opens WhatsApp with the message ready to send to a chosen group."""
    return "https://wa.me/?text=" + quote(text)


def caller_counts(session):
    """[(user, total, pending)] for callers with calls in the session."""
    rows = (
        CallTask.objects.filter(session=session, status=TaskStatus.OPEN)
        .values("caller")
        .annotate(total=Count("id"), pending=Count("id", filter=Q(attempt_count=0)))
    )
    users = User.objects.in_bulk([r["caller"] for r in rows])
    return [(users[r["caller"]], r["total"], r["pending"]) for r in rows]


def _already_sent(session, user):
    return AuditEvent.objects.filter(
        action="reminder.email",
        object_type=session._meta.label_lower,
        object_id=str(session.pk),
        details__caller=user.pk,
    ).exists()


def send_weekly_reminders(today=None, *, auto_start=None):
    """Start this week's calling (if enabled) and email each caller once per congregation.

    Returns a dict describing what happened. Raises CallingError if the coming
    Sunday's calling was already closed.
    """
    auto_start = settings.REMINDER_AUTO_START if auto_start is None else auto_start
    result = {"session": None, "started": False, "sent": [], "no_email": [], "already": [], "failed": []}
    if auto_start:
        session, totals, _ = start_weekly_calling(None, today=today)
        result["started"] = bool(totals)
    else:
        session = EmsSession.objects.filter(
            session_date=next_sunday(today), venue="", status=SessionStatus.OPEN
        ).first()
        if session is None:
            return result
    result["session"] = session

    link = my_calls_url()
    for user, total, pending in sorted(caller_counts(session), key=lambda row: str(row[0])):
        if not user.is_active:
            continue
        if not user.email:
            result["no_email"].append(user)
            continue
        if _already_sent(session, user):
            result["already"].append(user)
            continue
        body = (
            f"Dear {user.first_name or user},\n\n"
            f"Calling is open for {session}. You have {total} contact(s) to call this week"
            f" ({pending} not called yet).\n\n"
            f"Open your list: {link}\n\n"
            "After each call, tap Yes, Not Possible, Will Try or Call Not Connected.\n\n"
            "Thank you for your seva."
        )
        try:
            send_mail(f"EMS calling reminder: {session}", body, None, [user.email])
        except Exception as exc:  # report and continue with the other callers
            result["failed"].append((user, str(exc)))
            continue
        log_event(
            None,
            "reminder.email",
            f"Reminder emailed to {user} for {session}",
            session,
            caller=user.pk,
            contacts=total,
            pending=pending,
        )
        result["sent"].append(user)
    return result
