from django.db import models
from django.conf import settings
from django.db.models import Q


class Task(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    important = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class PerfilContribuyente(models.Model):
    """
    Perfil del contribuyente que se llena al registrarse.
    Estos datos se pre-llenan en formularios como ICA y RIT.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil'
    )

    # Datos de identificación
    nombre_razon_social = models.CharField(
        max_length=255,
        verbose_name="Nombres y apellidos o razón social"
    )

    TIPO_DOCUMENTO_CHOICES = (
        ("CC", "Cédula de ciudadanía"),
        ("NIT", "NIT"),
        ("PASAPORTE", "Pasaporte"),
        ("CE", "Cédula de extranjería"),
        ("OTRO", "Otro"),
    )
    tipo_documento = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_CHOICES,
        verbose_name="Tipo de documento"
    )
    numero_documento = models.CharField(
        max_length=30,
        verbose_name="Número de documento"
    )
    dv = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        verbose_name="DV",
        help_text="Solo aplica para NIT"
    )
    cual_documento = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        verbose_name="Cuál documento",
        help_text="Solo aplica si tipo de documento es OTRO"
    )

    # Datos de contacto
    direccion_notificacion = models.CharField(
        max_length=255,
        verbose_name="Dirección de notificación"
    )
    municipio_notificacion = models.ForeignKey(
        "catalogos.Municipio",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="perfiles_contribuyente",
        verbose_name="Municipio de notificación"
    )
    departamento_notificacion = models.ForeignKey(
        "catalogos.Departamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="perfiles_contribuyente",
        verbose_name="Departamento"
    )
    telefono = models.CharField(
        max_length=30,
        verbose_name="Teléfono"
    )
    correo_electronico = models.EmailField(
        verbose_name="Correo electrónico"
    )

    # Datos del negocio
    numero_establecimientos = models.PositiveIntegerField(
        default=1,
        verbose_name="Número de establecimientos"
    )

    CLASIFICACION_CONTRIBUYENTE_CHOICES = (
        ("REGIMEN_COMUN", "Régimen común de ICA"),
        ("REGIMEN_SIMPLE", "Régimen simplificado"),
        ("OTRA", "Otra"),
    )
    clasificacion_contribuyente = models.CharField(
        max_length=30,
        choices=CLASIFICACION_CONTRIBUYENTE_CHOICES,
        verbose_name="Clasificación contribuyente"
    )
    otra_clasificacion = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        verbose_name="Otra clasificación",
        help_text="Solo aplica si clasificación es Otra"
    )

    # Tipo de persona
    tipo_persona = models.CharField(
        max_length=10,
        choices=[("NATURAL", "Natural"), ("JURIDICA", "Jurídica")],
        verbose_name="Tipo de persona"
    )
    tipo_juridica = models.CharField(
        max_length=30,
        choices=[
            ("SOCIEDAD", "Sociedad"),
            ("CONSORCIO", "Consorcio"),
            ("UNION_TEMPORAL", "Unión temporal"),
            ("PATRIMONIO_AUTONOMO", "Patrimonio autónomo"),
            ("OTRO", "Otro"),
        ],
        blank=True,
        null=True,
        verbose_name="Tipo jurídica"
    )
    otro_tipo_juridica = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Otro tipo jurídico",
        help_text="Solo aplica si tipo jurídica es Otro"
    )

    must_change_password = models.BooleanField(
        default=False,
        verbose_name="Debe cambiar contraseña"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def asignar_departamento_notificacion(self):
        """Asigna automáticamente el departamento desde el municipio seleccionado."""
        if self.municipio_notificacion_id:
            self.departamento_notificacion = self.municipio_notificacion.departamento

    def __str__(self):
        return f"Perfil de {self.user.username} - {self.nombre_razon_social}"

    class Meta:
        verbose_name = "Perfil de Contribuyente"
        verbose_name_plural = "Perfiles de Contribuyentes"


class Proceso(models.Model):
    codigo = models.CharField(max_length=50, unique=True)  # ej: "ICA"
    nombre = models.CharField(max_length=100)  # ej: "Declaración ICA"
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class AccesoProceso(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    proceso = models.ForeignKey(Proceso, on_delete=models.CASCADE)
    habilitado = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "proceso")

    def __str__(self):
        username = getattr(self.user, "username", "Sin usuario")
        return f"{username} -> {self.proceso.codigo}"


class RegistroRIT(models.Model):
    """
    Registro de Información Tributaria (RIT).
    Copia los datos del perfil del contribuyente al momento de crear el registro.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    # Número de radicado único
    radicado = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Número de radicado"
    )

    @classmethod
    def generar_radicado(cls):
        """Genera un número de radicado único con formato RIT-AAAA-NNNNN"""
        from django.utils import timezone
        anio = timezone.now().year
        prefijo = f"RIT-{anio}-"

        # Buscar el último radicado del año actual
        ultimo = cls.objects.filter(
            radicado__startswith=prefijo
        ).order_by('-radicado').first()

        if ultimo and ultimo.radicado:
            try:
                ultimo_num = int(ultimo.radicado.split('-')[-1])
                nuevo_num = ultimo_num + 1
            except (ValueError, IndexError):
                nuevo_num = 1
        else:
            nuevo_num = 1

        return f"{prefijo}{nuevo_num:05d}"

    # =========================
    # SECCIÓN A: ENCABEZADO RIT
    # =========================
    OPCION_USO_CHOICES = (
        ("INSCRIPCION", "Inscripción"),
        ("ACTUALIZACION", "Actualización"),
        ("CANCELACION", "Cancelación"),
    )
    opcion_uso = models.CharField(
        max_length=15,
        choices=OPCION_USO_CHOICES,
        default="INSCRIPCION",
        verbose_name="Opción de uso"
    )

    # Estado del RIT (se actualiza automáticamente según opcion_uso)
    ESTADO_CHOICES = (
        ("PENDIENTE_FIRMA", "Pendiente de firma"),
        ("ACTIVO", "Activo"),
        ("CANCELADO", "Cancelado"),
    )
    estado = models.CharField(
        max_length=16,
        choices=ESTADO_CHOICES,
        default="PENDIENTE_FIRMA",
        verbose_name="Estado del RIT"
    )

    @classmethod
    def obtener_estado_usuario(cls, user):
        """
        Retorna el estado RIT del usuario:
        - 'SIN_RIT': No tiene ningún RIT inscrito
        - 'PENDIENTE_FIRMA': Tiene RIT guardado esperando firma OTP
        - 'ACTIVO': Tiene RIT activo firmado
        - 'CANCELADO': Último RIT está cancelado (puede inscribir uno nuevo)
        """
        ultimo_rit = cls.objects.filter(user=user).order_by('-fecha').first()
        if not ultimo_rit:
            return 'SIN_RIT'
        return ultimo_rit.estado

    @classmethod
    def get_rit_activo(cls, user):
        """Retorna el RIT activo (firmado) del usuario, o None si no tiene."""
        return cls.objects.filter(user=user, estado='ACTIVO').order_by('-fecha').first()

    @classmethod
    def get_rit_pendiente_firma(cls, user):
        """Retorna el RIT pendiente de firma del usuario, o None si no tiene."""
        return cls.objects.filter(user=user, estado='PENDIENTE_FIRMA').order_by('-fecha').first()

    CLASE_CONTRIBUYENTE_CHOICES = (
        ("ORDINARIO", "Ordinario"),
        ("ICA_SIMPLIFICADO", "ICA Simplificado"),
        ("OCASIONAL", "Ocasional"),
        ("ACTIVIDAD_INFORMAL", "Actividad Informal"),
        ("NO_SUJETO", "No Sujeto"),
    )
    clase_contribuyente = models.CharField(
        max_length=20,
        choices=CLASE_CONTRIBUYENTE_CHOICES,
        default="ORDINARIO",
        verbose_name="Tipo de contribuyente"
    )

    # Obligaciones tributarias
    es_retenedor_ica = models.BooleanField(
        default=False,
        verbose_name="Agente de Retención ICA"
    )
    es_autorretenedor_ica = models.BooleanField(
        default=False,
        verbose_name="Autorretenedor ICA"
    )

    # =========================
    # SECCIÓN B: CANCELACIÓN (solo si opcion_uso = CANCELACION)
    # =========================
    TIPO_CANCELACION_CHOICES = (
        ("TOTAL", "Total (queda sin establecimientos activos)"),
        ("PARCIAL", "Parcial (queda con establecimientos activos)"),
    )
    tipo_cancelacion = models.CharField(
        max_length=10,
        choices=TIPO_CANCELACION_CHOICES,
        blank=True,
        null=True,
        verbose_name="Tipo de cancelación"
    )

    MOTIVO_CANCELACION_CHOICES = (
        ("TRASPASO", "Traspaso (venta, fusión, herencia)"),
        ("TERMINACION", "Terminación del negocio"),
    )
    motivo_cancelacion = models.CharField(
        max_length=15,
        choices=MOTIVO_CANCELACION_CHOICES,
        blank=True,
        null=True,
        verbose_name="Motivo de cancelación"
    )

    # =========================
    # SECCIÓN C: INFORMACIÓN DEL CONTRIBUYENTE
    # =========================
    nombre_razon_social = models.CharField(
        max_length=255,
        verbose_name="Nombres y apellidos o razón social",
        default=""
    )

    TIPO_DOCUMENTO_CHOICES = (
        ("CC", "Cédula de ciudadanía"),
        ("NIT", "NIT"),
        ("PASAPORTE", "Pasaporte"),
        ("CE", "Cédula de extranjería"),
        ("OTRO", "Otro"),
    )
    tipo_documento = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_CHOICES,
        verbose_name="Tipo de documento",
        default="NIT"
    )
    numero_documento = models.CharField(
        max_length=30,
        verbose_name="Número de documento",
        default=""
    )
    dv = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        verbose_name="DV",
        help_text="Solo aplica para NIT"
    )
    cual_documento = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        verbose_name="Cuál documento",
        help_text="Solo aplica si tipo de documento es OTRO"
    )

    # Datos de contacto
    direccion_notificacion = models.CharField(
        max_length=255,
        verbose_name="Dirección de notificación",
        default=""
    )
    municipio_notificacion = models.ForeignKey(
        "catalogos.Municipio",
        on_delete=models.PROTECT,
        related_name="registros_rit",
        verbose_name="Municipio de notificación",
        null=True,
        blank=True
    )
    departamento_notificacion = models.ForeignKey(
        "catalogos.Departamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registros_rit",
        verbose_name="Departamento"
    )
    telefono = models.CharField(
        max_length=30,
        verbose_name="Celular",
        default=""
    )
    correo_electronico = models.EmailField(
        verbose_name="Correo electrónico",
        default=""
    )

    # Datos del negocio
    tiene_establecimientos = models.BooleanField(
        default=True,
        verbose_name="¿Tiene establecimientos?"
    )
    numero_establecimientos = models.PositiveIntegerField(
        default=1,
        verbose_name="Número de establecimientos"
    )

    CLASIFICACION_CONTRIBUYENTE_CHOICES = (
        ("REGIMEN_COMUN", "Régimen común de ICA"),
        ("REGIMEN_SIMPLE", "Régimen simplificado"),
        ("OTRA", "Otra"),
    )
    clasificacion_contribuyente = models.CharField(
        max_length=30,
        choices=CLASIFICACION_CONTRIBUYENTE_CHOICES,
        verbose_name="Clasificación contribuyente",
        default="REGIMEN_COMUN"
    )
    otra_clasificacion = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        verbose_name="Otra clasificación",
        help_text="Solo aplica si clasificación es Otra"
    )

    # Tipo de persona
    tipo_persona = models.CharField(
        max_length=10,
        choices=[("NATURAL", "Natural"), ("JURIDICA", "Jurídica")],
        verbose_name="Tipo de persona",
        default="NATURAL"
    )
    tipo_juridica = models.CharField(
        max_length=30,
        choices=[
            ("SOCIEDAD", "Sociedad"),
            ("CONSORCIO", "Consorcio"),
            ("UNION_TEMPORAL", "Unión temporal"),
            ("PATRIMONIO_AUTONOMO", "Patrimonio autónomo"),
            ("OTRO", "Otro"),
        ],
        blank=True,
        null=True,
        verbose_name="Tipo jurídica"
    )
    otro_tipo_juridica = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Otro tipo jurídico",
        help_text="Solo aplica si tipo jurídica es Otro"
    )

    fecha = models.DateTimeField(auto_now_add=True)

    # =========================
    # SECCIÓN G: FIRMAS
    # =========================
    firma_contribuyente = models.ImageField(
        upload_to="firmas/rit/contribuyente/",
        blank=True,
        null=True,
        verbose_name="Firma del contribuyente o representante legal"
    )
    firma_contribuyente_nombre = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Nombre del firmante"
    )
    firma_contribuyente_documento = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="Documento del firmante"
    )

    firma_funcionario = models.ImageField(
        upload_to="firmas/rit/funcionario/",
        blank=True,
        null=True,
        verbose_name="Firma del funcionario"
    )
    firma_funcionario_nombre = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Nombre del funcionario"
    )
    firma_funcionario_documento = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="Documento del funcionario"
    )
    fecha_recepcion = models.DateField(
        auto_now_add=True,
        verbose_name="Fecha de recepción"
    )

    # =========================
    # PDF FÍSICO (carga por alcaldía)
    # =========================
    pdf_fisico = models.FileField(
        upload_to='rit_fisicos/',
        blank=True,
        null=True,
        verbose_name="PDF físico escaneado",
        help_text="PDF del formulario RIT físico previamente firmado (solo alcaldía)"
    )

    # =========================
    # FIRMA ELECTRÓNICA OTP
    # =========================
    firma_otp_verificada = models.BooleanField(
        default=False,
        verbose_name="Firma OTP verificada"
    )
    firma_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha/hora de firma"
    )
    firma_hash = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name="Hash de firma"
    )

    def asignar_departamento_notificacion(self):
        """Asigna automáticamente el departamento desde el municipio seleccionado."""
        if self.municipio_notificacion_id:
            self.departamento_notificacion = self.municipio_notificacion.departamento

    def save(self, *args, **kwargs):
        """Auto-actualiza el estado según opcion_uso."""
        update_fields = kwargs.get('update_fields')
        # Solo modificar estado si no se están actualizando campos específicos
        if not update_fields or 'estado' in update_fields:
            if self.opcion_uso == "CANCELACION":
                self.estado = "CANCELADO"
                if self.user_id:
                    RegistroRIT.objects.filter(
                        user=self.user,
                        estado__in=("ACTIVO", "PENDIENTE_FIRMA"),
                    ).exclude(pk=self.pk).update(estado="CANCELADO")
            elif self.opcion_uso in ("INSCRIPCION", "ACTUALIZACION"):
                # Solo poner PENDIENTE_FIRMA si es un registro nuevo (sin pk aún)
                if not self.pk:
                    self.estado = "PENDIENTE_FIRMA"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"RIT - {self.numero_documento} - {self.nombre_razon_social}"

    class Meta:
        verbose_name = "Registro RIT"
        verbose_name_plural = "Registros RIT"


