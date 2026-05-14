from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0033_firma_otp_rit'),
    ]

    operations = [
        # Agregar tiene_avisos_tableros a DeclaracionICA
        migrations.AddField(
            model_name='declaracionica',
            name='tiene_avisos_tableros',
            field=models.CharField(
                blank=True,
                choices=[('SI', 'Sí'), ('NO', 'No')],
                max_length=2,
                null=True,
            ),
        ),
        # Agregar campos de representante legal
        migrations.AddField(
            model_name='declaracionica',
            name='rep_legal_email',
            field=models.EmailField(blank=True, max_length=254, null=True, verbose_name='Correo del representante legal'),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='rep_legal_nombre',
            field=models.CharField(blank=True, max_length=120, null=True, verbose_name='Nombre del representante legal'),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='rep_legal_tipo_documento',
            field=models.CharField(
                blank=True,
                choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')],
                max_length=3,
                null=True,
                verbose_name='Tipo doc. representante legal',
            ),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='rep_legal_numero_documento',
            field=models.CharField(blank=True, max_length=30, null=True, verbose_name='Número documento representante legal'),
        ),
        # Eliminar campos de firma como imagen (reemplazados por OTP)
        migrations.RemoveField(
            model_name='declaracionica',
            name='firma_declarante',
        ),
        migrations.RemoveField(
            model_name='declaracionica',
            name='firma_contador',
        ),
        migrations.RemoveField(
            model_name='declaracionica',
            name='firma_revisor_fiscal',
        ),
    ]
