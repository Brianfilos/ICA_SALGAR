from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_movil', '0008_add_estado_precargada'),
    ]

    operations = [
        migrations.AlterField(
            model_name='visitarit',
            name='estado',
            field=models.CharField(
                choices=[
                    ('precargada', 'Precargada (pendiente de visita)'),
                    ('pendiente', 'Pendiente de sincronización'),
                    ('sincronizado', 'Sincronizado'),
                    ('no_atendida', 'No atendida'),
                    ('incompleta', 'Incompleta (pendiente de completar)'),
                ],
                default='pendiente',
                max_length=20,
            ),
        ),
    ]