class RepresentanteLegalRIT(models.Model):
    """
    Sección D: Representación legal del RIT.
    """
    rit = models.ForeignKey(
        RegistroRIT,
        on_delete=models.CASCADE,
        related_name="representantes"
    )

    TIPO_REPRESENTANTE_CHOICES = (
        ("REPRESENTANTE_LEGAL", "Representante Legal"),
        ("REPRESENTANTE_SUPLENTE", "Representante Suplente"),
    )
    tipo_representante = models.CharField(
        max_length=25,
        choices=TIPO_REPRESENTANTE_CHOICES,
        default="REPRESENTANTE_LEGAL",
        verbose_name="Tipo"
    )

    nombre = models.CharField(
        max_length=200,
        verbose_name="Nombre completo"
    )
    TIPO_DOCUMENTO_CHOICES = (
        ("CC", "Cédula de ciudadanía"),
        ("CE", "Cédula de extranjería"),
        ("PASAPORTE", "Pasaporte"),
    )
    tipo_documento = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_CHOICES,
        verbose_name="Tipo de documento"
    )
    numero_documento = models.CharField(
        max_length=30,
        verbose_name="Número de documento"
    )
    correo_electronico = models.EmailField(
        verbose_name="Correo electrónico"
    )
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["orden"]
        verbose_name = "Representante Legal"
        verbose_name_plural = "Representantes Legales"

    def __str__(self):
        return f"{self.nombre} - {self.numero_documento}"


