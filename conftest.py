"""Shared pytest fixtures. All users and contacts are synthetic."""

import itertools
from datetime import date

import pytest
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import Role

PASSWORD = "Synthetic-pass-2026"
ALLOCATION_START = date(2026, 1, 1)
SESSION_DATE = date(2026, 11, 1)

_phone_numbers = itertools.count(1)


def synthetic_phone():
    return f"+9198{next(_phone_numbers):08d}"


@pytest.fixture
def make_user(db):
    def _make(username, roles=(), password=PASSWORD, **extra):
        user = User.objects.create_user(username=username, password=password, **extra)
        user.groups.set(Group.objects.filter(name__in=roles))
        return user

    return _make


@pytest.fixture
def caller(make_user):
    return make_user("caller", [Role.CALLER], first_name="Test", last_name="Caller")


@pytest.fixture
def caller2(make_user):
    return make_user("caller2", [Role.CALLER], first_name="Second", last_name="Caller")


@pytest.fixture
def coordinator(make_user):
    return make_user("coordinator", [Role.COORDINATOR])


@pytest.fixture
def caller_coordinator(make_user):
    return make_user("both", [Role.CALLER, Role.COORDINATOR])


@pytest.fixture
def sysadmin(make_user):
    return make_user("sysadmin", is_staff=True, is_superuser=True)


@pytest.fixture
def no_role_user(make_user):
    return make_user("norole")


@pytest.fixture
def make_contact(db, coordinator):
    from apps.contacts.services import create_contact

    def _make(full_name=None, phone=None, area="Riverside", registration_date=date(2025, 6, 1), **extra):
        phone = phone or synthetic_phone()
        return create_contact(
            {
                "full_name": full_name or f"Synthetic Person {phone[-4:]}",
                "phone_primary": phone,
                "area": area,
                "registration_date": registration_date,
                **extra,
            },
            coordinator,
        )

    return _make


@pytest.fixture
def allocate(coordinator):
    from apps.allocations.services import assign_individual

    def _allocate(contact, caller, effective_date=ALLOCATION_START, reason="test allocation"):
        return assign_individual(
            contact, caller, effective_date=effective_date, actor=coordinator, reason=reason
        )

    return _allocate


@pytest.fixture
def make_session(coordinator):
    from apps.calling.services import create_session, open_session

    def _make(session_date=SESSION_DATE, opened=True, venue=""):
        session = create_session(
            session_date=session_date, title="", venue=venue, notes="", actor=coordinator
        )
        if opened:
            session, _ = open_session(session, coordinator)
        return session

    return _make


@pytest.fixture
def record(coordinator):
    from apps.calling.services import record_attempt

    def _record(task, outcome, actor=None, **kwargs):
        return record_attempt(task, outcome=outcome, actor=actor or task.caller, **kwargs)

    return _record
