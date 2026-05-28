from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Crea o actualiza el usuario administrador (superusuario) de Salgar'

    def handle(self, *args, **options):
        username = 'filosbriandev'
        password = 'Gestionsalgar2026//'
        email = 'filosbriandev@gmail.com'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': 'Brian', 'last_name': 'Filos'}
        )
        user.set_password(password)
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.save()

        accion = 'Creado' if created else 'Actualizado'
        self.stdout.write(self.style.SUCCESS(
            f'{accion} superusuario: {username}'
        ))