class EstablecimientoRIT(models.Model):
    """
    Sección E: Establecimientos del RIT.
    """
    rit = models.ForeignKey(
        RegistroRIT,
        on_delete=models.CASCADE,
        related_name="establecimientos"
    )
    nombre = models.CharField(
        max_length=200,
        verbose_name="Nombre del establecimiento"
    )
    direccion = models.CharField(
        max_length=255,
        verbose_name="Dirección"
    )
    telefono = models.CharField(
        max_length=30,
        verbose_name="Teléfono"
    )
    fecha_inicio_actividades = models.DateField(
        verbose_name="Fecha de inicio de actividades"
    )
    tiene_avisos_tableros = models.BooleanField(
        default=False,
        verbose_name="¿Tiene avisos y tableros?"
    )
    # Para cancelación parcial
    fecha_cancelacion = models.DateField(
        blank=True,
        null=True,
        verbose_name="Fecha de cancelación"
    )
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["orden"]
        verbose_name = "Establecimiento"
        verbose_name_plural = "Establecimientos"

    def __str__(self):
        return f"{self.nombre} - {self.direccion}"


class ActividadEconomicaRIT(models.Model):
    """
    Sección F: Actividades económicas del RIT.
    """
    rit = models.ForeignKey(
        RegistroRIT,
        on_delete=models.CASCADE,
        related_name="actividades_rit"
    )
    establecimiento = models.ForeignKey(
        EstablecimientoRIT,
        on_delete=models.CASCADE,
        related_name="actividades",
        null=True,
        blank=True,
        verbose_name="Establecimiento",
    )
    actividad = models.ForeignKey(
        "catalogos.ActividadEconomica",
        on_delete=models.PROTECT,
        verbose_name="Actividad económica"
    )
    base_gravable_mensual = models.BigIntegerField(
        default=0,
        verbose_name="Base gravable mensual"
    )
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["orden"]
        verbose_name = "Actividad Económica RIT"
        verbose_name_plural = "Actividades Económicas RIT"

    def __str__(self):
        return f"{self.actividad.codigo} - {self.actividad.nombre}"


