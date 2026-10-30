"""PostgreSQL only: forbid overlapping allocation date ranges for the same contact.

``effective_to`` is exclusive, so ranges are '[)'. A null ``effective_to`` is an
unbounded range. ``btree_gist`` is a trusted extension (PostgreSQL 13+), so the
database owner can create it. On SQLite this migration does nothing; the
service layer and the one-open-allocation constraint still apply.
"""

from django.db import migrations

CREATE = """
CREATE EXTENSION IF NOT EXISTS btree_gist;
ALTER TABLE allocations_allocation
    ADD CONSTRAINT allocation_no_overlap
    EXCLUDE USING gist (contact_id WITH =, daterange(effective_from, effective_to, '[)') WITH &&);
"""

DROP = "ALTER TABLE allocations_allocation DROP CONSTRAINT IF EXISTS allocation_no_overlap;"


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(CREATE)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(DROP)


class Migration(migrations.Migration):
    dependencies = [("allocations", "0001_initial")]

    operations = [migrations.RunPython(forwards, backwards)]
