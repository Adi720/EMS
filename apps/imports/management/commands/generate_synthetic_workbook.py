"""Write a synthetic workbook for trying the import locally. Contains no real data."""

from pathlib import Path

from django.core.management.base import BaseCommand

from apps.imports.synthetic import CALLERS, build_workbook


class Command(BaseCommand):
    help = "Write a synthetic 'EMS DATA' workbook (fake contacts) for import testing."

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path of the .xlsx file to write.")
        parser.add_argument("--contacts", type=int, default=120)

    def handle(self, *args, output, contacts, **options):
        content, rows = build_workbook(contacts)
        Path(output).write_bytes(content)
        self.stdout.write(f"Wrote {len(rows)} synthetic contacts to {output}")
        self.stdout.write(
            "Create caller users with these full names to test caller matching: " + ", ".join(CALLERS)
        )
