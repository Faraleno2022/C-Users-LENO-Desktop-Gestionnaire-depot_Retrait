from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('sync', '0014_operationlock')]
    operations = [
        migrations.AddField(model_name='product', name='stock_initial', field=models.FloatField(null=True, blank=True)),
        migrations.AddField(model_name='product', name='stock_initial_source', field=models.CharField(max_length=40, default='', blank=True)),
        migrations.AddField(model_name='stockmovement', name='is_initial', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='stockmovement', name='stock_compte', field=models.FloatField(null=True, blank=True)),
        migrations.CreateModel(name='ReconciliationRun', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('version', models.CharField(max_length=40, unique=True)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('report', models.JSONField(default=dict)),
            ('snapshot', models.JSONField(default=dict)),
        ]),
    ]
