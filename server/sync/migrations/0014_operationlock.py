from django.db import migrations, models


def initialize_lock(apps, schema_editor):
    apps.get_model("sync", "OperationLock").objects.using(schema_editor.connection.alias).get_or_create(id=1)


class Migration(migrations.Migration):
    dependencies = [("sync", "0013_stockentryrequest_sync")]
    operations = [
        migrations.CreateModel(
            name="OperationLock",
            fields=[("id", models.PositiveSmallIntegerField(primary_key=True, serialize=False))],
        ),
        migrations.RunPython(initialize_lock, migrations.RunPython.noop),
    ]
