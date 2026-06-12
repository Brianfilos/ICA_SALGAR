from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Crea o actualiza el usuario demo_salgar con todos los permisos'

    def handle(self, *args, **options):
        username = 'demo_salgar'
        password = 'Salgar2026/'
        email = 'demo.salgar@portalterritorial.com.co'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': 'Demo', 'last_name': 'Salgar'}
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
