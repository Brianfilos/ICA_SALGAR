from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Cambia la contraseña del usuario revisor (admin)'

    def handle(self, *args, **options):
        username = 'revisor'
        new_password = 'Gestionbolivar2026*'

        try:
            user = User.objects.get(username=username)
            user.set_password(new_password)
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f'Contraseña actualizada para el usuario: {username}'
            ))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(
                f'No se encontró el usuario: {username}'
            ))
