from rest_framework import serializers
from django.contrib.auth.models import User
from .models import VisitaRIT, FotoVisita, PerfilFuncionario


class FotoVisitaSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FotoVisita
        fields = ['id', 'imagen', 'descripcion', 'orden', 'subida_en']
        read_only_fields = ['id', 'subida_en']


class VisitaRITSerializer(serializers.ModelSerializer):
    fotos       = FotoVisitaSerializer(many=True, read_only=True)
    funcionario = serializers.StringRelatedField(read_only=True)

    class Meta:
        model  = VisitaRIT
        fields = [
            'id', 'uuid_local', 'funcionario',
            'nombre_establecimiento', 'nombre_propietario',
            'numero_documento', 'tipo_documento',
            'direccion', 'municipio', 'telefono', 'correo',
            'actividad_economica', 'descripcion_actividad',
            'latitud', 'longitud', 'precision_gps',
            'observaciones', 'firma_contribuyente', 'firma_tipo', 'firma_funcionario',
            'motivo_no_atencion', 'motivo_descripcion',
            'estado', 'fecha_visita', 'creado_en', 'sincronizado_en',
            'fotos',
        ]
        read_only_fields = ['id', 'funcionario', 'creado_en', 'sincronizado_en', 'estado']

    def create(self, validated_data):
        import random, string
        from django.contrib.auth.models import Group

        validated_data['funcionario'] = self.context['request'].user

        # Visita no atendida: no crear cuenta ni RIT
        if validated_data.get('motivo_no_atencion'):
            validated_data['contribuyente'] = None
            return super().create(validated_data)

        correo = validated_data.get('correo', '').strip().lower()
        numero_documento = validated_data.get('numero_documento', '').strip()
        nombre = validated_data.get('nombre_propietario', '') or correo

        contribuyente_user = None
        es_cuenta_nueva = False
        temp_password = None

        from tasks.models import PerfilContribuyente

        # Buscar por correo primero
        if correo:
            contribuyente_user = (
                User.objects.filter(username=correo).first()
                or User.objects.filter(email=correo).first()
            )

        # Si no hay correo o no se encontró, buscar por número de documento
        if not contribuyente_user and numero_documento:
            perfil_doc = PerfilContribuyente.objects.filter(
                numero_documento=numero_documento
            ).select_related('user').first()
            if perfil_doc:
                contribuyente_user = perfil_doc.user

        # Municipio de la visita (para PerfilContribuyente)
        from catalogos.models import Municipio as _Municipio
        muni_nombre_v = validated_data.get('municipio', '')
        municipio_perfil = (
            _Municipio.objects.filter(nombre__iexact=muni_nombre_v, activo=True).first()
            if muni_nombre_v else None
        ) or _Municipio.objects.filter(activo=True).first()

        if contribuyente_user:
            # Usuario existente: asegurar que tenga PerfilContribuyente
            if not PerfilContribuyente.objects.filter(user=contribuyente_user).exists():
                es_cuenta_nueva = True
                temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                contribuyente_user.set_password(temp_password)
                contribuyente_user.save()
                try:
                    contribuyente_user.groups.add(Group.objects.get(name='CONTRIBUYENTE'))
                except Group.DoesNotExist:
                    pass
                try:
                    perfil = PerfilContribuyente(
                        user=contribuyente_user,
                        nombre_razon_social=nombre,
                        tipo_documento=validated_data.get('tipo_documento') or 'CC',
                        numero_documento=numero_documento,
                        correo_electronico=correo or contribuyente_user.email,
                        telefono=validated_data.get('telefono') or '',
                        direccion_notificacion=validated_data.get('direccion') or '-',
                        municipio_notificacion=municipio_perfil,
                        clasificacion_contribuyente='REGIMEN_COMUN',
                        tipo_persona='NATURAL',
                        must_change_password=True,
                    )
                    perfil.asignar_departamento_notificacion()
                    perfil.save()
                except Exception:
                    pass
        elif correo:
            # Crear nuevo usuario
            es_cuenta_nueva = True
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            contribuyente_user = User.objects.create_user(
                username=correo,
                email=correo,
                password=temp_password,
                first_name=nombre,
            )
            try:
                contribuyente_user.groups.add(Group.objects.get(name='CONTRIBUYENTE'))
            except Group.DoesNotExist:
                pass

            # Crear PerfilContribuyente con todos los datos disponibles de la visita
            try:
                perfil = PerfilContribuyente(
                    user=contribuyente_user,
                    nombre_razon_social=nombre,
                    tipo_documento=validated_data.get('tipo_documento') or 'CC',
                    numero_documento=numero_documento,
                    correo_electronico=correo,
                    telefono=validated_data.get('telefono') or '',
                    direccion_notificacion=validated_data.get('direccion') or '-',
                    municipio_notificacion=municipio_perfil,
                    clasificacion_contribuyente='REGIMEN_COMUN',
                    tipo_persona='NATURAL',
                    must_change_password=True,
                )
                perfil.asignar_departamento_notificacion()
                perfil.save()
            except Exception:
                pass

            # Habilitar solo RIT al crear desde visita móvil
            try:
                from tasks.models import Proceso, AccesoProceso
                p_rit = Proceso.objects.filter(codigo='RIT').first()
                if p_rit:
                    AccesoProceso.objects.get_or_create(
                        user=contribuyente_user, proceso=p_rit,
                        defaults={'habilitado': True}
                    )
                for cod in ('ICA', 'AUTO'):
                    p = Proceso.objects.filter(codigo=cod).first()
                    if p:
                        AccesoProceso.objects.update_or_create(
                            user=contribuyente_user, proceso=p,
                            defaults={'habilitado': False}
                        )
            except Exception:
                pass


        validated_data['contribuyente'] = contribuyente_user
        visita = super().create(validated_data)

        # Crear RegistroRIT de Inscripción a partir de la visita
        if contribuyente_user:
            try:
                from tasks.models import RegistroRIT, EstablecimientoRIT, ActividadEconomicaRIT
                from catalogos.models import ActividadEconomica, Municipio
                from django.utils import timezone as tz

                # Buscar municipio por nombre si existe
                muni_nombre = validated_data.get('municipio', '')
                municipio_obj = None
                if muni_nombre:
                    municipio_obj = Municipio.objects.filter(
                        nombre__iexact=muni_nombre, activo=True
                    ).first()

                # Si ya tiene un RIT activo o pendiente, no crear duplicado
                rit_existente = RegistroRIT.objects.filter(
                    user=contribuyente_user,
                    opcion_uso='INSCRIPCION',
                    estado__in=('ACTIVO', 'PENDIENTE_FIRMA'),
                ).first()
                if rit_existente:
                    fields_to_update = []
                    # Reparar radicado si quedó vacío por código anterior
                    if not rit_existente.radicado:
                        rit_existente.radicado = RegistroRIT.generar_radicado()
                        fields_to_update.append('radicado')
                    firma_tipo = validated_data.get('firma_tipo', 'DIBUJO')
                    if firma_tipo != 'OTP' and rit_existente.estado == 'PENDIENTE_FIRMA':
                        from django.utils import timezone as _tz
                        rit_existente.estado = 'ACTIVO'
                        rit_existente.firma_otp_verificada = True
                        rit_existente.firma_timestamp = _tz.now()
                        fields_to_update += ['estado', 'firma_otp_verificada', 'firma_timestamp']
                    if fields_to_update:
                        rit_existente.save(update_fields=fields_to_update)
                    visita.registro_rit = rit_existente
                    visita.save(update_fields=['registro_rit'])
                    return visita

                # Si firmó dibujando en pantalla → ya verificada; si es OTP → pendiente
                firma_tipo = validated_data.get('firma_tipo', 'DIBUJO')
                rit = RegistroRIT.objects.create(
                    user=contribuyente_user,
                    radicado=RegistroRIT.generar_radicado(),
                    opcion_uso='INSCRIPCION',
                    nombre_razon_social=nombre,
                    tipo_documento=validated_data.get('tipo_documento') or 'CC',
                    numero_documento=validated_data.get('numero_documento') or '',
                    correo_electronico=correo,
                    telefono=validated_data.get('telefono') or '',
                    direccion_notificacion=validated_data.get('direccion') or '',
                    municipio_notificacion=municipio_obj,
                )
                # save() fuerza PENDIENTE_FIRMA en creación; si el contribuyente ya
                # firmó con dibujo en pantalla, pasar a ACTIVO de inmediato.
                if firma_tipo != 'OTP':
                    from django.utils import timezone as _tz
                    rit.firma_otp_verificada = True
                    rit.estado = 'ACTIVO'
                    rit.firma_timestamp = _tz.now()
                    rit.save(update_fields=['firma_otp_verificada', 'estado', 'firma_timestamp'])

                # Establecimiento
                nombre_est = validated_data.get('nombre_establecimiento', '')
                dir_est = validated_data.get('direccion', '')
                if nombre_est:
                    EstablecimientoRIT.objects.create(
                        rit=rit,
                        nombre=nombre_est,
                        direccion=dir_est or '-',
                        telefono=validated_data.get('telefono') or '',
                        fecha_inicio_actividades=visita.fecha_visita.date(),
                    )

                # Actividad económica
                cod_act = validated_data.get('actividad_economica', '')
                if cod_act:
                    act_obj = ActividadEconomica.objects.filter(codigo=cod_act, activo=True).first()
                    if act_obj:
                        ActividadEconomicaRIT.objects.create(
                            rit=rit,
                            actividad=act_obj,
                            base_gravable_mensual=0,
                        )

                # Vincular el RIT a la visita
                visita.registro_rit = rit
                visita.save(update_fields=['registro_rit'])

            except Exception:
                pass

        # Enviar email cuando se crea cuenta nueva O cuando hay un RIT pendiente
        _tiene_rit_pendiente = bool(
            visita.registro_rit_id
            and getattr(visita.registro_rit, 'estado', '') == 'PENDIENTE_FIRMA'
        )
        if correo and contribuyente_user and (es_cuenta_nueva or _tiene_rit_pendiente):
            try:
                from django.conf import settings as cfg
                from tasks.views import _enviar_emailjs
                import logging as _logging
                radicado_rit = ''
                if visita.registro_rit_id:
                    radicado_rit = getattr(visita.registro_rit, 'radicado', '') or ''
                _enviar_emailjs(
                    cfg.EMAILJS_TEMPLATE_CREDENCIALES,
                    correo,
                    {
                        'to_name':    nombre,
                        'usuario':    correo,
                        'contrasena': temp_password or '',
                        'portal_url': 'https://segovia.portalterritorial.com.co',
                        'radicado':   radicado_rit,
                    },
                )
            except Exception as _e:
                import logging as _log
                _log.getLogger(__name__).error('Email bienvenida fallo para %s: %s', correo, _e)

        return visita


class VisitaRITListSerializer(serializers.ModelSerializer):
    """Versión resumida para el listado."""
    fotos_count = serializers.IntegerField(source='fotos.count', read_only=True)

    class Meta:
        model  = VisitaRIT
        fields = [
            'id', 'uuid_local', 'nombre_establecimiento',
            'direccion', 'fecha_visita', 'estado', 'fotos_count',
        ]


class PerfilFuncionarioSerializer(serializers.ModelSerializer):
    username   = serializers.CharField(source='user.username', read_only=True)
    nombre     = serializers.SerializerMethodField()
    email      = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model  = PerfilFuncionario
        fields = ['username', 'nombre', 'email', 'cargo', 'dependencia', 'activo']

    def get_nombre(self, obj):
        return obj.user.get_full_name() or obj.user.username


class LoginResponseSerializer(serializers.Serializer):
    """Solo para documentación del response de login."""
    access  = serializers.CharField()
    refresh = serializers.CharField()
    usuario = serializers.CharField()
    nombre  = serializers.CharField()
    cargo   = serializers.CharField()
