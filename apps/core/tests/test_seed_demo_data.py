"""The demo-data command only ever runs on an empty development database."""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from apps.calling.models import CallAttempt, EmsSession
from apps.contacts.models import Contact


@pytest.mark.django_db
def test_refuses_without_debug():
    with override_settings(DEBUG=False), pytest.raises(CommandError, match="DEBUG"):
        call_command("seed_demo_data", password="Demo-pass-2026x", stdout=StringIO())
    assert not Contact.objects.exists()


@pytest.mark.django_db
def test_fills_an_empty_database_and_refuses_a_second_time(make_contact):
    with override_settings(DEBUG=True):
        call_command("seed_demo_data", password="Demo-pass-2026x", saints=20, stdout=StringIO())
        assert Contact.objects.count() == 20
        assert EmsSession.objects.filter(status="open").count() == 1
        assert EmsSession.objects.filter(status="closed").count() == 1
        assert CallAttempt.objects.exists()
        with pytest.raises(CommandError, match="already has Saints"):
            call_command("seed_demo_data", password="Demo-pass-2026x", stdout=StringIO())