class DeclaracionICA(models.Model):
    # =========================
    # CAMPOS DATOS GENERALES
    # =========================
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    municipio = models.ForeignKey("catalogos.Municipio", on_delete=models.PROTECT)

    # Este campo lo llenas automáticamente desde municipio.departamento
    departamento = models.ForeignKey(
        "catalogos.Departamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    anio_gravable = models.PositiveIntegerField(verbose_name="Año gravable")

    opcion_uso = models.CharField(
        max_length=20,
        choices=[("INICIAL", "Declaración inicial"), ("CORRECCION", "Corrección")],
        default="INICIAL",
    )

    corrige_a = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="correcciones",
        help_text="Si es corrección, referencia a la declaración original o a la última versión.",
    )

    fecha_diligenciamiento = models.DateTimeField(auto_now_add=True)

    def asignar_departamento(self):
        if self.municipio_id:
            self.departamento = self.municipio.departamento

    # =========================
    # A. INFORMACIÓN DEL CONTRIBUYENTE
    # =========================

    nombre_razon_social = models.CharField(
        max_length=255,
        verbose_name="1. Nombres y apellidos o razón social",
        blank=True,
        null=True,
    )

    TIPO_DOCUMENTO_CHOICES = (
        ("CC", "Cédula de ciudadanía"),
        ("NIT", "NIT"),
        ("PASAPORTE", "Pasaporte"),
        ("CE", "Cédula de extranjería"),
        ("OTRO", "Otro"),
    )

    tipo_documento = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_CHOICES,
        verbose_name="2. Tipo de documento",
        blank=True,
        null=True,
    )

    numero_documento = models.CharField(
        max_length=30,
        verbose_name="No. documento",
        blank=True,
        null=True,
    )

    dv = models.CharField(
        max_length=2,
        verbose_name="DV",
        blank=True,
        null=True,
    )

    cual_documento = models.CharField(
        max_length=60,
        verbose_name="Cuál (si tipo de documento es OTRO)",
        blank=True,
        null=True,
    )

    direccion_notificacion = models.CharField(
        max_length=255,
        verbose_name="3. Dirección de notificación",
        blank=True,
        null=True,
    )

    municipio_notificacion = models.ForeignKey(
        "catalogos.Municipio",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="declaraciones_municipio_notificacion",
    )

    # ⚠️ CORREGIDO: related_name distinto, no puede repetirse
    departamento_notificacion = models.ForeignKey(
        "catalogos.Departamento",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="declaraciones_departamento_notificacion",
    )

    def asignar_departamento_notificacion(self):
        if self.municipio_notificacion_id:
            self.departamento_notificacion = self.municipio_notificacion.departamento

    telefono = models.CharField(
        max_length=30,
        verbose_name="4. Teléfono",
        blank=True,
        null=True,
    )

    correo_electronico = models.EmailField(
        verbose_name="5. Correo electrónico",
        blank=True,
        null=True,
    )

    numero_establecimientos = models.PositiveIntegerField(
        verbose_name="6. Número de establecimientos",
        blank=True,
        null=True,
    )

    CLASIFICACION_CONTRIBUYENTE_CHOICES = (
        ("REGIMEN_COMUN", "Régimen común de ICA"),
        ("REGIMEN_SIMPLE", "Régimen simplificado"),
        ("OTRA", "Otra"),
    )

    clasificacion_contribuyente = models.CharField(
        max_length=30,
        choices=CLASIFICACION_CONTRIBUYENTE_CHOICES,
        verbose_name="7. Clasificación contribuyente",
        blank=True,
        null=True,
    )

    otra_clasificacion = models.CharField(
        max_length=80,
        verbose_name="Cuál (si clasificación es Otra)",
        blank=True,
        null=True,
    )

    # =========================
    # PERSONA NATURAL / JURÍDICA
    # =========================
    tipo_persona = models.CharField(
        max_length=10,
        choices=[("NATURAL", "Natural"), ("JURIDICA", "Jurídica")],
        blank=True,
        null=True,
    )

    tipo_juridica = models.CharField(
        max_length=30,
        choices=[
            ("SOCIEDAD", "Sociedad"),
            ("CONSORCIO", "Consorcio"),
            ("UNION_TEMPORAL", "Unión temporal"),
            ("PATRIMONIO_AUTONOMO", "Patrimonio autónomo"),
            ("OTRO", "Otro"),
        ],
        blank=True,
        null=True,
    )

    otro_tipo_juridica = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Otro tipo jurídico",
        help_text="Solo aplica si Tipo jurídica = Otro.",
    )

    # =========================
    # TOTALES AUTOCALCULADOS
    # =========================
    valor_ica = models.BigIntegerField(default=0)
    avisos_tableros = models.BigIntegerField(default=0)
    sobretasa_bomberil = models.BigIntegerField(default=0)
    total_a_pagar = models.BigIntegerField(default=0)

    # =========================
    # FIRMAS
    # =========================

    tiene_contador = models.BooleanField(default=False)
    tiene_revisor_fiscal = models.BooleanField(default=False)

    # Correos para OTP de contador y revisor
    contador_email = models.EmailField(blank=True, null=True)
    revisor_email = models.EmailField(blank=True, null=True)

    # Verificación de firma por OTP para contador y revisor
    contador_firma_verificada = models.BooleanField(default=False)
    revisor_firma_verificada = models.BooleanField(default=False)

    # =========================
    # F. FIRMAS - Datos adicionales
    # =========================

    # Contador
    contador_nombre = models.CharField(max_length=120, blank=True, null=True)
    contador_tipo_documento = models.CharField(
        max_length=3,
        choices=[("CC", "C.C."), ("CE", "C.E."), ("TI", "T.I.")],
        blank=True,
        null=True
    )
    contador_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    contador_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)

    # Revisor fiscal
    revisor_nombre = models.CharField(max_length=120, blank=True, null=True)
    revisor_tipo_documento = models.CharField(
        max_length=3,
        choices=[("CC", "C.C."), ("CE", "C.E."), ("TI", "T.I.")],
        blank=True,
        null=True
    )
    revisor_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    revisor_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)

    # Representante legal
    rep_legal_email = models.EmailField(blank=True, null=True, verbose_name="Correo del representante legal")
    rep_legal_nombre = models.CharField(max_length=120, blank=True, null=True, verbose_name="Nombre del representante legal")
    rep_legal_tipo_documento = models.CharField(
        max_length=3,
        choices=[("CC", "C.C."), ("CE", "C.E."), ("TI", "T.I.")],
        blank=True,
        null=True,
        verbose_name="Tipo doc. representante legal"
    )
    rep_legal_numero_documento = models.CharField(max_length=30, blank=True, null=True, verbose_name="Número documento representante legal")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        pass

    def recalcular_totales(self, save=True):
        total_ica = 0

        for item in self.items_actividades.all():
            impuesto = int(
                round(
                    (float(item.ingresos_gravados) * float(item.tarifa_aplicada)) / 1000
                )
            )
            item.impuesto = impuesto
            item.save(update_fields=["impuesto"])
            total_ica += impuesto

        self.valor_ica = total_ica
        r20 = total_ica + (self.imp_ley_56_1981 or 0)
        tiene_avisos = (self.tiene_avisos_tableros == "SI")
        self.avisos_tableros = int(round(r20 * 0.15)) if tiene_avisos else 0
        self.sobretasa_bomberil = 0
        self.total_a_pagar = (
            self.valor_ica + self.avisos_tableros + self.sobretasa_bomberil
        )

        if save:
            self.save(
                update_fields=[
                    "valor_ica",
                    "avisos_tableros",
                    "sobretasa_bomberil",
                    "total_a_pagar",
                ]
            )

        return {
            "valor_ica": self.valor_ica,
            "avisos_tableros": self.avisos_tableros,
            "sobretasa_bomberil": self.sobretasa_bomberil,
            "total_a_pagar": self.total_a_pagar,
        }

    def __str__(self):
        return f"ICA {self.municipio} {self.anio_gravable} ({self.user}) - {self.opcion_uso}"


    # =========================
    # B. BASE GRAVABLE
    # =========================
    b8_total_ingresos_pais = models.BigIntegerField(default=0)
    b9_menos_ingresos_fuera_municipio = models.BigIntegerField(default=0)
    b11_menos_devoluciones_rebajas_descuentos = models.BigIntegerField(default=0)
    b12_menos_exportaciones_venta_activos_fijos = models.BigIntegerField(default=0)
    b13_menos_otras_actividades_excluidas_no_sujetas = models.BigIntegerField(default=0)
    b14_menos_actividades_exentas_por_acuerdo = models.BigIntegerField(default=0)

    # =========================
    # C. Ajustes (18-19)
    # =========================
    es_generador_energia = models.CharField(
        max_length=2, choices=[("SI", "Sí"), ("NO", "No")], blank=True, null=True
    )
    capacidad_instalada_kw = models.PositiveIntegerField(blank=True, null=True)
    imp_ley_56_1981 = models.BigIntegerField(default=0)
    tiene_avisos_tableros = models.CharField(
        max_length=2, choices=[("SI", "Sí"), ("NO", "No")], blank=True, null=True
    )

    # =========================
    # D. Liquidación (20-34) - valores capturados por usuario
    # =========================
    d22_sector_financiero = models.BigIntegerField(default=0)
    d24_sobretasa_seguridad = models.BigIntegerField(default=0)

    d26_exencion = models.BigIntegerField(default=0)
    d27_retenciones = models.BigIntegerField(default=0)
    d28_autorretenciones = models.BigIntegerField(default=0)
    d29_anticipo_anterior = models.BigIntegerField(default=0)
    d30_anticipo_siguiente = models.BigIntegerField(default=0)
    # =========================
    # E. PAGO (36-37)
    # =========================
    e36_descuento_pronto_pago = models.BigIntegerField(default=0)
    e37_intereses_mora = models.BigIntegerField(default=0)

    d31_tipo_sancion = models.CharField(
        max_length=20,
        choices=[
            ("NINGUNA", "Ninguna"),
            ("EXTEMPORANEIDAD", "Extemporaneidad"),
            ("CORRECCION", "Corrección"),
            ("INEXACTITUD", "Inexactitud"),
            ("OTRA", "Otra"),
        ],
        blank=True,
        null=True,
    )
    d31_cual = models.CharField(max_length=100, blank=True, null=True)
    d31_valor = models.BigIntegerField(default=0)

    d32_saldo_favor_anterior = models.BigIntegerField(default=0)

    # =========================
    # FIRMA ELECTRÓNICA OTP
    # =========================
    firma_otp_verificada = models.BooleanField(default=False)
    firma_timestamp = models.DateTimeField(null=True, blank=True)
    firma_hash = models.CharField(max_length=64, null=True, blank=True)



class DeclaracionActividad(models.Model):
    declaracion = models.ForeignKey(
        DeclaracionICA,
        on_delete=models.CASCADE,
        related_name="items_actividades",
    )

    actividad = models.ForeignKey(
        "catalogos.ActividadEconomica",
        on_delete=models.PROTECT,
    )

    ingresos_gravados = models.BigIntegerField(default=0)
    tarifa_aplicada = models.DecimalField(max_digits=10, decimal_places=6)
    tipo_aplicado = models.CharField(max_length=15)

    impuesto = models.BigIntegerField(default=0)
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["orden"]

    def __str__(self):
        return f"Decl {self.declaracion_id} - {self.actividad.codigo}"


