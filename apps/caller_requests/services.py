"""Raising and deciding caller requests. Approving "unable to attend" makes the Saint Inactive."""

from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.allocations.services import current_allocation
from apps.audit.services import log_event
from apps.contacts.models import ContactStatus, StatusReason
from apps.contacts.services import change_status

from .models import NEEDS_SAINT, CallerRequest, RequestKind, RequestStatus


class RequestError(Exception):
    pass


def my_saints(user):
    """Saints the user currently calls (the ones they may raise a request about)."""
    from apps.contacts.models import Contact

    return Contact.objects.filter(allocations__caller=user, allocations__effective_to__isnull=True).order_by(
        "full_name"
    )


def pending_count():
    return CallerRequest.objects.filter(status=RequestStatus.PENDING).count()


@transaction.atomic
def raise_request(user, kind, reason, contact=None):
    if kind not in RequestKind.values:
        raise RequestError("Choose what the request is about.")
    reason = (reason or "").strip()
    if not reason:
        raise RequestError("Please write the reason.")
    if kind in NEEDS_SAINT and contact is None:
        raise RequestError("Choose the Saint this request is about.")
    if contact is not None:
        allocation = current_allocation(contact)
        if (allocation is None or allocation.caller_id != user.pk) and not user.is_coordinator:
            raise RequestError("You can only raise requests about Saints you call.")
        if CallerRequest.objects.filter(
            kind=kind, contact=contact, raised_by=user, status=RequestStatus.PENDING
        ).exists():
            raise RequestError("You already have a waiting request about this Saint.")
    request = CallerRequest.objects.create(
        kind=kind,
        contact=contact,
        contact_name=contact.full_name if contact else "",
        reason=reason,
        raised_by=user,
    )
    log_event(user, "request.raise", f"Request: {request}", request, kind=kind)
    transaction.on_commit(lambda: notify_coordinators(request))
    return request


def notify_coordinators(request):
    """Email coordinators who have an address. The in-app badge is the main notification,
    so a failing mail server never blocks the request."""
    recipients = list(
        User.objects.filter(Q(groups__name=Role.COORDINATOR) | Q(is_superuser=True), is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .distinct()
    )
    if not recipients:
        return
    body = (
        f"{request.raised_by} raised a request: {request}\n\nReason: {request.reason}\n\n"
        "Open EMS Seva → Requests to approve or reject it."
    )
    send_mail(f"EMS Seva request: {request.get_kind_display()}", body, None, recipients, fail_silently=True)


@transaction.atomic
def decide(request, actor, *, approve, note=""):
    request = CallerRequest.objects.select_for_update().get(pk=request.pk)
    if not request.is_pending:
        raise RequestError("This request has already been decided.")
    if approve and request.kind == RequestKind.UNABLE_TO_ATTEND and request.contact:
        if request.contact.status != ContactStatus.INACTIVE:
            change_status(
                request.contact,
                ContactStatus.INACTIVE,
                actor,
                reason_category=StatusReason.CALLER_REQUEST,
                reason_text=f"{request.raised_by}: {request.reason}"[:1000],
            )
    if approve and request.kind == RequestKind.ON_LEAVE and not request.raised_by.is_on_leave:
        from apps.accounts.team import start_leave

        start_leave(request.raised_by, actor, reason=request.reason)
    request.status = RequestStatus.APPROVED if approve else RequestStatus.REJECTED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_note = (note or "").strip()[:1000]
    request.save()
    log_event(
        actor,
        "request.approve" if approve else "request.reject",
        f"{request.get_status_display()}: {request}",
        request,
        raised_by=request.raised_by_id,
    )
    return request
