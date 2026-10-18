from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0019_repair_zero_count_movements"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("value", models.TextField(blank=True, default="")),
            ],
        ),
    ]
