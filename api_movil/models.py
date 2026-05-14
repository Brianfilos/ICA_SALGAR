from django.db import models
from django.conf import settings


class VisitaRIT(models.Model):
    """
    Registro de visita de campo realizada por un funcionario de la Alcaldía.
    Puede crearse offline y sincronizarse cuando haya internet.
    """

    ESTADO_CHOICES = [
        ('precargada', 'Precargada (pendiente de visita)'),
        ('pendiente', 'Pendiente de sincronización'),
        ('sincronizado', 'Sincronizado'),
        ('no_atendida', 'No atendida'),
        ('incompleta', 'Incompleta (pendiente de completar)'),
    ]

    MOTIVO_CHOICES = [
        ('CERRADO',        'Local cerrado'),
        ('AUSENTE',        'Propietario / encargado ausente'),
        ('NEGATIVA',       'Se negó a atender'),
        ('DIRECCION',      'Dirección no encontrada'),
        ('REGIMEN_SIMPLE', 'Régimen Simple (no obligado a registrarse)'),
        ('OTRO',           'Otro motivo'),
    ]

    # Funcionario que realiza la visita
    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='visitas_rit',
        verbose_name='Funcionario'
    )

    # UUID generado en la app para evitar duplicados al sincronizar
    uuid_local = models.CharField(
        max_length=64,
        unique=True,
        verbose_name='UUID local (app)'
    )

    # Datos del establecimiento
    nombre_establecimiento = models.CharField(max_length=255, verbose_name='Nombre del establecimiento')
    nombre_propietario     = models.CharField(max_length=255, blank=True, verbose_name='Nombre del propietario')
    numero_documento       = models.CharField(max_length=30,  blank=True, verbose_name='Número de documento')
    tipo_documento         = models.CharField(max_length=10,  blank=True, verbose_name='Tipo de documento')
    direccion              = models.CharField(max_length=255, verbose_name='Dirección del establecimiento')
    municipio              = models.CharField(max_length=120, blank=True, verbose_name='Municipio')
    telefono               = models.CharField(max_length=30,  blank=True, verbose_name='Teléfono')
    correo                 = models.EmailField(blank=True,    verbose_name='Correo electrónico')
    actividad_economica    = models.CharField(max_length=10,  blank=True, verbose_name='Código actividad económica')
    descripcion_actividad  = models.CharField(max_length=255, blank=True, verbose_name='Descripción actividad')

    # Ubicación GPS del establecimiento
    latitud       = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name='Latitud')
    longitud      = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True, verbose_name='Longitud')
    precision_gps = models.FloatField(null=True, blank=True, verbose_name='Precisión GPS (metros)')

    # Observaciones del funcionario
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')

    # Firma del contribuyente (PNG en base64 o referencia OTP)
    FIRMA_TIPO_CHOICES = [('DIBUJO', 'Firma dibujada'), ('OTP', 'Código OTP')]
    firma_contribuyente = models.TextField(blank=True, verbose_name='Firma contribuyente (base64)')
    firma_tipo          = models.CharField(max_length=10, choices=FIRMA_TIPO_CHOICES, default='DIBUJO', verbose_name='Tipo de firma')
    firma_funcionario   = models.TextField(blank=True, verbose_name='Firma funcionario (base64)')

    # Usuario contribuyente vinculado (creado automáticamente si hay correo)
    contribuyente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='visitas_como_contribuyente',
        verbose_name='Contribuyente'
    )

    # RIT web creado automáticamente a partir de esta visita (si fue atendida)
    registro_rit = models.ForeignKey(
        'tasks.RegistroRIT',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='visita_movil',
        verbose_name='Registro RIT generado'
    )

    # Visita no atendida
    motivo_no_atencion = models.CharField(
        max_length=20, choices=MOTIVO_CHOICES, blank=True,
        verbose_name='Motivo de no atención'
    )
    motivo_descripcion = models.TextField(
        blank=True, verbose_name='Descripción del motivo'
    )

    # Control de sincronización
    estado          = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    fecha_visita    = models.DateTimeField(verbose_name='Fecha y hora de la visita')
    creado_en       = models.DateTimeField(auto_now_add=True)
    sincronizado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = 'Visita RIT'
        verbose_name_plural = 'Visitas RIT'
        ordering            = ['-fecha_visita']

    def __str__(self):
        return f"{self.nombre_establecimiento} — {self.funcionario.username} — {self.fecha_visita:%Y-%m-%d}"


class FotoVisita(models.Model):
    """Fotos del establecimiento tomadas durante la visita."""

    visita = models.ForeignKey(
        VisitaRIT,
        on_delete=models.CASCADE,
        related_name='fotos',
        verbose_name='Visita'
    )
    imagen      = models.ImageField(upload_to='visitas_rit/%Y/%m/', verbose_name='Foto')
    descripcion = models.CharField(max_length=100, blank=True, verbose_name='Descripción')
    orden       = models.PositiveSmallIntegerField(default=0)
    subida_en   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'Foto de visita'
        verbose_name_plural = 'Fotos de visita'
        ordering            = ['orden']

    def __str__(self):
        return f"Foto {self.orden} — {self.visita}"


class PerfilFuncionario(models.Model):
    """Perfil extendido para funcionarios de campo."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil_funcionario'
    )
    cargo       = models.CharField(max_length=100, blank=True, verbose_name='Cargo')
    dependencia = models.CharField(max_length=100, blank=True, verbose_name='Dependencia')
    activo      = models.BooleanField(default=True)

    class Meta:
        verbose_name        = 'Perfil Funcionario'
        verbose_name_plural = 'Perfiles Funcionarios'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} — {self.cargo}"


class CensoEstablecimientos(models.Model):
    """
    Archivo Excel con el padrón de establecimientos del municipio.
    Se sube desde el admin y la app móvil lo consulta por NIT para pre-llenar datos.
    """
    archivo     = models.FileField(
        upload_to='censo/',
        verbose_name='Archivo Excel (.xls / .xlsx)',
    )
    descripcion = models.CharField(max_length=200, blank=True, verbose_name='Descripción')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Censo de Establecimientos'
        verbose_name_plural = 'Censo de Establecimientos'

    def __str__(self):
        return f'Censo — {self.descripcion or self.archivo.name} ({self.actualizado:%d/%m/%Y})'


