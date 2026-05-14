from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_movil', '0009_alter_visitarit_estado'),
    ]

    operations = [
        migrations.AlterField(
            model_name='visitarit',
            name='motivo_no_atencion',
            field=models.CharField(
                blank=True,
                choices=[
                    ('CERRADO', 'Local cerrado'),
                    ('AUSENTE', 'Propietario / encargado ausente'),
                    ('NEGATIVA', 'Se negó a atender'),
                    ('DIRECCION', 'Dirección no encontrada'),
                    ('REGIMEN_SIMPLE', 'Régimen Simple (no obligado a registrarse)'),
                    ('OTRO', 'Otro motivo'),
                ],
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name='CensoEstablecimientos',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('archivo', models.FileField(upload_to='censo/', verbose_name='Archivo Excel (.xls / .xlsx)')),
                ('descripcion', models.CharField(blank=True, max_length=200, verbose_name='Descripción')),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Censo de Establecimientos',
                'verbose_name_plural': 'Censo de Establecimientos',
            },
        ),
    ]
