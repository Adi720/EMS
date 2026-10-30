import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.models import User
from apps.accounts.roles import Role


def test_custom_user_model_is_active():
    assert get_user_model() is User


@pytest.mark.django_db
def test_role_groups_are_created_by_migration():
    assert set(Group.objects.values_list("name", flat=True)) >= set(Role.ALL)


@pytest.mark.parametrize(
    ("fixture", "is_caller", "is_coordinator"),
    [
        ("caller", True, False),
        ("coordinator", False, True),
        ("caller_coordinator", True, True),
        ("sysadmin", False, True),
        ("no_role_user", False, False),
    ],
)
def test_role_flags(request, fixture, is_caller, is_coordinator):
    user = request.getfixturevalue(fixture)
    assert user.is_caller is is_caller
    assert user.is_coordinator is is_coordinator
    assert user.has_any_role is (is_caller or is_coordinator)


def test_inactive_user_has_no_roles(make_user):
    user = make_user("gone", [Role.CALLER, Role.COORDINATOR], is_active=False, is_superuser=True)
    assert not user.is_caller
    assert not user.is_coordinator


def test_str_prefers_full_name(caller, no_role_user):
    assert str(caller) == "Test Caller"
    assert str(no_role_user) == "norole"
