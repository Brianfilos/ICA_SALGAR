from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0026_firma_otp_ica'),
    ]

    operations = [
        # Correo OTP para contador y revisor en DeclaracionICA
        migrations.AddField(
            model_name='declaracionica',
            name='contador_email',
            field=models.EmailField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='revisor_email',
            field=models.EmailField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='contador_firma_verificada',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='declaracionica',
            name='revisor_firma_verificada',
            field=models.BooleanField(default=False),
        ),
        # Campo tipo en FirmaOTPICA para distinguir declarante/contador/revisor
        migrations.AddField(
            model_name='firmaotpica',
            name='tipo',
            field=models.CharField(
                choices=[('declarante', 'Declarante'), ('contador', 'Contador'), ('revisor', 'Revisor Fiscal')],
                default='declarante',
                max_length=20,
            ),
        ),
    ]
