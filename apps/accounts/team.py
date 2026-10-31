"""Caller account management by coordinators.

Rules (enforced here and in the views):
* coordinators create and manage accounts that are Callers only;
* they can never grant Coordinator or admin rights, nor change coordinators, staff or admins;
* deactivating keeps all history; the caller's Saints become unassigned (their unattempted
  calls in open congregations are withdrawn, attempted calls stay credited to them).
"""

import re
import secrets
import unicodedata

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_event

from .models import User
from .roles import Role


class TeamError(Exception):
    pass


# Easy to read aloud or type from a printout: no 0/O, 1/l/I.
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_LOWER = "abcdefghijkmnpqrstuvwxyz"
_DIGITS = "23456789"


def generate_password(length=None):
    """Random password with at least one upper-case letter, lower-case letter and digit."""
    length = max(length or settings.GENERATED_PASSWORD_LENGTH, 8)
    alphabet = _UPPER + _LOWER + _DIGITS
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c in _UPPER for c in password)
            and any(c in _LOWER for c in password)
            and any(c in _DIGITS for c in password)
        ):
            return password


def split_name(full_name):
    """'Shalini ji' -> ('Shalini', 'ji'); 'Kamlesh' -> ('Kamlesh', '')."""
    parts = full_name.split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def suggest_username(full_name, taken):
    """'Shalini ji' -> 'shalini.ji' (unique against ``taken``, which is updated)."""
    text = unicodedata.normalize("NFKC", full_name).strip().lower()
    base = re.sub(r"[^\w.@+-]+", ".", text).strip(".") or "caller"
    base = re.sub(r"\.{2,}", ".", base)[:140]
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate = f"{base}{n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


def taken_usernames():
    return {u.lower() for u in User.objects.values_list("username", flat=True)}


def team_members():
    """Everyone with the Caller role, active or not."""
    return User.objects.filter(groups__name=Role.CALLER).distinct()


def can_manage(actor, target):
    """Whether ``actor`` may edit ``target`` through the Team screens."""
    if not actor.is_coordinator or target.pk == actor.pk:
        return False
    if target.is_superuser or target.is_staff:
        return False
    return not target.groups.filter(name=Role.COORDINATOR).exists()


@transaction.atomic
def create_caller(*, username, first_name, last_name, email, password, actor):
    user = User(username=username, first_name=first_name, last_name=last_name, email=email)
    user.set_password(password)
    user.full_clean(exclude=["password"])
    user.save()
    user.groups.add(Group.objects.get(name=Role.CALLER))
    log_event(actor, "team.create", f"Created caller account {user} ({user.username})", user)
    return user


@transaction.atomic
def update_caller(target, data, actor):
    changed = [
        field for field in ("first_name", "last_name", "email") if getattr(target, field) != data[field]
    ]
    for field in changed:
        setattr(target, field, data[field])
    if changed:
        target.save(update_fields=changed)
        log_event(actor, "team.update", f"Edited caller {target}", target, fields=changed)
    return changed


@transaction.atomic
def reset_password(target, password, actor):
    target.set_password(password)  # also signs the caller out of existing sessions
    target.save(update_fields=["password"])
    log_event(actor, "team.password_reset", f"Reset the password of {target}", target)


@transaction.atomic
def deactivate_caller(target, actor):
    from apps.allocations.models import ChangeType
    from apps.allocations.services import PlannedChange, apply_plan, open_allocations

    target = User.objects.select_for_update().get(pk=target.pk)
    if not target.is_active:
        raise TeamError(f"{target} is already deactivated.")
    allocations = list(open_allocations().filter(caller=target).select_related("contact"))
    if allocations:
        effective = max([timezone.localdate(), *(a.effective_from for a in allocations)])
        apply_plan(
            [PlannedChange(a.contact, target, None) for a in allocations],
            kind=ChangeType.CALLER_DEACTIVATED,
            effective_date=effective,
            actor=actor,
            reason=f"Caller {target} deactivated",
        )
    target.is_active = False
    target.save(update_fields=["is_active"])
    log_event(
        actor,
        "team.deactivate",
        f"Deactivated {target}; {len(allocations)} Saint(s) now without a caller",
        target,
        saints_unassigned=len(allocations),
    )
    return len(allocations)


@transaction.atomic
def activate_caller(target, actor):
    if target.is_active:
        raise TeamError(f"{target} is already active.")
    target.is_active = True
    target.save(update_fields=["is_active"])
    log_event(actor, "team.activate", f"Reactivated {target}", target)


# --- On Leave ------------------------------------------------------------------


@transaction.atomic
def start_leave(target, actor, *, reason=""):
    """Mark a caller On Leave. Their Saints stay with them until a coordinator moves them;
    the dashboard keeps reminding until that is done."""
    target = User.objects.select_for_update().get(pk=target.pk)
    if not target.is_active:
        raise TeamError(f"{target} is deactivated.")
    if target.is_on_leave:
        raise TeamError(f"{target} is already On Leave.")
    target.on_leave_since = timezone.localdate()
    target.save(update_fields=["on_leave_since"])
    log_event(actor, "team.leave_start", f"{target} is On Leave", target, reason=reason[:300])
    return target


def saints_moved_during_leave(target):
    """Saints that were with ``target`` when the leave began and now have another caller."""
    from apps.allocations.services import open_allocations

    if not target.on_leave_since:
        return []
    from apps.allocations.models import Allocation

    left = Allocation.objects.filter(
        caller=target, effective_to__isnull=False, effective_to__gte=target.on_leave_since
    ).values("contact")
    return list(
        open_allocations()
        .filter(contact__in=left)
        .exclude(caller=target)
        .select_related("contact", "caller")
        .order_by("contact__full_name")
    )


@transaction.atomic
def end_leave(target, actor, *, move_back=()):
    """Back from leave. By default the Saints stay with their new callers; the coordinator
    may tick some (``move_back``: allocations from saints_moved_during_leave) to return."""
    from apps.allocations.models import ChangeType
    from apps.allocations.services import PlannedChange, apply_plan

    target = User.objects.select_for_update().get(pk=target.pk)
    if not target.is_on_leave:
        raise TeamError(f"{target} is not On Leave.")
    allowed = {a.pk: a for a in saints_moved_during_leave(target)}
    chosen = [allowed[pk] for pk in move_back if pk in allowed]
    if chosen:
        apply_plan(
            [PlannedChange(a.contact, a.caller, target) for a in chosen],
            kind=ChangeType.ASSIGN,
            effective_date=max([timezone.localdate(), *(a.effective_from for a in chosen)]),
            actor=actor,
            reason=f"{target} back from leave",
        )
    target.on_leave_since = None
    target.save(update_fields=["on_leave_since"])
    log_event(actor, "team.leave_end", f"{target} is back from leave", target, moved_back=len(chosen))
    return len(chosen)
