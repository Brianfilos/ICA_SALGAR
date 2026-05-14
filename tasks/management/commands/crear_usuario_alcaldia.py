from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from tasks.models import AccesoProceso, Proceso


class Command(BaseCommand):
    help = 'Crea el usuario de gestión de la alcaldía con acceso especial a ICA'

    def handle(self, *args, **options):
        email = 'legal.gestionbolivar@gmail.com'
        password = 'Gestionbolivar2026*'
        username = email

        # Crear o actualizar grupo ALCALDIA_GESTION
        grupo, _ = Group.objects.get_or_create(name='ALCALDIA_GESTION')
        self.stdout.write(f'Grupo ALCALDIA_GESTION: OK')

        # Crear o actualizar usuario
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': 'Gestión', 'last_name': 'Alcaldía'}
        )
        user.set_password(password)
        user.email = email
        user.is_staff = False
        user.save()

        # Asignar grupo
        user.groups.set([grupo])

        # Habilitar acceso al proceso ICA
        try:
            proceso_ica = Proceso.objects.get(codigo='ICA')
            AccesoProceso.objects.get_or_create(user=user, proceso=proceso_ica,
                                                 defaults={'habilitado': True})
            acceso = AccesoProceso.objects.get(user=user, proceso=proceso_ica)
            acceso.habilitado = True
            acceso.save()
            self.stdout.write('Acceso ICA habilitado: OK')
        except Exception as e:
            self.stdout.write(f'Advertencia al habilitar acceso ICA: {e}')

        accion = 'Creado' if created else 'Actualizado'
        self.stdout.write(self.style.SUCCESS(
            f'{accion} usuario: {username} / Grupo: ALCALDIA_GESTION'
        ))