class AutoRetencionICA(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    periodo = models.CharField(max_length=20)

    base = models.DecimalField(max_digits=15, decimal_places=2)
    tarifa = models.DecimalField(max_digits=10, decimal_places=6)
    valor = models.DecimalField(max_digits=15, decimal_places=2)

    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"AutoRet ICA {self.periodo} ({self.user})"


class DeclaracionAutoRetencion(models.Model):
    BIMESTRE_CHOICES = [
        ('01', 'Bimestre 01'), ('02', 'Bimestre 02'), ('03', 'Bimestre 03'),
        ('04', 'Bimestre 04'), ('05', 'Bimestre 05'), ('06', 'Bimestre 06'),
    ]
    OPCION_USO_CHOICES = [
        ('INICIAL', 'Declaración inicial'), ('CORRECCION', 'Corrección'),
    ]
    TIPO_DOCUMENTO_CHOICES = (
        ('CC', 'Cédula de ciudadanía'), ('NIT', 'NIT'), ('PASAPORTE', 'Pasaporte'),
        ('CE', 'Cédula de extranjería'), ('OTRO', 'Otro'),
    )
    CLASIFICACION_CONTRIBUYENTE_CHOICES = (
        ('REGIMEN_COMUN', 'Régimen común de ICA'), ('REGIMEN_SIMPLE', 'Régimen simplificado'),
        ('OTRA', 'Otra'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    municipio = models.ForeignKey('catalogos.Municipio', on_delete=models.PROTECT)
    departamento = models.ForeignKey('catalogos.Departamento', on_delete=models.PROTECT, null=True, blank=True)
    anio_gravable = models.PositiveIntegerField(verbose_name='Año gravable')
    bimestre = models.CharField(max_length=2, choices=BIMESTRE_CHOICES, verbose_name='Bimestre')
    opcion_uso = models.CharField(max_length=20, choices=OPCION_USO_CHOICES, default='INICIAL')
    corrige_a = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='correcciones')
    fecha_diligenciamiento = models.DateTimeField(auto_now_add=True)

    # Section A - Contributor Info
    nombre_razon_social = models.CharField(max_length=255, blank=True, null=True)
    tipo_documento = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES, blank=True, null=True)
    numero_documento = models.CharField(max_length=30, blank=True, null=True)
    dv = models.CharField(max_length=2, blank=True, null=True)
    cual_documento = models.CharField(max_length=60, blank=True, null=True)
    direccion_notificacion = models.CharField(max_length=255, blank=True, null=True)
    municipio_notificacion = models.ForeignKey('catalogos.Municipio', on_delete=models.PROTECT, null=True, blank=True, related_name='autos_municipio_notificacion')
    departamento_notificacion = models.ForeignKey('catalogos.Departamento', on_delete=models.PROTECT, null=True, blank=True, related_name='autos_departamento_notificacion')
    telefono = models.CharField(max_length=30, blank=True, null=True)
    correo_electronico = models.EmailField(blank=True, null=True)
    numero_establecimientos = models.PositiveIntegerField(blank=True, null=True)
    clasificacion_contribuyente = models.CharField(max_length=30, choices=CLASIFICACION_CONTRIBUYENTE_CHOICES, blank=True, null=True)
    otra_clasificacion = models.CharField(max_length=80, blank=True, null=True)
    tipo_persona = models.CharField(max_length=10, choices=[('NATURAL', 'Natural'), ('JURIDICA', 'Jurídica')], blank=True, null=True)
    tipo_juridica = models.CharField(max_length=30, choices=[('SOCIEDAD', 'Sociedad'), ('CONSORCIO', 'Consorcio'), ('UNION_TEMPORAL', 'Unión temporal'), ('PATRIMONIO_AUTONOMO', 'Patrimonio autónomo'), ('OTRO', 'Otro')], blank=True, null=True)
    otro_tipo_juridica = models.CharField(max_length=100, blank=True, null=True)

    # Section D - Liquidación
    TIPO_SANCION_CHOICES = [
        ("NINGUNA", "Ninguna"),
        ("EXTEMPORANEIDAD", "Extemporaneidad"),
        ("CORRECCION", "Corrección"),
        ("INEXACTITUD", "Inexactitud"),
        ("OTRA", "Otra"),
    ]
    tipo_sancion = models.CharField(max_length=20, choices=TIPO_SANCION_CHOICES, blank=True, null=True, default="NINGUNA")
    cual_sancion = models.CharField(max_length=100, blank=True, null=True)
    sanciones = models.BigIntegerField(default=0)
    intereses_mora = models.BigIntegerField(default=0)
    autorretencion_exceso = models.BigIntegerField(default=0)

    # Calculated totals
    total_valor_autorretencion = models.BigIntegerField(default=0)
    subtotal = models.BigIntegerField(default=0)
    total_a_pagar = models.BigIntegerField(default=0)

    # Signatures
    tiene_contador = models.BooleanField(default=False)
    tiene_revisor_fiscal = models.BooleanField(default=False)
    contador_email = models.EmailField(blank=True, null=True)
    revisor_email = models.EmailField(blank=True, null=True)
    contador_firma_verificada = models.BooleanField(default=False)
    revisor_firma_verificada = models.BooleanField(default=False)
    contador_nombre = models.CharField(max_length=120, blank=True, null=True)
    contador_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    contador_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    contador_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)
    revisor_nombre = models.CharField(max_length=120, blank=True, null=True)
    revisor_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    revisor_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    revisor_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)
    rep_legal_email = models.EmailField(blank=True, null=True)
    rep_legal_nombre = models.CharField(max_length=120, blank=True, null=True)
    rep_legal_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    rep_legal_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    firma_otp_verificada = models.BooleanField(default=False)
    firma_timestamp = models.DateTimeField(null=True, blank=True)
    firma_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def asignar_departamento(self):
        if self.municipio_id:
            self.departamento = self.municipio.departamento

    def asignar_departamento_notificacion(self):
        if self.municipio_notificacion_id:
            self.departamento_notificacion = self.municipio_notificacion.departamento

    def recalcular_totales(self, save=True):
        total_autorretencion = 0
        for item in self.actividades.all():
            ingreso_gravable = max(0, int(item.ingreso_total_bimestre) - int(item.ingreso_excluido))
            item.ingreso_gravable = ingreso_gravable
            valor = int(round(float(ingreso_gravable) * float(item.tarifa_aplicada) / 1000))
            item.valor_autorretencion = valor
            item.save(update_fields=['ingreso_gravable', 'valor_autorretencion'])
            total_autorretencion += valor
        self.total_valor_autorretencion = total_autorretencion
        self.subtotal = total_autorretencion + (self.sanciones or 0) + (self.intereses_mora or 0)
        self.total_a_pagar = max(0, self.subtotal - (self.autorretencion_exceso or 0))
        if save:
            self.save(update_fields=['total_valor_autorretencion', 'subtotal', 'total_a_pagar'])
        return {'total_valor_autorretencion': self.total_valor_autorretencion, 'subtotal': self.subtotal, 'total_a_pagar': self.total_a_pagar}

    def __str__(self):
        return f"AUTO {self.municipio} {self.anio_gravable} Bim.{self.bimestre} ({self.user}) - {self.opcion_uso}"

    class Meta:
        verbose_name = 'Declaración Autorretención ICA'
        verbose_name_plural = 'Declaraciones Autorretención ICA'


class DeclaracionActividadAuto(models.Model):
    declaracion = models.ForeignKey(DeclaracionAutoRetencion, on_delete=models.CASCADE, related_name='actividades')
    actividad = models.ForeignKey('catalogos.ActividadEconomica', on_delete=models.PROTECT)
    ingreso_total_bimestre = models.BigIntegerField(default=0)
    ingreso_excluido = models.BigIntegerField(default=0)
    ingreso_gravable = models.BigIntegerField(default=0)
    tarifa_aplicada = models.DecimalField(max_digits=10, decimal_places=6)
    tipo_aplicado = models.CharField(max_length=15)
    valor_autorretencion = models.BigIntegerField(default=0)
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['orden']

    def __str__(self):
        return f"AutoAct {self.declaracion_id} - {self.actividad.codigo}"


class FirmaOTPAuto(models.Model):
    declaracion = models.ForeignKey(DeclaracionAutoRetencion, on_delete=models.CASCADE, related_name='otps_firma')
    codigo = models.CharField(max_length=6)
    creado_en = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    tipo = models.CharField(max_length=20, default='declarante', choices=[('declarante', 'Declarante'), ('contador', 'Contador'), ('revisor', 'Revisor Fiscal')])

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f"OTP firma AUTO #{self.declaracion_id}"


