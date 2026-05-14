from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from tasks.models import AccesoProceso, Proceso


class Command(BaseCommand):
    help = 'Crea el usuario de gestión de la alcaldía con acceso a ICA y RIT'

    def handle(self, *args, **options):
        email = 'legal.gestionsalgar@gmail.com'
        password = 'GestionSalgar2026*'
        username = email

        # Crear o actualizar grupo ALCALDIA_GESTION
        grupo, _ = Group.objects.get_or_create(name='ALCALDIA_GESTION')
        self.stdout.write('Grupo ALCALDIA_GESTION: OK')

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

        # Habilitar acceso a ICA y RIT
        for codigo in ('ICA', 'RIT'):
            try:
                proceso = Proceso.objects.get(codigo=codigo)
                acceso, _ = AccesoProceso.objects.get_or_create(
                    user=user, proceso=proceso, defaults={'habilitado': True}
                )
                acceso.habilitado = True
                acceso.save()
                self.stdout.write(f'Acceso {codigo} habilitado: OK')
            except Exception as e:
                self.stdout.write(f'Advertencia al habilitar acceso {codigo}: {e}')

        accion = 'Creado' if created else 'Actualizado'
        self.stdout.write(self.style.SUCCESS(
            f'{accion} usuario: {username} / Grupo: ALCALDIA_GESTION'
        ))
