from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import connection


class Command(BaseCommand):
    help = 'Elimina todos los registros de declaraciones/RITs y usuarios, conservando municipios, departamentos, CIIU, revisor y legal.gestionbolivar@gmail.com'

    def handle(self, *args, **options):
        from tasks.models import (
            RegistroRIT, RepresentanteLegalRIT, EstablecimientoRIT, ActividadEconomicaRIT,
            DeclaracionICA, DeclaracionActividad, AutoRetencionICA, RetencionICA,
            FirmaOTPICA, PasswordResetCode, PerfilContribuyente, AccesoProceso, Task,
            CodigoEstablecimiento,
        )

        USUARIOS_CONSERVAR = ['revisor', 'legal.gestionbolivar@gmail.com', 'demo_contribuyente', 'demo_visitador']

        # 1. Borrar registros dependientes de DeclaracionICA
        n = FirmaOTPICA.objects.all().delete()[0]
        self.stdout.write(f'FirmaOTPICA eliminadas: {n}')

        n = AutoRetencionICA.objects.all().delete()[0]
        self.stdout.write(f'AutoRetencionICA eliminadas: {n}')

        n = RetencionICA.objects.all().delete()[0]
        self.stdout.write(f'RetencionICA eliminadas: {n}')

        n = DeclaracionActividad.objects.all().delete()[0]
        self.stdout.write(f'DeclaracionActividad eliminadas: {n}')

        n = DeclaracionICA.objects.all().delete()[0]
        self.stdout.write(f'DeclaracionICA eliminadas: {n}')

        # 2. Borrar registros dependientes de RegistroRIT
        n = ActividadEconomicaRIT.objects.all().delete()[0]
        self.stdout.write(f'ActividadEconomicaRIT eliminadas: {n}')

        n = EstablecimientoRIT.objects.all().delete()[0]
        self.stdout.write(f'EstablecimientoRIT eliminadas: {n}')

        n = RepresentanteLegalRIT.objects.all().delete()[0]
        self.stdout.write(f'RepresentanteLegalRIT eliminadas: {n}')

        n = RegistroRIT.objects.all().delete()[0]
        self.stdout.write(f'RegistroRIT eliminados: {n}')

        # 3. Otros
        n = PasswordResetCode.objects.all().delete()[0]
        self.stdout.write(f'PasswordResetCode eliminados: {n}')

        n = CodigoEstablecimiento.objects.all().delete()[0]
        self.stdout.write(f'CodigoEstablecimiento eliminados: {n}')

        n = Task.objects.all().delete()[0]
        self.stdout.write(f'Task eliminados: {n}')

        # 4. PerfilContribuyente - solo los que NO son de los usuarios conservados
        n = PerfilContribuyente.objects.exclude(user__username__in=USUARIOS_CONSERVAR).delete()[0]
        self.stdout.write(f'PerfilContribuyente eliminados: {n}')

        # 5. AccesoProceso - solo los de usuarios que no se conservan
        n = AccesoProceso.objects.exclude(user__username__in=USUARIOS_CONSERVAR).delete()[0]
        self.stdout.write(f'AccesoProceso eliminados: {n}')

        # 6. Usuarios - eliminar todos excepto los conservados
        n = User.objects.exclude(username__in=USUARIOS_CONSERVAR).delete()[0]
        self.stdout.write(f'Usuarios eliminados: {n}')

        # 7. Resetear secuencias (PostgreSQL)
        tablas = [
            'tasks_declaracionica',
            'tasks_declaracionactividad',
            'tasks_autoretencionica',
            'tasks_retencionica',
            'tasks_registrorit',
            'tasks_representantelegalrit',
            'tasks_establecimientorit',
            'tasks_actividadeconomicarit',
            'tasks_firmaotpica',
            'tasks_passwordresetcode',
            'tasks_perfilcontribuyente',
            'tasks_task',
            'tasks_codigoestablecimiento',
        ]

        db_engine = connection.settings_dict['ENGINE']
        if 'postgresql' in db_engine or 'postgis' in db_engine:
            with connection.cursor() as cursor:
                for tabla in tablas:
                    try:
                        cursor.execute(f"ALTER SEQUENCE {tabla}_id_seq RESTART WITH 1;")
                        self.stdout.write(f'Secuencia reseteada: {tabla}_id_seq')
                    except Exception as e:
                        self.stdout.write(f'No se pudo resetear {tabla}_id_seq: {e}')
        else:
            self.stdout.write('Base de datos no es PostgreSQL — IDs se resetearán solos al insertar nuevos registros.')

        self.stdout.write(self.style.SUCCESS('\n✓ Limpieza completada. Se conservaron: ' + ', '.join(USUARIOS_CONSERVAR)))
