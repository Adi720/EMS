"""Create synthetic demo users for local development. Refuses to run when DEBUG is off."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.accounts.roles import Role

DEMO_USERS = [
    ("demo.coordinator", "Demo", "Coordinator", [Role.COORDINATOR]),
    ("demo.caller1", "Demo", "Caller One", [Role.CALLER]),
    ("demo.caller2", "Demo", "Caller Two", [Role.CALLER]),
    ("demo.both", "Demo", "Coordinator Caller", [Role.COORDINATOR, Role.CALLER]),
]


class Command(BaseCommand):
    help = "Create synthetic demo users (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password for all demo users.")

    def handle(self, *args, password, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo_users only runs with DEBUG enabled.")
        for username, first, last, roles in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            user.set_password(password)
            user.save()
            user.groups.set(Group.objects.filter(name__in=roles))
            self.stdout.write(f"{'Created' if created else 'Updated'} {username} ({', '.join(roles)})")
