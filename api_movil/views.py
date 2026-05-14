from django.utils import timezone
from django.contrib.auth.models import User, Group

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from rest_framework_simplejwt.tokens import RefreshToken

from .models import VisitaRIT, FotoVisita, PerfilFuncionario, CensoEstablecimientos
from catalogos.models import ActividadEconomica, Municipio
from .serializers import (
    VisitaRITSerializer,
    VisitaRITListSerializer,
    FotoVisitaSerializer,
    PerfilFuncionarioSerializer,
)


def _es_funcionario(user):
    return user.groups.filter(name='FUNCIONARIO_CAMPO').exists() or user.is_superuser


# ─── AUTH ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def login_funcionario(request):
    """
    Login con usuario y contraseña.
    Devuelve access + refresh JWT solo si el usuario pertenece al grupo FUNCIONARIO_CAMPO.
    """
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '').strip()

    if not username or not password:
        return Response({'error': 'Usuario y contraseña requeridos.'}, status=400)

    from django.contrib.auth import authenticate
    user = authenticate(username=username, password=password)

    if user is None:
        return Response({'error': 'Credenciales incorrectas.'}, status=401)

    if not user.is_active:
        return Response({'error': 'Usuario inactivo.'}, status=403)

    if not _es_funcionario(user):
        return Response({'error': 'No tienes permiso para usar la app móvil.'}, status=403)

    refresh = RefreshToken.for_user(user)

    perfil = getattr(user, 'perfil_funcionario', None)
    return Response({
        'access':  str(refresh.access_token),
        'refresh': str(refresh),
        'usuario': user.username,
        'nombre':  user.get_full_name() or user.username,
        'cargo':   perfil.cargo if perfil else '',
        'dependencia': perfil.dependencia if perfil else '',
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_token(request):
    """Renueva el access token usando el refresh token."""
    from rest_framework_simplejwt.views import TokenRefreshView
    return TokenRefreshView.as_view()(request._request)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def perfil_funcionario(request):
    """Devuelve el perfil del funcionario autenticado."""
    perfil = getattr(request.user, 'perfil_funcionario', None)
    if perfil:
        return Response(PerfilFuncionarioSerializer(perfil).data)
    return Response({
        'username': request.user.username,
        'nombre':   request.user.get_full_name() or request.user.username,
        'email':    request.user.email,
        'cargo':    '',
        'dependencia': '',
        'activo':   True,
    })


# ─── VISITAS ─────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def visitas_list_create(request):
    """
    GET  → lista las visitas del funcionario autenticado.
    POST → crea una nueva visita (con soporte para sync offline).
    """
    if not _es_funcionario(request.user):
        return Response({'error': 'Sin permiso.'}, status=403)

    if request.method == 'GET':
        visitas = VisitaRIT.objects.filter(funcionario=request.user)
        serializer = VisitaRITListSerializer(visitas, many=True)
        return Response(serializer.data)

    # POST — crear visita
    # Si ya existe ese uuid_local, devolver el existente (idempotente para re-sync)
    uuid_local = request.data.get('uuid_local')
    if uuid_local:
        existente = VisitaRIT.objects.filter(uuid_local=uuid_local).first()
        if existente:
            existente.estado = 'sincronizado'
            existente.sincronizado_en = timezone.now()
            existente.save(update_fields=['estado', 'sincronizado_en'])
            return Response(VisitaRITSerializer(existente).data, status=200)

    serializer = VisitaRITSerializer(data=request.data, context={'request': request})
    if serializer.is_valid():
        motivo = request.data.get('motivo_no_atencion')
        estado_enviado = request.data.get('estado', '')
        if motivo:
            estado_final = 'no_atendida'
        elif estado_enviado == 'incompleta':
            estado_final = 'incompleta'
        else:
            estado_final = 'sincronizado'
        try:
            visita = serializer.save(estado=estado_final, sincronizado_en=timezone.now())
            if estado_final == 'incompleta':
                from tasks.views import _vincular_usuario_visita_incompleta
                _vincular_usuario_visita_incompleta(visita)
            return Response(VisitaRITSerializer(visita).data, status=201)
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).error(
                'visitas_list_create: error guardando visita: %s', _exc, exc_info=True)
            return Response({'error': 'Error interno al guardar la visita.',
                             'detalle': str(_exc)}, status=500)

    return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def visita_detalle(request, pk):
    """Detalle completo de una visita incluyendo fotos."""
    try:
        visita = VisitaRIT.objects.get(pk=pk, funcionario=request.user)
    except VisitaRIT.DoesNotExist:
        return Response({'error': 'No encontrada.'}, status=404)

    return Response(VisitaRITSerializer(visita).data)


# ─── FOTOS ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def subir_fotos(request, pk):
    """
    Sube una o varias fotos a una visita existente.
    Se puede llamar múltiples veces (para subir foto por foto desde la app).
    """
    try:
        visita = VisitaRIT.objects.get(pk=pk, funcionario=request.user)
    except VisitaRIT.DoesNotExist:
        return Response({'error': 'Visita no encontrada.'}, status=404)

    imagenes = request.FILES.getlist('imagenes')
    if not imagenes:
        return Response({'error': 'No se recibieron imágenes.'}, status=400)

    orden_base = visita.fotos.count()
    fotos_creadas = []
    for i, img in enumerate(imagenes):
        foto = FotoVisita.objects.create(
            visita=visita,
            imagen=img,
            descripcion=request.data.get('descripcion', ''),
            orden=orden_base + i,
        )
        fotos_creadas.append(FotoVisitaSerializer(foto, context={'request': request}).data)

    return Response({'fotos': fotos_creadas, 'total': visita.fotos.count()}, status=201)


# ─── SYNC BATCH ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def sync_batch(request):
    """
    Recibe una lista de visitas pendientes desde la app (modo offline).
    Guarda las nuevas y devuelve el resultado por uuid_local.
    """
    if not _es_funcionario(request.user):
        return Response({'error': 'Sin permiso.'}, status=403)

    visitas_data = request.data.get('visitas', [])
    if not isinstance(visitas_data, list):
        return Response({'error': 'Se esperaba una lista de visitas.'}, status=400)

    resultados = []
    for item in visitas_data:
        uuid_local = item.get('uuid_local')
        existente = VisitaRIT.objects.filter(uuid_local=uuid_local).first() if uuid_local else None

        if existente:
            resultados.append({'uuid_local': uuid_local, 'id': existente.id,
                               'estado': 'ya_existia', 'estado_visita': existente.estado})
            continue

        serializer = VisitaRITSerializer(data=item, context={'request': request})
        if serializer.is_valid():
            if item.get('motivo_no_atencion'):
                estado_final = 'no_atendida'
            elif item.get('estado') == 'incompleta':
                estado_final = 'incompleta'
            else:
                estado_final = 'sincronizado'
            try:
                visita = serializer.save(estado=estado_final, sincronizado_en=timezone.now())
                if estado_final == 'incompleta':
                    from tasks.views import _vincular_usuario_visita_incompleta
                    _vincular_usuario_visita_incompleta(visita)
                resultados.append({'uuid_local': uuid_local, 'id': visita.id,
                                   'estado': 'creado', 'estado_visita': visita.estado})
            except Exception as _exc:
                import logging as _log
                _log.getLogger(__name__).error(
                    'sync_batch: error guardando visita %s: %s', uuid_local, _exc, exc_info=True)
                resultados.append({'uuid_local': uuid_local, 'estado': 'error',
                                   'errores': {'__all__': [str(_exc)]}})
        else:
            resultados.append({'uuid_local': uuid_local, 'errores': serializer.errors, 'estado': 'error'})

    return Response({'resultados': resultados})


# ─── CATÁLOGOS ────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def actividades_economicas(request):
    """Lista todas las actividades económicas activas."""
    actividades = ActividadEconomica.objects.filter(activo=True).order_by('codigo')
    data = [
        {'codigo': a.codigo, 'nombre': a.nombre, 'tipo': a.tipo}
        for a in actividades
    ]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def municipios(request):
    """Lista municipios activos, filtrables por ?q= para autocompletar."""
    q = request.GET.get('q', '').strip()
    qs = Municipio.objects.filter(activo=True).select_related('departamento').order_by('nombre')
    if q:
        qs = qs.filter(nombre__icontains=q)
    data = [
        {'id': m.id, 'nombre': m.nombre, 'departamento': m.departamento.nombre}
        for m in qs[:50]
    ]
    return Response(data)


# ─── VISITAS PRECARGADAS ──────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def precargadas_list(request):
    """
    Lista las visitas precargadas (pendientes de realizar) asignadas al funcionario.
    Estas son creadas desde el portal web (carga masiva desde archivo).
    """
    if not _es_funcionario(request.user):
        return Response({'error': 'Sin permiso.'}, status=403)

    visitas = VisitaRIT.objects.filter(
        funcionario=request.user,
        estado='precargada'
    ).order_by('nombre_establecimiento')

    data = [
        {
            'id':                    v.id,
            'nombre_establecimiento': v.nombre_establecimiento,
            'nombre_propietario':    v.nombre_propietario,
            'numero_documento':      v.numero_documento,
            'tipo_documento':        v.tipo_documento,
            'direccion':             v.direccion,
            'municipio':             v.municipio,
            'telefono':              v.telefono,
            'correo':                v.correo,
            'actividad_economica':   v.actividad_economica,
            'descripcion_actividad': v.descripcion_actividad,
        }
        for v in visitas
    ]
    return Response({'precargadas': data, 'total': len(data)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def completar_precargada(request, pk):
    """
    Convierte una visita precargada en una visita real.
    El funcionario confirma/corrige los datos y añade observaciones, GPS y firma.
    """
    if not _es_funcionario(request.user):
        return Response({'error': 'Sin permiso.'}, status=403)

    try:
        visita = VisitaRIT.objects.get(pk=pk, funcionario=request.user, estado='precargada')
    except VisitaRIT.DoesNotExist:
        return Response({'error': 'Visita precargada no encontrada.'}, status=404)

    # Actualizar campos con los datos enviados desde la app (confirmar/corregir)
    campos_editables = [
        'nombre_establecimiento', 'nombre_propietario', 'numero_documento', 'tipo_documento',
        'direccion', 'municipio', 'telefono', 'correo',
        'actividad_economica', 'descripcion_actividad',
        'latitud', 'longitud', 'precision_gps',
        'observaciones', 'firma_contribuyente', 'firma_tipo', 'firma_funcionario',
        'motivo_no_atencion', 'motivo_descripcion',
    ]
    for campo in campos_editables:
        if campo in request.data:
            setattr(visita, campo, request.data[campo])

    motivo = request.data.get('motivo_no_atencion', visita.motivo_no_atencion)
    estado_enviado = request.data.get('estado', '')
    if motivo:
        visita.estado = 'no_atendida'
    elif estado_enviado == 'incompleta':
        visita.estado = 'incompleta'
    else:
        visita.estado = 'sincronizado'
    visita.sincronizado_en = timezone.now()
    visita.save()

    # Homologar a RegistroRIT si fue atendida y tiene contribuyente
    if visita.estado == 'sincronizado' and visita.contribuyente and not visita.registro_rit:
        try:
            from tasks.models import RegistroRIT, EstablecimientoRIT, ActividadEconomicaRIT
            from catalogos.models import ActividadEconomica, Municipio as MuniModel

            muni_obj = MuniModel.objects.filter(
                nombre__iexact=visita.municipio, activo=True
            ).first() if visita.municipio else None

            rit = RegistroRIT.objects.create(
                user=visita.contribuyente,
                radicado=RegistroRIT.generar_radicado(),
                opcion_uso='INSCRIPCION',
                estado='ACTIVO',
                nombre_razon_social=visita.nombre_propietario or '',
                tipo_documento=visita.tipo_documento or 'CC',
                numero_documento=visita.numero_documento or '',
                correo_electronico=visita.correo or '',
                telefono=visita.telefono or '',
                direccion_notificacion=visita.direccion or '',
                municipio_notificacion=muni_obj,
                firma_otp_verificada=(visita.firma_tipo != 'OTP'),
            )
            if visita.nombre_establecimiento:
                EstablecimientoRIT.objects.create(
                    rit=rit, nombre=visita.nombre_establecimiento,
                    direccion=visita.direccion or '-',
                    telefono=visita.telefono or '',
                    fecha_inicio_actividades=visita.fecha_visita.date(),
                )
            if visita.actividad_economica:
                act = ActividadEconomica.objects.filter(
                    codigo=visita.actividad_economica, activo=True
                ).first()
                if act:
                    ActividadEconomicaRIT.objects.create(
                        rit=rit, actividad=act, base_gravable_mensual=0
                    )
            visita.registro_rit = rit
            visita.save(update_fields=['registro_rit'])
        except Exception:
            pass

    return Response({
        'id':     visita.id,
        'estado': visita.estado,
        'radicado_rit': visita.registro_rit.radicado if visita.registro_rit else None,
    })


# ─── OTP FIRMA ───────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def enviar_otp_visita(request, pk):
    """Genera y envía el código OTP de firma para una visita RIT."""
    try:
        visita = VisitaRIT.objects.get(pk=pk, funcionario=request.user)
    except VisitaRIT.DoesNotExist:
        return Response({'error': 'Visita no encontrada.'}, status=404)

    if not visita.registro_rit:
        return Response({'error': 'La visita no tiene registro RIT asociado.'}, status=400)

    correo = visita.correo or (visita.contribuyente.email if visita.contribuyente else '')
    if not correo:
        return Response({'error': 'La visita no tiene correo para enviar el OTP.'}, status=400)

    import random
    from tasks.models import FirmaOTPRIT
    from django.conf import settings as cfg
    from tasks.views import _enviar_emailjs

    codigo = ''.join([str(random.randint(0, 9)) for _ in range(6)])

    # Invalidar OTPs anteriores y crear el nuevo
    FirmaOTPRIT.objects.filter(registro=visita.registro_rit, usado=False).update(usado=True)
    FirmaOTPRIT.objects.create(registro=visita.registro_rit, codigo=codigo, tipo='declarante')

    enviado = _enviar_emailjs(
        cfg.EMAILJS_TEMPLATE_OTP,
        correo,
        {
            'to_name':        visita.nombre_propietario or correo,
            'codigo':         codigo,
            'radicado':       visita.registro_rit.radicado or '',
            'tipo_formulario': 'RIT',
        }
    )

    if enviado:
        return Response({'ok': True, 'correo': correo})
    return Response({'ok': False, 'error': 'No se pudo enviar el correo.'}, status=503)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([JSONParser])
def verificar_otp_visita(request, pk):
    """Verifica el código OTP, marca la firma y envía credenciales al contribuyente."""
    try:
        visita = VisitaRIT.objects.get(pk=pk, funcionario=request.user)
    except VisitaRIT.DoesNotExist:
        return Response({'error': 'Visita no encontrada.'}, status=404)

    codigo = str(request.data.get('codigo', '')).strip()
    if not codigo:
        return Response({'error': 'Código requerido.'}, status=400)

    if not visita.registro_rit:
        return Response({'error': 'La visita no tiene registro RIT asociado.'}, status=400)

    from tasks.models import FirmaOTPRIT
    from django.utils import timezone as tz
    from datetime import timedelta

    limite = tz.now() - timedelta(minutes=15)
    otp = FirmaOTPRIT.objects.filter(
        registro=visita.registro_rit,
        codigo=codigo,
        usado=False,
        creado_en__gte=limite,
    ).first()

    if not otp:
        return Response({'ok': False, 'error': 'Código incorrecto o expirado.'}, status=400)

    otp.usado = True
    otp.save()

    import hashlib as _hashlib
    rit = visita.registro_rit
    rit.firma_otp_verificada = True
    rit.estado = 'ACTIVO'
    rit.firma_timestamp = timezone.now()
    _hash_data = f"RIT|{rit.id}|{rit.radicado}|{rit.numero_documento}|{rit.firma_timestamp.isoformat()}"
    rit.firma_hash = _hashlib.sha256(_hash_data.encode()).hexdigest()
    rit.save(update_fields=['firma_otp_verificada', 'estado', 'firma_timestamp', 'firma_hash'])

    # Enviar credenciales al contribuyente siempre que se verifique el OTP
    if visita.contribuyente:
        import random, string as _str
        from django.conf import settings as cfg
        from tasks.views import _enviar_emailjs
        from tasks.models import PerfilContribuyente
        nueva_pass = ''.join(random.choices(_str.ascii_letters + _str.digits, k=10))
        visita.contribuyente.set_password(nueva_pass)
        visita.contribuyente.save()
        # Activar cambio de contraseña obligatorio al primer login
        try:
            perfil = visita.contribuyente.perfil
            perfil.must_change_password = True
            perfil.save(update_fields=['must_change_password'])
        except Exception:
            pass
        correo_destino = visita.contribuyente.email or visita.correo
        if correo_destino:
            _enviar_emailjs(
                cfg.EMAILJS_TEMPLATE_CREDENCIALES,
                correo_destino,
                {
                    'to_name':    visita.nombre_propietario or correo_destino,
                    'usuario':    correo_destino,
                    'contrasena': nueva_pass,
                    'portal_url': 'https://segovia.portalterritorial.com.co',
                }
            )

    return Response({'ok': True, 'radicado': rit.radicado})


# ─── CENSO DE ESTABLECIMIENTOS ────────────────────────────────────────────────

_censo_cache: dict = {}  # {nit: [lista de establecimientos]}


import logging as _logging
_censo_log = _logging.getLogger('api_movil.censo')


def _cargar_censo() -> dict:
    """Lee el archivo Excel cargado vía admin y devuelve dict {nit: [estabs]}."""
    global _censo_cache
    try:
        config = CensoEstablecimientos.objects.order_by('-actualizado').first()
        if not config:
            _censo_log.warning('[censo] No hay archivo cargado en el admin.')
            return {}
        ruta = config.archivo.path
        ext  = ruta.rsplit('.', 1)[-1].lower()
        _censo_log.info('[censo] Leyendo %s (ext=%s)', ruta, ext)

        if ext == 'xls':
            import xlrd
            wb = xlrd.open_workbook(ruta)
            sh = wb.sheet_by_index(0)
            headers = [str(c or '').strip().lower() for c in sh.row_values(0)]
            filas   = [sh.row_values(r) for r in range(1, sh.nrows)]
        else:
            import openpyxl
            wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
            sh = wb.active
            rows    = list(sh.iter_rows(min_row=1, values_only=True))
            headers = [str(c or '').strip().lower() for c in rows[0]]
            filas   = rows[1:]

        _censo_log.info('[censo] Headers detectados: %s', headers[:10])

        # Encontrar índices por nombre de columna (tolerante a variaciones)
        def _col(*names):
            for name in names:
                for i, h in enumerate(headers):
                    if name in h:
                        return i
            return None

        i_nit  = _col('nit')
        i_nest = _col('nombre establecimiento', 'nombre_establecimiento', 'establecimiento')
        i_nom  = _col('primer nombre', 'primer_nombre', 'nombre')
        i_ap1  = _col('primer apellido', 'primer_apellido')
        i_ap2  = _col('segundo apellido', 'segundo_apellido')
        i_dir  = _col('direccion', 'dirección', 'direcci')
        i_tel  = _col('telefono', 'teléfono', 'celular')
        i_cod  = _col('codigo_act_eco', 'cod_act', 'codigo act', 'código actividad')
        i_act  = _col('actividad_economica', 'actividad economica', 'actividad')
        i_est  = _col('estado')

        _censo_log.info('[censo] Columnas → nit=%s nest=%s nom=%s ap1=%s ap2=%s dir=%s tel=%s cod=%s',
                        i_nit, i_nest, i_nom, i_ap1, i_ap2, i_dir, i_tel, i_cod)

        if i_nit is None:
            # Fallback: asumir que columna 0 = nit
            i_nit = 0
            _censo_log.warning('[censo] No se encontró columna NIT, usando índice 0')

        def _val(row, i, es_nit=False):
            if i is None or i >= len(row):
                return ''
            v = str(row[i] or '').strip()
            return v.split('.')[0] if es_nit else v

        cache: dict = {}
        for row in filas:
            nit = _val(row, i_nit, es_nit=True)
            if not nit:
                continue
            nombre_prop = ' '.join(filter(None, [
                _val(row, i_nom),
                _val(row, i_ap1),
                _val(row, i_ap2),
            ]))
            entry = {
                'nombre_establecimiento': _val(row, i_nest),
                'nombre_propietario':     nombre_prop,
                'codigo_act_eco':         _val(row, i_cod),
                'actividad_economica':    _val(row, i_act),
                'direccion':              _val(row, i_dir),
                'telefono':               _val(row, i_tel),
                'estado':                 _val(row, i_est),
            }
            cache.setdefault(nit, []).append(entry)

        _censo_log.info('[censo] Cargados %d NITs únicos de %d filas', len(cache), len(filas))
        _censo_cache = cache
        return cache
    except Exception as exc:
        _censo_log.error('[censo] Error cargando Excel: %s', exc, exc_info=True)
        return {}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def consultar_nit(request):
    """
    Consulta un NIT/documento en el censo y verifica si ya está registrado en el portal.
    Query param: ?doc=1234567
    """
    import re
    raw = request.GET.get('doc', '').strip()
    # Normalizar: quitar puntos/espacios y el DV separado por guión o punto
    doc = re.sub(r'[\s.]', '', raw).split('-')[0]
    if not doc:
        return Response({'error': 'Parámetro doc requerido'}, status=400)

    from tasks.models import PerfilContribuyente, RegistroRIT
    registrado_portal = (
        PerfilContribuyente.objects.filter(numero_documento=doc).exists()
        or RegistroRIT.objects.filter(
            numero_documento=doc,
            estado__in=('ACTIVO', 'PENDIENTE_FIRMA'),
        ).exists()
    )

    cache = _censo_cache if _censo_cache else _cargar_censo()
    establecimientos = cache.get(doc, [])

    return Response({
        'registrado_portal': registrado_portal,
        'establecimientos':  establecimientos,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def catalogo_censo(request):
    """Descarga el catálogo completo del censo para caché offline en la app móvil."""
    cache = _censo_cache if _censo_cache else _cargar_censo()
    resultado = [
        {'nit': nit, **e}
        for nit, estabs in cache.items()
        for e in estabs
    ]
    return Response(resultado)