class RetencionICA(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    periodo = models.CharField(max_length=20)
    tercero = models.CharField(max_length=200)

    base = models.DecimalField(max_digits=15, decimal_places=2)
    tarifa = models.DecimalField(max_digits=10, decimal_places=6)
    valor = models.DecimalField(max_digits=15, decimal_places=2)

    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Ret ICA {self.periodo} - {self.tercero} ({self.user})"


# =========================
# DECLARACIÓN DE RETENCIÓN ICA
# =========================
class DeclaracionRetencionICA(models.Model):
    BIMESTRE_CHOICES = [
        ('01', 'Bimestre 01'), ('02', 'Bimestre 02'), ('03', 'Bimestre 03'),
        ('04', 'Bimestre 04'), ('05', 'Bimestre 05'), ('06', 'Bimestre 06'),
    ]
    OPCION_USO_CHOICES = [
        ('INICIAL', 'Declaración inicial'), ('CORRECCION', 'Corrección'),
    ]
    TIPO_DOCUMENTO_CHOICES = (
        ('CC', 'Cédula de ciudadanía'), ('NIT', 'NIT'), ('PASAPORTE', 'Pasaporte'),
        ('CE', 'Cédula de extranjería'), ('OTRO', 'Otro'),
    )
    CLASIFICACION_CONTRIBUYENTE_CHOICES = (
        ('REGIMEN_COMUN', 'Régimen común de ICA'), ('REGIMEN_SIMPLE', 'Régimen simplificado'),
        ('OTRA', 'Otra'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    municipio = models.ForeignKey('catalogos.Municipio', on_delete=models.PROTECT, related_name='retes_municipio')
    departamento = models.ForeignKey('catalogos.Departamento', on_delete=models.PROTECT, null=True, blank=True, related_name='retes_departamento')
    anio_gravable = models.PositiveIntegerField(verbose_name='Año gravable')
    bimestre = models.CharField(max_length=2, choices=BIMESTRE_CHOICES, verbose_name='Bimestre')
    opcion_uso = models.CharField(max_length=20, choices=OPCION_USO_CHOICES, default='INICIAL')
    corrige_a = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='correcciones')
    fecha_diligenciamiento = models.DateTimeField(auto_now_add=True)

    # Section A - Contributor Info
    nombre_razon_social = models.CharField(max_length=255, blank=True, null=True)
    tipo_documento = models.CharField(max_length=10, choices=TIPO_DOCUMENTO_CHOICES, blank=True, null=True)
    numero_documento = models.CharField(max_length=30, blank=True, null=True)
    dv = models.CharField(max_length=2, blank=True, null=True)
    cual_documento = models.CharField(max_length=60, blank=True, null=True)
    direccion_notificacion = models.CharField(max_length=255, blank=True, null=True)
    municipio_notificacion = models.ForeignKey('catalogos.Municipio', on_delete=models.PROTECT, null=True, blank=True, related_name='retes_municipio_notificacion')
    departamento_notificacion = models.ForeignKey('catalogos.Departamento', on_delete=models.PROTECT, null=True, blank=True, related_name='retes_departamento_notificacion')
    telefono = models.CharField(max_length=30, blank=True, null=True)
    correo_electronico = models.EmailField(blank=True, null=True)
    numero_establecimientos = models.PositiveIntegerField(blank=True, null=True)
    clasificacion_contribuyente = models.CharField(max_length=30, choices=CLASIFICACION_CONTRIBUYENTE_CHOICES, blank=True, null=True)
    otra_clasificacion = models.CharField(max_length=80, blank=True, null=True)
    tipo_persona = models.CharField(max_length=10, choices=[('NATURAL', 'Natural'), ('JURIDICA', 'Jurídica')], blank=True, null=True)
    tipo_juridica = models.CharField(max_length=30, choices=[('SOCIEDAD', 'Sociedad'), ('CONSORCIO', 'Consorcio'), ('UNION_TEMPORAL', 'Unión temporal'), ('PATRIMONIO_AUTONOMO', 'Patrimonio autónomo'), ('OTRO', 'Otro')], blank=True, null=True)
    otro_tipo_juridica = models.CharField(max_length=100, blank=True, null=True)

    # Section D - Liquidación
    TIPO_SANCION_CHOICES = [
        ("NINGUNA", "Ninguna"),
        ("EXTEMPORANEIDAD", "Extemporaneidad"),
        ("CORRECCION", "Corrección"),
        ("INEXACTITUD", "Inexactitud"),
        ("OTRA", "Otra"),
    ]
    tipo_sancion = models.CharField(max_length=20, choices=TIPO_SANCION_CHOICES, blank=True, null=True, default="NINGUNA")
    cual_sancion = models.CharField(max_length=100, blank=True, null=True)
    sanciones = models.BigIntegerField(default=0)
    intereses_mora = models.BigIntegerField(default=0)
    devoluciones = models.BigIntegerField(default=0, verbose_name='Devoluciones, anulaciones, rescisiones, retenciones practicadas en exceso')

    # Calculated totals
    total_valor_retencion = models.BigIntegerField(default=0)
    subtotal_retenciones = models.BigIntegerField(default=0, verbose_name='Subtotal retenciones menos devoluciones')
    total_a_pagar = models.BigIntegerField(default=0)

    # Signatures
    tiene_contador = models.BooleanField(default=False)
    tiene_revisor_fiscal = models.BooleanField(default=False)
    contador_email = models.EmailField(blank=True, null=True)
    revisor_email = models.EmailField(blank=True, null=True)
    contador_firma_verificada = models.BooleanField(default=False)
    revisor_firma_verificada = models.BooleanField(default=False)
    contador_nombre = models.CharField(max_length=120, blank=True, null=True)
    contador_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    contador_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    contador_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)
    revisor_nombre = models.CharField(max_length=120, blank=True, null=True)
    revisor_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    revisor_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    revisor_tarjeta_profesional = models.CharField(max_length=30, blank=True, null=True)
    rep_legal_email = models.EmailField(blank=True, null=True)
    rep_legal_nombre = models.CharField(max_length=120, blank=True, null=True)
    rep_legal_tipo_documento = models.CharField(max_length=3, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], blank=True, null=True)
    rep_legal_numero_documento = models.CharField(max_length=30, blank=True, null=True)
    firma_otp_verificada = models.BooleanField(default=False)
    firma_timestamp = models.DateTimeField(null=True, blank=True)
    firma_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def asignar_departamento(self):
        if self.municipio_id:
            self.departamento = self.municipio.departamento

    def asignar_departamento_notificacion(self):
        if self.municipio_notificacion_id:
            self.departamento_notificacion = self.municipio_notificacion.departamento

    def recalcular_totales(self, save=True):
        total_retencion = 0
        for item in self.actividades.all():
            valor = int(round(float(item.valor_base) * float(item.tarifa) / 1000))
            item.valor_retencion = valor
            item.save(update_fields=['valor_retencion'])
            total_retencion += valor
        self.total_valor_retencion = total_retencion
        self.subtotal_retenciones = max(0, total_retencion - (self.devoluciones or 0))
        self.total_a_pagar = self.subtotal_retenciones + (self.sanciones or 0) + (self.intereses_mora or 0)
        if save:
            self.save(update_fields=['total_valor_retencion', 'subtotal_retenciones', 'total_a_pagar'])
        return {
            'total_valor_retencion': self.total_valor_retencion,
            'subtotal_retenciones': self.subtotal_retenciones,
            'total_a_pagar': self.total_a_pagar,
        }

    def __str__(self):
        return f"RETE {self.municipio} {self.anio_gravable} Bim.{self.bimestre} ({self.user}) - {self.opcion_uso}"

    class Meta:
        verbose_name = 'Declaración Retención ICA'
        verbose_name_plural = 'Declaraciones Retención ICA'


