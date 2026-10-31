"""Create the shared Stall Lead login (default ``stall.sewa.admin``) and print its password once.

Stall leads can only add new Saints; each Saint they add records the name of the person
who added it, so the shared login stays traceable.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.accounts.team import generate_password
from apps.audit.services import log_event


class Command(BaseCommand):
    help = "Create (or reset the password of) the Stall Lead login."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?", default="stall.sewa.admin")
        parser.add_argument(
            "--reset-password", action="store_true", help="Give an existing Stall Lead a new password."
        )

    @transaction.atomic
    def handle(self, *args, username, reset_password, **options):
        user = User.objects.filter(username=username).first()
        if user and not reset_password:
            raise CommandError(f"{username} already exists. Use --reset-password to give it a new password.")
        if user and (user.is_superuser or user.groups.exclude(name=Role.STALL_LEAD).exists()):
            raise CommandError(f"{username} has other roles; change it in Django Admin instead.")
        password = generate_password()
        if user is None:
            user = User.objects.create_user(
                username=username, password=password, first_name="Stall", last_name="Sewa"
            )
            log_event(None, "team.stall_lead_create", f"Created Stall Lead login {username}", user)
        else:
            user.set_password(password)
            user.is_active = True
            user.save()
            log_event(None, "team.password_reset", f"Reset the password of {username}", user)
        user.groups.add(Group.objects.get(name=Role.STALL_LEAD))
        self.stdout.write(f"Stall Lead login: {username}")
        self.stdout.write(f"Password (shown only now): {password}")
