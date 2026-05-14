import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0025_add_must_change_password_to_perfil'),
    ]

    operations = [
        # Campos de firma en DeclaracionICA
        migrations.AddField(
            model_name='declaracionica',
            name='firma_otp_verificada',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='firma_timestamp',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='firma_hash',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        # Modelo FirmaOTPICA
        migrations.CreateModel(
            name='FirmaOTPICA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=6)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('usado', models.BooleanField(default=False)),
                ('declaracion', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='otps_firma',
                    to='tasks.declaracionica',
                )),
            ],
            options={
                'ordering': ['-creado_en'],
            },
        ),
    ]
