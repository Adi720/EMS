"""Run once a day from the host's scheduler. On the reminder day (Saturday) it starts this
week's calling (unless REMINDER_AUTO_START=False) and emails every caller their link."""

from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.calling.reminders import send_weekly_reminders
from apps.calling.services import CallingError

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class Command(BaseCommand):
    help = "Saturday reminder: start this week's calling and email each caller (safe to run daily)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if today is not the reminder day.")
        parser.add_argument("--date", help="Pretend today is this date (YYYY-MM-DD), for testing.")

    def handle(self, *args, force, date: str | None = None, **options):
        today = self._today(date)
        if today.weekday() != settings.REMINDER_WEEKDAY and not force:
            self.stdout.write(f"Today is not {DAYS[settings.REMINDER_WEEKDAY]}; nothing to do.")
            return
        try:
            result = send_weekly_reminders(today)
        except CallingError as exc:
            raise CommandError(str(exc)) from exc
        session = result["session"]
        if session is None:
            self.stdout.write("Calling has not been started for this Sunday; no reminders sent.")
            return
        self.stdout.write(f"{session}: calling {'started now' if result['started'] else 'already open'}.")
        self.stdout.write(f"Emailed: {len(result['sent'])}")
        for label, users in [
            ("Already reminded", result["already"]),
            ("No email address", result["no_email"]),
        ]:
            if users:
                self.stdout.write(f"{label}: " + ", ".join(str(u) for u in users))
        for user, error in result["failed"]:
            self.stderr.write(f"Failed for {user}: {error}")

    def _today(self, value):
        if not value:
            return timezone.localdate()
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError("--date must be YYYY-MM-DD") from exc