class DeclaracionActividadRete(models.Model):
    declaracion = models.ForeignKey(DeclaracionRetencionICA, on_delete=models.CASCADE, related_name='actividades')
    actividad = models.ForeignKey('catalogos.ActividadEconomica', on_delete=models.PROTECT)
    valor_base = models.BigIntegerField(default=0)
    tarifa = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    valor_retencion = models.BigIntegerField(default=0)
    orden = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['orden']

    def __str__(self):
        return f"ReteAct {self.declaracion_id} - {self.actividad.codigo}"


class FirmaOTPRete(models.Model):
    declaracion = models.ForeignKey(DeclaracionRetencionICA, on_delete=models.CASCADE, related_name='otps_firma')
    codigo = models.CharField(max_length=6)
    creado_en = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    tipo = models.CharField(max_length=20, default='declarante', choices=[('declarante', 'Declarante'), ('contador', 'Contador'), ('revisor', 'Revisor Fiscal')])

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f"OTP firma RETE #{self.declaracion_id}"


# =========================
# CONFIGURACIÓN PDF
# =========================
class ConfiguracionPDF(models.Model):
    """
    Configuración parametrizable para los PDFs generados.
    Solo debe existir un registro activo.
    """
    nombre = models.CharField(
        max_length=100,
        default="Configuración Principal",
        verbose_name="Nombre de configuración"
    )
    activo = models.BooleanField(
        default=True,
        verbose_name="Configuración activa"
    )

    # Logos
    logo_izquierdo = models.ImageField(
        upload_to="config/logos/",
        blank=True,
        null=True,
        verbose_name="Logo izquierdo (Escudo/Alcaldía)",
        help_text="Tamaño recomendado: 150x150px"
    )
    logo_derecho = models.ImageField(
        upload_to="config/logos/",
        blank=True,
        null=True,
        verbose_name="Logo derecho (Institucional)",
        help_text="Tamaño recomendado: 150x150px"
    )

    # Textos del encabezado
    nombre_entidad = models.CharField(
        max_length=200,
        default="Secretaría de Hacienda",
        verbose_name="Nombre de la entidad"
    )
    nombre_municipio = models.CharField(
        max_length=100,
        default="Municipio de Salgar",
        verbose_name="Nombre del municipio"
    )
    slogan = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        default="Portal de Servicios Tributarios",
        verbose_name="Slogan o subtítulo"
    )

    # Colores (en formato hexadecimal)
    color_primario = models.CharField(
        max_length=7,
        default="#1a5276",
        verbose_name="Color primario",
        help_text="Formato hexadecimal, ej: #1a5276"
    )
    color_secundario = models.CharField(
        max_length=7,
        default="#2c3e50",
        verbose_name="Color secundario",
        help_text="Formato hexadecimal, ej: #2c3e50"
    )
    color_radicado = models.CharField(
        max_length=7,
        default="#c0392b",
        verbose_name="Color del radicado",
        help_text="Formato hexadecimal, ej: #c0392b"
    )
    color_exito = models.CharField(
        max_length=7,
        default="#27ae60",
        verbose_name="Color de éxito/total",
        help_text="Formato hexadecimal, ej: #27ae60"
    )

    # Instructivo
    mostrar_instructivo = models.BooleanField(
        default=True,
        verbose_name="Mostrar instructivo en PDF"
    )
    texto_instructivo = models.TextField(
        default="""1. Conserve este documento como soporte de su trámite tributario.
2. El número de radicado es su comprobante oficial ante la administración municipal.
3. Para cualquier consulta, presente este documento con el número de radicado.
4. Este documento fue generado electrónicamente y es válido sin firma.""",
        verbose_name="Texto del instructivo",
        help_text="Cada línea será un punto del instructivo"
    )

    # Instructivo ICA – página 2 del PDF
    instructivo_ica_col_izquierda = models.TextField(
        verbose_name="Instructivo ICA – columna izquierda",
        help_text=(
            "Use ### ETIQUETA para iniciar una sección con franja vertical. "
            "Use ## TÍTULO para encabezados en negrita. Separe bloques con línea en blanco. "
            "El texto antes del primer ### se muestra como introducción sin franja."
        ),
        default="""Este formulario lo deben utilizar las personas naturales y jurídicas que ejerzan directa o indirectamente actividades permanentes u ocasionales en la jurisdicción del Municipio de Salgar, Antioquia, en cumplimiento de la Ley 14 de 1983, Decreto Ley 1333 de 1986 y el Acuerdo Municipal vigente.

El formulario debe ser presentado ante el Área Administrativa de Impuestos de la Alcaldía Municipal de Salgar, Salgar, Antioquia, en las fechas del Calendario Tributario.

Todas las casillas de valores deben aproximarse al múltiplo de mil (1000) más cercano. Si no hay valor, escriba cero (0).

## MUNICIPIO O DISTRITO
Escriba SEGOVIA, municipio ante quien presenta esta declaración.

## DEPARTAMENTO
Escriba ANTIOQUIA.

## FECHA MÁXIMA DE PRESENTACIÓN
Consulte el decreto municipal con el Calendario Tributario del Municipio de Salgar.

## AÑO GRAVABLE
El período gravable es el año calendario inmediatamente anterior al de presentación.

## DECLARACIÓN INICIAL
Marque si es la primera declaración por este período gravable.

## CORRECCIÓN
Si corrige una declaración anterior, escriba el número, día, mes y año de la declaración que corrige.

### A. INFORMACIÓN DEL CONTRIBUYENTE

## 1. NOMBRES Y APELLIDOS O RAZÓN SOCIAL
Escriba los datos tal como figuran en el documento de identificación, R.U.T. o certificado de Cámara de Comercio. Si es PERSONA NATURAL, escriba nombres y apellidos completos. Si es PERSONA JURÍDICA, escriba la razón social completa.

## 2. TIPO DE DOCUMENTO
Marque con "X" el recuadro y escriba el número de C.C., Nit. o Tarjeta de Identidad. Para el NIT, el dígito de verificación va separado con guion.

## 3. DIRECCIÓN DE NOTIFICACIÓN
Escriba la dirección que usa para efectos tributarios, indicando municipio y departamento. – Dirección establecimiento: escriba la dirección de establecimientos, agencias o sucursales en Salgar.

## 4. TELÉFONO
Escriba el número de teléfono de contacto.

## 5. CORREO ELECTRÓNICO
Escriba la dirección electrónica de contacto.

## 6. NÚMERO DE ESTABLECIMIENTOS
Escriba el número de establecimientos comerciales, agencias, oficinas o sucursales ubicadas en Salgar.

## 7. CLASIFICACIÓN
Escriba si es Gran Contribuyente, Régimen Común o Simplificado según la DIAN. – Tipo de actividad económica: marque si desarrolla en Salgar una actividad en forma permanente u ocasional.

### B. BASE GRAVABLE

## 8. TOTAL INGRESOS ORDINARIOS Y EXTRAORDINARIOS DEL PERÍODO EN TODO EL PAÍS
Registre la totalidad de ingresos obtenidos en todo el país durante el período gravable, incluyendo rendimientos financieros y comisiones.

## 9. MENOS INGRESOS FUERA DE ESTE MUNICIPIO
Registre el total de ingresos obtenidos fuera del municipio de Salgar.

## 10. TOTAL INGRESOS EN ESTE MUNICIPIO (RENGLÓN 8 MENOS 9)
Resultado de restar los ingresos fuera del municipio al total del país.

## 11. MENOS DEVOLUCIONES, REBAJAS Y DESCUENTOS
Valor de ingresos por devoluciones, rebajas o descuentos registrados en Salgar del año anterior.

## 12. MENOS INGRESOS POR EXPORTACIONES
Valor de exportaciones realizadas en el año inmediatamente anterior.

## 13. MENOS VENTA DE ACTIVOS FIJOS
Valor de venta de activos fijos en el año inmediatamente anterior.

## 14. MENOS ACTIVIDADES EXCLUIDAS, NO SUJETAS Y OTROS INGRESOS NO GRAVADOS
Valor de ingresos por actividades excluidas, no sujetas u otros no gravados según las normas del impuesto de industria y comercio.

## 15. MENOS ACTIVIDADES EXENTAS EN ESTE MUNICIPIO
Valor de ingresos de actividades con tratamiento de exención concedido por el Concejo Municipal de Salgar.

## 16. TOTAL INGRESOS GRAVABLES (RENGLÓN 10 MENOS 11, 12, 13, 14 Y 15)
Resultado de restar al total de ingresos en el municipio los conceptos deducibles de los renglones 11 a 15.""",
    )

    instructivo_ica_col_derecha = models.TextField(
        verbose_name="Instructivo ICA – columna derecha",
        help_text=(
            "Use ### ETIQUETA para iniciar una sección con franja vertical. "
            "Use ## TÍTULO para encabezados en negrita. Separe bloques con línea en blanco."
        ),
        default="""### C. DISCRIMINACIÓN DE ACTIVIDADES GRAVADAS

Según las actividades que realice como PERSONA NATURAL o JURÍDICA en Salgar, registre para cada una la información requerida, iniciando con la actividad principal.

Consulte el código y tarifa de cada actividad en el Estatuto Tributario Municipal vigente de Salgar.

Escriba en la columna "IMPUESTO" el valor que resulte de multiplicar los ingresos gravados por la tarifa. Ejemplo: $10.000.000 x 8 ÷ 1000 = $80.000.

## TOTAL INGRESOS GRAVADOS
Totalice la sumatoria de la columna "Ingresos Gravados".

## 17. TOTAL IMPUESTO
Totalice la sumatoria de la columna "IMPUESTO".

## 18. LIQUIDACIÓN – LEY 56 DE 1981
Sólo lo diligencian empresas generadoras de energía eléctrica (Art. 51, Ley 383 de 1997). Escriba en kilovatios la capacidad instalada de la generadora en el municipio.

### D. LIQUIDACIÓN PRIVADA

## 20. TOTAL IMPUESTO DE INDUSTRIA Y COMERCIO (RENGLÓN 17 + 19)
Escriba el impuesto del renglón N° 17 más el valor de la casilla N° 19.

## 21. IMPUESTO DE AVISOS Y TABLEROS (15% del renglón 20)
Si tiene avisos y tableros en Salgar, multiplique el renglón N° 20 por el 15%.

## 22. PAGO POR UNIDADES COMERCIALES ADICIONALES DEL SECTOR FINANCIERO
Liquidar 25 UVT por cada oficina adicional excepto la principal (Establecimientos de crédito, instituciones financieras y compañías de seguros).

## 23. SOBRETASA BOMBERIL
No aplica para el Municipio de Salgar.

## 24. SOBRETASA DE SEGURIDAD
No aplica para el Municipio de Salgar.

## 25. TOTAL IMPUESTO A CARGO
Resultado de sumar los renglones 20 + 21 + 22 + 23 + 24.

## 26. MENOS EXENCIÓN O EXONERACIÓN SOBRE EL IMPUESTO
Si tiene derecho a disminuir el impuesto liquidado por una exención concedida, escriba el valor exento.

## 27. MENOS RETENCIONES
Valor retenido el año anterior a favor del Municipio de Salgar, anexando los certificados de retención.

## 28. MENOS AUTORRETENCIONES
No aplica para el Municipio de Salgar.

## 29. MENOS ANTICIPO LIQUIDADO EN EL AÑO ANTERIOR
Sólo aplica a contribuyentes nuevos inscritos en el R.I.T. en el año inmediatamente anterior.

## 30. ANTICIPO PARA EL AÑO SIGUIENTE
No aplica para el Municipio de Salgar.

## 31. SANCIONES
Valor de sanciones tributarias a liquidar con esta declaración (Arts. 192 a 198 del Estatuto Tributario Municipal).

## 32. MENOS SALDO A FAVOR DEL PERIODO ANTERIOR
Escriba el saldo a favor con los anexos que acrediten su determinación.

## 33. TOTAL SALDO A CARGO
Resultado: renglón 25 - 26 - 27 - 28 - 29 + 30 + 31 - 32.

## 34. TOTAL SALDO A FAVOR
Si el resultado del renglón 25 - 26 - 27 - 28 - 29 + 30 + 31 - 32 es menor a cero.

### E. PAGO

## 35. VALOR A PAGAR
Escriba el valor que va a pagar durante la vigencia fiscal declarada. Si no va a pagar, escriba cero.

## 36. DESCUENTO POR PRONTO PAGO
No aplica para la declaración privada de Salgar.

## 37. INTERESES DE MORA
No aplica para la declaración privada de Salgar.

## 38. TOTAL A PAGAR
Escriba el resultado del renglón N° 35.

### SELECCIÓN PAGO VOLUNTARIO

Este recuadro no aplica para la Declaración que se presenta en el Municipio de Salgar (Antioquia).

### F. FIRMAS

## FIRMA DEL DECLARANTE
Esta declaración debe ser firmada por quien deba cumplir el deber formal de declarar.

## FIRMA DEL CONTADOR O REVISOR FISCAL
Diligencie si existe la obligación ante el Municipio de Salgar.""",
    )

    # Pie de página
    texto_pie_pagina = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        default="Documento generado por el Portal de Servicios Tributarios",
        verbose_name="Texto adicional pie de página"
    )

    # Contacto
    direccion_entidad = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Dirección de la entidad"
    )
    telefono_entidad = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Teléfono de la entidad"
    )
    email_entidad = models.EmailField(
        blank=True,
        null=True,
        verbose_name="Email de la entidad"
    )
    sitio_web = models.URLField(
        blank=True,
        null=True,
        verbose_name="Sitio web"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración de PDF"
        verbose_name_plural = "Configuraciones de PDF"

    def __str__(self):
        estado = "✓ Activa" if self.activo else "○ Inactiva"
        return f"{self.nombre} ({estado})"

    def save(self, *args, **kwargs):
        # Si esta configuración se marca como activa, desactivar las demás
        if self.activo:
            ConfiguracionPDF.objects.exclude(pk=self.pk).update(activo=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_config_activa(cls):
        """Retorna la configuración activa o None."""
        return cls.objects.filter(activo=True).first()


class PasswordResetCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reset_codes'
    )
    codigo = models.CharField(max_length=6)
    creado_en = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f"Código de recuperación para {self.user.username}"


class FirmaOTPICA(models.Model):
    """OTP de firma electrónica para declaraciones ICA (Ley 527/1999)."""
    declaracion = models.ForeignKey(
        'DeclaracionICA',
        on_delete=models.CASCADE,
        related_name='otps_firma'
    )
    codigo = models.CharField(max_length=6)
    creado_en = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    tipo = models.CharField(
        max_length=20,
        default='declarante',
        choices=[('declarante', 'Declarante'), ('contador', 'Contador'), ('revisor', 'Revisor Fiscal')],
    )

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f"OTP firma ICA #{self.declaracion_id}"


class FirmaOTPRIT(models.Model):
    """OTP de firma electrónica para registros RIT (Ley 527/1999)."""
    registro = models.ForeignKey(
        'RegistroRIT',
        on_delete=models.CASCADE,
        related_name='otps_firma'
    )
    codigo = models.CharField(max_length=6)
    creado_en = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    tipo = models.CharField(
        max_length=20,
        default='declarante',
        choices=[('declarante', 'Declarante')],
    )

    class Meta:
        ordering = ['-creado_en']

    def __str__(self):
        return f"OTP firma RIT #{self.registro_id}"
