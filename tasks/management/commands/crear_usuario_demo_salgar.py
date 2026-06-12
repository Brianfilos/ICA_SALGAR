from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from tasks.models import AccesoProceso, Proceso, PerfilContribuyente


class Command(BaseCommand):
    help = 'Crea o actualiza el usuario demo_salgar como contribuyente con todos los procesos habilitados'

    def handle(self, *args, **options):
        username = 'demo_salgar'
        password = 'Salgar2026/'
        email = 'demo.salgar@portalterritorial.com.co'

        # Municipio Salgar (o el primero disponible)
        municipio = None
        try:
            from catalogos.models import Municipio
            municipio = (
                Municipio.objects.filter(nombre__icontains='Salgar').first()
                or Municipio.objects.first()
            )
        except Exception:
            pass

        # Grupo CONTRIBUYENTE
        grupo, _ = Group.objects.get_or_create(name='CONTRIBUYENTE')

        # Crear / actualizar usuario
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'first_name': 'Demo', 'last_name': 'Salgar'}
        )
        user.set_password(password)
        user.email = email
        user.first_name = 'Demo'
        user.last_name = 'Salgar'
        user.is_staff = False
        user.is_superuser = False
        user.save()
        user.groups.set([grupo])

        # Perfil contribuyente
        if municipio:
            perfil, _ = PerfilContribuyente.objects.get_or_create(
                user=user,
                defaults={
                    'nombre_razon_social': 'Demo Salgar',
                    'tipo_documento': 'CC',
                    'numero_documento': '1000000099',
                    'direccion_notificacion': 'Calle Demo 99',
                    'municipio_notificacion': municipio,
                    'telefono': '3000000099',
                    'correo_electronico': email,
                    'numero_establecimientos': 1,
                    'clasificacion_contribuyente': 'REGIMEN_COMUN',
                    'tipo_persona': 'NATURAL',
                    'must_change_password': False,
                }
            )
            try:
                perfil.asignar_departamento_notificacion()
                perfil.save()
            except Exception:
                pass
            self.stdout.write('Perfil contribuyente: OK')
        else:
            self.stdout.write('Advertencia: sin municipio — perfil no creado')

        # Habilitar todos los procesos
        for codigo in ('RIT', 'ICA', 'AUTO', 'RETE'):
            try:
                proceso = Proceso.objects.get(codigo=codigo)
                acceso, _ = AccesoProceso.objects.get_or_create(
                    user=user, proceso=proceso, defaults={'habilitado': True}
                )
                acceso.habilitado = True
                acceso.save()
                self.stdout.write(f'Acceso {codigo}: OK')
            except Proceso.DoesNotExist:
                self.stdout.write(f'Advertencia: proceso {codigo} no existe en BD')

        accion = 'Creado' if created else 'Actualizado'
        self.stdout.write(self.style.SUCCESS(
            f'{accion} contribuyente demo: {username} / Salgar2026/'
        ))
