"""Caller account management by coordinators.

Rules (enforced here and in the views):
* coordinators create and manage accounts that are Callers only;
* they can never grant Coordinator or admin rights, nor change coordinators, staff or admins;
* deactivating keeps all history; the caller's Saints become unassigned (their unattempted
  calls in open congregations are withdrawn, attempted calls stay credited to them).
"""

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_event

from .models import User
from .roles import Role


class TeamError(Exception):
    pass


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
