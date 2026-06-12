import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0041_add_pdf_fisico_to_rit'),
    ]

    operations = [
        migrations.AddField(
            model_name='actividadeconomicarit',
            name='establecimiento',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='actividades', to='tasks.establecimientorit', verbose_name='Establecimiento'),
        ),
    ]
