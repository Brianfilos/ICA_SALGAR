from django.db import migrations, models


def migrate_clase_contribuyente(apps, schema_editor):
    RegistroRIT = apps.get_model('tasks', 'RegistroRIT')
    mapping = {
        'NORMAL': 'ORDINARIO',
        'INFORMAL_OCASIONAL': 'ACTIVIDAD_INFORMAL',
        'REGIMEN_SIMPLE': 'ORDINARIO',
    }
    for old, new in mapping.items():
        RegistroRIT.objects.filter(clase_contribuyente=old).update(clase_contribuyente=new)


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0037_auto_tipo_sancion'),
    ]

    operations = [
        migrations.RunPython(migrate_clase_contribuyente, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='registrorit',
            name='clase_contribuyente',
            field=models.CharField(
                choices=[
                    ('ORDINARIO', 'Ordinario'),
                    ('ICA_SIMPLIFICADO', 'ICA Simplificado'),
                    ('OCASIONAL', 'Ocasional'),
                    ('ACTIVIDAD_INFORMAL', 'Actividad Informal'),
                    ('NO_SUJETO', 'No Sujeto'),
                ],
                default='ORDINARIO',
                max_length=20,
                verbose_name='Tipo de contribuyente',
            ),
        ),
        migrations.AlterField(
            model_name='registrorit',
            name='es_retenedor_ica',
            field=models.BooleanField(default=False, verbose_name='Agente de Retención ICA'),
        ),
        migrations.AlterField(
            model_name='registrorit',
            name='tipo_documento',
            field=models.CharField(
                choices=[
                    ('CC', 'Cédula de ciudadanía'),
                    ('NIT', 'NIT'),
                    ('PASAPORTE', 'Pasaporte'),
                    ('CE', 'Cédula de extranjería'),
                    ('OTRO', 'Otro'),
                ],
                default='NIT',
                max_length=10,
                verbose_name='Tipo de documento',
            ),
        ),
        migrations.AlterField(
            model_name='registrorit',
            name='telefono',
            field=models.CharField(default='', max_length=30, verbose_name='Celular'),
        ),
    ]
