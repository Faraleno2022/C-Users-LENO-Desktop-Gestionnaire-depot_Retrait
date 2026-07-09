from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0011_product_extra_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockmovement",
            name="deleted",
            field=models.BooleanField(default=False),
        ),
    ]
