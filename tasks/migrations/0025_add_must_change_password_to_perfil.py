from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0024_password_reset_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilcontribuyente',
            name='must_change_password',
            field=models.BooleanField(default=False, verbose_name='Debe cambiar contraseña'),
        ),
    ]
