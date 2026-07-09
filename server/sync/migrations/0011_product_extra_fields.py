# Generated manually to align product sync fields with the desktop schema.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0010_stockentryrequest_kind_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="categorie",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="product",
            name="unite",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="product",
            name="prix_achat",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="product",
            name="stock_max",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="product",
            name="emplacement",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
    ]
