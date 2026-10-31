"""Fill an EMPTY development database with made-up demo data (for trying the app and
for documentation screenshots). Refuses to run when DEBUG is off or Saints already exist."""

import random
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.allocations.services import assign_individual, create_cycle
from apps.calling.models import Outcome
from apps.calling.services import (
    close_session,
    create_session,
    next_sunday,
    open_session,
    record_attempt,
    start_weekly_calling,
)
from apps.contacts.models import Contact, ContactStatus, StatusReason
from apps.contacts.services import change_status, create_contact

FIRST = [
    "Aarav",
    "Diya",
    "Kabir",
    "Meera",
    "Rohan",
    "Sara",
    "Vihaan",
    "Anaya",
    "Arjun",
    "Riya",
    "Ishaan",
    "Tanvi",
    "Karan",
    "Myra",
    "Nikhil",
    "Kiara",
    "Aditya",
    "Simran",
    "Varun",
    "Pooja",
    "Dev",
    "Isha",
]
LAST = ["Example", "Sample", "Demo", "Placeholder", "Testwala", "Mockkar"]
AREAS = ["North Block", "Riverside", "Old Town", "Hill View", "Market Road", "Station Area"]
CALLERS = [
    ("Asha", "Demo"),
    ("Bharat", "Sample"),
    ("Chitra", "Example"),
    ("Deepak", "Placeholder"),
    ("Esha", "Testwala"),
    ("Farhan", "Mockkar"),
]


class Command(BaseCommand):
    help = "Fill an empty development database with made-up Saints, callers and calling results."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password for the demo logins.")
        parser.add_argument("--saints", type=int, default=42)

    def handle(self, *args, password, saints, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_data only runs with DEBUG enabled.")
        if Contact.objects.exists():
            raise CommandError("This database already has Saints. Use an empty database for demo data.")
        with transaction.atomic():
            self._seed(password, saints)
        self.stdout.write(
            self.style.SUCCESS("Demo data created. Logins: demo.coordinator, asha.demo (caller).")
        )

    def _seed(self, password, count):
        rng = random.Random(2026)
        caller_group = Group.objects.get(name=Role.CALLER)
        coordinator, _ = User.objects.get_or_create(
            username="demo.coordinator", defaults={"first_name": "Demo", "last_name": "Coordinator"}
        )
        coordinator.set_password(password)
        coordinator.save()
        coordinator.groups.add(Group.objects.get(name=Role.COORDINATOR))

        callers = []
        for first, last in CALLERS:
            user, _ = User.objects.get_or_create(
                username=f"{first}.{last}".lower(),
                defaults={"first_name": first, "last_name": last, "email": f"{first.lower()}@example.org"},
            )
            user.set_password(password)
            user.save()
            user.groups.add(caller_group)
            callers.append(user)

        today = timezone.localdate()
        cycle_start = today - timedelta(days=60)
        create_cycle(
            name=f"{cycle_start:%b} – {(cycle_start + timedelta(days=90)):%b %Y}",
            start_date=cycle_start,
            planned_end_date=cycle_start + timedelta(days=90),
            actor=coordinator,
        )

        contacts = []
        for i in range(count):
            contact = create_contact(
                {
                    "full_name": f"{FIRST[i % len(FIRST)]} {LAST[(i // len(FIRST)) % len(LAST)]}",
                    "phone_primary": f"+9198{rng.randint(10000000, 99999999)}",
                    "area": AREAS[i % len(AREAS)],
                    "registration_date": date(2026, 1, 4) + timedelta(days=7 * (i % 30)),
                    "qualification": rng.choice(["", "B.Com", "BSc", "12th", "MBA"]),
                    "collected_by_name": rng.choice(["Stall team A", "Stall team B"]),
                },
                coordinator,
            )
            contacts.append(contact)
        for i, contact in enumerate(contacts[:-2]):  # two Saints are left without a caller
            assign_individual(
                contact,
                callers[i % len(callers)],
                effective_date=cycle_start,
                actor=coordinator,
                reason="Demo allocation",
            )

        change_status(
            contacts[3],
            ContactStatus.TEMP_UNAVAILABLE,
            coordinator,
            reason_category=StatusReason.TEMPORARILY_AWAY,
            reason_text="Exams this month",
            review_date=today + timedelta(days=21),
        )
        change_status(
            contacts[7],
            ContactStatus.INACTIVE,
            coordinator,
            reason_category=StatusReason.MOVED_AWAY,
            reason_text="Moved to another city",
        )
        change_status(
            contacts[11],
            ContactStatus.DO_NOT_CALL,
            coordinator,
            reason_category=StatusReason.REQUESTED_NO_CALLS,
        )

        outcomes = (
            [Outcome.YES] * 5
            + [Outcome.NOT_POSSIBLE] * 2
            + [Outcome.WILL_TRY] * 2
            + [Outcome.NOT_CONNECTED] * 2
        )
        # Last week's congregation: almost everyone called, then closed.
        last_week = create_session(
            session_date=next_sunday(today) - timedelta(days=7),
            title="",
            venue="",
            notes="",
            actor=coordinator,
        )
        last_week, _ = open_session(last_week, coordinator)
        for task in last_week.tasks.select_related("caller"):
            if rng.random() < 0.9:
                record_attempt(task, outcome=rng.choice(outcomes), actor=task.caller)
        close_session(last_week, coordinator)

        # This week: calling open, about 60% done.
        session, _, _ = start_weekly_calling(coordinator, today=today)
        for task in session.tasks.select_related("caller"):
            if task.caller.username == "asha.demo" and task.attempt_count == 0 and rng.random() < 0.5:
                continue  # leave some pending for the caller screenshot
            if rng.random() < 0.6:
                outcome = rng.choice(outcomes)
                notes = "Will come with a friend" if outcome == Outcome.YES and rng.random() < 0.3 else ""
                record_attempt(task, outcome=outcome, notes=notes, actor=task.caller)
