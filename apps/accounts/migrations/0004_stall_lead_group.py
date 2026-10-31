from django.db import migrations


def create_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.get_or_create(name="Stall Lead")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_leave_and_blessing")]

    operations = [migrations.RunPython(create_group, migrations.RunPython.noop)]
