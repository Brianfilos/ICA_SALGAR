import os
from django.core.management.base import BaseCommand, CommandError
from api_movil.models import EstablecimientoCenso


class Command(BaseCommand):
    help = 'Importa el padrón de establecimientos desde un archivo .xls/.xlsx'

    def add_arguments(self, parser):
        parser.add_argument(
            'archivo',
            nargs='?',
            default='ESTABLECIMIENTOS 24-04-2026.xls',
            help='Ruta al archivo Excel (default: ESTABLECIMIENTOS 24-04-2026.xls)',
        )

    def handle(self, *args, **options):
        ruta = options['archivo']
        if not os.path.exists(ruta):
            raise CommandError(f'Archivo no encontrado: {ruta}')

        try:
            import xlrd
            wb = xlrd.open_workbook(ruta)
            sh = wb.sheet_by_index(0)
        except ImportError:
            raise CommandError('Instala xlrd: pip install xlrd')

        self.stdout.write(f'Leyendo {sh.nrows - 1} filas...')

        EstablecimientoCenso.objects.all().delete()
        self.stdout.write('Tabla limpiada.')

        lote = []
        LOTE_SIZE = 500

        for r in range(1, sh.nrows):
            row = sh.row_values(r)
            nit    = str(row[0]).strip().split('.')[0]  # quitar decimales de xlrd
            nombre = str(row[1]).strip()
            nombre_prop = ' '.join(filter(None, [
                str(row[2]).strip(),
                str(row[3]).strip(),
                str(row[4]).strip(),
            ]))
            lote.append(EstablecimientoCenso(
                nit                   = nit,
                nombre_establecimiento = nombre,
                nombre_propietario    = nombre_prop,
                codigo_estab          = str(row[5]).strip(),
                direccion             = str(row[7]).strip(),
                telefono              = str(row[11]).strip(),
                codigo_act_eco        = str(row[22]).strip(),
                actividad_economica   = str(row[23]).strip(),
                estado                = str(row[17]).strip(),
            ))
            if len(lote) >= LOTE_SIZE:
                EstablecimientoCenso.objects.bulk_create(lote)
                lote = []

        if lote:
            EstablecimientoCenso.objects.bulk_create(lote)

        total = EstablecimientoCenso.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'✓ Importados {total} establecimientos desde {ruta}'
        ))
