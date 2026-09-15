from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('sync', '0015_reconciliation')]
    operations = [migrations.CreateModel(
        name='ReconciliationSnapshotChunk',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('table_name', models.CharField(max_length=32)),
            ('sequence', models.PositiveIntegerField()),
            ('rows', models.JSONField(default=list)),
            ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='snapshot_chunks', to='sync.reconciliationrun')),
        ],
        options={'constraints': [models.UniqueConstraint(fields=('run', 'table_name', 'sequence'), name='unique_reconciliation_chunk')]},
    )]
