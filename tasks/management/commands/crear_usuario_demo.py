from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from tasks.models import AccesoProceso, Proceso, PerfilContribuyente
from api_movil.models import PerfilFuncionario


def _get_municipio_segovia():
    try:
        from catalogos.models import Municipio
        return (
            Municipio.objects.filter(nombre__icontains='Segovia').first()
            or Municipio.objects.first()
        )
    except Exception:
        return None


class Command(BaseCommand):
    help = 'Crea los usuarios demo: demo_contribuyente y demo_visitador'

    def handle(self, *args, **options):
        PASSWORD = 'Legal2026'
        municipio = _get_municipio_segovia()

        self._crear_contribuyente(PASSWORD, municipio)
        self.stdout.write('')
        self._crear_visitador(PASSWORD)

        self.stdout.write(self.style.SUCCESS(
            '\n✓ Usuarios demo listos:\n'
            '   demo_contribuyente / Legal2026  →  portal web (RIT, ICA, Autoretención)\n'
            '   demo_visitador     / Legal2026  →  app móvil + visitador web'
        ))

    # ── Contribuyente ──────────────────────────────────────────────────────────
    def _crear_contribuyente(self, password, municipio):
        USERNAME = 'demo_contribuyente'
        EMAIL    = 'demo.contribuyente@segovia.gov.co'

        grp, _ = Group.objects.get_or_create(name='CONTRIBUYENTE')

        user, created = User.objects.get_or_create(
            username=USERNAME,
            defaults={'email': EMAIL, 'first_name': 'Demo', 'last_name': 'Contribuyente'}
        )
        user.set_password(password)
        user.email      = EMAIL
        user.first_name = 'Demo'
        user.last_name  = 'Contribuyente'
        user.is_staff   = False
        user.save()
        user.groups.set([grp])
        self.stdout.write(f'{"Creado" if created else "Actualizado"}: {USERNAME}')

        if municipio:
            PerfilContribuyente.objects.get_or_create(
                user=user,
                defaults={
                    'nombre_razon_social': 'Demo Contribuyente',
                    'tipo_documento': 'CC',
                    'numero_documento': '1000000001',
                    'direccion_notificacion': 'Calle Demo 1',
                    'municipio_notificacion': municipio,
                    'telefono': '3000000001',
                    'correo_electronico': EMAIL,
                    'numero_establecimientos': 1,
                    'clasificacion_contribuyente': 'REGIMEN_COMUN',
                    'tipo_persona': 'NATURAL',
                    'must_change_password': False,
                }
            )
            self.stdout.write('  Perfil contribuyente: OK')
        else:
            self.stdout.write('  Advertencia: sin municipio — perfil no creado')

        for codigo in ('RIT', 'ICA', 'AUTO'):
            try:
                proceso = Proceso.objects.get(codigo=codigo)
                obj, _ = AccesoProceso.objects.get_or_create(
                    user=user, proceso=proceso, defaults={'habilitado': True}
                )
                obj.habilitado = True
                obj.save()
                self.stdout.write(f'  Acceso {codigo}: OK')
            except Proceso.DoesNotExist:
                self.stdout.write(f'  Advertencia: proceso {codigo} no existe en BD')

    # ── Visitador ──────────────────────────────────────────────────────────────
    def _crear_visitador(self, password):
        USERNAME = 'demo_visitador'
        EMAIL    = 'demo.visitador@segovia.gov.co'

        grp, _ = Group.objects.get_or_create(name='FUNCIONARIO_CAMPO')

        user, created = User.objects.get_or_create(
            username=USERNAME,
            defaults={'email': EMAIL, 'first_name': 'Demo', 'last_name': 'Visitador'}
        )
        user.set_password(password)
        user.email      = EMAIL
        user.first_name = 'Demo'
        user.last_name  = 'Visitador'
        user.is_staff   = False
        user.save()
        user.groups.set([grp])
        self.stdout.write(f'{"Creado" if created else "Actualizado"}: {USERNAME}')

        try:
            PerfilFuncionario.objects.get_or_create(
                user=user,
                defaults={'cargo': 'Visitador Demo', 'dependencia': 'Demo', 'activo': True}
            )
            self.stdout.write('  Perfil funcionario: OK')
        except Exception as e:
            self.stdout.write(f'  Advertencia al crear perfil funcionario: {e}')
