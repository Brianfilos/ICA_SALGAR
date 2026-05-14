import json
import io
import logging
import random
import string
from urllib import request
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse

logger = logging.getLogger('tasks.emailjs')

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User, Group
from django.contrib.auth import login, logout, authenticate
from django.db import IntegrityError
from django.utils import timezone
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings as django_settings
import requests as _requests

from .forms import (
    RITForm, ICAForm,
    DeclaracionActividadFormSet,
    DeclaracionActividadFormSetEdicion,
    RepresentanteLegalRITFormSet,
    EstablecimientoRITFormSet,
    ActividadEconomicaRITFormSet,
    AutoForm, ReteForm,
    SignupForm, PerfilContribuyenteForm,
    DeclaracionAutoRetencionForm, DeclaracionActividadAutoForm,
)
from django.contrib import messages

from .models import Task, Proceso, AccesoProceso, RegistroRIT, DeclaracionICA, ConfiguracionPDF, PasswordResetCode, FirmaOTPICA, FirmaOTPRIT, DeclaracionAutoRetencion, DeclaracionActividadAuto, FirmaOTPAuto
from catalogos.models import ActividadEconomica, Municipio


# ----------------------------
# Helper EmailJS
# ----------------------------
def _enviar_emailjs(template_id, to_email, params):
    """Envía correo via EmailJS REST API desde el servidor."""
    payload = {
        'service_id':  django_settings.EMAILJS_SERVICE_ID,
        'template_id': template_id,
        'user_id':     django_settings.EMAILJS_PUBLIC_KEY,
        'accessToken': django_settings.EMAILJS_PRIVATE_KEY,
        'template_params': {'email': to_email, **params},
    }
    verify_ssl = getattr(django_settings, 'EMAILJS_VERIFY_SSL', True)
    try:
        resp = _requests.post(
            'https://api.emailjs.com/api/v1.0/email/send',
            json=payload,
            timeout=10,
            verify=verify_ssl,
        )
        if resp.status_code == 200:
            logger.info('[EmailJS] OK → template=%s to=%s', template_id, to_email)
            return True
        logger.error(
            '[EmailJS] ERROR %s → template=%s to=%s body=%s',
            resp.status_code, template_id, to_email, resp.text[:300],
        )
        return False
    except Exception as exc:
        logger.error('[EmailJS] EXCEPCIÓN → template=%s to=%s error=%s', template_id, to_email, exc)
        return False


# ----------------------------
# Helpers de rol
# ----------------------------
def is_admin(user):
    return user.is_authenticated and user.groups.filter(name="ADMIN").exists()

def is_revisor(user):
    return user.is_authenticated and (user.is_staff or user.groups.filter(name="REVISOR").exists())

def is_contribuyente(user):
    return user.is_authenticated and user.groups.filter(name="CONTRIBUYENTE").exists()

def is_alcaldia_gestion(user):
    return user.is_authenticated and user.groups.filter(name="ALCALDIA_GESTION").exists()

def tiene_acceso(user, codigo):
    return AccesoProceso.objects.filter(
        user=user, habilitado=True, proceso__codigo=codigo, proceso__activo=True
    ).exists()


def _vincular_usuario_visita_incompleta(visita):
    """Crea cuenta portal + PerfilContribuyente y vincula cuando visita incompleta tiene correo."""
    from .models import PerfilContribuyente
    from catalogos.models import Municipio

    if not visita.correo or visita.contribuyente_id:
        return

    correo = visita.correo.strip().lower()
    es_usuario_nuevo = False
    temp_password = None

    user = User.objects.filter(username=correo).first()
    if not user:
        es_usuario_nuevo = True
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        user = User.objects.create_user(
            username=correo,
            password=temp_password,
            email=correo,
            first_name=visita.nombre_propietario or '',
        )
        try:
            grupo = Group.objects.get(name='CONTRIBUYENTE')
            user.groups.add(grupo)
        except Group.DoesNotExist:
            pass

        try:
            municipio = (
                Municipio.objects.filter(nombre__iexact=visita.municipio, activo=True).first()
                or Municipio.objects.filter(activo=True).first()
            )
            if municipio and not hasattr(user, 'perfil'):
                perfil = PerfilContribuyente(
                    user=user,
                    nombre_razon_social=visita.nombre_propietario or correo,
                    tipo_documento=visita.tipo_documento or 'CC',
                    numero_documento=visita.numero_documento or '0',
                    dv='',
                    direccion_notificacion=visita.direccion or '-',
                    municipio_notificacion=municipio,
                    telefono=visita.telefono or '-',
                    correo_electronico=correo,
                    clasificacion_contribuyente='REGIMEN_COMUN',
                    tipo_persona='NATURAL',
                    must_change_password=True,
                )
                perfil.asignar_departamento_notificacion()
                perfil.save()
        except Exception as exc:
            logger.warning('[visita_incompleta] No se pudo crear perfil para %s: %s', correo, exc)

        try:
            proceso_rit = Proceso.objects.get(codigo='RIT')
            AccesoProceso.objects.get_or_create(
                user=user, proceso=proceso_rit, defaults={'habilitado': True}
            )
        except Proceso.DoesNotExist:
            pass

        if temp_password:
            _enviar_emailjs(
                django_settings.EMAILJS_TEMPLATE_CREDENCIALES,
                correo,
                {
                    'to_name': visita.nombre_propietario or correo,
                    'usuario': correo,
                    'contrasena': temp_password,
                    'portal_url': 'https://segovia.portalterritorial.com.co',
                },
            )

    visita.contribuyente = user
    visita.save(update_fields=['contribuyente'])


# ----------------------------
# Helpers para ICA
# ----------------------------
def get_tarifas_json():
    """
    Devuelve { "actividad_id": tarifa_por_mil } como JSON para usar en JS.
    """
    tarifas = {
        str(a.id): float(a.tarifa)
        for a in ActividadEconomica.objects.filter(activo=True)
    }
    return json.dumps(tarifas, cls=DjangoJSONEncoder)


def get_municipios_departamentos_json():
    """
    Devuelve { "municipio_id": "nombre_departamento" } como JSON para usar en JS.
    """
    mapeo = {
        str(m.id): m.departamento.nombre
        for m in Municipio.objects.select_related('departamento').filter(activo=True)
    }
    return json.dumps(mapeo, cls=DjangoJSONEncoder)


# ----------------------------
# Publico
# ----------------------------
def home(request):
    if request.user.is_authenticated:
        if is_admin(request.user):
            return redirect("admin_panel")
        if request.user.groups.filter(name__in=['FUNCIONARIO_CAMPO', 'REVISOR']).exists():
            return redirect("mis_visitas")
        return redirect("tasks")
    return render(request, "home.html")


def signup(request):
    if request.method == "GET":
        perfil_form = PerfilContribuyenteForm()
        municipios_json = get_municipios_departamentos_json()
        # Pre-llenado desde QR de visita no atendida
        prefill = {
            'ref':    request.GET.get('ref', ''),
            'nombre': request.GET.get('nombre', ''),
            'dir':    request.GET.get('dir', ''),
            'mun':    request.GET.get('mun', ''),
            'act':    request.GET.get('act', ''),
            'est':    request.GET.get('est', ''),
        }
        return render(request, "signup.html", {
            "perfil_form": perfil_form,
            "municipios_json": municipios_json,
            "prefill": prefill,
        })

    # POST: procesar formulario de perfil
    perfil_form = PerfilContribuyenteForm(request.POST)

    if perfil_form.is_valid():
        email = perfil_form.cleaned_data.get('correo_electronico', '').strip().lower()

        # Verificar si ya existe usuario con ese email/username
        if User.objects.filter(username=email).exists():
            municipios_json = get_municipios_departamentos_json()
            return render(request, "signup.html", {
                "perfil_form": perfil_form,
                "municipios_json": municipios_json,
                "ya_registrado": True,
                "error": "Tu información ya fue registrada por la Alcaldía de Salgar. Para ingresar al portal, recupera tu contraseña.",
            })

        try:
            # 1. Generar contraseña temporal
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

            # 2. Crear usuario usando el email como username
            user = User.objects.create_user(
                username=email,
                password=temp_password,
                email=email,
                first_name=perfil_form.cleaned_data.get('nombre_razon_social', ''),
            )
            user.save()

            # 3. Asignar grupo CONTRIBUYENTE
            try:
                grupo = Group.objects.get(name="CONTRIBUYENTE")
                user.groups.add(grupo)
            except Group.DoesNotExist:
                pass

            # 4. Crear perfil del contribuyente con must_change_password=True
            perfil = perfil_form.save(commit=False)
            perfil.user = user
            perfil.must_change_password = True
            perfil.asignar_departamento_notificacion()
            perfil.save()

            # 5. Habilitar solo RIT al registrarse; otros procesos los habilita el admin
            try:
                proceso_rit = Proceso.objects.get(codigo='RIT')
                AccesoProceso.objects.get_or_create(
                    user=user,
                    proceso=proceso_rit,
                    defaults={'habilitado': True}
                )
            except Proceso.DoesNotExist:
                pass

            # 6. Enviar correo con credenciales temporales via EmailJS
            nombre_display = perfil_form.cleaned_data.get('nombre_razon_social', email)
            _enviar_emailjs(
                django_settings.EMAILJS_TEMPLATE_CREDENCIALES,
                email,
                {
                    'to_name':   nombre_display,
                    'usuario':   email,
                    'contrasena': temp_password,
                    'portal_url': 'https://segovia.portalterritorial.com.co',
                },
            )

            # 7. Redirigir al login con mensaje de registro exitoso
            return redirect("/signin/?registro=exitoso")

        except IntegrityError:
            municipios_json = get_municipios_departamentos_json()
            return render(request, "signup.html", {
                "perfil_form": perfil_form,
                "municipios_json": municipios_json,
                "ya_registrado": True,
                "error": "Tu información ya fue registrada por la Alcaldía de Salgar. Para ingresar al portal, recupera tu contraseña.",
            })

    # Formulario no válido
    municipios_json = get_municipios_departamentos_json()
    return render(request, "signup.html", {
        "perfil_form": perfil_form,
        "municipios_json": municipios_json,
        "error": "Por favor corrija los errores en el formulario"
    })


@login_required
def bienvenida(request):
    """Página de bienvenida después del registro."""
    if hasattr(request.user, 'perfil') and request.user.perfil.must_change_password:
        return redirect("cambiar_contrasena")
    from api_movil.models import VisitaRIT
    visita_incompleta = VisitaRIT.objects.filter(
        contribuyente=request.user, estado='incompleta', registro_rit=None
    ).order_by('-fecha_visita').first()
    return render(request, "bienvenida.html", {'visita_incompleta': visita_incompleta})


@login_required
def cambiar_contrasena(request):
    """Vista para cambio de contraseña obligatorio en el primer login."""
    if request.method == "GET":
        return render(request, "cambiar_contrasena.html")

    nueva = request.POST.get("nueva_contrasena", "").strip()
    confirmar = request.POST.get("confirmar_contrasena", "").strip()

    if not nueva or len(nueva) < 8:
        return render(request, "cambiar_contrasena.html", {
            "error": "La contraseña debe tener al menos 8 caracteres."
        })

    if nueva != confirmar:
        return render(request, "cambiar_contrasena.html", {
            "error": "Las contraseñas no coinciden."
        })

    request.user.set_password(nueva)
    request.user.save()

    # Marcar que ya no debe cambiar contraseña
    if hasattr(request.user, 'perfil'):
        request.user.perfil.must_change_password = False
        request.user.perfil.save(update_fields=['must_change_password'])

    # Re-autenticar para mantener la sesión activa
    from django.contrib.auth import update_session_auth_hash
    update_session_auth_hash(request, request.user)

    messages.success(request, "Contraseña actualizada correctamente.")
    return redirect("tasks")


def signin(request):
    if request.method == "GET":
        context = {"form": AuthenticationForm}
        if request.GET.get("registro") == "exitoso":
            context["success"] = "¡Registro exitoso! Revisa tu correo electrónico, encontrarás tus credenciales de acceso temporales. Luego inicia sesión aquí."
        return render(request, "signin.html", context)

    user = authenticate(
        request,
        username=request.POST.get("username"),
        password=request.POST.get("password")
    )

    if user is None:
        return render(request, "signin.html", {
            "form": AuthenticationForm,
            "error": "Usuario o Contraseña Incorrecta"
        })

    login(request, user)
    # Verificar si debe cambiar contraseña (primera vez)
    if hasattr(user, 'perfil') and user.perfil.must_change_password:
        return redirect("cambiar_contrasena")
    if is_admin(user):
        return redirect("admin_panel")
    if user.groups.filter(name__in=['FUNCIONARIO_CAMPO', 'REVISOR']).exists():
        return redirect("mis_visitas")
    return redirect("tasks")


@login_required
def signout(request):
    logout(request)
    return redirect("home")


# ----------------------------
# Recuperación de contraseña
# ----------------------------
def recuperar_contrasena(request):
    if request.method == "GET":
        return render(request, "recuperar_contrasena.html")

    username_or_email = request.POST.get("username_or_email", "").strip()

    # Buscar usuario por username, User.email o PerfilContribuyente.correo_electronico
    from tasks.models import PerfilContribuyente
    user = None
    try:
        user = User.objects.get(username=username_or_email)
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=username_or_email)
        except User.DoesNotExist:
            perfil = PerfilContribuyente.objects.filter(correo_electronico=username_or_email).first()
            if perfil:
                user = perfil.user

    # Si el usuario no tiene email en User, sincronizarlo desde el perfil
    if user and not user.email:
        try:
            perfil = user.perfil
            if perfil.correo_electronico:
                user.email = perfil.correo_electronico
                user.save(update_fields=['email'])
        except Exception:
            pass

    if user is None or not user.email:
        return render(request, "recuperar_contrasena.html", {
            "error": "No se encontró ningún usuario con ese nombre o correo, o el usuario no tiene email registrado."
        })

    # Invalidar códigos anteriores
    PasswordResetCode.objects.filter(user=user, usado=False).update(usado=True)

    # Generar código de 6 dígitos
    codigo = ''.join(random.choices(string.digits, k=6))
    PasswordResetCode.objects.create(user=user, codigo=codigo)

    # Enviar email con SendGrid
    nombre_display = user.get_full_name() or user.username
    mensaje_texto = (
        f"Hola {nombre_display},\n\n"
        f"Tu código de recuperación de contraseña es:\n\n"
        f"  {codigo}\n\n"
        f"Este código es válido por 15 minutos.\n\n"
        f"Si no solicitaste este código, ignora este mensaje.\n\n"
        f"Portal Tributario - Municipio de Segovia"
    )
    mensaje_html = f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Recuperación de contraseña</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6f9;padding:30px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;background-color:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.1);">

          <!-- Header verde -->
          <tr>
            <td align="center" style="background-color:#2e7d32;padding:35px 30px 25px;">
              <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:bold;letter-spacing:0.5px;">
                Portal Tributario
              </h1>
              <p style="margin:6px 0 0;color:#c8e6c9;font-size:14px;">
                Municipio de Segovia &mdash; Antioquia
              </p>
            </td>
          </tr>

          <!-- Cuerpo -->
          <tr>
            <td style="padding:40px 40px 30px;">
              <p style="margin:0 0 12px;color:#333333;font-size:16px;">
                Hola <strong>{nombre_display}</strong>,
              </p>
              <p style="margin:0 0 24px;color:#555555;font-size:15px;line-height:1.6;">
                Recibimos una solicitud para restablecer la contraseña de tu cuenta en el
                Portal Tributario. Usa el siguiente código de verificación:
              </p>

              <!-- Código destacado -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="padding:10px 0 28px;">
                    <div style="display:inline-block;background-color:#e8f5e9;border:2px solid #2e7d32;
                                border-radius:10px;padding:20px 40px;">
                      <span style="font-size:36px;font-weight:bold;color:#1b5e20;letter-spacing:10px;">
                        {codigo}
                      </span>
                    </div>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 8px;color:#555555;font-size:14px;line-height:1.6;">
                &#8226; Este código es <strong>válido por 15 minutos</strong>.
              </p>
              <p style="margin:0 0 30px;color:#555555;font-size:14px;line-height:1.6;">
                &#8226; Si no solicitaste este código, puedes ignorar este mensaje. Tu contraseña no será cambiada.
              </p>

              <hr style="border:none;border-top:1px solid #e0e0e0;margin:0 0 24px;">

              <p style="margin:0;color:#888888;font-size:13px;text-align:center;">
                Este es un mensaje automático, por favor no respondas a este correo.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="background-color:#f1f8e9;padding:20px 30px;border-top:1px solid #dcedc8;">
              <p style="margin:0 0 6px;color:#666666;font-size:12px;">
                Alcaldía Municipal de Segovia &mdash; Antioquia, Colombia
              </p>
              <p style="margin:0;color:#999999;font-size:11px;">
                Portal Tributario &bull; Municipio de Segovia
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    ok = _enviar_emailjs(
        django_settings.EMAILJS_TEMPLATE_RESET,
        user.email,
        {'to_name': nombre_display, 'codigo': codigo},
    )
    if not ok:
        return render(request, "recuperar_contrasena.html", {
            "error": "No se pudo enviar el correo. Intenta de nuevo más tarde."
        })

    # Guardar el id del usuario en sesión para el siguiente paso
    request.session['reset_user_id'] = user.id
    return redirect("verificar_codigo")


def verificar_codigo(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect("recuperar_contrasena")

    if request.method == "GET":
        return render(request, "verificar_codigo.html")

    codigo_ingresado = request.POST.get("codigo", "").strip()

    # Buscar código válido (no usado) creado en los últimos 15 minutos
    hace_15_min = timezone.now() - timezone.timedelta(minutes=15)
    reset_obj = PasswordResetCode.objects.filter(
        user_id=user_id,
        codigo=codigo_ingresado,
        usado=False,
        creado_en__gte=hace_15_min
    ).first()

    if reset_obj is None:
        return render(request, "verificar_codigo.html", {
            "error": "Código incorrecto o expirado. Intenta de nuevo."
        })

    reset_obj.usado = True
    reset_obj.save()
    request.session['reset_verificado'] = True
    return redirect("nueva_contrasena")


def nueva_contrasena(request):
    user_id = request.session.get('reset_user_id')
    verificado = request.session.get('reset_verificado')

    if not user_id or not verificado:
        return redirect("recuperar_contrasena")

    if request.method == "GET":
        return render(request, "nueva_contrasena.html")

    password1 = request.POST.get("password1", "")
    password2 = request.POST.get("password2", "")

    if len(password1) < 8:
        return render(request, "nueva_contrasena.html", {
            "error": "La contraseña debe tener al menos 8 caracteres."
        })

    if password1 != password2:
        return render(request, "nueva_contrasena.html", {
            "error": "Las contraseñas no coinciden."
        })

    user = get_object_or_404(User, id=user_id)
    user.set_password(password1)
    user.save()

    # Limpiar sesión
    del request.session['reset_user_id']
    del request.session['reset_verificado']

    messages.success(request, "Contraseña actualizada correctamente. Ya puedes iniciar sesión.")
    return redirect("signin")


# ----------------------------
# Panel ADMIN
# ----------------------------
@login_required
@user_passes_test(is_admin)
def admin_panel(request):
    return render(request, "admin_panel.html")


# ----------------------------
# Panel CONTRIBUYENTE
# ----------------------------
@login_required
def tasks(request):
    if is_admin(request.user):
        return redirect("admin_panel")

    # IDs de procesos habilitados para este usuario
    habilitados_ids = set(
        AccesoProceso.objects
        .filter(user=request.user, habilitado=True, proceso__activo=True)
        .values_list("proceso_id", flat=True)
    )

    # Todos los procesos activos ordenados
    procesos = Proceso.objects.filter(activo=True).order_by("nombre")

    # Determinar estado RIT del usuario para mostrar opciones correctas
    estado_rit = RegistroRIT.obtener_estado_usuario(request.user)
    rit_activo = RegistroRIT.get_rit_activo(request.user)

    # Si hay RIT pendiente pero ya fue firmado por OTP desde móvil, activarlo
    rit_pendiente_panel = None
    if estado_rit == 'PENDIENTE_FIRMA' and not rit_activo:
        rit_pendiente = RegistroRIT.get_rit_pendiente_firma(request.user)
        if rit_pendiente and rit_pendiente.firma_otp_verificada:
            from django.utils import timezone as _tz
            rit_pendiente.estado = 'ACTIVO'
            rit_pendiente.firma_timestamp = rit_pendiente.firma_timestamp or _tz.now()
            rit_pendiente.save(update_fields=['estado', 'firma_timestamp'])
            estado_rit = 'ACTIVO'
            rit_activo = rit_pendiente
        else:
            rit_pendiente_panel = rit_pendiente

    return render(request, "procesos.html", {
        "procesos": procesos,
        "habilitados_ids": habilitados_ids,
        "estado_rit": estado_rit,
        "rit_activo": rit_activo,
        "rit_pendiente_panel": rit_pendiente_panel,
        "es_alcaldia_gestion": is_alcaldia_gestion(request.user),
    })


@login_required
@user_passes_test(is_contribuyente)
def procesos(request):
    return tasks(request)


@login_required
def tasks_completed(request):
    """Vista de procesos completados (RIT, ICA, AUTO, Visitas móvil)."""
    from api_movil.models import VisitaRIT as VisitaRITMovil

    is_admin_user  = is_admin(request.user)
    is_revisor_user = is_revisor(request.user)
    is_alcaldia = is_alcaldia_gestion(request.user)
    puede_ver_todo = is_admin_user or is_revisor_user or is_alcaldia

    filtro_documento = request.GET.get('documento', '').strip()
    filtro_proceso   = request.GET.get('proceso', '')

    if puede_ver_todo:
        rits    = RegistroRIT.objects.select_related('user', 'municipio_notificacion').order_by('-fecha')
        icas    = DeclaracionICA.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')
        autos   = DeclaracionAutoRetencion.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')
        visitas = VisitaRITMovil.objects.select_related('funcionario', 'registro_rit').order_by('-fecha_visita')

        if filtro_documento:
            rits    = rits.filter(numero_documento__icontains=filtro_documento)
            icas    = icas.filter(numero_documento__icontains=filtro_documento)
            autos   = autos.filter(numero_documento__icontains=filtro_documento)
            visitas = visitas.filter(numero_documento__icontains=filtro_documento)

        if filtro_proceso == 'RIT':
            icas = DeclaracionICA.objects.none(); autos = DeclaracionAutoRetencion.objects.none(); visitas = VisitaRITMovil.objects.none()
        elif filtro_proceso == 'ICA':
            rits = RegistroRIT.objects.none(); autos = DeclaracionAutoRetencion.objects.none(); visitas = VisitaRITMovil.objects.none()
        elif filtro_proceso == 'AUTO':
            rits = RegistroRIT.objects.none(); icas = DeclaracionICA.objects.none(); visitas = VisitaRITMovil.objects.none()
        elif filtro_proceso == 'VISITA':
            rits = RegistroRIT.objects.none(); icas = DeclaracionICA.objects.none(); autos = DeclaracionAutoRetencion.objects.none()
    else:
        from django.db.models import Q
        rits    = RegistroRIT.objects.filter(user=request.user).select_related('municipio_notificacion').order_by('-fecha')
        icas    = DeclaracionICA.objects.filter(user=request.user).select_related('municipio').order_by('-fecha_diligenciamiento')
        autos   = DeclaracionAutoRetencion.objects.filter(user=request.user).select_related('municipio').order_by('-fecha_diligenciamiento')
        # El visitador ve sus propias visitas; el contribuyente ve las visitas donde está vinculado
        visitas = VisitaRITMovil.objects.filter(
            Q(funcionario=request.user) | Q(contribuyente=request.user)
        ).select_related('funcionario', 'registro_rit').order_by('-fecha_visita')

    es_contribuyente_user = is_contribuyente(request.user)

    return render(request, "tasks_completed.html", {
        "rits": rits,
        "icas": icas,
        "autos": autos,
        "visitas": visitas,
        "is_admin": is_admin_user,
        "is_revisor": is_revisor_user,
        "puede_ver_todo": puede_ver_todo,
        "es_contribuyente": es_contribuyente_user,
        "filtro_documento": filtro_documento,
        "filtro_proceso": filtro_proceso,
    })


# ----------------------------
# CRUD Task
# ----------------------------
@login_required
def create_task(request):
    if is_admin(request.user):
        return redirect("admin_panel")

    if request.method == "GET":
        return render(request, "create_task.html", {"form": TaskForm()})

    try:
        form = TaskForm(request.POST)
        new_task = form.save(commit=False)
        new_task.user = request.user
        new_task.save()
        return redirect("tasks")
    except ValueError:
        return render(request, "create_task.html", {
            "form": TaskForm(),
            "error": "Por favor proporciona datos validos"
        })


@login_required
def task_detail(request, task_id):
    task = get_object_or_404(Task, pk=task_id)

    if not is_admin(request.user) and task.user != request.user:
        return redirect("tasks")

    if request.method == "GET":
        form = TaskForm(instance=task)
        return render(request, "task_detail.html", {"task": task, "form": form})

    try:
        form = TaskForm(request.POST, instance=task)
        form.save()
        return redirect("tasks")
    except ValueError:
        return render(request, "task_detail.html", {
            "task": task,
            "form": TaskForm(instance=task),
            "error": "Error al Actualizar la Tarea"
        })


@login_required
def complete_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id, user=request.user)
    if request.method == "POST":
        task.datecompleted = timezone.now()
        task.save()
    return redirect("tasks")


@login_required
def delete_task(request, task_id):
    task = get_object_or_404(Task, pk=task_id, user=request.user)
    if request.method == "POST":
        task.delete()
    return redirect("tasks")


# ----------------------------
# ADMIN: usuarios/procesos
# ----------------------------
@login_required
@user_passes_test(is_admin)
def admin_usuarios(request):
    usuarios = User.objects.filter(groups__name="CONTRIBUYENTE").select_related('perfil').order_by("username")

    # Búsqueda
    criterio = request.GET.get('criterio', 'nombre')
    busqueda = request.GET.get('q', '').strip()

    if busqueda:
        if criterio == 'nombre':
            usuarios = usuarios.filter(perfil__nombre_razon_social__icontains=busqueda)
        elif criterio == 'documento':
            usuarios = usuarios.filter(perfil__numero_documento__icontains=busqueda)

    return render(request, "admin_usuarios.html", {
        "usuarios": usuarios,
        "criterio": criterio,
        "busqueda": busqueda,
    })


@login_required
@user_passes_test(is_admin)
def admin_accesos(request, user_id):
    u = get_object_or_404(User, id=user_id)
    procesos = Proceso.objects.filter(activo=True).order_by("nombre")

    if request.method == "POST":
        seleccionados = request.POST.getlist("procesos")

        AccesoProceso.objects.filter(user=u).update(habilitado=False)

        for pid in seleccionados:
            AccesoProceso.objects.update_or_create(
                user=u,
                proceso_id=pid,
                defaults={"habilitado": True}
            )

        # Obtener nombre del usuario para el mensaje
        nombre_usuario = u.username
        if hasattr(u, 'perfil') and u.perfil:
            nombre_usuario = u.perfil.nombre_razon_social

        messages.success(request, f'Procesos asignados exitosamente a "{nombre_usuario}"')
        return redirect("admin_usuarios")

    habilitados = set(
        AccesoProceso.objects.filter(user=u, habilitado=True)
        .values_list("proceso_id", flat=True)
    )

    return render(request, "admin_accesos.html", {
        "u": u,
        "procesos": procesos,
        "habilitados": habilitados
    })


@login_required
@user_passes_test(is_admin)
def admin_config_pdf(request):
    """Vista para configurar los parámetros de los PDFs."""
    from .forms import ConfiguracionPDFForm

    config = ConfiguracionPDF.get_config_activa()

    if request.method == "POST":
        if config:
            form = ConfiguracionPDFForm(request.POST, request.FILES, instance=config)
        else:
            form = ConfiguracionPDFForm(request.POST, request.FILES)

        if form.is_valid():
            config = form.save(commit=False)
            config.activo = True
            config.save()
            messages.success(request, 'Configuración de PDF guardada exitosamente.')
            return redirect('admin_config_pdf')
    else:
        if config:
            form = ConfiguracionPDFForm(instance=config)
        else:
            form = ConfiguracionPDFForm()

    return render(request, "admin_config_pdf.html", {
        "form": form,
        "config": config,
    })


@login_required
@user_passes_test(is_admin)
def admin_reportes(request):
    """Vista de reportería avanzada para ADMIN."""
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth

    # Filtros
    filtro_tipo = request.GET.get('tipo', '')  # RIT, ICA, o vacío para todos
    filtro_anio = request.GET.get('anio', '')
    filtro_mes = request.GET.get('mes', '')
    filtro_documento = request.GET.get('documento', '')

    # Datos base
    rits  = RegistroRIT.objects.select_related('user', 'municipio_notificacion').order_by('-fecha')
    icas  = DeclaracionICA.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')
    autos = DeclaracionAutoRetencion.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')

    # Aplicar filtros
    if filtro_documento:
        rits  = rits.filter(numero_documento__icontains=filtro_documento)
        icas  = icas.filter(numero_documento__icontains=filtro_documento)
        autos = autos.filter(numero_documento__icontains=filtro_documento)

    if filtro_anio:
        rits  = rits.filter(fecha__year=filtro_anio)
        icas  = icas.filter(anio_gravable=filtro_anio)
        autos = autos.filter(anio_gravable=filtro_anio)

    if filtro_mes:
        rits  = rits.filter(fecha__month=filtro_mes)
        icas  = icas.filter(fecha_diligenciamiento__month=filtro_mes)
        autos = autos.filter(fecha_diligenciamiento__month=filtro_mes)

    if filtro_tipo == 'RIT':
        icas  = DeclaracionICA.objects.none()
        autos = DeclaracionAutoRetencion.objects.none()
    elif filtro_tipo == 'ICA':
        rits  = RegistroRIT.objects.none()
        autos = DeclaracionAutoRetencion.objects.none()
    elif filtro_tipo == 'AUTO':
        rits = RegistroRIT.objects.none()
        icas = DeclaracionICA.objects.none()

    # Estadísticas generales
    total_rits        = RegistroRIT.objects.count()
    total_icas        = DeclaracionICA.objects.count()
    total_autos       = DeclaracionAutoRetencion.objects.count()
    total_recaudo_ica  = DeclaracionICA.objects.aggregate(total=Sum('total_a_pagar'))['total'] or 0
    total_recaudo_auto = DeclaracionAutoRetencion.objects.aggregate(total=Sum('total_a_pagar'))['total'] or 0

    # Estadísticas por mes (últimos 12 meses)
    from datetime import datetime, timedelta
    hace_12_meses = datetime.now() - timedelta(days=365)

    rits_por_mes = (
        RegistroRIT.objects
        .filter(fecha__gte=hace_12_meses)
        .annotate(mes=TruncMonth('fecha'))
        .values('mes')
        .annotate(total=Count('id'))
        .order_by('mes')
    )

    icas_por_mes = (
        DeclaracionICA.objects
        .filter(fecha_diligenciamiento__gte=hace_12_meses)
        .annotate(mes=TruncMonth('fecha_diligenciamiento'))
        .values('mes')
        .annotate(total=Count('id'), recaudo=Sum('total_a_pagar'))
        .order_by('mes')
    )

    autos_por_mes = (
        DeclaracionAutoRetencion.objects
        .filter(fecha_diligenciamiento__gte=hace_12_meses)
        .annotate(mes=TruncMonth('fecha_diligenciamiento'))
        .values('mes')
        .annotate(total=Count('id'), recaudo=Sum('total_a_pagar'))
        .order_by('mes')
    )

    # Estadísticas por tipo de operación
    rits_por_operacion = (
        RegistroRIT.objects
        .values('opcion_uso')
        .annotate(total=Count('id'))
    )

    icas_por_tipo = (
        DeclaracionICA.objects
        .values('opcion_uso')
        .annotate(total=Count('id'), recaudo=Sum('total_a_pagar'))
    )

    autos_por_tipo = (
        DeclaracionAutoRetencion.objects
        .values('opcion_uso')
        .annotate(total=Count('id'), recaudo=Sum('total_a_pagar'))
    )

    # Años disponibles para filtro
    anios_rit  = RegistroRIT.objects.dates('fecha', 'year')
    anios_ica  = DeclaracionICA.objects.values_list('anio_gravable', flat=True).distinct()
    anios_auto = DeclaracionAutoRetencion.objects.values_list('anio_gravable', flat=True).distinct()
    anios_disponibles = sorted(set(
        [d.year for d in anios_rit] + list(anios_ica) + list(anios_auto)
    ), reverse=True)

    return render(request, "admin_reportes.html", {
        "rits":  rits[:100],
        "icas":  icas[:100],
        "autos": autos[:100],
        "total_rits":         total_rits,
        "total_icas":         total_icas,
        "total_autos":        total_autos,
        "total_recaudo_ica":  total_recaudo_ica,
        "total_recaudo_auto": total_recaudo_auto,
        "rits_por_mes":       list(rits_por_mes),
        "icas_por_mes":       list(icas_por_mes),
        "autos_por_mes":      list(autos_por_mes),
        "rits_por_operacion": list(rits_por_operacion),
        "icas_por_tipo":      list(icas_por_tipo),
        "autos_por_tipo":     list(autos_por_tipo),
        "anios_disponibles":  anios_disponibles,
        "filtro_tipo":        filtro_tipo,
        "filtro_anio":        filtro_anio,
        "filtro_mes":         filtro_mes,
        "filtro_documento":   filtro_documento,
    })


# ----------------------------
# Formularios
# ----------------------------
@login_required
def proceso_rit(request):
    if is_admin(request.user):
        return redirect("admin_panel")

    # Obtener perfil del usuario (si existe)
    perfil = getattr(request.user, 'perfil', None)

    # Determinar estado RIT del usuario
    estado_rit = RegistroRIT.obtener_estado_usuario(request.user)
    rit_activo = RegistroRIT.get_rit_activo(request.user)
    rit_pendiente = RegistroRIT.get_rit_pendiente_firma(request.user)

    # Determinar opción de uso (inscripción por defecto para nuevos)
    opcion_uso = request.GET.get('opcion', 'INSCRIPCION')

    # Si hay un RIT pendiente de firma, verificar si ya fue firmado por OTP desde móvil
    if estado_rit == 'PENDIENTE_FIRMA' and rit_pendiente:
        if rit_pendiente.firma_otp_verificada:
            # Activar automáticamente el RIT firmado desde la app móvil
            from django.utils import timezone as _tz
            rit_pendiente.estado = 'ACTIVO'
            rit_pendiente.firma_timestamp = rit_pendiente.firma_timestamp or _tz.now()
            rit_pendiente.save(update_fields=['estado', 'firma_timestamp'])
            return redirect('tasks')
        # Redirigir al formulario de completar (editar + firmar)
        if opcion_uso != 'COMPLETAR':
            from django.urls import reverse as _rev
            return redirect(_rev('proceso_rit') + '?opcion=COMPLETAR')

    # Validar que la operación sea válida según el estado del RIT
    if estado_rit == 'ACTIVO':
        # Usuario con RIT activo solo puede ACTUALIZAR o CANCELAR
        if opcion_uso == 'INSCRIPCION':
            messages.warning(request, 'Ya tienes un RIT activo. Solo puedes actualizar o cancelar.')
            return redirect('tasks')
    else:
        # Usuario sin RIT o con RIT cancelado solo puede INSCRIBIRSE
        if opcion_uso in ('ACTUALIZACION', 'CANCELACION'):
            messages.warning(request, 'No tienes un RIT activo. Debes realizar una inscripción primero.')
            return redirect('tasks')

    # ---- GET ----
    if request.method == "GET":
        # Pre-llenar datos según la opción de uso
        initial_data = {
            'opcion_uso': opcion_uso,
            'clase_contribuyente': 'NORMAL',
        }
        visita_incompleta = None

        # Para ACTUALIZACION o CANCELACION, cargar datos del RIT activo
        if opcion_uso == 'COMPLETAR' and rit_pendiente:
            # Pre-llenar desde el RIT pendiente creado por la visita móvil
            initial_data.update({
                'opcion_uso': 'INSCRIPCION',
                'clase_contribuyente': rit_pendiente.clase_contribuyente,
                'es_retenedor_ica': rit_pendiente.es_retenedor_ica,
                'es_autorretenedor_ica': rit_pendiente.es_autorretenedor_ica,
                'nombre_razon_social': rit_pendiente.nombre_razon_social,
                'tipo_documento': rit_pendiente.tipo_documento,
                'numero_documento': rit_pendiente.numero_documento,
                'dv': rit_pendiente.dv,
                'cual_documento': rit_pendiente.cual_documento,
                'direccion_notificacion': rit_pendiente.direccion_notificacion,
                'municipio_notificacion': rit_pendiente.municipio_notificacion_id,
                'telefono': rit_pendiente.telefono,
                'correo_electronico': rit_pendiente.correo_electronico,
                'clasificacion_contribuyente': rit_pendiente.clasificacion_contribuyente,
                'tipo_persona': rit_pendiente.tipo_persona,
                'tipo_juridica': rit_pendiente.tipo_juridica,
                'numero_establecimientos': rit_pendiente.numero_establecimientos,
            })
            representantes_formset = RepresentanteLegalRITFormSet(prefix='representantes', instance=rit_pendiente)
            establecimientos_formset = EstablecimientoRITFormSet(prefix='establecimientos', instance=rit_pendiente)
            actividades_formset = ActividadEconomicaRITFormSet(prefix='actividades', instance=rit_pendiente)
            visita_incompleta = None
        elif opcion_uso in ('ACTUALIZACION', 'CANCELACION') and rit_activo:
            # Cargar datos del RIT activo
            initial_data.update({
                'clase_contribuyente': rit_activo.clase_contribuyente,
                'es_retenedor_ica': rit_activo.es_retenedor_ica,
                'es_autorretenedor_ica': rit_activo.es_autorretenedor_ica,
                'nombre_razon_social': rit_activo.nombre_razon_social,
                'tipo_documento': rit_activo.tipo_documento,
                'numero_documento': rit_activo.numero_documento,
                'dv': rit_activo.dv,
                'cual_documento': rit_activo.cual_documento,
                'direccion_notificacion': rit_activo.direccion_notificacion,
                'municipio_notificacion': rit_activo.municipio_notificacion_id,
                'telefono': rit_activo.telefono,
                'correo_electronico': rit_activo.correo_electronico,
                'numero_establecimientos': rit_activo.numero_establecimientos,
                'clasificacion_contribuyente': rit_activo.clasificacion_contribuyente,
                'otra_clasificacion': rit_activo.otra_clasificacion,
                'tipo_persona': rit_activo.tipo_persona,
                'tipo_juridica': rit_activo.tipo_juridica,
                'otro_tipo_juridica': rit_activo.otro_tipo_juridica,
            })
            # Cargar formsets del RIT activo
            representantes_formset = RepresentanteLegalRITFormSet(
                prefix='representantes',
                instance=rit_activo
            )
            establecimientos_formset = EstablecimientoRITFormSet(
                prefix='establecimientos',
                instance=rit_activo
            )
            actividades_formset = ActividadEconomicaRITFormSet(
                prefix='actividades',
                instance=rit_activo
            )
        else:
            # Para INSCRIPCION, usar datos del perfil
            if perfil:
                initial_data.update({
                    'nombre_razon_social': perfil.nombre_razon_social,
                    'tipo_documento': perfil.tipo_documento,
                    'numero_documento': perfil.numero_documento,
                    'dv': perfil.dv,
                    'cual_documento': perfil.cual_documento,
                    'direccion_notificacion': perfil.direccion_notificacion,
                    'municipio_notificacion': perfil.municipio_notificacion_id,
                    'telefono': perfil.telefono,
                    'correo_electronico': perfil.correo_electronico,
                    'numero_establecimientos': perfil.numero_establecimientos,
                    'clasificacion_contribuyente': perfil.clasificacion_contribuyente,
                    'otra_clasificacion': perfil.otra_clasificacion,
                    'tipo_persona': perfil.tipo_persona,
                    'tipo_juridica': perfil.tipo_juridica,
                    'otro_tipo_juridica': perfil.otro_tipo_juridica,
                })
            # Pre-llenar también desde visita incompleta vinculada (override perfil si existe)
            from api_movil.models import VisitaRIT as _VisitaRIT
            visita_incompleta = _VisitaRIT.objects.filter(
                contribuyente=request.user, estado='incompleta', registro_rit=None
            ).order_by('-fecha_visita').first()
            if visita_incompleta:
                if visita_incompleta.nombre_propietario:
                    initial_data['nombre_razon_social'] = visita_incompleta.nombre_propietario
                if visita_incompleta.tipo_documento:
                    initial_data['tipo_documento'] = visita_incompleta.tipo_documento
                if visita_incompleta.numero_documento:
                    initial_data['numero_documento'] = visita_incompleta.numero_documento
                if visita_incompleta.direccion:
                    initial_data['direccion_notificacion'] = visita_incompleta.direccion
                if visita_incompleta.telefono:
                    initial_data['telefono'] = visita_incompleta.telefono
                if visita_incompleta.correo:
                    initial_data['correo_electronico'] = visita_incompleta.correo
                if visita_incompleta.municipio:
                    mun = Municipio.objects.filter(
                        nombre__iexact=visita_incompleta.municipio, activo=True
                    ).first()
                    if mun:
                        initial_data['municipio_notificacion'] = mun.id
                # Pre-llenar actividad en el formset inicial
                actividad_inicial = []
                if visita_incompleta.actividad_economica:
                    from catalogos.models import ActividadEconomica as _AE
                    act = _AE.objects.filter(
                        codigo=visita_incompleta.actividad_economica, activo=True
                    ).first()
                    if act:
                        actividad_inicial = [{'actividad': act.pk}]
            else:
                visita_incompleta = None
                actividad_inicial = []
            # Formsets vacíos para inscripción
            representantes_formset = RepresentanteLegalRITFormSet(prefix='representantes')
            establecimientos_formset = EstablecimientoRITFormSet(prefix='establecimientos')
            actividades_formset = ActividadEconomicaRITFormSet(
                prefix='actividades',
                initial=actividad_inicial if actividad_inicial else None,
            )

        form = RITForm(initial=initial_data, perfil=perfil, opcion_uso=opcion_uso)
        municipios_json = get_municipios_departamentos_json()

        return render(request, "formularios/rit.html", {
            "form": form,
            "perfil": perfil,
            "municipios_json": municipios_json,
            "representantes_formset": representantes_formset,
            "establecimientos_formset": establecimientos_formset,
            "actividades_formset": actividades_formset,
            "opcion_uso": opcion_uso,
            "rit_activo": rit_activo,
            "visita_incompleta": visita_incompleta,
        })

    # ---- POST ----
    if opcion_uso == 'COMPLETAR' and rit_pendiente:
        form = RITForm(request.POST, request.FILES, instance=rit_pendiente, perfil=perfil, opcion_uso='INSCRIPCION')
        representantes_formset = RepresentanteLegalRITFormSet(request.POST, prefix='representantes', instance=rit_pendiente)
        establecimientos_formset = EstablecimientoRITFormSet(request.POST, prefix='establecimientos', instance=rit_pendiente)
        actividades_formset = ActividadEconomicaRITFormSet(request.POST, prefix='actividades', instance=rit_pendiente)
    else:
        form = RITForm(request.POST, request.FILES, perfil=perfil, opcion_uso=opcion_uso)
        representantes_formset = RepresentanteLegalRITFormSet(request.POST, prefix='representantes')
        establecimientos_formset = EstablecimientoRITFormSet(request.POST, prefix='establecimientos')
        actividades_formset = ActividadEconomicaRITFormSet(request.POST, prefix='actividades')

    municipios_json = get_municipios_departamentos_json()

    # Validar formulario principal primero
    form_valido = form.is_valid()

    # Si tiene_establecimientos es False, no validar el formset de establecimientos
    tiene_establecimientos = form.cleaned_data.get('tiene_establecimientos', True) if form_valido else True
    establecimientos_valido = establecimientos_formset.is_valid() if tiene_establecimientos else True

    # Validar todos los formularios
    if (form_valido and representantes_formset.is_valid() and
        establecimientos_valido and actividades_formset.is_valid()):

        # Guardar RIT principal
        rit = form.save(commit=False)
        rit.user = request.user
        if opcion_uso == 'COMPLETAR' and rit_pendiente:
            rit.radicado = rit_pendiente.radicado  # preservar radicado original
        else:
            rit.radicado = RegistroRIT.generar_radicado()
        rit.asignar_departamento_notificacion()
        rit.save()

        # Guardar representantes
        representantes = representantes_formset.save(commit=False)
        for idx, rep in enumerate(representantes):
            rep.rit = rit
            rep.orden = idx + 1
            rep.save()
        for obj in representantes_formset.deleted_objects:
            obj.delete()

        # Guardar establecimientos (solo si tiene_establecimientos es True)
        if rit.tiene_establecimientos:
            establecimientos = establecimientos_formset.save(commit=False)
            for idx, est in enumerate(establecimientos):
                est.rit = rit
                est.orden = idx + 1
                est.save()
            for obj in establecimientos_formset.deleted_objects:
                obj.delete()

        # Guardar actividades
        actividades = actividades_formset.save(commit=False)
        for idx, act in enumerate(actividades):
            act.rit = rit
            act.orden = idx + 1
            act.save()
        for obj in actividades_formset.deleted_objects:
            obj.delete()

        # ===== FIRMA ELECTRÓNICA OTP =====
        # Invalidar OTPs anteriores de este registro
        FirmaOTPRIT.objects.filter(registro=rit, usado=False).update(usado=True)

        # Generar y enviar OTP al declarante
        email_destino = request.user.email or getattr(perfil, 'correo_electronico', None)
        nombre = getattr(perfil, 'nombre_razon_social', request.user.get_full_name()) or request.user.username
        otp_code = ''.join(random.choices('0123456789', k=6))
        FirmaOTPRIT.objects.create(registro=rit, codigo=otp_code, tipo='declarante')
        _enviar_otp_firma_rit(email_destino, nombre, otp_code, rit)

        return redirect("verificar_firma_rit", registro_id=rit.id)

    # Si hay errores - mostrar detalles para debug
    errores = []
    if form.errors:
        errores.append(f"Formulario principal: {form.errors}")
    if representantes_formset.errors:
        errores.append(f"Representantes: {representantes_formset.errors}")
    if establecimientos_formset.errors:
        errores.append(f"Establecimientos: {establecimientos_formset.errors}")
    if actividades_formset.errors:
        errores.append(f"Actividades: {actividades_formset.errors}")

    print("=== ERRORES RIT ===")
    for e in errores:
        print(e)

    messages.error(request, 'Por favor corrija los errores en el formulario.')
    return render(request, "formularios/rit.html", {
        "form": form,
        "perfil": perfil,
        "municipios_json": municipios_json,
        "representantes_formset": representantes_formset,
        "establecimientos_formset": establecimientos_formset,
        "actividades_formset": actividades_formset,
        "opcion_uso": opcion_uso,
    })


# ----------------------------
# RIT — CARGA POR ALCALDÍA
# ----------------------------

@login_required
def rit_alcaldia(request):
    """Vista exclusiva para ALCALDIA_GESTION: crea RIT inicial para un contribuyente sin OTP."""
    from .models import PerfilContribuyente
    from catalogos.models import Municipio as _Municipio

    if not is_alcaldia_gestion(request.user):
        return redirect("tasks")

    municipios_json = get_municipios_departamentos_json()

    if request.method == "GET":
        form = RITForm(initial={'opcion_uso': 'INSCRIPCION'}, perfil=None, opcion_uso='INSCRIPCION')
        representantes_formset = RepresentanteLegalRITFormSet(prefix='representantes')
        establecimientos_formset = EstablecimientoRITFormSet(prefix='establecimientos')
        actividades_formset = ActividadEconomicaRITFormSet(prefix='actividades')
        return render(request, "formularios/rit_alcaldia.html", {
            "form": form,
            "representantes_formset": representantes_formset,
            "establecimientos_formset": establecimientos_formset,
            "actividades_formset": actividades_formset,
            "municipios_json": municipios_json,
        })

    # ---- POST ----
    form = RITForm(request.POST, request.FILES, perfil=None, opcion_uso='INSCRIPCION')
    representantes_formset = RepresentanteLegalRITFormSet(request.POST, prefix='representantes')
    establecimientos_formset = EstablecimientoRITFormSet(request.POST, prefix='establecimientos')
    actividades_formset = ActividadEconomicaRITFormSet(request.POST, prefix='actividades')

    tiene_establecimientos = True
    form_valido = form.is_valid()
    if form_valido:
        tiene_establecimientos = form.cleaned_data.get('tiene_establecimientos', True)
    establecimientos_valido = establecimientos_formset.is_valid() if tiene_establecimientos else True

    if (form_valido and representantes_formset.is_valid() and
            establecimientos_valido and actividades_formset.is_valid()):

        correo = form.cleaned_data.get('correo_electronico', '').strip().lower()

        # 1. Buscar o crear el usuario contribuyente (sin enviar credenciales)
        contribuyente_user = User.objects.filter(username=correo).first()
        if not contribuyente_user:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            contribuyente_user = User.objects.create_user(
                username=correo,
                password=temp_password,
                email=correo,
                first_name=form.cleaned_data.get('nombre_razon_social', ''),
            )
            try:
                grupo = Group.objects.get(name='CONTRIBUYENTE')
                contribuyente_user.groups.add(grupo)
            except Group.DoesNotExist:
                pass

        # 2. Crear PerfilContribuyente si no existe
        if not hasattr(contribuyente_user, 'perfil'):
            mun = form.cleaned_data.get('municipio_notificacion')
            try:
                perfil_c = PerfilContribuyente(
                    user=contribuyente_user,
                    nombre_razon_social=form.cleaned_data.get('nombre_razon_social', correo),
                    tipo_documento=form.cleaned_data.get('tipo_documento', 'CC'),
                    numero_documento=form.cleaned_data.get('numero_documento', '0'),
                    dv=form.cleaned_data.get('dv', ''),
                    cual_documento=form.cleaned_data.get('cual_documento', ''),
                    direccion_notificacion=form.cleaned_data.get('direccion_notificacion', '-'),
                    municipio_notificacion=mun,
                    telefono=form.cleaned_data.get('telefono', '-'),
                    correo_electronico=correo,
                    clasificacion_contribuyente='REGIMEN_COMUN',
                    tipo_persona=form.cleaned_data.get('tipo_persona', 'NATURAL'),
                    tipo_juridica=form.cleaned_data.get('tipo_juridica', ''),
                    must_change_password=True,
                )
                perfil_c.asignar_departamento_notificacion()
                perfil_c.save()
            except Exception as exc:
                logger.warning('[rit_alcaldia] No se pudo crear perfil para %s: %s', correo, exc)

        # 3. Habilitar acceso RIT si no lo tiene
        try:
            proceso_rit_obj = Proceso.objects.get(codigo='RIT')
            AccesoProceso.objects.get_or_create(
                user=contribuyente_user,
                proceso=proceso_rit_obj,
                defaults={'habilitado': True}
            )
        except Proceso.DoesNotExist:
            pass

        # 4. Crear el RIT (save() lo pone en PENDIENTE_FIRMA, luego forzamos ACTIVO)
        from django.utils import timezone as _tz
        rit = form.save(commit=False)
        rit.user = contribuyente_user
        rit.radicado = RegistroRIT.generar_radicado()
        rit.asignar_departamento_notificacion()

        # 5. PDF físico adjunto
        if request.FILES.get('pdf_fisico'):
            rit.pdf_fisico = request.FILES['pdf_fisico']

        rit.save()  # save() pone estado=PENDIENTE_FIRMA para registro nuevo

        # Forzar ACTIVO saltando la máquina de estados del save()
        now_ts = _tz.now()
        RegistroRIT.objects.filter(pk=rit.pk).update(
            estado='ACTIVO',
            firma_otp_verificada=True,
            firma_timestamp=now_ts,
        )

        # Guardar representantes
        representantes = representantes_formset.save(commit=False)
        for idx, rep in enumerate(representantes):
            rep.rit = rit
            rep.orden = idx + 1
            rep.save()
        for obj in representantes_formset.deleted_objects:
            obj.delete()

        # Guardar establecimientos
        if rit.tiene_establecimientos:
            establecimientos = establecimientos_formset.save(commit=False)
            for idx, est in enumerate(establecimientos):
                est.rit = rit
                est.orden = idx + 1
                est.save()
            for obj in establecimientos_formset.deleted_objects:
                obj.delete()

        # Guardar actividades
        actividades = actividades_formset.save(commit=False)
        for idx, act in enumerate(actividades):
            act.rit = rit
            act.orden = idx + 1
            act.save()
        for obj in actividades_formset.deleted_objects:
            obj.delete()

        messages.success(
            request,
            f'RIT registrado exitosamente — Radicado: {rit.radicado} para {correo}.'
        )
        return redirect("rit_alcaldia")

    messages.error(request, 'Por favor corrija los errores en el formulario.')
    return render(request, "formularios/rit_alcaldia.html", {
        "form": form,
        "representantes_formset": representantes_formset,
        "establecimientos_formset": establecimientos_formset,
        "actividades_formset": actividades_formset,
        "municipios_json": municipios_json,
    })


# ----------------------------
# RIT — FIRMA ELECTRÓNICA OTP
# ----------------------------

def _enviar_otp_firma_rit(email_destino, nombre, otp_code, registro):
    """Envía el correo OTP de firma electrónica RIT via EmailJS."""
    radicado = getattr(registro, 'radicado', None) or registro.id
    if email_destino:
        _enviar_emailjs(
            django_settings.EMAILJS_TEMPLATE_OTP,
            email_destino,
            {'to_name': nombre, 'codigo': otp_code, 'tipo_formulario': 'RIT', 'radicado': radicado},
        )


@login_required
def verificar_firma_rit(request, registro_id):
    """Verificación OTP para firma electrónica del Registro RIT."""
    import hashlib
    registro = get_object_or_404(RegistroRIT, id=registro_id, user=request.user)

    if registro.firma_otp_verificada:
        messages.success(request, '¡RIT ya fue firmado y guardado exitosamente!')
        return redirect("tasks_completed")

    otp_pendiente = FirmaOTPRIT.objects.filter(registro=registro, usado=False).first()
    if not otp_pendiente:
        from django.urls import reverse as _rev
        return redirect(_rev('proceso_rit') + '?opcion=COMPLETAR')

    perfil = getattr(request.user, 'perfil', None)
    email_destino = request.user.email or getattr(perfil, 'correo_electronico', '')
    nombre = getattr(perfil, 'nombre_razon_social', request.user.get_full_name()) or request.user.username

    if request.method == 'GET':
        return render(request, "formularios/verificar_firma_rit.html", {
            "registro": registro,
            "email": email_destino,
        })

    action = request.POST.get("action", "verificar")

    if action == "reenviar":
        nuevo_otp = ''.join(random.choices('0123456789', k=6))
        FirmaOTPRIT.objects.filter(registro=registro, usado=False).update(usado=True)
        FirmaOTPRIT.objects.create(registro=registro, codigo=nuevo_otp, tipo='declarante')
        _enviar_otp_firma_rit(email_destino, nombre, nuevo_otp, registro)
        messages.info(request, f'Se reenvió un nuevo código a {email_destino}.')
        return render(request, "formularios/verificar_firma_rit.html", {
            "registro": registro,
            "email": email_destino,
        })

    codigo_ingresado = request.POST.get("codigo", "").strip()
    limite = timezone.now() - timezone.timedelta(minutes=15)
    otp_obj = FirmaOTPRIT.objects.filter(
        registro=registro,
        codigo=codigo_ingresado,
        usado=False,
        creado_en__gte=limite,
    ).first()

    if not otp_obj:
        return render(request, "formularios/verificar_firma_rit.html", {
            "registro": registro,
            "email": email_destino,
            "error": "Código incorrecto o expirado. Verifique e intente de nuevo.",
        })

    otp_obj.usado = True
    otp_obj.save()

    ahora = timezone.now()
    datos_firma = (
        f"{registro.id}|{request.user.username}"
        f"|{getattr(perfil, 'numero_documento', '')}|{ahora.isoformat()}"
    )
    firma_hash = hashlib.sha256(datos_firma.encode()).hexdigest()
    registro.firma_otp_verificada = True
    registro.firma_timestamp = ahora
    registro.firma_hash = firma_hash
    # Activar el RIT solo al completar la firma
    if registro.opcion_uso in ('INSCRIPCION', 'ACTUALIZACION'):
        registro.estado = 'ACTIVO'
    registro.save(update_fields=['firma_otp_verificada', 'firma_timestamp', 'firma_hash', 'estado'])

    # Vincular visita incompleta al RIT recién firmado
    from api_movil.models import VisitaRIT as _VisitaRIT
    _VisitaRIT.objects.filter(
        contribuyente=request.user, estado='incompleta', registro_rit=None
    ).update(registro_rit=registro, estado='sincronizado')

    if registro.opcion_uso == 'INSCRIPCION':
        msg = f'¡RIT inscrito y firmado exitosamente! Radicado: {registro.radicado}'
    elif registro.opcion_uso == 'ACTUALIZACION':
        msg = f'¡RIT actualizado y firmado exitosamente! Radicado: {registro.radicado}'
    elif registro.opcion_uso == 'CANCELACION':
        msg = f'¡RIT cancelado y firmado exitosamente! Radicado: {registro.radicado}.'
    else:
        msg = f'¡RIT firmado exitosamente! Radicado: {registro.radicado}'

    messages.success(request, msg)
    return redirect("tasks_completed")


# ----------------------------
# ICA + ACTIVIDADES + TOTALES
# ----------------------------

def _enviar_otp_firma_ica(email_destino, nombre, otp_code, declaracion, tipo):
    """Envía el correo OTP de firma electrónica ICA via EmailJS."""
    etiquetas = {'contador': 'Contador', 'revisor': 'Revisor Fiscal', 'declarante': 'Declarante'}
    rol = etiquetas.get(tipo, 'Firmante')
    radicado = getattr(declaracion, 'radicado', None) or declaracion.id
    if email_destino:
        _enviar_emailjs(
            django_settings.EMAILJS_TEMPLATE_OTP,
            email_destino,
            {'to_name': nombre, 'codigo': otp_code, 'tipo_formulario': f'ICA — {rol}', 'radicado': radicado},
        )


@login_required
def proceso_ica(request):
    if is_admin(request.user):
        return redirect("admin_panel")

    if not tiene_acceso(request.user, "ICA"):
        return redirect("tasks")

    tarifas_json = get_tarifas_json()

    # Usuario alcaldía: ingresa datos del contribuyente manualmente, sin perfil
    es_alcaldia = request.user.groups.filter(name='ALCALDIA_GESTION').exists()

    # Obtener perfil del usuario (si existe y no es alcaldía)
    perfil = None if es_alcaldia else getattr(request.user, 'perfil', None)

    # Obtener declaraciones anteriores del usuario para correcciones
    declaraciones_anteriores = DeclaracionICA.objects.filter(
        user=request.user
    ).order_by('-anio_gravable', '-fecha_diligenciamiento')

    # JSON con años gravables que ya tienen declaración inicial
    # ALCALDIA_GESTION puede crear múltiples INICIAL, no bloquear en frontend
    if es_alcaldia:
        anios_con_inicial = []
    else:
        anios_con_inicial = list(
            DeclaracionICA.objects.filter(
                user=request.user,
                opcion_uso='INICIAL'
            ).values_list('anio_gravable', flat=True).distinct()
        )

    # ---- GET ----
    if request.method == "GET":
        editar_id = request.GET.get('editar')
        declaracion_editar = None
        if editar_id:
            declaracion_editar = DeclaracionICA.objects.filter(
                id=editar_id, user=request.user, firma_otp_verificada=False
            ).first()

        if declaracion_editar:
            form = ICAForm(instance=declaracion_editar, perfil=perfil, user=request.user)
            formset = DeclaracionActividadFormSetEdicion(instance=declaracion_editar)
            anios_con_inicial = [a for a in anios_con_inicial if a != declaracion_editar.anio_gravable]
        else:
            initial_data = {}
            if perfil:
                initial_data = {
                    'nombre_razon_social': perfil.nombre_razon_social,
                    'tipo_documento': perfil.tipo_documento,
                    'numero_documento': perfil.numero_documento,
                    'dv': perfil.dv,
                    'cual_documento': perfil.cual_documento,
                    'direccion_notificacion': perfil.direccion_notificacion,
                    'municipio_notificacion': perfil.municipio_notificacion_id,
                    'telefono': perfil.telefono,
                    'correo_electronico': perfil.correo_electronico,
                    'numero_establecimientos': perfil.numero_establecimientos,
                    'clasificacion_contribuyente': perfil.clasificacion_contribuyente,
                    'otra_clasificacion': perfil.otra_clasificacion,
                    'tipo_persona': perfil.tipo_persona,
                    'tipo_juridica': perfil.tipo_juridica,
                    'otro_tipo_juridica': perfil.otro_tipo_juridica,
                }
            form = ICAForm(initial=initial_data, perfil=perfil, user=request.user)
            formset = DeclaracionActividadFormSet()

        return render(request, "formularios/ica.html", {
            "form": form,
            "formset": formset,
            "tarifas_json": tarifas_json,
            "perfil": perfil,
            "declaraciones_anteriores": declaraciones_anteriores,
            "anios_con_inicial_json": json.dumps(anios_con_inicial),
            "es_alcaldia": es_alcaldia,
            "editar_id": editar_id,
        })

    # ---- POST ----
    editar_id = request.POST.get('editar_id')
    declaracion_editar = None
    if editar_id:
        declaracion_editar = DeclaracionICA.objects.filter(
            id=editar_id, user=request.user, firma_otp_verificada=False
        ).first()

    if declaracion_editar:
        form = ICAForm(request.POST, request.FILES, instance=declaracion_editar, perfil=perfil, user=request.user)
        formset = DeclaracionActividadFormSetEdicion(request.POST, instance=declaracion_editar)
    else:
        form = ICAForm(request.POST, request.FILES, perfil=perfil, user=request.user)
        formset = DeclaracionActividadFormSet(request.POST)

    if not form.is_valid() or not formset.is_valid():
        return render(request, "formularios/ica.html", {
            "form": form,
            "formset": formset,
            "tarifas_json": tarifas_json,
            "perfil": perfil,
            "declaraciones_anteriores": declaraciones_anteriores,
            "anios_con_inicial_json": json.dumps(anios_con_inicial),
            "es_alcaldia": es_alcaldia,
            "editar_id": editar_id,
        })

    # Validar que renglón 15 == renglón 16 (suma de ingresos de actividades)
    # Calcular renglón 15: Total ingresos gravables
    from decimal import Decimal
    b8 = Decimal(str(form.cleaned_data.get('b8_total_ingresos_pais') or 0))
    b9 = Decimal(str(form.cleaned_data.get('b9_menos_ingresos_fuera_municipio') or 0))
    b11 = Decimal(str(form.cleaned_data.get('b11_menos_devoluciones_rebajas_descuentos') or 0))
    b12 = Decimal(str(form.cleaned_data.get('b12_menos_exportaciones_venta_activos_fijos') or 0))
    b13 = Decimal(str(form.cleaned_data.get('b13_menos_otras_actividades_excluidas_no_sujetas') or 0))
    b14 = Decimal(str(form.cleaned_data.get('b14_menos_actividades_exentas_por_acuerdo') or 0))

    renglon_10 = max(Decimal(0), b8 - b9)
    renglon_15 = max(Decimal(0), renglon_10 - b11 - b12 - b13 - b14)

    # Calcular renglón 16: Suma de ingresos de las actividades
    renglon_16 = Decimal(0)
    for f in formset:
        if f.cleaned_data and not f.cleaned_data.get('DELETE', False):
            ingresos = f.cleaned_data.get('ingresos_gravados') or 0
            renglon_16 += Decimal(str(ingresos))

    if renglon_15 != renglon_16 and not declaracion_editar:
        form.add_error(None, f'El total de ingresos gravados (renglón 16: ${renglon_16:,.0f}) debe ser igual al total de ingresos gravables (renglón 15: ${renglon_15:,.0f}). Revisa la discriminación de tus actividades económicas.')
        return render(request, "formularios/ica.html", {
            "form": form,
            "formset": formset,
            "tarifas_json": tarifas_json,
            "perfil": perfil,
            "declaraciones_anteriores": declaraciones_anteriores,
            "anios_con_inicial_json": json.dumps(anios_con_inicial),
            "es_alcaldia": es_alcaldia,
            "editar_id": editar_id,
            "error": f"Error de validación: El renglón 16 (${renglon_16:,.0f}) no coincide con el renglón 15 (${renglon_15:,.0f})."
        })

    # Guardar cabecera
    declaracion = form.save(commit=False)
    declaracion.user = request.user
    declaracion.asignar_departamento()
    declaracion.asignar_departamento_notificacion()
    declaracion.save()

    # Si es edición de declaración sin firmar, limpiar OTPs anteriores
    if declaracion_editar:
        FirmaOTPICA.objects.filter(declaracion=declaracion, usado=False).update(usado=True)

    # Sincronizar perfil con datos editados
    if perfil:
        campos_sync = [
            'nombre_razon_social', 'tipo_documento', 'numero_documento',
            'dv', 'cual_documento', 'direccion_notificacion',
            'municipio_notificacion', 'telefono', 'correo_electronico',
            'clasificacion_contribuyente', 'otra_clasificacion',
            'tipo_persona', 'tipo_juridica', 'otro_tipo_juridica',
        ]
        for campo in campos_sync:
            valor = form.cleaned_data.get(campo)
            if valor is not None:
                setattr(perfil, campo, valor)
        perfil.asignar_departamento_notificacion()
        perfil.save()

    # Ahora sí, formset con instance
    formset = DeclaracionActividadFormSet(request.POST, instance=declaracion)

    if not formset.is_valid():
        return render(request, "formularios/ica.html", {
            "form": form,
            "formset": formset,
            "tarifas_json": tarifas_json,
            "perfil": perfil,
            "declaraciones_anteriores": declaraciones_anteriores,
            "anios_con_inicial_json": json.dumps(anios_con_inicial),
            "es_alcaldia": es_alcaldia,
            "editar_id": editar_id,
        })

    items = formset.save(commit=False)

    for it in items:
        # snapshots del catálogo
        it.tarifa_aplicada = it.actividad.tarifa
        it.tipo_aplicado = it.actividad.tipo

        # impuesto por actividad: ingresos * tarifa / 1000
        it.impuesto = int(round((float(it.ingresos_gravados) * float(it.tarifa_aplicada)) / 1000))
        it.save()

    for obj in formset.deleted_objects:
        obj.delete()

    # Totales: ICA + 15% avisos + 5% bomberil
    declaracion.recalcular_totales()

    # ===== FIRMA ELECTRÓNICA OTP =====
    # Usuario de alcaldía: terminar directamente sin OTP
    if request.user.groups.filter(name='ALCALDIA_GESTION').exists():
        import hashlib as _hashlib
        _ahora = timezone.now()
        _datos = f"{declaracion.id}|{request.user.username}|{_ahora.isoformat()}"
        declaracion.firma_otp_verificada = True
        declaracion.firma_timestamp = _ahora
        declaracion.firma_hash = _hashlib.sha256(_datos.encode()).hexdigest()
        declaracion.save(update_fields=['firma_otp_verificada', 'firma_timestamp', 'firma_hash'])
        messages.success(request, '✓ Declaración ICA guardada exitosamente.')
        return redirect("tasks_completed")

    # Invalidar OTPs anteriores de esta declaración
    FirmaOTPICA.objects.filter(declaracion=declaracion, usado=False).update(usado=True)

    # Determinar primer paso de verificación:
    # Contador → Revisor → Declarante
    if declaracion.tiene_contador and declaracion.contador_email:
        tipo_otp = 'contador'
        email_destino = declaracion.contador_email
        nombre = declaracion.contador_nombre or 'Contador'
    elif declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
        tipo_otp = 'revisor'
        email_destino = declaracion.revisor_email
        nombre = declaracion.revisor_nombre or 'Revisor Fiscal'
    else:
        tipo_otp = 'declarante'
        email_destino = request.user.email or getattr(getattr(request.user, 'perfil', None), 'correo_electronico', None)
        nombre = getattr(getattr(request.user, 'perfil', None), 'nombre_razon_social', request.user.get_full_name()) or request.user.username

    otp_code = ''.join(random.choices('0123456789', k=6))
    FirmaOTPICA.objects.create(declaracion=declaracion, codigo=otp_code, tipo=tipo_otp)

    _enviar_otp_firma_ica(email_destino, nombre, otp_code, declaracion, tipo_otp)

    return redirect("verificar_firma_ica", declaracion_id=declaracion.id)


@login_required
def reiniciar_firma_ica(request, declaracion_id):
    """Reinicia el flujo OTP para una declaración sin firmar."""
    declaracion = get_object_or_404(DeclaracionICA, id=declaracion_id, user=request.user)

    if declaracion.firma_otp_verificada:
        messages.info(request, 'Esta declaración ya fue firmada.')
        return redirect('tasks_completed')

    # Invalidar OTPs anteriores
    FirmaOTPICA.objects.filter(declaracion=declaracion, usado=False).update(usado=True)

    # Determinar primer paso
    if declaracion.tiene_contador and declaracion.contador_email:
        tipo_otp = 'contador'
        email_destino = declaracion.contador_email
        nombre = declaracion.contador_nombre or 'Contador'
    elif declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
        tipo_otp = 'revisor'
        email_destino = declaracion.revisor_email
        nombre = declaracion.revisor_nombre or 'Revisor Fiscal'
    else:
        tipo_otp = 'declarante'
        email_destino = request.user.email or getattr(getattr(request.user, 'perfil', None), 'correo_electronico', None)
        nombre = getattr(getattr(request.user, 'perfil', None), 'nombre_razon_social', request.user.get_full_name()) or request.user.username

    otp_code = ''.join(random.choices('0123456789', k=6))
    FirmaOTPICA.objects.create(declaracion=declaracion, codigo=otp_code, tipo=tipo_otp)
    _enviar_otp_firma_ica(email_destino, nombre, otp_code, declaracion, tipo_otp)

    return redirect('verificar_firma_ica', declaracion_id=declaracion.id)


@login_required
def verificar_firma_ica(request, declaracion_id):
    """Verificación OTP encadenada: Contador → Revisor → Declarante."""
    import hashlib
    declaracion = get_object_or_404(DeclaracionICA, id=declaracion_id, user=request.user)

    if declaracion.firma_otp_verificada:
        messages.success(request, '¡Declaración ICA ya fue firmada y guardada exitosamente!')
        return redirect("tasks_completed")

    # OTP pendiente más reciente
    otp_pendiente = FirmaOTPICA.objects.filter(declaracion=declaracion, usado=False).first()
    if not otp_pendiente:
        messages.error(request, 'No hay código de verificación pendiente. Vuelva a enviar la declaración.')
        return redirect("proceso_ica")

    tipo = otp_pendiente.tipo  # 'declarante', 'contador', 'revisor'

    etiquetas = {'contador': 'Contador', 'revisor': 'Revisor Fiscal', 'declarante': 'Declarante'}
    rol = etiquetas.get(tipo, 'Declarante')

    if tipo == 'contador':
        email_destino = declaracion.contador_email or ''
        nombre = declaracion.contador_nombre or 'Contador'
    elif tipo == 'revisor':
        email_destino = declaracion.revisor_email or ''
        nombre = declaracion.revisor_nombre or 'Revisor Fiscal'
    else:
        email_destino = request.user.email or getattr(getattr(request.user, 'perfil', None), 'correo_electronico', '')
        nombre = getattr(getattr(request.user, 'perfil', None), 'nombre_razon_social', '') or request.user.username

    # Pasos para la barra de progreso
    pasos = []
    if declaracion.tiene_contador and declaracion.contador_email:
        pasos.append('Contador')
    if declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
        pasos.append('Revisor Fiscal')
    pasos.append('Declarante')

    paso_actual = rol if rol in pasos else 'Declarante'

    if request.method == "POST":
        action = request.POST.get("action", "verificar")

        if action == "reenviar":
            nuevo_otp = ''.join(random.choices('0123456789', k=6))
            FirmaOTPICA.objects.filter(declaracion=declaracion, usado=False).update(usado=True)
            FirmaOTPICA.objects.create(declaracion=declaracion, codigo=nuevo_otp, tipo=tipo)
            _enviar_otp_firma_ica(email_destino, nombre, nuevo_otp, declaracion, tipo)
            messages.info(request, f'Se reenvió un nuevo código a {email_destino}.')
            return render(request, "formularios/verificar_firma_ica.html", {
                "declaracion": declaracion,
                "email": email_destino,
                "rol": rol,
                "pasos": pasos,
                "paso_actual": paso_actual,
            })

        # Verificar código
        codigo_ingresado = request.POST.get("codigo", "").strip()
        if not codigo_ingresado:
            return render(request, "formularios/verificar_firma_ica.html", {
                "declaracion": declaracion,
                "email": email_destino,
                "rol": rol,
                "pasos": pasos,
                "paso_actual": paso_actual,
                "error": "Ingrese el código de verificación.",
            })

        limite = timezone.now() - timezone.timedelta(minutes=15)
        otp_obj = FirmaOTPICA.objects.filter(
            declaracion=declaracion,
            codigo=codigo_ingresado,
            usado=False,
            creado_en__gte=limite,
        ).first()

        if not otp_obj:
            return render(request, "formularios/verificar_firma_ica.html", {
                "declaracion": declaracion,
                "email": email_destino,
                "rol": rol,
                "pasos": pasos,
                "paso_actual": paso_actual,
                "error": "Código incorrecto o expirado. Verifique e intente de nuevo.",
            })

        otp_obj.usado = True
        otp_obj.save()

        # Marcar la firma correspondiente
        if tipo == 'contador':
            declaracion.contador_firma_verificada = True
            declaracion.save(update_fields=['contador_firma_verificada'])
            # ¿Sigue revisor?
            if declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
                nuevo_otp = ''.join(random.choices('0123456789', k=6))
                FirmaOTPICA.objects.create(declaracion=declaracion, codigo=nuevo_otp, tipo='revisor')
                _enviar_otp_firma_ica(
                    declaracion.revisor_email,
                    declaracion.revisor_nombre or 'Revisor Fiscal',
                    nuevo_otp, declaracion, 'revisor'
                )
                messages.info(request, '✓ Firma del contador verificada. Ahora se requiere la firma del revisor fiscal.')
                return redirect("verificar_firma_ica", declaracion_id=declaracion.id)
            # No hay revisor → declarante
            nuevo_otp = ''.join(random.choices('0123456789', k=6))
            FirmaOTPICA.objects.create(declaracion=declaracion, codigo=nuevo_otp, tipo='declarante')
            email_decl = request.user.email or getattr(getattr(request.user, 'perfil', None), 'correo_electronico', '')
            nombre_decl = getattr(getattr(request.user, 'perfil', None), 'nombre_razon_social', '') or request.user.username
            _enviar_otp_firma_ica(email_decl, nombre_decl, nuevo_otp, declaracion, 'declarante')
            messages.info(request, '✓ Firma del contador verificada. Ahora se requiere su firma como declarante.')
            return redirect("verificar_firma_ica", declaracion_id=declaracion.id)

        elif tipo == 'revisor':
            declaracion.revisor_firma_verificada = True
            declaracion.save(update_fields=['revisor_firma_verificada'])
            # Continuar con declarante
            nuevo_otp = ''.join(random.choices('0123456789', k=6))
            FirmaOTPICA.objects.create(declaracion=declaracion, codigo=nuevo_otp, tipo='declarante')
            email_decl = request.user.email or getattr(getattr(request.user, 'perfil', None), 'correo_electronico', '')
            nombre_decl = getattr(getattr(request.user, 'perfil', None), 'nombre_razon_social', '') or request.user.username
            _enviar_otp_firma_ica(email_decl, nombre_decl, nuevo_otp, declaracion, 'declarante')
            messages.info(request, '✓ Firma del revisor fiscal verificada. Ahora se requiere su firma como declarante.')
            return redirect("verificar_firma_ica", declaracion_id=declaracion.id)

        else:  # declarante
            ahora = timezone.now()
            perfil = getattr(request.user, 'perfil', None)
            datos_firma = (
                f"{declaracion.id}|{request.user.username}"
                f"|{getattr(perfil, 'numero_documento', '')}|{ahora.isoformat()}"
            )
            firma_hash = hashlib.sha256(datos_firma.encode()).hexdigest()
            declaracion.firma_otp_verificada = True
            declaracion.firma_timestamp = ahora
            declaracion.firma_hash = firma_hash
            declaracion.save(update_fields=['firma_otp_verificada', 'firma_timestamp', 'firma_hash'])
            messages.success(request, '✓ Declaración ICA firmada y enviada correctamente.')
            return redirect("/tasks/completed?aviso=pago")

    # GET
    return render(request, "formularios/verificar_firma_ica.html", {
        "declaracion": declaracion,
        "email": email_destino,
        "rol": rol,
        "pasos": pasos,
        "paso_actual": paso_actual,
    })


def _enviar_otp_firma_auto(email_destino, nombre, otp_code, declaracion, tipo):
    """Envía el correo OTP de firma electrónica AUTO via EmailJS."""
    etiquetas = {'contador': 'Contador', 'revisor': 'Revisor Fiscal', 'declarante': 'Declarante'}
    rol = etiquetas.get(tipo, 'Firmante')
    radicado = getattr(declaracion, 'radicado', None) or declaracion.id
    if email_destino:
        _enviar_emailjs(
            django_settings.EMAILJS_TEMPLATE_OTP,
            email_destino,
            {'to_name': nombre, 'codigo': otp_code, 'tipo_formulario': f'AUTO — {rol}', 'radicado': radicado},
        )


@login_required
def proceso_auto(request):
    if is_admin(request.user):
        return redirect('admin_panel')

    if not tiene_acceso(request.user, 'AUTO'):
        return redirect('tasks')

    from catalogos.models import ActividadEconomica
    perfil = getattr(request.user, 'perfil', None)
    es_alcaldia = request.user.groups.filter(name='ALCALDIA_GESTION').exists()

    # Build tariff JSON for JavaScript
    tarifas_json = json.dumps({
        str(a.id): {'tarifa': float(a.tarifa), 'tipo': a.tipo, 'codigo': a.codigo}
        for a in ActividadEconomica.objects.all()
    }, cls=DjangoJSONEncoder)

    # Municipio->Departamento maps
    from catalogos.models import Municipio
    mun_depto_map = {m.id: m.departamento.nombre for m in Municipio.objects.select_related('departamento')}

    # Existing declarations for correction dropdown
    declaraciones_anteriores = list(
        DeclaracionAutoRetencion.objects.filter(user=request.user, firma_otp_verificada=True)
        .order_by('-anio_gravable', '-bimestre')
        .values('id', 'anio_gravable', 'bimestre', 'opcion_uso')
    )

    # Years+bimestres with signed INICIAL
    bimestres_con_inicial = list(
        DeclaracionAutoRetencion.objects.filter(user=request.user, opcion_uso='INICIAL', firma_otp_verificada=True)
        .values_list('anio_gravable', 'bimestre')
    )
    bimestres_con_inicial_json = json.dumps([{'anio': a, 'bimestre': b} for a, b in bimestres_con_inicial])

    editar_id = None

    if request.method == 'GET':
        editar_id = request.GET.get('editar')
        instance = None
        actividades_existentes = []

        if editar_id:
            instance = get_object_or_404(DeclaracionAutoRetencion, id=editar_id, user=request.user)
            if instance.firma_otp_verificada:
                return redirect('tasks')
            actividades_existentes = list(instance.actividades.select_related('actividad').order_by('orden'))
            # Exclude this declaration from bimestres_con_inicial
            bimestres_con_inicial_json = json.dumps([
                {'anio': a, 'bimestre': b} for a, b in bimestres_con_inicial
                if not (a == instance.anio_gravable and b == instance.bimestre)
            ])

        actividades_existentes_json = json.dumps([
            {
                'actividad_id': a.actividad_id,
                'ingreso_total_bimestre': a.ingreso_total_bimestre,
                'ingreso_excluido': a.ingreso_excluido,
            }
            for a in actividades_existentes
        ], cls=DjangoJSONEncoder)

        form = DeclaracionAutoRetencionForm(
            instance=instance,
            perfil=perfil if not instance else None,
            user=request.user,
        )
        return render(request, 'formularios/auto.html', {
            'form': form,
            'tarifas_json': tarifas_json,
            'mun_depto_json': json.dumps(mun_depto_map, cls=DjangoJSONEncoder),
            'perfil': perfil,
            'declaraciones_anteriores': declaraciones_anteriores,
            'bimestres_con_inicial_json': bimestres_con_inicial_json,
            'es_alcaldia': es_alcaldia,
            'editar_id': editar_id,
            'actividades_existentes': actividades_existentes,
            'actividades_existentes_json': actividades_existentes_json,
            'actividades_opciones': ActividadEconomica.objects.order_by('codigo'),
        })

    # POST
    editar_id = request.POST.get('editar_id')
    instance = None
    if editar_id:
        instance = get_object_or_404(DeclaracionAutoRetencion, id=editar_id, user=request.user)
        if instance.firma_otp_verificada:
            return redirect('tasks')

    form = DeclaracionAutoRetencionForm(request.POST, instance=instance, user=request.user, perfil=perfil)

    # Parse activities from POST
    actividades_data = []
    idx = 0
    while True:
        act_id = request.POST.get(f'actividad_id_{idx}')
        if act_id is None:
            break
        ingreso_total_raw = request.POST.get(f'ingreso_total_{idx}', '0')
        ingreso_excluido_raw = request.POST.get(f'ingreso_excluido_{idx}', '0')
        def parse_money(v):
            try:
                return int(str(v).replace('.', '').replace(',', '').strip())
            except Exception:
                return 0
        actividades_data.append({
            'actividad_id': int(act_id) if act_id else None,
            'ingreso_total_bimestre': parse_money(ingreso_total_raw),
            'ingreso_excluido': parse_money(ingreso_excluido_raw),
        })
        idx += 1

    errors = []
    if not actividades_data:
        errors.append('Debe agregar al menos una actividad económica.')

    _render_ctx_post = {
        'tarifas_json': tarifas_json,
        'mun_depto_json': json.dumps(mun_depto_map, cls=DjangoJSONEncoder),
        'perfil': perfil,
        'declaraciones_anteriores': declaraciones_anteriores,
        'bimestres_con_inicial_json': bimestres_con_inicial_json,
        'es_alcaldia': es_alcaldia,
        'editar_id': editar_id,
        'actividades_existentes': [],
        'actividades_existentes_json': '[]',
        'actividades_opciones': ActividadEconomica.objects.order_by('codigo'),
    }

    if not form.is_valid():
        _render_ctx_post['form'] = form
        _render_ctx_post['errores_actividades'] = errors
        return render(request, 'formularios/auto.html', _render_ctx_post)

    if errors:
        _render_ctx_post['form'] = form
        _render_ctx_post['errores_actividades'] = errors
        return render(request, 'formularios/auto.html', _render_ctx_post)

    # Save declaration
    declaracion = form.save(commit=False)
    declaracion.user = request.user
    declaracion.asignar_departamento()
    declaracion.asignar_departamento_notificacion()
    declaracion.save()

    # Invalidate old OTPs if editing
    if editar_id:
        declaracion.otps_firma.all().update(usado=True)
        declaracion.contador_firma_verificada = False
        declaracion.revisor_firma_verificada = False
        declaracion.firma_otp_verificada = False
        declaracion.save(update_fields=['contador_firma_verificada', 'revisor_firma_verificada', 'firma_otp_verificada'])

    # Save activities
    declaracion.actividades.all().delete()
    for orden, act_data in enumerate(actividades_data, 1):
        if not act_data['actividad_id']:
            continue
        try:
            actividad = ActividadEconomica.objects.get(pk=act_data['actividad_id'])
        except ActividadEconomica.DoesNotExist:
            continue
        ingreso_total = act_data['ingreso_total_bimestre']
        ingreso_excluido = act_data['ingreso_excluido']
        ingreso_gravable = max(0, ingreso_total - ingreso_excluido)
        valor_autorretencion = int(round(float(ingreso_gravable) * float(actividad.tarifa) / 1000))
        DeclaracionActividadAuto.objects.create(
            declaracion=declaracion,
            actividad=actividad,
            ingreso_total_bimestre=ingreso_total,
            ingreso_excluido=ingreso_excluido,
            ingreso_gravable=ingreso_gravable,
            tarifa_aplicada=actividad.tarifa,
            tipo_aplicado=actividad.tipo,
            valor_autorretencion=valor_autorretencion,
            orden=orden,
        )

    declaracion.recalcular_totales()

    # Auto-sign for ALCALDIA_GESTION
    if es_alcaldia:
        import hashlib
        hash_data = f"AUTO|{declaracion.id}|{declaracion.user_id}|{declaracion.anio_gravable}|{declaracion.bimestre}|{declaracion.total_a_pagar}"
        declaracion.firma_otp_verificada = True
        declaracion.firma_timestamp = timezone.now()
        declaracion.firma_hash = hashlib.sha256(hash_data.encode()).hexdigest()
        declaracion.save(update_fields=['firma_otp_verificada', 'firma_timestamp', 'firma_hash'])
        return redirect('tasks_completed')

    # OTP flow - start with contador if exists, else revisor, else declarante
    otp_code = ''.join(random.choices(string.digits, k=6))
    if declaracion.tiene_contador and declaracion.contador_email:
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='contador')
        _enviar_otp_firma_auto(declaracion.contador_email, declaracion.contador_nombre or 'Contador', otp_code, declaracion, 'contador')
    elif declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='revisor')
        _enviar_otp_firma_auto(declaracion.revisor_email, declaracion.revisor_nombre or 'Revisor', otp_code, declaracion, 'revisor')
    else:
        email_declarante = declaracion.rep_legal_email or request.user.email or ''
        nombre_declarante = declaracion.rep_legal_nombre or request.user.get_full_name() or request.user.username
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='declarante')
        _enviar_otp_firma_auto(email_declarante, nombre_declarante, otp_code, declaracion, 'declarante')

    return redirect('verificar_firma_auto', declaracion_id=declaracion.id)


@login_required
def verificar_firma_auto(request, declaracion_id):
    declaracion = get_object_or_404(DeclaracionAutoRetencion, id=declaracion_id, user=request.user)
    if declaracion.firma_otp_verificada:
        return redirect('tasks_completed')

    # Determine current step
    if declaracion.tiene_contador and not declaracion.contador_firma_verificada:
        paso_actual = 'contador'
        email_mostrar = declaracion.contador_email
        nombre_mostrar = declaracion.contador_nombre or 'Contador'
    elif declaracion.tiene_revisor_fiscal and not declaracion.revisor_firma_verificada:
        paso_actual = 'revisor'
        email_mostrar = declaracion.revisor_email
        nombre_mostrar = declaracion.revisor_nombre or 'Revisor Fiscal'
    else:
        paso_actual = 'declarante'
        email_mostrar = declaracion.rep_legal_email or request.user.email or ''
        nombre_mostrar = declaracion.rep_legal_nombre or request.user.get_full_name() or request.user.username

    if request.method == 'GET':
        return render(request, 'formularios/verificar_firma_auto.html', {
            'declaracion': declaracion,
            'paso_actual': paso_actual,
            'email_mostrar': email_mostrar,
            'nombre_mostrar': nombre_mostrar,
        })

    action = request.POST.get('action', 'verificar')

    if action == 'reenviar':
        declaracion.otps_firma.filter(tipo=paso_actual, usado=False).update(usado=True)
        otp_code = ''.join(random.choices(string.digits, k=6))
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo=paso_actual)
        _enviar_otp_firma_auto(email_mostrar, nombre_mostrar, otp_code, declaracion, paso_actual)
        return render(request, 'formularios/verificar_firma_auto.html', {
            'declaracion': declaracion,
            'paso_actual': paso_actual,
            'email_mostrar': email_mostrar,
            'nombre_mostrar': nombre_mostrar,
            'mensaje': 'Se reenvió el código.',
        })

    codigo_ingresado = request.POST.get('codigo', '').strip()
    limite = timezone.now() - timezone.timedelta(minutes=15)
    otp_obj = declaracion.otps_firma.filter(tipo=paso_actual, usado=False, creado_en__gte=limite).order_by('-creado_en').first()

    if not otp_obj or otp_obj.codigo != codigo_ingresado:
        return render(request, 'formularios/verificar_firma_auto.html', {
            'declaracion': declaracion,
            'paso_actual': paso_actual,
            'email_mostrar': email_mostrar,
            'nombre_mostrar': nombre_mostrar,
            'error': 'Código inválido o expirado.',
        })

    otp_obj.usado = True
    otp_obj.save()

    if paso_actual == 'contador':
        declaracion.contador_firma_verificada = True
        declaracion.save(update_fields=['contador_firma_verificada'])
        otp_code = ''.join(random.choices(string.digits, k=6))
        if declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
            FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='revisor')
            _enviar_otp_firma_auto(declaracion.revisor_email, declaracion.revisor_nombre or 'Revisor', otp_code, declaracion, 'revisor')
        else:
            email_d = declaracion.rep_legal_email or request.user.email or ''
            nombre_d = declaracion.rep_legal_nombre or request.user.get_full_name() or request.user.username
            FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='declarante')
            _enviar_otp_firma_auto(email_d, nombre_d, otp_code, declaracion, 'declarante')
        return redirect('verificar_firma_auto', declaracion_id=declaracion.id)

    elif paso_actual == 'revisor':
        declaracion.revisor_firma_verificada = True
        declaracion.save(update_fields=['revisor_firma_verificada'])
        otp_code = ''.join(random.choices(string.digits, k=6))
        email_d = declaracion.rep_legal_email or request.user.email or ''
        nombre_d = declaracion.rep_legal_nombre or request.user.get_full_name() or request.user.username
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='declarante')
        _enviar_otp_firma_auto(email_d, nombre_d, otp_code, declaracion, 'declarante')
        return redirect('verificar_firma_auto', declaracion_id=declaracion.id)

    else:  # declarante
        import hashlib
        hash_data = f"AUTO|{declaracion.id}|{declaracion.user_id}|{declaracion.anio_gravable}|{declaracion.bimestre}|{declaracion.total_a_pagar}"
        declaracion.firma_otp_verificada = True
        declaracion.firma_timestamp = timezone.now()
        declaracion.firma_hash = hashlib.sha256(hash_data.encode()).hexdigest()
        declaracion.save(update_fields=['firma_otp_verificada', 'firma_timestamp', 'firma_hash'])
        return redirect('tasks_completed')


@login_required
def reiniciar_firma_auto(request, declaracion_id):
    declaracion = get_object_or_404(DeclaracionAutoRetencion, id=declaracion_id, user=request.user)
    if declaracion.firma_otp_verificada:
        return redirect('tasks_completed')
    declaracion.otps_firma.all().update(usado=True)
    declaracion.contador_firma_verificada = False
    declaracion.revisor_firma_verificada = False
    declaracion.save(update_fields=['contador_firma_verificada', 'revisor_firma_verificada'])
    otp_code = ''.join(random.choices(string.digits, k=6))
    if declaracion.tiene_contador and declaracion.contador_email:
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='contador')
        _enviar_otp_firma_auto(declaracion.contador_email, declaracion.contador_nombre or 'Contador', otp_code, declaracion, 'contador')
    elif declaracion.tiene_revisor_fiscal and declaracion.revisor_email:
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='revisor')
        _enviar_otp_firma_auto(declaracion.revisor_email, declaracion.revisor_nombre or 'Revisor', otp_code, declaracion, 'revisor')
    else:
        email_d = declaracion.rep_legal_email or request.user.email or ''
        nombre_d = declaracion.rep_legal_nombre or request.user.get_full_name() or request.user.username
        FirmaOTPAuto.objects.create(declaracion=declaracion, codigo=otp_code, tipo='declarante')
        _enviar_otp_firma_auto(email_d, nombre_d, otp_code, declaracion, 'declarante')
    return redirect('verificar_firma_auto', declaracion_id=declaracion.id)


@login_required
def proceso_rete(request):
    if request.method == "GET":
        return render(request, "formularios/rete.html", {"form": ReteForm()})

    form = ReteForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        return redirect("tasks")

    return render(request, "formularios/rete.html", {"form": form})


# ----------------------------
# PDF - Generación de documentos
# ----------------------------
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable, PageBreak
from reportlab.platypus import Flowable as RLFlowable, Frame, PageTemplate as RLPageTemplate, FrameBreak, NextPageTemplate
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from django.conf import settings
import os


def get_pdf_config():
    """Obtiene la configuración de PDF activa o valores por defecto."""
    config = ConfiguracionPDF.get_config_activa()
    if config:
        return {
            'logo_izquierdo': config.logo_izquierdo.path if config.logo_izquierdo else None,
            'logo_derecho': config.logo_derecho.path if config.logo_derecho else None,
            'nombre_entidad': config.nombre_entidad,
            'nombre_municipio': config.nombre_municipio,
            'slogan': config.slogan,
            'color_primario': config.color_primario,
            'color_secundario': config.color_secundario,
            'color_radicado': config.color_radicado,
            'color_exito': config.color_exito,
            'mostrar_instructivo': config.mostrar_instructivo,
            'texto_instructivo': config.texto_instructivo,
            'texto_pie_pagina': config.texto_pie_pagina,
            'direccion_entidad': config.direccion_entidad,
            'telefono_entidad': config.telefono_entidad,
            'email_entidad': config.email_entidad,
            'sitio_web': config.sitio_web,
            'instructivo_ica_col_izquierda': config.instructivo_ica_col_izquierda,
            'instructivo_ica_col_derecha': config.instructivo_ica_col_derecha,
        }
    # Valores por defecto si no hay configuración
    return {
        'logo_izquierdo': os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_ciudad.png'),
        'logo_derecho': None,
        'nombre_entidad': 'Secretaría de Hacienda',
        'nombre_municipio': 'Municipio de Segovia - Antioquia',
        'slogan': 'Portal de Servicios Tributarios',
        'color_primario': '#006633',
        'color_secundario': '#004883',
        'color_radicado': '#006633',
        'color_exito': '#009735',
        'mostrar_instructivo': True,
        'texto_instructivo': """1. Conserve este documento como soporte de su trámite tributario.
2. El número de radicado es su comprobante oficial ante la administración municipal.
3. Para cualquier consulta, presente este documento con el número de radicado.
4. Este documento fue generado electrónicamente y es válido sin firma.""",
        'texto_pie_pagina': 'Documento generado por el Portal de Servicios Tributarios',
        'direccion_entidad': 'Segovia, Antioquia',
        'telefono_entidad': None,
        'email_entidad': None,
        'sitio_web': None,
        'instructivo_ica_col_izquierda': '',
        'instructivo_ica_col_derecha': '',
    }


def get_pdf_styles(config=None):
    """Retorna estilos personalizados para los PDFs."""
    if config is None:
        config = get_pdf_config()

    styles = getSampleStyleSheet()

    # Título principal
    styles.add(ParagraphStyle(
        name='PDF_Title',
        alignment=TA_CENTER,
        fontSize=16,
        fontName='Helvetica-Bold',
        spaceAfter=6,
        textColor=colors.HexColor(config['color_primario'])
    ))

    # Subtítulo
    styles.add(ParagraphStyle(
        name='PDF_Subtitle',
        alignment=TA_CENTER,
        fontSize=11,
        fontName='Helvetica',
        spaceAfter=4,
        textColor=colors.HexColor(config['color_secundario'])
    ))

    # Radicado destacado
    styles.add(ParagraphStyle(
        name='PDF_Radicado',
        alignment=TA_CENTER,
        fontSize=14,
        fontName='Helvetica-Bold',
        spaceAfter=12,
        spaceBefore=6,
        textColor=colors.HexColor(config['color_radicado']),
        borderColor=colors.HexColor(config['color_radicado']),
        borderWidth=1,
        borderPadding=8
    ))

    # Encabezado de sección
    styles.add(ParagraphStyle(
        name='PDF_Section',
        fontSize=11,
        fontName='Helvetica-Bold',
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.white,
        backColor=colors.HexColor(config['color_primario']),
        borderPadding=4
    ))

    # Texto pequeño
    styles.add(ParagraphStyle(
        name='PDF_Small',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#7f8c8d')
    ))

    # Instructivo
    styles.add(ParagraphStyle(
        name='PDF_Instructivo',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#34495e'),
        alignment=TA_LEFT,
        spaceBefore=6
    ))

    return styles


def get_pdf_header(styles, titulo, radicado, config=None, municipio_nombre=None, extra_info=None):
    """Genera el encabezado del PDF con logos y radicado destacado."""
    if config is None:
        config = get_pdf_config()

    elements = []

    # Rutas de logos desde configuración
    logo_path = config['logo_izquierdo']
    logo_legal_path = config['logo_derecho']

    # Construir fila de encabezado con logos
    header_data = []

    # Logo izquierdo
    logo_left = ''
    if logo_path and os.path.exists(logo_path):
        try:
            _tmp = Image(logo_path)
            _aspect = _tmp.imageWidth / _tmp.imageHeight if _tmp.imageHeight else 1
            _h = 0.75 * inch
            logo_img = Image(logo_path, width=_h * _aspect, height=_h)
            logo_left = logo_img
        except:
            pass

    # Información central
    entidad_nombre = municipio_nombre or config['nombre_entidad']
    slogan = config['slogan'] or 'Portal de Servicios Tributarios'

    centro_text = f"""<b>{titulo}</b><br/>
    <font size="8">{entidad_nombre}</font><br/>
    <font size="7">{slogan}</font>"""
    centro = Paragraph(centro_text, ParagraphStyle(
        name='Centro',
        alignment=TA_CENTER,
        fontSize=10,
        leading=12
    ))

    # Logo derecho
    logo_right = ''
    if logo_legal_path and os.path.exists(logo_legal_path):
        try:
            _tmp2 = Image(logo_legal_path)
            _aspect2 = _tmp2.imageWidth / _tmp2.imageHeight if _tmp2.imageHeight else 1
            _h2 = 0.75 * inch
            logo_legal = Image(logo_legal_path, width=_h2 * _aspect2, height=_h2)
            logo_right = logo_legal
        except:
            pass

    header_data.append([logo_left, centro, logo_right])

    header_table = Table(header_data, colWidths=[1.3*inch, 4.9*inch, 1.3*inch])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.04*inch))

    # Línea divisoria con color primario
    elements.append(HRFlowable(
        width="100%",
        thickness=2,
        color=colors.HexColor(config['color_primario']),
        spaceBefore=3,
        spaceAfter=3
    ))

    # Radicado destacado en caja
    if radicado:
        color_rad = config['color_radicado']
        # Color más oscuro para el borde
        radicado_data = [[
            Paragraph(f'<b>RADICADO N°</b>', ParagraphStyle(name='rad1', alignment=TA_CENTER, fontSize=9, textColor=colors.white)),
        ], [
            Paragraph(f'<b>{radicado}</b>', ParagraphStyle(name='rad2', alignment=TA_CENTER, fontSize=16, textColor=colors.white, fontName='Helvetica-Bold')),
        ]]
        radicado_table = Table(radicado_data, colWidths=[3*inch])
        radicado_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(color_rad)),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 4),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 20),
            ('RIGHTPADDING', (0, 0), (-1, -1), 20),
            ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#004d26')),
        ]))

        # Centrar la tabla de radicado
        wrapper = Table([[radicado_table]], colWidths=[7.5*inch])
        wrapper.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        elements.append(wrapper)
        elements.append(Spacer(1, 0.15*inch))

    # Info extra (fecha, estado, etc.)
    if extra_info:
        info_text = ' | '.join([f'<b>{k}:</b> {v}' for k, v in extra_info.items()])
        elements.append(Paragraph(info_text, ParagraphStyle(
            name='ExtraInfo',
            alignment=TA_CENTER,
            fontSize=9,
            textColor=colors.HexColor('#7f8c8d'),
            spaceBefore=3,
            spaceAfter=10
        )))

    return elements


def get_pdf_footer(styles, config=None):
    """Genera el pie de página con información e instructivo."""
    if config is None:
        config = get_pdf_config()

    elements = []

    elements.append(Spacer(1, 0.3*inch))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#bdc3c7'), spaceBefore=6, spaceAfter=6))

    # Instructivo (si está habilitado)
    if config['mostrar_instructivo']:
        texto_inst = config['texto_instructivo'] or ""
        # Formatear el instructivo
        lineas = texto_inst.strip().split('\n')
        instructivo_html = "<b>INSTRUCCIONES:</b><br/>" + "<br/>".join(lineas)
        elements.append(Paragraph(instructivo_html, styles['PDF_Instructivo']))
        elements.append(Spacer(1, 0.15*inch))

    # Información de contacto (si existe)
    contacto_items = []
    if config['direccion_entidad']:
        contacto_items.append(f"Dir: {config['direccion_entidad']}")
    if config['telefono_entidad']:
        contacto_items.append(f"Tel: {config['telefono_entidad']}")
    if config['email_entidad']:
        contacto_items.append(f"Email: {config['email_entidad']}")
    if config['sitio_web']:
        contacto_items.append(f"Web: {config['sitio_web']}")

    if contacto_items:
        contacto_text = ' | '.join(contacto_items)
        elements.append(Paragraph(contacto_text, ParagraphStyle(
            name='Contacto',
            fontSize=7,
            textColor=colors.HexColor('#95a5a6'),
            alignment=TA_CENTER
        )))
        elements.append(Spacer(1, 0.1*inch))

    return elements


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# Helpers para el instructivo del PDF ICA
# ─────────────────────────────────────────────

class VerticalText(RLFlowable):
    """Texto rotado 90° dentro de una franja coloreada. Requiere fixed_height pre-medido."""
    def __init__(self, text, fixed_height, fontsize=7, fontname='Helvetica-Bold',
                 text_color='#ffffff', bg_color='#2c3e50'):
        RLFlowable.__init__(self)
        self.text = text
        self._fixed_height = fixed_height
        self.fontsize = fontsize
        self.fontname = fontname
        self.text_color = text_color
        self.bg_color = bg_color

    def wrap(self, availWidth, availHeight):
        self.width = self.fontsize + 8
        self.height = self._fixed_height
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(colors.HexColor(self.bg_color))
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setFillColor(colors.HexColor(self.text_color))
        c.setFont(self.fontname, self.fontsize)
        c.translate(self.width / 2, self.height / 2)
        c.rotate(90)
        c.drawCentredString(0, -self.fontsize / 3, self.text)
        c.restoreState()


def _measure_table_height(table, available_width):
    """Devuelve la altura real de una tabla usando un canvas ficticio."""
    buf = io.BytesIO()
    dummy = rl_canvas.Canvas(buf, pagesize=letter)
    _, h = table.wrapOn(dummy, available_width, 10 * inch)
    return h


def _paras_to_table(paras, col_w, style_body):
    """Wraps a list of Paragraphs into a single-column Table for safe cell nesting."""
    if not paras:
        paras = [Paragraph('', style_body)]
    rows = [[p] for p in paras]
    t = Table(rows, colWidths=[col_w])
    t.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _parse_instructivo_blocks(raw_text, style_normal, style_header):
    """
    Parses instructive text into a list of Paragraphs.
    Lines starting with ## become bold headers.
    Blocks separated by blank lines.
    """
    paras = []
    if not raw_text:
        return paras
    blocks = raw_text.strip().split('\n\n')
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')
        first = lines[0].strip()
        if first.startswith('## '):
            title = first[3:]
            paras.append(Paragraph(f'<b>{title}</b>', style_header))
            rest = ' '.join(l.strip() for l in lines[1:] if l.strip())
            if rest:
                paras.append(Paragraph(rest, style_normal))
        else:
            text = ' '.join(l.strip() for l in lines if l.strip())
            paras.append(Paragraph(text, style_normal))
        paras.append(Spacer(1, 4))
    return paras


def _parse_instructivo_columns(raw_text, style_body, style_hdr):
    """
    Convierte el texto de una columna en lista de (etiqueta, párrafos).
    Líneas con ### ETIQUETA inician nueva sección con franja vertical.
    Texto antes del primer ### es el bloque intro (etiqueta=None).
    """
    sections = []
    current_label = None
    current_lines = []

    for line in (raw_text or '').split('\n'):
        if line.startswith('### '):
            text = '\n'.join(current_lines).strip()
            if text:
                paras = _parse_instructivo_blocks(text, style_body, style_hdr)
                sections.append((current_label, paras))
            current_label = line[4:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    text = '\n'.join(current_lines).strip()
    if text:
        paras = _parse_instructivo_blocks(text, style_body, style_hdr)
        sections.append((current_label, paras))

    return sections


def get_instructivo_ica_page(config, styles):
    """
    Genera el instructivo ICA como una LongTable de ancho completo con secciones.
    Retorna [] si no hay contenido en las columnas (evita página en blanco).
    """
    from reportlab.platypus import LongTable

    izq = (config.get('instructivo_ica_col_izquierda') or '').strip()
    der = (config.get('instructivo_ica_col_derecha') or '').strip()
    if not izq and not der:
        return []

    color_pri = config['color_primario']
    color_sec = config['color_secundario']

    pw, _ = letter
    full_w = pw - 1.0 * inch   # 7.5 inches (márgenes 0.5 c/u)
    pad = 5

    style_body = ParagraphStyle(
        name='IB', fontName='Helvetica', fontSize=7.5,
        leading=10.5, alignment=TA_JUSTIFY, spaceAfter=3, textColor=colors.black,
    )
    style_item_hdr = ParagraphStyle(
        name='IH', fontName='Helvetica-Bold', fontSize=7.5,
        leading=10.5, spaceAfter=2, textColor=colors.black,
    )
    style_sec_hdr = ParagraphStyle(
        name='ISH', fontName='Helvetica-Bold', fontSize=8.5,
        leading=12, textColor=colors.white, alignment=TA_LEFT,
    )
    style_title = ParagraphStyle(
        name='IT', fontName='Helvetica-Bold', fontSize=10,
        leading=13, textColor=colors.white, alignment=TA_CENTER,
    )

    data = []
    header_rows = []   # (row_idx, color_hex)

    # Fila 0: título
    data.append([Paragraph(
        'INSTRUCTIVO PARA DILIGENCIAR EL FORMULARIO ÚNICO DE DECLARACIÓN '
        'DEL IMPUESTO DE INDUSTRIA Y COMERCIO', style_title)])
    header_rows.append((0, color_sec))

    def add_col(raw_text, sec_color):
        for label, paras in _parse_instructivo_columns(raw_text, style_body, style_item_hdr):
            if not paras:
                continue
            if label is not None:
                row_idx = len(data)
                data.append([Paragraph(label, style_sec_hdr)])
                header_rows.append((row_idx, sec_color))
            # Contenido: paragraphs directo en la celda (ReportLab los maneja)
            data.append(paras)   # lista de flowables → celda multi-párrafo

    add_col(config.get('instructivo_ica_col_izquierda', ''), color_sec)
    add_col(config.get('instructivo_ica_col_derecha', ''), color_pri)

    # Convertir filas con lista de párrafos a tabla anidada para que funcione bien
    clean_data = []
    for row in data:
        if isinstance(row, list) and row and not isinstance(row[0], Paragraph):
            clean_data.append([row[0]])
        elif isinstance(row, list) and all(isinstance(x, (Paragraph, Spacer)) for x in row):
            inner = _paras_to_table(row, full_w - pad * 2, style_body)
            clean_data.append([inner])
        else:
            clean_data.append(row)

    t = LongTable(clean_data, colWidths=[full_w], repeatRows=0)

    ts = [
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
        ('LEFTPADDING', (0, 0), (-1, -1), pad),
        ('RIGHTPADDING', (0, 0), (-1, -1), pad),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]
    for r, col in header_rows:
        ts.append(('BACKGROUND', (0, r), (0, r), colors.HexColor(col)))
        ts.append(('TEXTCOLOR', (0, r), (0, r), colors.white))
        # Evitar que el encabezado de sección quede separado de su contenido
        if r + 1 < len(clean_data):
            ts.append(('NOSPLIT', (0, r), (0, r + 1)))

    t.setStyle(TableStyle(ts))
    return [PageBreak(), t]


def _rit_public_token(rit_id):
    """HMAC-SHA256 corto para acceso público sin login al PDF del RIT."""
    import hmac as _hmac, hashlib as _hl
    return _hmac.new(
        django_settings.SECRET_KEY.encode(),
        f"rit-pdf-{rit_id}".encode(),
        _hl.sha256
    ).hexdigest()[:20]


def generar_pdf_rit_publico(request, rit_id, token):
    """Vista pública del PDF RIT — accesible sin login mediante token firmado."""
    if token != _rit_public_token(rit_id):
        return HttpResponse("Enlace inválido o expirado.", status=403, content_type="text/plain")
    # Reutiliza la lógica de generación pasando el request pero saltando permisos
    request._rit_public = True
    return generar_pdf_rit(request, rit_id)


def generar_pdf_rit(request, rit_id):
    """Genera PDF de un registro RIT."""
    rit = get_object_or_404(RegistroRIT, id=rit_id)

    # Verificar permisos: usuario normal solo puede ver sus propios PDFs
    # (omitido si viene desde la vista pública con token válido)
    if not getattr(request, '_rit_public', False):
        if not is_admin(request.user) and rit.user != request.user:
            messages.error(request, 'No tienes permiso para ver este documento.')
            return redirect('tasks_completed')

    # Si la alcaldía cargó un PDF físico, servirlo directamente
    if rit.pdf_fisico:
        from django.http import FileResponse
        import mimetypes
        try:
            file_handle = rit.pdf_fisico.open('rb')
            mime_type, _ = mimetypes.guess_type(rit.pdf_fisico.name)
            mime_type = mime_type or 'application/octet-stream'
            inline = request.GET.get('inline', '0') == '1'
            disposition = 'inline' if inline else 'attachment'
            filename = f"RIT_{rit.radicado}.pdf"
            response = FileResponse(file_handle, content_type=mime_type)
            response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
            return response
        except Exception:
            pass  # Si falla la lectura del archivo, genera el PDF normalmente

    # Obtener configuración de PDF
    config = get_pdf_config()

    # Crear buffer para el PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.4*inch,
        bottomMargin=0.4*inch,
        leftMargin=0.5*inch,
        rightMargin=0.5*inch
    )

    styles = get_pdf_styles(config)
    elements = []

    # Encabezado con logos y radicado destacado
    municipio_raw = str(rit.municipio_notificacion) if rit.municipio_notificacion else 'SEGOVIA'
    municipio_header = f"MUNICIPIO DE {municipio_raw.upper()} — SECRETARÍA DE HACIENDA"
    extra_info = {
        'FECHA ÚLTIMO REGISTRO': rit.fecha.strftime('%d/%m/%Y %H:%M'),
        'Estado': rit.get_estado_display(),
        'Operación': rit.get_opcion_uso_display()
    }
    elements.extend(get_pdf_header(
        styles,
        "REGISTRO DE INFORMACIÓN TRIBUTARIA",
        rit.radicado,
        config,
        municipio_header,
        extra_info
    ))

    # Sección A: Clasificación del obligado
    elements.append(Paragraph("A. DATOS DE REGISTRO Y CLASIFICACIÓN DEL OBLIGADO", styles['PDF_Section']))
    data_a = [
        ['Tipo de contribuyente:', rit.get_clase_contribuyente_display(), 'Agente de Retención ICA:', 'Sí' if rit.es_retenedor_ica else 'No'],
        ['Autorretenedor ICA:', 'Sí' if rit.es_autorretenedor_ica else 'No', '', ''],
    ]
    t = Table(data_a, colWidths=[1.8*inch, 2.0*inch, 1.8*inch, 1.7*inch])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.1*inch))

    # Sección B: Datos del contribuyente o responsable
    elements.append(Paragraph("B. DATOS DEL CONTRIBUYENTE O RESPONSABLE", styles['PDF_Section']))
    muni_depto = str(rit.municipio_notificacion) if rit.municipio_notificacion else '-'
    if rit.departamento_notificacion:
        muni_depto += f" / {rit.departamento_notificacion}"
    _lbl = ParagraphStyle(name='B_label', fontSize=9, fontName='Helvetica-Bold', leading=12)
    _val = ParagraphStyle(name='B_value', fontSize=9, fontName='Helvetica', leading=12)
    def _brow(label, value):
        return [Paragraph(label, _lbl), Paragraph(str(value), _val)]
    data_b = [
        _brow('Tipo de persona:', rit.get_tipo_persona_display() or '-'),
        _brow('Tipo y N° Documento:', f"{rit.get_tipo_documento_display()} {rit.numero_documento}" + (f" — DV {rit.dv}" if rit.dv else "")),
        _brow('Nombre completo / Razón social:', rit.nombre_razon_social or '-'),
        _brow('Dirección:', rit.direccion_notificacion or '-'),
        _brow('Municipio / Departamento:', muni_depto),
        _brow('Celular:', rit.telefono or '-'),
        _brow('Correo electrónico:', rit.correo_electronico or '-'),
    ]
    t = Table(data_b, colWidths=[2.6*inch, 4.7*inch])
    t.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#ecf0f1')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.1*inch))

    # Sección C: Representantes legales
    if rit.representantes.exists():
        elements.append(Paragraph("C. REPRESENTACIÓN LEGAL", styles['PDF_Section']))
        rep_data = [['#', 'Tipo', 'Nombre Completo', 'Documento']]
        for i, rep in enumerate(rit.representantes.all(), 1):
            rep_data.append([
                str(i),
                rep.get_tipo_representante_display(),
                rep.nombre,
                f"{rep.get_tipo_documento_display()} {rep.numero_documento}"
            ])
        t = Table(rep_data, colWidths=[0.4*inch, 1.5*inch, 3.2*inch, 2.2*inch])
        t.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(config['color_secundario'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 0.1*inch))

    # Sección D: Establecimientos + Actividades económicas juntas
    elements.append(Paragraph("D. ESTABLECIMIENTOS DE COMERCIO, SUC, AGENCIAS EN SEGOVIA", styles['PDF_Section']))
    if rit.establecimientos.exists():
        est_data = [['#', 'Nombre Comercial', 'Dirección', 'Inicio Act.', 'Avisos']]
        for i, est in enumerate(rit.establecimientos.all(), 1):
            fecha_inicio = est.fecha_inicio_actividades.strftime('%d/%m/%Y') if est.fecha_inicio_actividades else '-'
            avisos = 'Sí' if est.tiene_avisos_tableros else 'No'
            est_data.append([str(i), est.nombre, est.direccion or '-', fecha_inicio, avisos])
        t = Table(est_data, colWidths=[0.4*inch, 2.2*inch, 2.4*inch, 1.0*inch, 0.7*inch])
        t.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(config['color_secundario'])),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("Sin establecimientos registrados.", styles['PDF_Small']))

    # Actividades económicas — dentro de la sección D, sin título propio
    if rit.actividades_rit.exists():
        elements.append(Spacer(1, 0.08*inch))
        act_data = [['#', 'Código', 'Descripción Actividad', 'Tarifa']]
        for i, act in enumerate(rit.actividades_rit.all(), 1):
            nombre_act = act.actividad.nombre if act.actividad else '-'
            if len(nombre_act) > 60:
                nombre_act = nombre_act[:60] + '...'
            act_data.append([
                str(i),
                act.actividad.codigo if act.actividad else '-',
                nombre_act,
                f"{act.actividad.tarifa}‰" if act.actividad else '-'
            ])
        t = Table(act_data, colWidths=[0.4*inch, 0.9*inch, 4.8*inch, 1.2*inch])
        t.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#455a64')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
    elements.append(Spacer(1, 0.1*inch))

    # Sección E: Firma
    elements.append(Paragraph("E. FIRMA DEL DECLARANTE", styles['PDF_Section']))
    if rit.firma_otp_verificada and rit.firma_timestamp:
        nombre_firmante = rit.nombre_razon_social or rit.user.get_full_name() or rit.user.username
        firma_data = [
            ['Tipo de firma:', 'Firma Electrónica Simple (OTP) — Ley 527 de 1999'],
            ['Firmado por:', f"{nombre_firmante} — {rit.get_tipo_documento_display()} {rit.numero_documento}"],
            ['Hash de verificación:', rit.firma_hash or '-'],
            ['Fecha y hora de firma:', rit.firma_timestamp.strftime('%d/%m/%Y %H:%M:%S UTC')],
        ]
        t = Table(firma_data, colWidths=[2.2*inch, 5.1*inch])
        t.setStyle(TableStyle([
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e8f5e9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#c8e6c9')),
        ]))
        elements.append(t)
    elif rit.firma_contribuyente:
        try:
            _sig_path = rit.firma_contribuyente.path
            if os.path.exists(_sig_path):
                sig_img = Image(_sig_path, width=2.5*inch, height=0.8*inch)
                nombre_firmante = rit.firma_contribuyente_nombre or rit.nombre_razon_social or '-'
                doc_firmante = rit.firma_contribuyente_documento or rit.numero_documento or '-'
                firma_data = [[sig_img, Paragraph(
                    f"<b>{nombre_firmante}</b><br/>Doc: {doc_firmante}",
                    ParagraphStyle(name='FirmaInfo', fontSize=8, leading=11)
                )]]
                t = Table(firma_data, colWidths=[3*inch, 4.3*inch])
                t.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('BOX', (0, 0), (0, 0), 0.5, colors.HexColor('#bdc3c7')),
                ]))
                elements.append(t)
        except Exception:
            elements.append(Paragraph("Firma registrada.", styles['PDF_Small']))
    else:
        elements.append(Paragraph(
            "Pendiente de firma electrónica.",
            ParagraphStyle(name='PFirma', fontSize=8, textColor=colors.HexColor('#7f8c8d'))
        ))

    # Pie (sin instructivo para RIT)
    config_rit = dict(config)
    config_rit['mostrar_instructivo'] = False
    elements.extend(get_pdf_footer(styles, config_rit))

    # Texto y fecha de generación
    if config['texto_pie_pagina']:
        elements.append(Paragraph(
            f"<i>{config['texto_pie_pagina']}</i>",
            styles['PDF_Small']
        ))
    elements.append(Paragraph(
        f"<i>Documento generado electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
        styles['PDF_Small']
    ))

    # Generar PDF
    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    disp = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disp}; filename="RIT_{rit.radicado or rit.id}.pdf"'
    return response


def generar_pdf_ica(request, ica_id):
    """Genera PDF de una declaración ICA."""
    ica = get_object_or_404(DeclaracionICA, id=ica_id)

    # Verificar permisos
    if not is_admin(request.user) and ica.user != request.user:
        messages.error(request, 'No tienes permiso para ver este documento.')
        return redirect('tasks_completed')

    # Obtener configuración de PDF
    config = get_pdf_config()

    _radicado_title = f"ICA-{ica.anio_gravable}-{ica.id:06d}"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.25*inch,
        bottomMargin=0.35*inch,
        leftMargin=0.5*inch,
        rightMargin=0.5*inch,
        title=_radicado_title,
        author="Portal Tributario Segovia",
    )

    styles = get_pdf_styles(config)
    elements = []

    # Encabezado con logos y radicado destacado
    municipio_nombre = ica.municipio.nombre if ica.municipio else None
    extra_info = {
        'Año Gravable': str(ica.anio_gravable),
        'Tipo': ica.get_opcion_uso_display(),
        'Fecha': ica.fecha_diligenciamiento.strftime('%Y-%m-%d %H:%M') if ica.fecha_diligenciamiento else '-'
    }

    # Generar radicado para ICA si no existe
    radicado_ica = f"ICA-{ica.anio_gravable}-{ica.id:06d}"

    # ── Header compacto ICA ────────────────────────────────────────────
    _h_logo = 0.9 * inch
    _logo_l = ''
    if config['logo_izquierdo'] and os.path.exists(config['logo_izquierdo']):
        try:
            _tmp = Image(config['logo_izquierdo'])
            _asp = _tmp.imageWidth / _tmp.imageHeight if _tmp.imageHeight else 1
            _logo_l = Image(config['logo_izquierdo'], width=_h_logo * _asp, height=_h_logo)
        except Exception:
            pass
    _logo_r = ''
    if config['logo_derecho'] and os.path.exists(config['logo_derecho']):
        try:
            _tmp2 = Image(config['logo_derecho'])
            _asp2 = _tmp2.imageWidth / _tmp2.imageHeight if _tmp2.imageHeight else 1
            _logo_r = Image(config['logo_derecho'], width=_h_logo * _asp2, height=_h_logo)
        except Exception:
            pass
    _ent_nombre = municipio_nombre or config['nombre_entidad']
    _hdr_centro = Paragraph(
        f'<b>DECLARACIÓN DEL IMPUESTO DE INDUSTRIA Y COMERCIO</b><br/>'
        f'<font size="8">{_ent_nombre}</font>',
        ParagraphStyle('_hc', fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=TA_CENTER)
    )
    # Fecha de radicado: usar firma_timestamp si existe, sino fecha_diligenciamiento
    _MESES_ES = {1:'enero',2:'febrero',3:'marzo',4:'abril',5:'mayo',6:'junio',
                 7:'julio',8:'agosto',9:'septiembre',10:'octubre',11:'noviembre',12:'diciembre'}
    _fecha_rad_dt = ica.firma_timestamp or ica.fecha_diligenciamiento
    if _fecha_rad_dt:
        _fecha_rad_str = f"{_fecha_rad_dt.day} de {_MESES_ES[_fecha_rad_dt.month]} de {_fecha_rad_dt.year}"
    else:
        _fecha_rad_str = ''
    _hdr_rad = Paragraph(
        f'<b>Radicado:</b> {radicado_ica}<br/>'
        + (f'<font size="7">Fecha: {_fecha_rad_str}</font>' if _fecha_rad_str else ''),
        ParagraphStyle('_hr', fontName='Helvetica-Bold', fontSize=8, leading=10,
                       alignment=TA_RIGHT, textColor=colors.HexColor(config['color_radicado']))
    )
    _hdr_t = Table(
        [[_logo_l, _hdr_centro, _hdr_rad if not _logo_r else _logo_r]],
        colWidths=[1.0*inch, 5.5*inch, 1.0*inch]
    )
    _hdr_t.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (0,  0),  'LEFT'),
        ('ALIGN',         (1, 0), (1,  0),  'CENTER'),
        ('ALIGN',         (2, 0), (2,  0),  'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(_hdr_t)
    if _logo_r:
        # Si hay logo derecho, agregar radicado debajo del header en pequeño
        elements.append(Paragraph(
            f'<b>Radicado:</b> {radicado_ica}',
            ParagraphStyle('_hr2', fontName='Helvetica-Bold', fontSize=8, leading=9,
                           alignment=TA_RIGHT, textColor=colors.HexColor(config['color_radicado']))
        ))
    elements.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor(config['color_primario']),
        spaceBefore=2, spaceAfter=2
    ))

    # ══════════════════════════════════════════════════════════════════
    # FORMULARIO ÚNICO NACIONAL – diseño tipo formato oficial
    # ══════════════════════════════════════════════════════════════════
    def fmt_cop(val):
        try:
            return f"${int(val or 0):,.0f}".replace(',', '.')
        except Exception:
            return "$0"

    # Colores
    C_LBL    = colors.HexColor(config['color_primario'])
    C_SEC    = colors.HexColor(config['color_secundario'])
    C_GOOD   = colors.HexColor(config['color_exito'])
    C_GRAY   = colors.HexColor('#f2f2f2')
    C_BORDER = colors.HexColor('#999999')
    C_TITLE  = colors.HexColor('#1a1a2e')

    # Estilos de párrafo para celdas de la tabla
    _fs = 7
    ST   = ParagraphStyle('_n',  fontName='Helvetica',      fontSize=_fs, leading=8.5)
    STB  = ParagraphStyle('_b',  fontName='Helvetica-Bold', fontSize=_fs, leading=8.5)
    STV  = ParagraphStyle('_v',  fontName='Helvetica',      fontSize=_fs, leading=8.5, alignment=TA_RIGHT)
    STVB = ParagraphStyle('_vb', fontName='Helvetica-Bold', fontSize=_fs, leading=8.5, alignment=TA_RIGHT)
    STC  = ParagraphStyle('_c',  fontName='Helvetica',      fontSize=_fs, leading=8.5, alignment=TA_CENTER)
    ST_TITLE_F = ParagraphStyle('_tf', fontName='Helvetica-Bold', fontSize=8.5, leading=10, alignment=TA_CENTER, textColor=colors.white)
    ST_SEC_LBL = ParagraphStyle('_sl', fontName='Helvetica-Bold', fontSize=7.5, leading=9,  alignment=TA_CENTER, textColor=colors.white)

    def P(txt, s=None):   return Paragraph(txt, s or ST)
    def PB(txt):          return Paragraph(txt, STB)
    def PV(val):          return Paragraph(fmt_cop(val), STV)
    def PVB(val):         return Paragraph(fmt_cop(val), STVB)
    def PC(txt):          return Paragraph(txt, STC)
    def PSEC(txt):        return Paragraph(f'<b>{txt}</b>', ST_SEC_LBL)

    # Anchos de columna principal: [etiqueta_sec | num_renglón | descripción | valor]
    W = [0.28*inch, 0.28*inch, 5.14*inch, 1.8*inch]
    W_INNER = W[2] + W[3]   # 6.94 in – ancho de tablas anidadas que span cols 2-3

    rows = []
    ts   = []

    def ri():         return len(rows)
    def add_ts(*args): ts.extend(args)

    # Shortcut: filas anidadas que ocupan cols 2-3 fusionadas
    def nested_row(sec_cell, num_cell, inner_table):
        r = ri()
        rows.append([sec_cell, num_cell, inner_table, ''])
        add_ts(
            ('SPAN',          (2, r), (3, r)),
            ('TOPPADDING',    (0, r), (-1, r), 0),
            ('BOTTOMPADDING', (0, r), (-1, r), 0),
            ('LEFTPADDING',   (2, r), (3,  r), 0),
            ('RIGHTPADDING',  (2, r), (3,  r), 0),
        )
        return r

    def inner_style():
        return TableStyle([
            ('INNERGRID',     (0, 0), (-1, -1), 0.3, C_BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('LEFTPADDING',   (0, 0), (-1, -1), 2),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
        ])

    # ── Título del formulario ──────────────────────────────────────────
    r = ri()
    rows.append([P('FORMULARIO ÚNICO NACIONAL DE DECLARACIÓN Y PAGO DE INDUSTRIA Y COMERCIO', ST_TITLE_F), '', '', ''])
    add_ts(
        ('SPAN',          (0, r), (3, r)),
        ('BACKGROUND',    (0, r), (3, r), C_TITLE),
        ('TOPPADDING',    (0, r), (3, r), 5),
        ('BOTTOMPADDING', (0, r), (3, r), 5),
    )

    # ── Municipio / Fecha ──────────────────────────────────────────────
    mpio_val   = ica.municipio.nombre if ica.municipio else '-'
    fecha_decl = ica.fecha_diligenciamiento.strftime('%d/%m/%Y') if ica.fecha_diligenciamiento else '-'
    mpio_t = Table(
        [[PB('MUNICIPIO O DISTRITO:'), P(mpio_val), PB('Fecha diligenciamiento:'), P(fecha_decl)]],
        colWidths=[1.8*inch, 3.14*inch, 1.5*inch, 0.5*inch],
    )
    mpio_t.setStyle(inner_style())
    nested_row('', '', mpio_t)

    # ── Departamento ───────────────────────────────────────────────────
    dpto_val = ica.departamento.nombre if ica.departamento else '-'
    r = ri()
    rows.append(['', '', P(f'<b>DEPARTAMENTO:</b>  {dpto_val}'), ''])
    add_ts(('SPAN', (0, r), (1, r)), ('SPAN', (2, r), (3, r)))

    # ── Año gravable + Opción de uso ───────────────────────────────────
    corrige_no = (f"ICA-{ica.corrige_a.anio_gravable}-{ica.corrige_a.id:06d}" if ica.corrige_a else '')
    _chk_ini = 'X' if ica.opcion_uso == 'INICIAL'    else ''
    _chk_cor = 'X' if ica.opcion_uso == 'CORRECCION' else ''
    _chk_w = 0.17*inch
    _lbl_ini_w = 1.55*inch
    _lbl_cor_w = 1.3*inch
    _ano_w   = 1.5*inch
    _corrige_w = 7.5*inch - _ano_w - _chk_w - _lbl_ini_w - _chk_w - _lbl_cor_w
    opcion_cells = [
        PB(f'AÑO GRAVABLE: {ica.anio_gravable}'),
        PC(_chk_ini), P('DECLARACIÓN INICIAL'),
        PC(_chk_cor), P('CORRECCIÓN'),
        P(f'<b>Corrige No.:</b> {corrige_no}' if corrige_no else ''),
    ]
    opcion_widths = [_ano_w, _chk_w, _lbl_ini_w, _chk_w, _lbl_cor_w, _corrige_w]
    opcion_t = Table([opcion_cells], colWidths=opcion_widths)
    _chk_ts = [
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        # Bordes de los cuadros de verificación (cols 1 y 3)
        ('BOX',  (1, 0), (1, 0), 0.8, colors.black),
        ('BOX',  (3, 0), (3, 0), 0.8, colors.black),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (3, 0), (3, 0), 'CENTER'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (3, 0), (3, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (1, 0), (1, 0), 8),
        ('FONTSIZE', (3, 0), (3, 0), 8),
    ]
    opcion_t.setStyle(TableStyle(_chk_ts))
    r = ri()
    rows.append(['', '', opcion_t, ''])
    add_ts(
        ('SPAN', (0, r), (1, r)), ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 0),
        ('BOTTOMPADDING', (0, r), (-1, r), 0),
        ('LEFTPADDING',   (2, r), (3,  r), 0),
        ('RIGHTPADDING',  (2, r), (3,  r), 0),
    )

    # ══════════════════════════════════════════════════════════════════
    # A. INFORMACIÓN DEL CONTRIBUYENTE
    # ══════════════════════════════════════════════════════════════════
    sec_A_start = ri()

    # A-1: Nombre / Razón social
    r = ri()
    rows.append([PSEC('A'), PC('1'),
                 P(f'<b>NOMBRES Y APELLIDOS O RAZÓN SOCIAL:</b>  {ica.nombre_razon_social or ""}'), ''])
    add_ts(('SPAN', (2, r), (3, r)))

    # A-2: Tipo y número de documento (cuadros con borde)
    tdoc = ica.tipo_documento or ''
    _opts_doc = [('CC', 'CC', 0.55*inch), ('NIT', 'NIT', 0.55*inch),
                 ('CE', 'CE', 0.55*inch), ('PASAPORTE', 'Pasaporte', 0.8*inch)]
    _doc_cells = []
    _doc_widths = []
    _doc_chk_cols = []
    for _k, _lbl, _lw in _opts_doc:
        _doc_chk_cols.append(len(_doc_cells))
        _doc_cells.append(PC('X' if tdoc == _k else ''))
        _doc_cells.append(P(_lbl))
        _doc_widths.extend([0.17*inch, _lw])
    # No. y DV
    _no_w  = 1.0*inch
    _dv_w  = W_INNER - sum(_doc_widths) - 0.4*inch - _no_w
    _doc_cells.extend([P('<b>No.:</b>'), P(ica.numero_documento or ''), P('<b>DV:</b>'), P(ica.dv or '')])
    _doc_widths.extend([0.4*inch, _no_w, 0.35*inch, max(_dv_w, 0.3*inch)])
    doc_row_t = Table([_doc_cells], colWidths=_doc_widths)
    _dts = [
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for _ci in _doc_chk_cols:
        _dts.extend([
            ('BOX',      (_ci, 0), (_ci, 0), 0.8, colors.black),
            ('ALIGN',    (_ci, 0), (_ci, 0), 'CENTER'),
            ('FONTNAME', (_ci, 0), (_ci, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (_ci, 0), (_ci, 0), 8),
        ])
    doc_row_t.setStyle(TableStyle(_dts))
    r = ri()
    rows.append(['', PC('2'), doc_row_t, ''])
    add_ts(
        ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 0),
        ('BOTTOMPADDING', (0, r), (-1, r), 0),
        ('LEFTPADDING',   (2, r), (3,  r), 0),
        ('RIGHTPADDING',  (2, r), (3,  r), 0),
    )

    # A-3: Dirección | Municipio | Departamento notificación
    dir_val  = ica.direccion_notificacion or '-'
    mpio_not = ica.municipio_notificacion.nombre if ica.municipio_notificacion else '-'
    dpto_not = ica.departamento_notificacion.nombre if ica.departamento_notificacion else '-'
    addr_t = Table(
        [[P(f'<b>3. DIRECCIÓN DE NOTIFICACIÓN:</b>  {dir_val}'),
          P(f'<b>MUNICIPIO:</b>  {mpio_not}'),
          P(f'<b>DPTO:</b>  {dpto_not}')]],
        colWidths=[3.44*inch, 2.3*inch, 1.2*inch],
    )
    addr_t.setStyle(inner_style())
    nested_row('', '', addr_t)

    # A-4: Teléfono | Correo | No. Est | Clasificación
    clasif = ica.get_clasificacion_contribuyente_display() if ica.clasificacion_contribuyente else '-'
    contact_t = Table(
        [[P(f'<b>4. TEL:</b>  {ica.telefono or "-"}'),
          P(f'<b>5. CORREO:</b>  {ica.correo_electronico or "-"}'),
          P(f'<b>6. No. EST:</b>  {ica.numero_establecimientos or "-"}'),
          P(f'<b>7. CLASIF:</b>  {clasif}')]],
        colWidths=[1.3*inch, 2.84*inch, 1.1*inch, 1.7*inch],
    )
    contact_t.setStyle(inner_style())
    nested_row('', '', contact_t)

    sec_A_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_A_start), (0, sec_A_end)),
        ('BACKGROUND', (0, sec_A_start), (0, sec_A_end), C_LBL),
        ('VALIGN',     (0, sec_A_start), (0, sec_A_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # B. BASE GRAVABLE
    # ══════════════════════════════════════════════════════════════════
    sec_B_start = ri()

    b8  = ica.b8_total_ingresos_pais or 0
    b9  = ica.b9_menos_ingresos_fuera_municipio or 0
    b10 = max(0, b8 - b9)
    b11 = ica.b11_menos_devoluciones_rebajas_descuentos or 0
    b12 = ica.b12_menos_exportaciones_venta_activos_fijos or 0
    b13 = ica.b13_menos_otras_actividades_excluidas_no_sujetas or 0
    b14 = ica.b14_menos_actividades_exentas_por_acuerdo or 0
    b15 = max(0, b10 - b11 - b12 - b13 - b14)

    b_data = [
        ( 8,  'TOTAL DE INGRESOS ORDINARIOS Y EXTRAORDINARIOS EN TODO EL PAÍS',                                        b8,  False),
        ( 9,  'MENOS INGRESOS FUERA DE ESTE MUNICIPIO O DISTRITO',                                                     b9,  False),
        (10,  'TOTAL DE INGRESOS ORDINARIOS Y EXTRAORDINARIOS EN ESTE MUNICIPIO (RENGLÓN 8 MENOS 9)',                   b10, False),
        (11,  'MENOS INGRESOS POR DEVOLUCIONES, REBAJAS, DESCUENTOS',                                                  b11, False),
        (12,  'MENOS INGRESOS POR EXPORTACIONES',                                                                       b12, False),
        (13,  'MENOS INGRESOS POR VENTA DE ACTIVOS FIJOS',                                                             b13, False),
        (14,  'MENOS INGRESOS POR ACTIVIDADES EXCLUIDAS O NO SUJETAS Y OTROS INGRESOS NO GRAVADOS',                    b14, False),
        (15,  'MENOS INGRESOS POR OTRAS ACTIVIDADES EXENTAS EN ESTE MUNICIPIO O DISTRITO (POR ACUERDO)',               0,   False),
        (16,  'TOTAL INGRESOS GRAVABLES (RENGLÓN 10 MENOS 11, 12, 13, 14 Y 15)',                                       b15, True),
    ]
    for num, desc, val, is_total in b_data:
        r = ri()
        rows.append([PSEC('B'), PC(str(num)),
                     PB(desc) if is_total else P(desc),
                     PVB(val) if is_total else PV(val)])
        if is_total:
            add_ts(
                ('BACKGROUND', (2, r), (3, r), C_GRAY),
                ('BOX',        (2, r), (3, r), 0.8, C_GOOD),
            )

    sec_B_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_B_start), (0, sec_B_end)),
        ('BACKGROUND', (0, sec_B_start), (0, sec_B_end), C_LBL),
        ('VALIGN',     (0, sec_B_start), (0, sec_B_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # C. DISCRIMINACIÓN DE ACTIVIDADES GRAVADAS
    # ══════════════════════════════════════════════════════════════════
    sec_C_start = ri()

    total_ing = 0
    total_imp = 0
    act_items = list(ica.items_actividades.all().order_by('orden'))
    cw_c = [2.54*inch, 0.8*inch, 1.4*inch, 1.1*inch, 1.1*inch]   # suma = 6.94

    act_inner_rows = [[
        PB('ACTIVIDADES GRAVADAS'), PB('CÓDIGO'),
        PC('<b>INGRESOS GRAVADOS</b>'), PC('<b>TARIFA (por mil)</b>'), PC('<b>IMPUESTO</b>'),
    ]]
    for i, act in enumerate(act_items):
        nombre  = act.actividad.nombre if act.actividad else '-'
        codigo  = act.actividad.codigo if act.actividad else '-'
        ing     = int(act.ingresos_gravados or 0)
        imp     = int(act.impuesto or 0)
        tarifa  = f"{float(act.tarifa_aplicada):g}" if act.tarifa_aplicada else '-'
        total_ing += ing
        total_imp += imp
        lbl = 'ACTIVIDAD 1 (PRINCIPAL)' if i == 0 else f'ACTIVIDAD {i + 1}'
        act_inner_rows.append([
            P(f'{lbl}: {nombre}'), PC(codigo),
            Paragraph(fmt_cop(ing),  STV),
            PC(tarifa),
            Paragraph(fmt_cop(imp),  STV),
        ])

    act_inner_rows.append([
        PB('TOTAL INGRESOS GRAVADOS'), P(''),
        Paragraph(fmt_cop(total_ing), STVB),
        PB('17. TOTAL IMPUESTOS'),
        Paragraph(fmt_cop(total_imp), STVB),
    ])
    kw_val = str(ica.capacidad_instalada_kw or '-')
    imp_56 = ica.imp_ley_56_1981 or 0
    act_inner_rows.append([
        P('18. GENERACIÓN DE ENERGÍA'), PC('CAP. INST.'),
        PC(f'{kw_val} kW'),
        PB('19. IMP. LEY 56/1981'),
        Paragraph(fmt_cop(imp_56), STV),
    ])

    act_t = Table(act_inner_rows, colWidths=cw_c)
    act_t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, C_BORDER),
        ('BACKGROUND',    (0, 0), (-1,  0), colors.HexColor(config['color_secundario'])),
        ('TEXTCOLOR',     (0, 0), (-1,  0), colors.white),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('BACKGROUND',    (0, -2), (-1, -1), C_GRAY),
        ('FONTNAME',      (0, -2), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN',         (2,  0), (2, -1), 'RIGHT'),
        ('ALIGN',         (4,  0), (4, -1), 'RIGHT'),
        ('TOPPADDING',    (0,  0), (-1, -1), 1),
        ('BOTTOMPADDING', (0,  0), (-1, -1), 1),
        ('LEFTPADDING',   (0,  0), (-1, -1), 2),
        ('RIGHTPADDING',  (0,  0), (-1, -1), 2),
    ]))
    nested_row(PSEC('C'), P(''), act_t)

    sec_C_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_C_start), (0, sec_C_end)),
        ('BACKGROUND', (0, sec_C_start), (0, sec_C_end), C_SEC),
        ('VALIGN',     (0, sec_C_start), (0, sec_C_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # D. LIQUIDACIÓN PRIVADA
    # ══════════════════════════════════════════════════════════════════
    sec_D_start = ri()

    d20 = (ica.valor_ica or 0) + (ica.imp_ley_56_1981 or 0)
    d21 = ica.avisos_tableros or 0
    d22 = ica.d22_sector_financiero or 0
    d23 = ica.sobretasa_bomberil or 0
    d24 = ica.d24_sobretasa_seguridad or 0
    d25 = d20 + d21 + d22 + d23 + d24
    d26 = ica.d26_exencion or 0
    d27 = ica.d27_retenciones or 0
    d28 = ica.d28_autorretenciones or 0
    d29 = ica.d29_anticipo_anterior or 0
    d30 = ica.d30_anticipo_siguiente or 0
    d31 = ica.d31_valor or 0
    d32 = ica.d32_saldo_favor_anterior or 0
    _net = d25 - d26 - d27 - d28 - d29 + d30 + d31 - d32
    d33 = max(0,  _net)
    d34 = max(0, -_net)
    sancion_tipo = ica.get_d31_tipo_sancion_display() if ica.d31_tipo_sancion else 'N/A'

    d_data = [
        (20, 'TOTAL IMPUESTO DE INDUSTRIA Y COMERCIO (RENGLÓN 17+19)',                                              d20, False),
        (21, 'IMPUESTO DE AVISOS Y TABLEROS (15% del renglón 20)',                                                  d21, False),
        (22, 'PAGO POR UNIDADES COMERCIALES ADICIONALES DEL SECTOR FINANCIERO',                                     d22, False),
        (23, 'SOBRETASA BOMBERIL (Ley 1575 de 2012)',                                                               d23, False),
        (24, 'SOBRETASA DE SEGURIDAD (LEY 1421 de 2011)',                                                           d24, False),
        (25, 'TOTAL IMPUESTO A CARGO (RENGLÓN 20+21+22+23+24)',                                                     d25, True),
        (26, 'MENOS VALOR DE EXENCIÓN O EXONERACIÓN SOBRE EL IMPUESTO Y NO SOBRE LOS INGRESOS',                   d26, False),
        (27, 'MENOS RETENCIONES que le practicaron a favor de este municipio en este periodo',                      d27, False),
        (28, 'MENOS AUTORETENCIONES practicadas a favor de este municipio en este periodo',                         d28, False),
        (29, 'MENOS ANTICIPO LIQUIDADO EN EL AÑO ANTERIOR',                                                        d29, False),
        (30, 'ANTICIPO DEL AÑO SIGUIENTE',                                                                          d30, False),
        (31, f'SANCIONES: {sancion_tipo}',                                                                          d31, False),
        (32, 'MENOS SALDO A FAVOR DEL PERIODO ANTERIOR SIN SOLICITUD DE DEVOLUCIÓN O COMPENSACIÓN',               d32, False),
        (33, 'TOTAL SALDO A CARGO (RENGLÓN 25-26-27-28-29+30+31-32)',                                              d33, True),
        (34, 'TOTAL SALDO A FAVOR (si el resultado anterior es menor a cero)',                                      d34, False),
    ]
    for num, desc, val, is_total in d_data:
        r = ri()
        rows.append([PSEC('D'), PC(str(num)),
                     PB(desc) if is_total else P(desc),
                     PVB(val) if is_total else PV(val)])
        if is_total:
            add_ts(('BACKGROUND', (2, r), (3, r), C_GRAY))

    sec_D_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_D_start), (0, sec_D_end)),
        ('BACKGROUND', (0, sec_D_start), (0, sec_D_end), C_LBL),
        ('VALIGN',     (0, sec_D_start), (0, sec_D_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # E. PAGO
    # ══════════════════════════════════════════════════════════════════
    sec_E_start = ri()

    e35 = d33
    e36 = ica.e36_descuento_pronto_pago or 0
    e37 = ica.e37_intereses_mora or 0
    e38 = max(0, e35 - e36 + e37)

    e_data = [
        (35, 'VALOR A PAGAR',                                                                            e35, True),
        (36, 'DESCUENTO POR PRONTO PAGO (Si existe, liquidelo según el acuerdo municipal o distrital)',  e36, False),
        (37, 'INTERESES DE MORA',                                                                        e37, False),
        (38, 'TOTAL A PAGAR (Renglón 35-36+37)',                                                         e38, True),
    ]
    for num, desc, val, is_total in e_data:
        r = ri()
        rows.append([PSEC('E'), PC(str(num)),
                     PB(desc) if is_total else P(desc),
                     PVB(val) if is_total else PV(val)])
        if is_total:
            add_ts(
                ('BACKGROUND', (2, r), (3, r), C_GOOD),
                ('TEXTCOLOR',  (2, r), (3, r), colors.white),
                ('TEXTCOLOR',  (3, r), (3, r), colors.white),
            )

    sec_E_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_E_start), (0, sec_E_end)),
        ('BACKGROUND', (0, sec_E_start), (0, sec_E_end), C_LBL),
        ('VALIGN',     (0, sec_E_start), (0, sec_E_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # F. FIRMAS
    # ══════════════════════════════════════════════════════════════════
    sec_F_start = ri()

    cont_nombre = (ica.contador_nombre or '-')              if ica.tiene_contador       else ''
    cont_tp     = (ica.contador_tarjeta_profesional or '-') if ica.tiene_contador       else ''
    cont_doc    = (ica.contador_numero_documento or '-')    if ica.tiene_contador       else ''
    rev_nombre  = (ica.revisor_nombre or '-')               if ica.tiene_revisor_fiscal else ''
    rev_tp      = (ica.revisor_tarjeta_profesional or '-')  if ica.tiene_revisor_fiscal else ''
    rev_doc     = (ica.revisor_numero_documento or '-')     if ica.tiene_revisor_fiscal else ''
    rep_nombre  = ica.rep_legal_nombre or '-'
    rep_doc     = ica.rep_legal_numero_documento or '-'

    fw = W_INNER / 3
    firma_t = Table(
        [
            [PB('FIRMA DEL DECLARANTE'), PB('FIRMA DEL CONTADOR'), PB('REVISOR FISCAL')],
            [P(f'<b>NOMBRE:</b> {rep_nombre}'),
             P(f'<b>NOMBRE:</b> {cont_nombre}'),
             P(f'<b>NOMBRE:</b> {rev_nombre}')],
            [P(f'<b>CC.:</b> {rep_doc}'),
             Table([[P(f'<b>CC.:</b> {cont_doc}'), P(f'<b>T.P.:</b> {cont_tp}')]], colWidths=[fw/2, fw/2]),
             Table([[P(f'<b>CC.:</b> {rev_doc}'),  P(f'<b>T.P.:</b> {rev_tp}')]],  colWidths=[fw/2, fw/2])],
        ],
        colWidths=[fw, fw, fw],
    )
    firma_t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, C_BORDER),
        ('BACKGROUND',    (0, 0), (-1,  0), C_GRAY),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 2),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
    ]))
    r = nested_row(PSEC('F'), P(''), firma_t)
    add_ts(('VALIGN', (0, r), (1, r), 'MIDDLE'))

    sec_F_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_F_start), (0, sec_F_end)),
        ('BACKGROUND', (0, sec_F_start), (0, sec_F_end), C_LBL),
        ('VALIGN',     (0, sec_F_start), (0, sec_F_end), 'MIDDLE'),
    )

    # ── FIRMA ELECTRÓNICA OTP ─────────────────────────────────────────
    r = ri()
    if ica.firma_otp_verificada and ica.firma_timestamp:
        ts_fmt = ica.firma_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
        firma_txt = (
            f'<b>✓ FIRMA ELECTRÓNICA VERIFICADA</b> — Ley 527 de 1999 — '
            f'Fecha/Hora: {ts_fmt} — '
            f'Hash SHA-256: {ica.firma_hash or "-"}'
        )
        rows.append(['', '', P(firma_txt), ''])
        add_ts(
            ('SPAN', (0, r), (1, r)),
            ('SPAN', (2, r), (3, r)),
            ('BACKGROUND', (2, r), (3, r), colors.HexColor('#e6f4ea')),
        )
    else:
        rows.append(['', '', P('<b>ADVERTENCIA:</b> Esta declaración no ha sido firmada electrónicamente.'), ''])
        add_ts(
            ('SPAN', (0, r), (1, r)),
            ('SPAN', (2, r), (3, r)),
            ('BACKGROUND', (2, r), (3, r), colors.HexColor('#fff3cd')),
        )

    # ── NOTA ──────────────────────────────────────────────────────────
    _ST_NOTA = ParagraphStyle('_nota', fontName='Helvetica-Bold', fontSize=10, leading=13)
    r = ri()
    rows.append(['', '', Paragraph(
        '<b>NOTA:</b> Para realizar el pago del valor declarado, la administración municipal le enviará '
        'el documento de cobro al correo electrónico suministrado, el cual se entiende como correo de notificación.',
        _ST_NOTA
    ), ''])
    add_ts(
        ('SPAN', (0, r), (1, r)),
        ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 6),
        ('BOTTOMPADDING', (0, r), (-1, r), 6),
    )

    # ── Aplicar estilos globales y construir tabla principal ───────────
    add_ts(
        ('GRID',          (0, 0), (-1, -1), 0.4, C_BORDER),
        ('FONTSIZE',      (0, 0), (-1, -1), 7),
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING',   (0, 0), (-1, -1), 2),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (1, 0), (1,  -1), 'CENTER'),
        ('ALIGN',         (3, 0), (3,  -1), 'RIGHT'),
        ('TEXTCOLOR',     (0, 0), (0,  -1), colors.white),
    )
    main_t = Table(rows, colWidths=W)
    main_t.setStyle(TableStyle(ts))
    elements.append(main_t)

    # El instructivo se eliminó del PDF — ahora aparece como tooltips en el formulario web

    # Texto y fecha de generación al final absoluto del documento
    if config['texto_pie_pagina']:
        elements.append(Paragraph(
            f"<i>{config['texto_pie_pagina']}</i>",
            styles['PDF_Small']
        ))
    elements.append(Paragraph(
        f"<i>Documento generado electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
        styles['PDF_Small']
    ))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    disp = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disp}; filename="ICA_{ica.anio_gravable}_{ica.id}.pdf"'
    return response


@login_required
def generar_pdf_auto(request, auto_id):
    """Genera PDF de una declaración de Autorretención ICA."""
    auto = get_object_or_404(DeclaracionAutoRetencion, id=auto_id)

    if not is_admin(request.user) and auto.user != request.user:
        messages.error(request, 'No tienes permiso para ver este documento.')
        return redirect('tasks_completed')

    config = get_pdf_config()

    _radicado_title = f"AUTO-{auto.anio_gravable}-B{auto.bimestre}-{auto.id:06d}"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.25 * inch,
        bottomMargin=0.35 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        title=_radicado_title,
        author="Portal Tributario Segovia",
    )

    styles = get_pdf_styles(config)
    elements = []

    municipio_nombre = auto.municipio.nombre if auto.municipio else None

    _h_logo = 0.9 * inch
    _logo_l = ''
    if config['logo_izquierdo'] and os.path.exists(config['logo_izquierdo']):
        try:
            _tmp = Image(config['logo_izquierdo'])
            _asp = _tmp.imageWidth / _tmp.imageHeight if _tmp.imageHeight else 1
            _logo_l = Image(config['logo_izquierdo'], width=_h_logo * _asp, height=_h_logo)
        except Exception:
            pass
    _logo_r = ''
    if config['logo_derecho'] and os.path.exists(config['logo_derecho']):
        try:
            _tmp2 = Image(config['logo_derecho'])
            _asp2 = _tmp2.imageWidth / _tmp2.imageHeight if _tmp2.imageHeight else 1
            _logo_r = Image(config['logo_derecho'], width=_h_logo * _asp2, height=_h_logo)
        except Exception:
            pass

    _ent_nombre = municipio_nombre or config['nombre_entidad']
    _hdr_centro = Paragraph(
        f'<b>DECLARACIÓN BIMESTRAL DE AUTORRETENCIÓN DEL IMPUESTO DE INDUSTRIA Y COMERCIO</b><br/>'
        f'<font size="8">{_ent_nombre}</font>',
        ParagraphStyle('_hc', fontName='Helvetica-Bold', fontSize=10, leading=12, alignment=TA_CENTER)
    )
    _MESES_ES = {1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
                 7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre'}
    _fecha_rad_dt = auto.firma_timestamp or auto.fecha_diligenciamiento
    if _fecha_rad_dt:
        _fecha_rad_str = f"{_fecha_rad_dt.day} de {_MESES_ES[_fecha_rad_dt.month]} de {_fecha_rad_dt.year}"
    else:
        _fecha_rad_str = ''
    _hdr_rad = Paragraph(
        f'<b>Radicado:</b> {_radicado_title}<br/>'
        + (f'<font size="7">Fecha: {_fecha_rad_str}</font>' if _fecha_rad_str else ''),
        ParagraphStyle('_hr', fontName='Helvetica-Bold', fontSize=8, leading=10,
                       alignment=TA_RIGHT, textColor=colors.HexColor(config['color_radicado']))
    )
    _hdr_t = Table(
        [[_logo_l, _hdr_centro, _hdr_rad if not _logo_r else _logo_r]],
        colWidths=[1.0 * inch, 5.5 * inch, 1.0 * inch]
    )
    _hdr_t.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (0,  0),  'LEFT'),
        ('ALIGN',         (1, 0), (1,  0),  'CENTER'),
        ('ALIGN',         (2, 0), (2,  0),  'RIGHT'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(_hdr_t)
    if _logo_r:
        elements.append(Paragraph(
            f'<b>Radicado:</b> {_radicado_title}',
            ParagraphStyle('_hr2', fontName='Helvetica-Bold', fontSize=8, leading=9,
                           alignment=TA_RIGHT, textColor=colors.HexColor(config['color_radicado']))
        ))
    elements.append(HRFlowable(
        width="100%", thickness=2,
        color=colors.HexColor(config['color_primario']),
        spaceBefore=2, spaceAfter=2
    ))

    def fmt_cop(val):
        try:
            return f"${int(val or 0):,.0f}".replace(',', '.')
        except Exception:
            return "$0"

    C_LBL    = colors.HexColor(config['color_primario'])
    C_SEC    = colors.HexColor(config['color_secundario'])
    C_GOOD   = colors.HexColor(config['color_exito'])
    C_GRAY   = colors.HexColor('#f2f2f2')
    C_BORDER = colors.HexColor('#999999')
    C_TITLE  = colors.HexColor('#1a1a2e')

    _fs = 7
    ST   = ParagraphStyle('_n',  fontName='Helvetica',      fontSize=_fs, leading=8.5)
    STB  = ParagraphStyle('_b',  fontName='Helvetica-Bold', fontSize=_fs, leading=8.5)
    STV  = ParagraphStyle('_v',  fontName='Helvetica',      fontSize=_fs, leading=8.5, alignment=TA_RIGHT)
    STVB = ParagraphStyle('_vb', fontName='Helvetica-Bold', fontSize=_fs, leading=8.5, alignment=TA_RIGHT)
    STC  = ParagraphStyle('_c',  fontName='Helvetica',      fontSize=_fs, leading=8.5, alignment=TA_CENTER)
    ST_TITLE_F = ParagraphStyle('_tf', fontName='Helvetica-Bold', fontSize=8.5, leading=10, alignment=TA_CENTER, textColor=colors.white)
    ST_SEC_LBL = ParagraphStyle('_sl', fontName='Helvetica-Bold', fontSize=7.5, leading=9,  alignment=TA_CENTER, textColor=colors.white)

    def P(txt, s=None):   return Paragraph(txt, s or ST)
    def PB(txt):          return Paragraph(txt, STB)
    def PV(val):          return Paragraph(fmt_cop(val), STV)
    def PVB(val):         return Paragraph(fmt_cop(val), STVB)
    def PC(txt):          return Paragraph(txt, STC)
    def PSEC(txt):        return Paragraph(f'<b>{txt}</b>', ST_SEC_LBL)

    W = [0.28 * inch, 0.28 * inch, 5.14 * inch, 1.8 * inch]
    W_INNER = W[2] + W[3]

    rows = []
    ts   = []

    def ri():          return len(rows)
    def add_ts(*args): ts.extend(args)

    def nested_row(sec_cell, num_cell, inner_table):
        r = ri()
        rows.append([sec_cell, num_cell, inner_table, ''])
        add_ts(
            ('SPAN',          (2, r), (3, r)),
            ('TOPPADDING',    (0, r), (-1, r), 0),
            ('BOTTOMPADDING', (0, r), (-1, r), 0),
            ('LEFTPADDING',   (2, r), (3,  r), 0),
            ('RIGHTPADDING',  (2, r), (3,  r), 0),
        )
        return r

    def inner_style():
        return TableStyle([
            ('INNERGRID',     (0, 0), (-1, -1), 0.3, C_BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('LEFTPADDING',   (0, 0), (-1, -1), 2),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
        ])

    # ── Título del formulario ──────────────────────────────────────────
    r = ri()
    rows.append([P('FORMULARIO DE DECLARACIÓN BIMESTRAL DE AUTORRETENCIÓN — IMPUESTO DE INDUSTRIA Y COMERCIO', ST_TITLE_F), '', '', ''])
    add_ts(
        ('SPAN',          (0, r), (3, r)),
        ('BACKGROUND',    (0, r), (3, r), C_TITLE),
        ('TOPPADDING',    (0, r), (3, r), 5),
        ('BOTTOMPADDING', (0, r), (3, r), 5),
    )

    # ── Municipio / Fecha ──────────────────────────────────────────────
    mpio_val   = auto.municipio.nombre if auto.municipio else '-'
    fecha_decl = auto.fecha_diligenciamiento.strftime('%d/%m/%Y') if auto.fecha_diligenciamiento else '-'
    mpio_t = Table(
        [[PB('MUNICIPIO O DISTRITO:'), P(mpio_val), PB('Fecha diligenciamiento:'), P(fecha_decl)]],
        colWidths=[1.8 * inch, 3.14 * inch, 1.5 * inch, 0.5 * inch],
    )
    mpio_t.setStyle(inner_style())
    nested_row('', '', mpio_t)

    # ── Departamento ───────────────────────────────────────────────────
    dpto_val = auto.departamento.nombre if auto.departamento else '-'
    r = ri()
    rows.append(['', '', P(f'<b>DEPARTAMENTO:</b>  {dpto_val}'), ''])
    add_ts(('SPAN', (0, r), (1, r)), ('SPAN', (2, r), (3, r)))

    # ── Año gravable + Bimestre + Opción de uso ────────────────────────
    corrige_no = (f"AUTO-{auto.corrige_a.anio_gravable}-B{auto.corrige_a.bimestre}-{auto.corrige_a.id:06d}" if auto.corrige_a else '')
    _chk_ini = 'X' if auto.opcion_uso == 'INICIAL'    else ''
    _chk_cor = 'X' if auto.opcion_uso == 'CORRECCION' else ''
    bimestre_display = auto.get_bimestre_display()

    _chk_w = 0.17 * inch
    _lbl_ini_w = 1.55 * inch
    _lbl_cor_w = 1.3 * inch
    _ano_w   = 1.0 * inch
    _bim_w   = 1.0 * inch
    _corrige_w = 7.5 * inch - _ano_w - _bim_w - _chk_w - _lbl_ini_w - _chk_w - _lbl_cor_w
    opcion_cells = [
        PB(f'AÑO: {auto.anio_gravable}'),
        PB(f'BIMESTRE: {bimestre_display}'),
        PC(_chk_ini), P('DECLARACIÓN INICIAL'),
        PC(_chk_cor), P('CORRECCIÓN'),
        P(f'<b>Corrige No.:</b> {corrige_no}' if corrige_no else ''),
    ]
    opcion_widths = [_ano_w, _bim_w, _chk_w, _lbl_ini_w, _chk_w, _lbl_cor_w, _corrige_w]
    opcion_t = Table([opcion_cells], colWidths=opcion_widths)
    _chk_ts = [
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX',  (2, 0), (2, 0), 0.8, colors.black),
        ('BOX',  (4, 0), (4, 0), 0.8, colors.black),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
        ('ALIGN', (4, 0), (4, 0), 'CENTER'),
        ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),
        ('FONTNAME', (4, 0), (4, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (2, 0), (2, 0), 8),
        ('FONTSIZE', (4, 0), (4, 0), 8),
    ]
    opcion_t.setStyle(TableStyle(_chk_ts))
    r = ri()
    rows.append(['', '', opcion_t, ''])
    add_ts(
        ('SPAN', (0, r), (1, r)), ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 0),
        ('BOTTOMPADDING', (0, r), (-1, r), 0),
        ('LEFTPADDING',   (2, r), (3,  r), 0),
        ('RIGHTPADDING',  (2, r), (3,  r), 0),
    )

    # ══════════════════════════════════════════════════════════════════
    # A. INFORMACIÓN DEL CONTRIBUYENTE
    # ══════════════════════════════════════════════════════════════════
    sec_A_start = ri()

    r = ri()
    rows.append([PSEC('A'), PC('1'),
                 P(f'<b>NOMBRES Y APELLIDOS O RAZÓN SOCIAL:</b>  {auto.nombre_razon_social or ""}'), ''])
    add_ts(('SPAN', (2, r), (3, r)))

    tdoc = auto.tipo_documento or ''
    _opts_doc = [('CC', 'CC', 0.55 * inch), ('NIT', 'NIT', 0.55 * inch),
                 ('CE', 'CE', 0.55 * inch), ('PASAPORTE', 'Pasaporte', 0.8 * inch)]
    _doc_cells = []
    _doc_widths = []
    _doc_chk_cols = []
    for _k, _lbl, _lw in _opts_doc:
        _doc_chk_cols.append(len(_doc_cells))
        _doc_cells.append(PC('X' if tdoc == _k else ''))
        _doc_cells.append(P(_lbl))
        _doc_widths.extend([0.17 * inch, _lw])
    _no_w  = 1.0 * inch
    _dv_w  = W_INNER - sum(_doc_widths) - 0.4 * inch - _no_w
    _doc_cells.extend([P('<b>No.:</b>'), P(auto.numero_documento or ''), P('<b>DV:</b>'), P(auto.dv or '')])
    _doc_widths.extend([0.4 * inch, _no_w, 0.35 * inch, max(_dv_w, 0.3 * inch)])
    doc_row_t = Table([_doc_cells], colWidths=_doc_widths)
    _dts = [
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]
    for _ci in _doc_chk_cols:
        _dts.extend([
            ('BOX',      (_ci, 0), (_ci, 0), 0.8, colors.black),
            ('ALIGN',    (_ci, 0), (_ci, 0), 'CENTER'),
            ('FONTNAME', (_ci, 0), (_ci, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (_ci, 0), (_ci, 0), 8),
        ])
    doc_row_t.setStyle(TableStyle(_dts))
    r = ri()
    rows.append(['', PC('2'), doc_row_t, ''])
    add_ts(
        ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 0),
        ('BOTTOMPADDING', (0, r), (-1, r), 0),
        ('LEFTPADDING',   (2, r), (3,  r), 0),
        ('RIGHTPADDING',  (2, r), (3,  r), 0),
    )

    dir_val  = auto.direccion_notificacion or '-'
    mpio_not = auto.municipio_notificacion.nombre if auto.municipio_notificacion else '-'
    dpto_not = auto.departamento_notificacion.nombre if auto.departamento_notificacion else '-'
    addr_t = Table(
        [[P(f'<b>3. DIRECCIÓN DE NOTIFICACIÓN:</b>  {dir_val}'),
          P(f'<b>MUNICIPIO:</b>  {mpio_not}'),
          P(f'<b>DPTO:</b>  {dpto_not}')]],
        colWidths=[3.44 * inch, 2.3 * inch, 1.2 * inch],
    )
    addr_t.setStyle(inner_style())
    nested_row('', '', addr_t)

    clasif = auto.get_clasificacion_contribuyente_display() if auto.clasificacion_contribuyente else '-'
    contact_t = Table(
        [[P(f'<b>4. TEL:</b>  {auto.telefono or "-"}'),
          P(f'<b>5. CORREO:</b>  {auto.correo_electronico or "-"}'),
          P(f'<b>6. No. EST:</b>  {auto.numero_establecimientos or "-"}'),
          P(f'<b>7. CLASIF:</b>  {clasif}')]],
        colWidths=[1.3 * inch, 2.84 * inch, 1.1 * inch, 1.7 * inch],
    )
    contact_t.setStyle(inner_style())
    nested_row('', '', contact_t)

    sec_A_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_A_start), (0, sec_A_end)),
        ('BACKGROUND', (0, sec_A_start), (0, sec_A_end), C_LBL),
        ('VALIGN',     (0, sec_A_start), (0, sec_A_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # B. LIQUIDACIÓN DE ACTIVIDADES (tabla de 7 columnas)
    # ══════════════════════════════════════════════════════════════════
    sec_B_start = ri()

    act_items = list(auto.actividades.all().order_by('orden'))
    total_ing_grav = 0
    total_autorretencion = 0

    cw_act = [0.3 * inch, 2.0 * inch, 1.2 * inch, 1.1 * inch, 1.1 * inch, 0.7 * inch, 1.04 * inch]  # suma = 7.44 → W_INNER

    act_inner_rows = [[
        PC('<b>#</b>'),
        PB('ACTIVIDAD ECONÓMICA'),
        PC('<b>INGRESO TOTAL BIMESTRE</b>'),
        PC('<b>INGRESO EXCLUIDO</b>'),
        PC('<b>INGRESO GRAVABLE</b>'),
        PC('<b>TARIFA (x mil)</b>'),
        PC('<b>VALOR AUTORRETENCIÓN</b>'),
    ]]
    for i, act in enumerate(act_items):
        nombre  = act.actividad.nombre if act.actividad else '-'
        codigo  = act.actividad.codigo if act.actividad else '-'
        ing_tot = int(act.ingreso_total_bimestre or 0)
        ing_exc = int(act.ingreso_excluido or 0)
        ing_grav = int(act.ingreso_gravable or 0)
        tarifa  = f"{float(act.tarifa_aplicada):g}" if act.tarifa_aplicada else '-'
        valor   = int(act.valor_autorretencion or 0)
        total_ing_grav += ing_grav
        total_autorretencion += valor
        act_inner_rows.append([
            PC(str(i + 1)),
            P(f'{nombre} ({codigo})'),
            Paragraph(fmt_cop(ing_tot), STV),
            Paragraph(fmt_cop(ing_exc), STV),
            Paragraph(fmt_cop(ing_grav), STV),
            PC(tarifa),
            Paragraph(fmt_cop(valor), STV),
        ])

    act_inner_rows.append([
        P(''),
        PB('TOTAL INGRESOS GRAVADOS'),
        P(''), P(''),
        Paragraph(fmt_cop(total_ing_grav), STVB),
        PB('TOTAL AUTORRETENCIÓN'),
        Paragraph(fmt_cop(total_autorretencion), STVB),
    ])

    act_t = Table(act_inner_rows, colWidths=cw_act)
    act_t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, C_BORDER),
        ('BACKGROUND',    (0, 0), (-1,  0), C_SEC),
        ('TEXTCOLOR',     (0, 0), (-1,  0), colors.white),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('BACKGROUND',    (0, -1), (-1, -1), C_GRAY),
        ('FONTNAME',      (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN',         (2,  1), (4, -1), 'RIGHT'),
        ('ALIGN',         (6,  1), (6, -1), 'RIGHT'),
        ('TOPPADDING',    (0,  0), (-1, -1), 1),
        ('BOTTOMPADDING', (0,  0), (-1, -1), 1),
        ('LEFTPADDING',   (0,  0), (-1, -1), 2),
        ('RIGHTPADDING',  (0,  0), (-1, -1), 2),
    ]))
    nested_row(PSEC('B'), P(''), act_t)

    sec_B_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_B_start), (0, sec_B_end)),
        ('BACKGROUND', (0, sec_B_start), (0, sec_B_end), C_SEC),
        ('VALIGN',     (0, sec_B_start), (0, sec_B_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # D. LIQUIDACIÓN PRIVADA
    # ══════════════════════════════════════════════════════════════════
    sec_D_start = ri()

    sanciones         = int(auto.sanciones or 0)
    intereses_mora    = int(auto.intereses_mora or 0)
    subtotal          = int(auto.subtotal or 0)
    autorretencion_ex = int(auto.autorretencion_exceso or 0)
    total_a_pagar     = int(auto.total_a_pagar or 0)

    tipo_sancion_display = auto.get_tipo_sancion_display() if auto.tipo_sancion and auto.tipo_sancion != 'NINGUNA' else 'Ninguna'
    cual_sancion_str = f' — {auto.cual_sancion}' if auto.cual_sancion and auto.tipo_sancion == 'OTRA' else ''
    d_data = [
        ('D1', 'TOTAL VALOR AUTORRETENCIÓN (suma de columna valor autorretención)',                   total_autorretencion, True),
        ('D2', f'SANCIONES: {tipo_sancion_display}{cual_sancion_str}',                               sanciones,           False),
        ('D3', 'INTERESES DE MORA',                                                                   intereses_mora,      False),
        ('D4', 'SUBTOTAL (D1 + D2 + D3)',                                                             subtotal,            True),
        ('D5', 'MENOS AUTORRETENCIÓN EN EXCESO DE PERIODOS ANTERIORES',                               autorretencion_ex,   False),
        ('D6', 'TOTAL A PAGAR (D4 - D5)',                                                             total_a_pagar,       True),
    ]
    for num, desc, val, is_total in d_data:
        r = ri()
        rows.append([PSEC('D'), PC(num),
                     PB(desc) if is_total else P(desc),
                     PVB(val) if is_total else PV(val)])
        if is_total:
            bg = C_GOOD if num == 'D6' else C_GRAY
            add_ts(('BACKGROUND', (2, r), (3, r), bg))
            if num == 'D6':
                add_ts(
                    ('TEXTCOLOR', (2, r), (3, r), colors.white),
                    ('TEXTCOLOR', (3, r), (3, r), colors.white),
                )

    sec_D_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_D_start), (0, sec_D_end)),
        ('BACKGROUND', (0, sec_D_start), (0, sec_D_end), C_LBL),
        ('VALIGN',     (0, sec_D_start), (0, sec_D_end), 'MIDDLE'),
    )

    # ══════════════════════════════════════════════════════════════════
    # F. FIRMAS
    # ══════════════════════════════════════════════════════════════════
    sec_F_start = ri()

    cont_nombre = (auto.contador_nombre or '-')              if auto.tiene_contador       else ''
    cont_tp     = (auto.contador_tarjeta_profesional or '-') if auto.tiene_contador       else ''
    cont_doc    = (auto.contador_numero_documento or '-')    if auto.tiene_contador       else ''
    rev_nombre  = (auto.revisor_nombre or '-')               if auto.tiene_revisor_fiscal else ''
    rev_tp      = (auto.revisor_tarjeta_profesional or '-')  if auto.tiene_revisor_fiscal else ''
    rev_doc     = (auto.revisor_numero_documento or '-')     if auto.tiene_revisor_fiscal else ''
    rep_nombre  = auto.rep_legal_nombre or '-'
    rep_doc     = auto.rep_legal_numero_documento or '-'

    fw = W_INNER / 3
    firma_t = Table(
        [
            [PB('FIRMA DEL DECLARANTE'), PB('FIRMA DEL CONTADOR'), PB('REVISOR FISCAL')],
            [P(f'<b>NOMBRE:</b> {rep_nombre}'),
             P(f'<b>NOMBRE:</b> {cont_nombre}'),
             P(f'<b>NOMBRE:</b> {rev_nombre}')],
            [P(f'<b>CC.:</b> {rep_doc}'),
             Table([[P(f'<b>CC.:</b> {cont_doc}'), P(f'<b>T.P.:</b> {cont_tp}')]], colWidths=[fw / 2, fw / 2]),
             Table([[P(f'<b>CC.:</b> {rev_doc}'),  P(f'<b>T.P.:</b> {rev_tp}')]],  colWidths=[fw / 2, fw / 2])],
        ],
        colWidths=[fw, fw, fw],
    )
    firma_t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.5, C_BORDER),
        ('BACKGROUND',    (0, 0), (-1,  0), C_GRAY),
        ('FONTNAME',      (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('TOPPADDING',    (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING',   (0, 0), (-1, -1), 2),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
    ]))
    r = nested_row(PSEC('F'), P(''), firma_t)
    add_ts(('VALIGN', (0, r), (1, r), 'MIDDLE'))

    sec_F_end = ri() - 1
    add_ts(
        ('SPAN',       (0, sec_F_start), (0, sec_F_end)),
        ('BACKGROUND', (0, sec_F_start), (0, sec_F_end), C_LBL),
        ('VALIGN',     (0, sec_F_start), (0, sec_F_end), 'MIDDLE'),
    )

    # ── FIRMA ELECTRÓNICA OTP ─────────────────────────────────────────
    r = ri()
    if auto.firma_otp_verificada and auto.firma_timestamp:
        ts_fmt = auto.firma_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
        firma_txt = (
            f'<b>✓ FIRMA ELECTRÓNICA VERIFICADA</b> — Ley 527 de 1999 — '
            f'Fecha/Hora: {ts_fmt} — '
            f'Hash SHA-256: {auto.firma_hash or "-"}'
        )
        rows.append(['', '', P(firma_txt), ''])
        add_ts(
            ('SPAN', (0, r), (1, r)),
            ('SPAN', (2, r), (3, r)),
            ('BACKGROUND', (2, r), (3, r), colors.HexColor('#e6f4ea')),
        )
    else:
        rows.append(['', '', P('<b>ADVERTENCIA:</b> Esta declaración no ha sido firmada electrónicamente.'), ''])
        add_ts(
            ('SPAN', (0, r), (1, r)),
            ('SPAN', (2, r), (3, r)),
            ('BACKGROUND', (2, r), (3, r), colors.HexColor('#fff3cd')),
        )

    # ── NOTA ──────────────────────────────────────────────────────────
    _ST_NOTA = ParagraphStyle('_nota', fontName='Helvetica-Bold', fontSize=10, leading=13)
    r = ri()
    rows.append(['', '', Paragraph(
        '<b>NOTA:</b> Para realizar el pago del valor declarado, la administración municipal le enviará '
        'el documento de cobro al correo electrónico suministrado, el cual se entiende como correo de notificación.',
        _ST_NOTA
    ), ''])
    add_ts(
        ('SPAN', (0, r), (1, r)),
        ('SPAN', (2, r), (3, r)),
        ('TOPPADDING',    (0, r), (-1, r), 6),
        ('BOTTOMPADDING', (0, r), (-1, r), 6),
    )

    # ── Estilos globales y tabla principal ────────────────────────────
    add_ts(
        ('GRID',          (0, 0), (-1, -1), 0.4, C_BORDER),
        ('FONTSIZE',      (0, 0), (-1, -1), 7),
        ('TOPPADDING',    (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LEFTPADDING',   (0, 0), (-1, -1), 2),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (1, 0), (1,  -1), 'CENTER'),
        ('ALIGN',         (3, 0), (3,  -1), 'RIGHT'),
        ('TEXTCOLOR',     (0, 0), (0,  -1), colors.white),
    )
    main_t = Table(rows, colWidths=W)
    main_t.setStyle(TableStyle(ts))
    elements.append(main_t)

    if config['texto_pie_pagina']:
        elements.append(Paragraph(
            f"<i>{config['texto_pie_pagina']}</i>",
            styles['PDF_Small']
        ))
    elements.append(Paragraph(
        f"<i>Documento generado electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</i>",
        styles['PDF_Small']
    ))

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    disp = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disp}; filename="AUTO_{auto.anio_gravable}_B{auto.bimestre}_{auto.id}.pdf"'
    return response


# ----------------------------
# EXPORTACIÓN EXCEL REPORTERÍA
# ----------------------------
@login_required
@user_passes_test(is_admin)
def exportar_excel_rit(request):
    """Exporta todos los RITs a Excel con múltiples hojas."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        messages.error(request, 'Se requiere openpyxl para exportar a Excel. Instálelo con: pip install openpyxl')
        return redirect('admin_reportes')

    # Crear workbook
    wb = openpyxl.Workbook()

    # Estilos
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='2C3E50', end_color='2C3E50', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # --- HOJA 1: RITs Principal ---
    ws_rit = wb.active
    ws_rit.title = "RITs"

    rit_headers = [
        'ID', 'Radicado', 'Fecha', 'Opción Uso', 'Estado', 'Clase Contribuyente',
        'Retenedor ICA', 'Autorretenedor ICA', 'Nombre/Razón Social', 'Tipo Doc',
        'Número Doc', 'DV', 'Dirección', 'Municipio', 'Departamento', 'Teléfono',
        'Correo', 'N° Establecimientos', 'Clasificación', 'Tipo Persona',
        'Tipo Jurídica', 'Usuario'
    ]

    for col, header in enumerate(rit_headers, 1):
        cell = ws_rit.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    rits = RegistroRIT.objects.select_related('user', 'municipio_notificacion', 'departamento_notificacion').order_by('-fecha')
    _fd = _parse_fecha(request.GET.get('fecha_desde', ''))
    _fh = _parse_fecha(request.GET.get('fecha_hasta', ''))
    if _fd:
        rits = rits.filter(fecha__date__gte=_fd)
    if _fh:
        rits = rits.filter(fecha__date__lte=_fh)

    for row_num, rit in enumerate(rits, 2):
        data = [
            rit.id,
            rit.radicado or '',
            rit.fecha.strftime('%Y-%m-%d %H:%M') if rit.fecha else '',
            rit.get_opcion_uso_display(),
            rit.get_estado_display(),
            rit.get_clase_contribuyente_display(),
            'Sí' if rit.es_retenedor_ica else 'No',
            'Sí' if rit.es_autorretenedor_ica else 'No',
            rit.nombre_razon_social or '',
            rit.get_tipo_documento_display(),
            rit.numero_documento or '',
            rit.dv or '',
            rit.direccion_notificacion or '',
            str(rit.municipio_notificacion) if rit.municipio_notificacion else '',
            str(rit.departamento_notificacion) if rit.departamento_notificacion else '',
            rit.telefono or '',
            rit.correo_electronico or '',
            rit.numero_establecimientos or 0,
            rit.get_clasificacion_contribuyente_display(),
            rit.get_tipo_persona_display() if rit.tipo_persona else '',
            rit.get_tipo_juridica_display() if rit.tipo_juridica else '',
            rit.user.username if rit.user else '',
        ]
        for col, value in enumerate(data, 1):
            cell = ws_rit.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    # Ajustar ancho de columnas
    for col in range(1, len(rit_headers) + 1):
        ws_rit.column_dimensions[get_column_letter(col)].width = 15

    # --- HOJA 2: Establecimientos ---
    ws_est = wb.create_sheet("Establecimientos")
    est_headers = ['RIT ID', 'Radicado', 'Nombre Establecimiento', 'Dirección', 'Teléfono',
                   'Fecha Inicio', 'Tiene Avisos', 'Fecha Cancelación']

    for col, header in enumerate(est_headers, 1):
        cell = ws_est.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    from .models import EstablecimientoRIT
    establecimientos = EstablecimientoRIT.objects.select_related('rit').all()

    for row_num, est in enumerate(establecimientos, 2):
        data = [
            est.rit_id,
            est.rit.radicado if est.rit else '',
            est.nombre or '',
            est.direccion or '',
            est.telefono or '',
            est.fecha_inicio_actividades.strftime('%Y-%m-%d') if est.fecha_inicio_actividades else '',
            'Sí' if est.tiene_avisos_tableros else 'No',
            est.fecha_cancelacion.strftime('%Y-%m-%d') if est.fecha_cancelacion else '',
        ]
        for col, value in enumerate(data, 1):
            cell = ws_est.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(est_headers) + 1):
        ws_est.column_dimensions[get_column_letter(col)].width = 18

    # --- HOJA 3: Actividades Económicas ---
    ws_act = wb.create_sheet("Actividades")
    act_headers = ['RIT ID', 'Radicado', 'Código Actividad', 'Nombre Actividad', 'Tarifa', 'Base Gravable']

    for col, header in enumerate(act_headers, 1):
        cell = ws_act.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    from .models import ActividadEconomicaRIT
    actividades = ActividadEconomicaRIT.objects.select_related('rit', 'actividad').all()

    for row_num, act in enumerate(actividades, 2):
        data = [
            act.rit_id,
            act.rit.radicado if act.rit else '',
            act.actividad.codigo if act.actividad else '',
            act.actividad.nombre if act.actividad else '',
            float(act.actividad.tarifa) if act.actividad else 0,
            act.base_gravable_mensual or 0,
        ]
        for col, value in enumerate(data, 1):
            cell = ws_act.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(act_headers) + 1):
        ws_act.column_dimensions[get_column_letter(col)].width = 20

    # Guardar y enviar
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Reporte_RIT_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response


@login_required
def json_actividades_visita(request):
    from django.http import JsonResponse
    from django.db.models import Q
    q = request.GET.get('q', '').strip()
    qs = ActividadEconomica.objects.filter(activo=True).order_by('codigo')
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
    data = list(qs.values('codigo', 'nombre')[:60])
    return JsonResponse({'results': data})


@login_required
def json_municipios_visita(request):
    from django.http import JsonResponse
    q = request.GET.get('q', '').strip()
    qs = Municipio.objects.filter(activo=True).select_related('departamento').order_by('nombre')
    if q:
        qs = qs.filter(nombre__icontains=q)
    data = [{'nombre': m.nombre, 'departamento': m.departamento.nombre} for m in qs[:50]]
    return JsonResponse({'results': data})


@login_required
def nueva_visita_web(request):
    from api_movil.models import VisitaRIT, FotoVisita
    import uuid as _uuid

    es_func = request.user.groups.filter(name='FUNCIONARIO_CAMPO').exists() or request.user.is_superuser
    if not es_func:
        messages.error(request, 'No tienes permiso para registrar visitas de campo.')
        return redirect('home')

    if request.method == 'POST':
        tipo_visita    = request.POST.get('tipo_visita', 'atendida')
        es_no_atendida = tipo_visita == 'no_atendida'
        es_incompleta  = tipo_visita == 'incompleta'

        lat  = request.POST.get('latitud',      '').strip() or None
        lng  = request.POST.get('longitud',     '').strip() or None
        prec = request.POST.get('precision_gps','').strip() or None

        nombre_est  = request.POST.get('nombre_establecimiento', '').strip()
        nombre_prop = request.POST.get('nombre_propietario',     '').strip()

        visita = VisitaRIT(
            funcionario          = request.user,
            uuid_local           = str(_uuid.uuid4()),
            nombre_establecimiento = nombre_est or nombre_prop or '-',
            nombre_propietario   = nombre_prop,
            numero_documento     = request.POST.get('numero_documento', '').strip(),
            tipo_documento       = request.POST.get('tipo_documento', 'CC'),
            direccion            = request.POST.get('direccion_final', '').strip() or '-',
            municipio            = request.POST.get('municipio', '').strip(),
            telefono             = request.POST.get('telefono', '').strip(),
            correo               = request.POST.get('correo', '').strip(),
            actividad_economica  = request.POST.get('actividad_economica', '').strip(),
            descripcion_actividad= request.POST.get('descripcion_actividad', '').strip(),
            latitud              = lat,
            longitud             = lng,
            precision_gps        = prec,
            observaciones        = request.POST.get('observaciones', '').strip(),
            firma_contribuyente  = request.POST.get('firma_base64', ''),
            firma_tipo           = request.POST.get('firma_tipo', 'DIBUJO'),
            firma_funcionario    = request.POST.get('firma_funcionario_base64', ''),
            motivo_no_atencion   = request.POST.get('motivo_no_atencion', '') if es_no_atendida else '',
            motivo_descripcion   = request.POST.get('motivo_descripcion', '') if es_no_atendida else '',
            fecha_visita         = timezone.now(),
            estado               = 'no_atendida' if es_no_atendida else ('incompleta' if es_incompleta else 'sincronizado'),
            sincronizado_en      = timezone.now(),
        )
        visita.save()

        for i, foto in enumerate(request.FILES.getlist('fotos')):
            FotoVisita.objects.create(visita=visita, imagen=foto, orden=i)

        if es_incompleta:
            _vincular_usuario_visita_incompleta(visita)
        elif not es_no_atendida:
            # Visita atendida: crear/vincular contribuyente y generar RegistroRIT
            correo = visita.correo.strip().lower() if visita.correo else ''
            numero_documento = visita.numero_documento.strip()
            nombre = visita.nombre_propietario or correo

            contribuyente_user = None
            if correo:
                contribuyente_user = (
                    User.objects.filter(username=correo).first()
                    or User.objects.filter(email=correo).first()
                )
            if not contribuyente_user and numero_documento:
                from .models import PerfilContribuyente
                perfil_doc = PerfilContribuyente.objects.filter(
                    numero_documento=numero_documento
                ).select_related('user').first()
                if perfil_doc:
                    contribuyente_user = perfil_doc.user

            if not contribuyente_user and correo:
                temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                contribuyente_user = User.objects.create_user(
                    username=correo, email=correo,
                    password=temp_password, first_name=nombre,
                )
                try:
                    contribuyente_user.groups.add(Group.objects.get(name='CONTRIBUYENTE'))
                except Group.DoesNotExist:
                    pass
                try:
                    from .models import PerfilContribuyente
                    municipio_obj = Municipio.objects.filter(
                        nombre__iexact=visita.municipio, activo=True
                    ).first()
                    PerfilContribuyente.objects.create(
                        user=contribuyente_user,
                        nombre_razon_social=nombre,
                        tipo_documento=visita.tipo_documento or 'CC',
                        numero_documento=numero_documento,
                        correo_electronico=correo,
                        telefono=visita.telefono or '',
                        direccion_notificacion=visita.direccion or '',
                        municipio_notificacion=municipio_obj,
                        must_change_password=True,
                    )
                except Exception:
                    pass
                try:
                    proceso_rit = Proceso.objects.get(codigo='RIT')
                    AccesoProceso.objects.get_or_create(
                        user=contribuyente_user, proceso=proceso_rit,
                        defaults={'habilitado': True}
                    )
                except Proceso.DoesNotExist:
                    pass
                _enviar_emailjs(
                    django_settings.EMAILJS_TEMPLATE_CREDENCIALES, correo,
                    {
                        'to_name': nombre, 'usuario': correo,
                        'contrasena': temp_password,
                        'portal_url': 'https://segovia.portalterritorial.com.co',
                    },
                )

            if contribuyente_user:
                visita.contribuyente = contribuyente_user
                visita.save(update_fields=['contribuyente'])

                try:
                    from .models import RegistroRIT, EstablecimientoRIT, ActividadEconomicaRIT
                    rit_existente = RegistroRIT.objects.filter(
                        user=contribuyente_user,
                        opcion_uso='INSCRIPCION',
                        estado__in=('ACTIVO', 'PENDIENTE_FIRMA'),
                    ).first()
                    if rit_existente:
                        visita.registro_rit = rit_existente
                        visita.save(update_fields=['registro_rit'])
                    else:
                        municipio_obj = Municipio.objects.filter(
                            nombre__iexact=visita.municipio, activo=True
                        ).first() if visita.municipio else None
                        rit = RegistroRIT.objects.create(
                            user=contribuyente_user,
                            radicado=RegistroRIT.generar_radicado(),
                            opcion_uso='INSCRIPCION',
                            estado='ACTIVO',
                            nombre_razon_social=nombre,
                            tipo_documento=visita.tipo_documento or 'CC',
                            numero_documento=visita.numero_documento or '',
                            correo_electronico=correo,
                            telefono=visita.telefono or '',
                            direccion_notificacion=visita.direccion or '',
                            municipio_notificacion=municipio_obj,
                            firma_otp_verificada=True,
                        )
                        if visita.nombre_establecimiento:
                            EstablecimientoRIT.objects.create(
                                rit=rit,
                                nombre=visita.nombre_establecimiento,
                                direccion=visita.direccion or '-',
                                telefono=visita.telefono or '',
                                fecha_inicio_actividades=visita.fecha_visita.date(),
                            )
                        if visita.actividad_economica:
                            act_obj = ActividadEconomica.objects.filter(
                                codigo=visita.actividad_economica, activo=True
                            ).first()
                            if act_obj:
                                ActividadEconomicaRIT.objects.create(
                                    rit=rit, actividad=act_obj, base_gravable_mensual=0,
                                )
                        visita.registro_rit = rit
                        visita.save(update_fields=['registro_rit'])
                except Exception:
                    pass

        messages.success(request, f'Visita "{visita.nombre_establecimiento}" registrada correctamente.')
        return redirect('mis_visitas')

    return render(request, 'nueva_visita_web.html', {})


@login_required
def mis_visitas(request):
    """Panel web del funcionario/revisor: lista visitas de campo."""
    from api_movil.models import VisitaRIT
    from django.core.paginator import Paginator
    from django.db.models import Q, Count

    es_revisor = request.user.groups.filter(name__in=['ADMIN', 'REVISOR']).exists() or request.user.is_superuser
    qs_base = VisitaRIT.objects.all() if es_revisor else VisitaRIT.objects.filter(funcionario=request.user)

    q             = request.GET.get('q', '').strip()
    estado_filtro = request.GET.get('estado', '').strip()
    desde         = request.GET.get('desde', '').strip()
    hasta         = request.GET.get('hasta', '').strip()
    func_filtro   = request.GET.get('funcionario', '').strip()

    qs = qs_base
    if q:
        qs = qs.filter(Q(nombre_establecimiento__icontains=q) | Q(direccion__icontains=q))
    if estado_filtro:
        qs = qs.filter(estado=estado_filtro)
    if desde:
        qs = qs.filter(fecha_visita__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha_visita__date__lte=hasta)
    if func_filtro and es_revisor:
        qs = qs.filter(funcionario__id=func_filtro)

    qs = qs.order_by('-fecha_visita').prefetch_related('fotos').select_related('funcionario')

    total         = qs.count()
    sincronizadas = qs.filter(estado='sincronizado').count()
    no_atendidas  = qs.filter(estado='no_atendida').count()
    incompletas   = qs.filter(estado='incompleta').count()

    # Stats por funcionario (solo para REVISOR/ADMIN)
    stats_funcionarios = None
    funcionarios_lista = None
    if es_revisor:
        stats_funcionarios = (
            qs_base
            .values('funcionario__id', 'funcionario__username',
                    'funcionario__first_name', 'funcionario__last_name')
            .annotate(
                total=Count('id'),
                sincronizadas=Count('id', filter=Q(estado='sincronizado')),
                incompletas=Count('id', filter=Q(estado='incompleta')),
                no_atendidas=Count('id', filter=Q(estado='no_atendida')),
                pendientes=Count('id', filter=Q(estado='pendiente')),
            )
            .order_by('-total')
        )
        funcionarios_lista = [
            {'id': s['funcionario__id'],
             'nombre': (f"{s['funcionario__first_name']} {s['funcionario__last_name']}".strip()
                        or s['funcionario__username'])}
            for s in stats_funcionarios
        ]

    paginator = Paginator(qs, 12)
    visitas   = paginator.get_page(request.GET.get('page'))

    return render(request, 'mis_visitas.html', {
        'visitas':             visitas,
        'total':               total,
        'sincronizadas':       sincronizadas,
        'no_atendidas':        no_atendidas,
        'incompletas':         incompletas,
        'q':                   q,
        'estado_filtro':       estado_filtro,
        'desde':               desde,
        'hasta':               hasta,
        'func_filtro':         func_filtro,
        'es_revisor':          es_revisor,
        'stats_funcionarios':  stats_funcionarios,
        'funcionarios_lista':  funcionarios_lista,
    })


@login_required
def exportar_visitas_excel(request):
    """Exporta las visitas del funcionario (o todas si es admin/revisor) a Excel."""
    from api_movil.models import VisitaRIT as VisitaRITMovil
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        return HttpResponse('openpyxl no está instalado en el servidor.', status=500)

    is_admin_user   = is_admin(request.user)
    is_revisor_user = is_revisor(request.user)

    if is_admin_user or is_revisor_user:
        visitas = VisitaRITMovil.objects.select_related('funcionario', 'registro_rit').order_by('-fecha_visita')
    else:
        visitas = VisitaRITMovil.objects.filter(
            funcionario=request.user
        ).select_related('funcionario', 'registro_rit').order_by('-fecha_visita')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Visitas RIT'

    header_fill = PatternFill(start_color='0D6EFD', end_color='0D6EFD', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)

    headers = [
        'ID', 'UUID Local', 'Fecha Visita', 'Funcionario', 'Estado',
        'Nombre Propietario', 'Tipo Doc.', 'Nº Documento', 'Correo', 'Teléfono',
        'Nombre Establecimiento', 'Dirección', 'Municipio',
        'Cód. Actividad', 'Descripción Actividad',
        'Latitud', 'Longitud', 'Precisión GPS (m)',
        'Observaciones', 'Motivo No Atención', 'Descripción Motivo',
        'Radicado RIT', 'Sincronizado En',
    ]

    ws.row_dimensions[1].height = 30
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    for v in visitas:
        ws.append([
            v.id,
            v.uuid_local,
            v.fecha_visita.strftime('%Y-%m-%d %H:%M') if v.fecha_visita else '',
            v.funcionario.get_full_name() or v.funcionario.username,
            v.get_estado_display(),
            v.nombre_propietario,
            v.tipo_documento,
            v.numero_documento,
            v.correo,
            v.telefono,
            v.nombre_establecimiento,
            v.direccion,
            v.municipio,
            v.actividad_economica,
            v.descripcion_actividad,
            float(v.latitud) if v.latitud else '',
            float(v.longitud) if v.longitud else '',
            v.precision_gps or '',
            v.observaciones,
            v.get_motivo_no_atencion_display() if v.motivo_no_atencion else '',
            v.motivo_descripcion,
            v.registro_rit.radicado if v.registro_rit else '',
            v.sincronizado_en.strftime('%Y-%m-%d %H:%M') if v.sincronizado_en else '',
        ])

    col_widths = [6, 22, 16, 20, 14, 25, 10, 16, 30, 14, 30, 30, 16, 12, 35, 12, 12, 14, 40, 18, 30, 16, 16]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fecha = timezone.now().strftime('%Y%m%d')
    response = HttpResponse(
        buffer,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Reporte_Visitas_{fecha}.xlsx"'
    return response


@login_required
@user_passes_test(is_admin)
def exportar_excel_ica(request):
    """Exporta todas las declaraciones ICA a Excel con múltiples hojas."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        messages.error(request, 'Se requiere openpyxl para exportar a Excel. Instálelo con: pip install openpyxl')
        return redirect('admin_reportes')

    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='27AE60', end_color='27AE60', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # --- HOJA 1: ICA Principal ---
    ws_ica = wb.active
    ws_ica.title = "Declaraciones ICA"

    ica_headers = [
        'ID', 'Fecha', 'Año Gravable', 'Opción Uso', 'Municipio', 'Departamento',
        'Nombre/Razón Social', 'Tipo Doc', 'Número Doc', 'DV', 'Dirección',
        'Teléfono', 'Correo', 'N° Establecimientos', 'Clasificación',
        'Tipo Persona', 'Tipo Jurídica',
        # Base gravable
        'B8 Total Ingresos País', 'B9 Menos Ingresos Fuera', 'B11 Devoluciones',
        'B12 Exportaciones', 'B13 Excluidas', 'B14 Exentas',
        # Liquidación
        'Valor ICA', 'Avisos Tableros', 'Sobretasa Bomberil',
        'D22 Sector Financiero', 'D24 Sobretasa Seguridad', 'D26 Exención',
        'D27 Retenciones', 'D28 Autorretenciones', 'D29 Anticipo Anterior',
        'D30 Anticipo Siguiente', 'D31 Sanciones', 'D32 Saldo Favor Anterior',
        'E36 Descuento Pronto Pago', 'E37 Intereses Mora',
        'Total a Pagar', 'Usuario'
    ]

    for col, header in enumerate(ica_headers, 1):
        cell = ws_ica.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', wrap_text=True)

    icas = DeclaracionICA.objects.select_related('user', 'municipio', 'departamento').order_by('-fecha_diligenciamiento')
    _fd2 = _parse_fecha(request.GET.get('fecha_desde', ''))
    _fh2 = _parse_fecha(request.GET.get('fecha_hasta', ''))
    if _fd2:
        icas = icas.filter(fecha_diligenciamiento__date__gte=_fd2)
    if _fh2:
        icas = icas.filter(fecha_diligenciamiento__date__lte=_fh2)

    for row_num, ica in enumerate(icas, 2):
        data = [
            ica.id,
            ica.fecha_diligenciamiento.strftime('%Y-%m-%d %H:%M') if ica.fecha_diligenciamiento else '',
            ica.anio_gravable,
            ica.get_opcion_uso_display(),
            str(ica.municipio) if ica.municipio else '',
            str(ica.departamento) if ica.departamento else '',
            ica.nombre_razon_social or '',
            ica.get_tipo_documento_display() if ica.tipo_documento else '',
            ica.numero_documento or '',
            ica.dv or '',
            ica.direccion_notificacion or '',
            ica.telefono or '',
            ica.correo_electronico or '',
            ica.numero_establecimientos or 0,
            ica.get_clasificacion_contribuyente_display() if ica.clasificacion_contribuyente else '',
            ica.get_tipo_persona_display() if ica.tipo_persona else '',
            ica.get_tipo_juridica_display() if ica.tipo_juridica else '',
            # Base gravable
            ica.b8_total_ingresos_pais or 0,
            ica.b9_menos_ingresos_fuera_municipio or 0,
            ica.b11_menos_devoluciones_rebajas_descuentos or 0,
            ica.b12_menos_exportaciones_venta_activos_fijos or 0,
            ica.b13_menos_otras_actividades_excluidas_no_sujetas or 0,
            ica.b14_menos_actividades_exentas_por_acuerdo or 0,
            # Liquidación
            ica.valor_ica or 0,
            ica.avisos_tableros or 0,
            ica.sobretasa_bomberil or 0,
            ica.d22_sector_financiero or 0,
            ica.d24_sobretasa_seguridad or 0,
            ica.d26_exencion or 0,
            ica.d27_retenciones or 0,
            ica.d28_autorretenciones or 0,
            ica.d29_anticipo_anterior or 0,
            ica.d30_anticipo_siguiente or 0,
            ica.d31_valor or 0,
            ica.d32_saldo_favor_anterior or 0,
            ica.e36_descuento_pronto_pago or 0,
            ica.e37_intereses_mora or 0,
            ica.total_a_pagar or 0,
            ica.user.username if ica.user else '',
        ]
        for col, value in enumerate(data, 1):
            cell = ws_ica.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(ica_headers) + 1):
        ws_ica.column_dimensions[get_column_letter(col)].width = 15

    # --- HOJA 2: Actividades por Declaración ---
    ws_act = wb.create_sheet("Actividades ICA")
    act_headers = ['ICA ID', 'Año Gravable', 'Documento', 'Código Actividad',
                   'Nombre Actividad', 'Ingresos Gravados', 'Tarifa Aplicada', 'Impuesto']

    for col, header in enumerate(act_headers, 1):
        cell = ws_act.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    from .models import DeclaracionActividad
    actividades = DeclaracionActividad.objects.select_related('declaracion', 'actividad').all()

    for row_num, act in enumerate(actividades, 2):
        data = [
            act.declaracion_id,
            act.declaracion.anio_gravable if act.declaracion else '',
            act.declaracion.numero_documento if act.declaracion else '',
            act.actividad.codigo if act.actividad else '',
            act.actividad.nombre if act.actividad else '',
            act.ingresos_gravados or 0,
            float(act.tarifa_aplicada) if act.tarifa_aplicada else 0,
            act.impuesto or 0,
        ]
        for col, value in enumerate(data, 1):
            cell = ws_act.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(act_headers) + 1):
        ws_act.column_dimensions[get_column_letter(col)].width = 18

    # Guardar y enviar
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Reporte_ICA_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response


def _parse_fecha(valor):
    """Convierte string YYYY-MM-DD a date, o None si falla."""
    if not valor:
        return None
    try:
        from datetime import date
        return date.fromisoformat(valor)
    except ValueError:
        return None


@login_required
@user_passes_test(is_admin)
def exportar_csv_rit(request):
    """Exporta RITs a CSV con filtro opcional de rango de fechas."""
    import csv

    fecha_desde = _parse_fecha(request.GET.get('fecha_desde', ''))
    fecha_hasta = _parse_fecha(request.GET.get('fecha_hasta', ''))
    sufijo = timezone.now().strftime("%Y%m%d")

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Reporte_RIT_{sufijo}.csv"'
    response.write('\ufeff')  # BOM para Excel

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Radicado', 'Fecha', 'Opción Uso', 'Estado', 'Clase Contribuyente',
        'Nombre/Razón Social', 'Tipo Doc', 'Número Doc', 'Municipio', 'Teléfono',
        'Correo', 'N° Establecimientos', 'Usuario'
    ])

    rits = RegistroRIT.objects.select_related('user', 'municipio_notificacion').order_by('-fecha')
    if fecha_desde:
        rits = rits.filter(fecha__date__gte=fecha_desde)
    if fecha_hasta:
        rits = rits.filter(fecha__date__lte=fecha_hasta)

    for rit in rits:
        writer.writerow([
            rit.id,
            rit.radicado or '',
            rit.fecha.strftime('%Y-%m-%d %H:%M') if rit.fecha else '',
            rit.get_opcion_uso_display(),
            rit.get_estado_display(),
            rit.get_clase_contribuyente_display(),
            rit.nombre_razon_social or '',
            rit.get_tipo_documento_display(),
            rit.numero_documento or '',
            str(rit.municipio_notificacion) if rit.municipio_notificacion else '',
            rit.telefono or '',
            rit.correo_electronico or '',
            rit.numero_establecimientos or 0,
            rit.user.username if rit.user else '',
        ])

    return response


@login_required
@user_passes_test(is_admin)
def exportar_csv_ica(request):
    """Exporta ICA a CSV con filtro opcional de rango de fechas."""
    import csv

    fecha_desde = _parse_fecha(request.GET.get('fecha_desde', ''))
    fecha_hasta = _parse_fecha(request.GET.get('fecha_hasta', ''))
    sufijo = timezone.now().strftime("%Y%m%d")

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Reporte_ICA_{sufijo}.csv"'
    response.write('\ufeff')  # BOM para Excel

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Fecha', 'Año Gravable', 'Opción Uso', 'Municipio', 'Nombre/Razón Social',
        'Tipo Doc', 'Número Doc', 'Valor ICA', 'Avisos Tableros (15%)',
        'Sobretasa Bomberil (5%)', 'D22 Sector Financiero', 'D24 Sobretasa Seguridad',
        'D26 Exención', 'D27 Retenciones', 'D28 Autorretenciones',
        'D29 Anticipo Anterior', 'D30 Anticipo Siguiente', 'D31 Sanciones',
        'D32 Saldo Favor Anterior', 'E36 Descuento Pronto Pago', 'E37 Intereses Mora',
        'Total a Pagar', 'Radicado', 'Firma Verificada', 'Usuario'
    ])

    icas = DeclaracionICA.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')
    if fecha_desde:
        icas = icas.filter(fecha_diligenciamiento__date__gte=fecha_desde)
    if fecha_hasta:
        icas = icas.filter(fecha_diligenciamiento__date__lte=fecha_hasta)

    for ica in icas:
        radicado = f"ICA-{ica.anio_gravable}-{ica.id:06d}"
        writer.writerow([
            ica.id,
            ica.fecha_diligenciamiento.strftime('%Y-%m-%d %H:%M') if ica.fecha_diligenciamiento else '',
            ica.anio_gravable,
            ica.get_opcion_uso_display(),
            str(ica.municipio) if ica.municipio else '',
            ica.nombre_razon_social or '',
            ica.get_tipo_documento_display() if hasattr(ica, 'get_tipo_documento_display') else ica.tipo_documento or '',
            ica.numero_documento or '',
            ica.valor_ica or 0,
            ica.avisos_tableros or 0,
            ica.sobretasa_bomberil or 0,
            ica.d22_sector_financiero or 0,
            ica.d24_sobretasa_seguridad or 0,
            ica.d26_exencion or 0,
            ica.d27_retenciones or 0,
            ica.d28_autorretenciones or 0,
            ica.d29_anticipo_anterior or 0,
            ica.d30_anticipo_siguiente or 0,
            ica.d31_valor or 0,
            ica.d32_saldo_favor_anterior or 0,
            ica.e36_descuento_pronto_pago or 0,
            ica.e37_intereses_mora or 0,
            ica.total_a_pagar or 0,
            radicado,
            'Sí' if ica.firma_otp_verificada else 'No',
            ica.user.username if ica.user else '',
        ])


@login_required
@user_passes_test(is_admin)
def exportar_excel_auto(request):
    """Exporta todas las declaraciones de Autorreteción a Excel."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        messages.error(request, 'Se requiere openpyxl para exportar a Excel.')
        return redirect('admin_reportes')

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='E67E22', end_color='E67E22', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'),  bottom=Side(style='thin'),
    )

    ws = wb.active
    ws.title = "Declaraciones AUTO"

    headers = [
        'ID', 'Fecha', 'Año Gravable', 'Bimestre', 'Opción Uso', 'Municipio', 'Departamento',
        'Nombre/Razón Social', 'Tipo Doc', 'Número Doc', 'DV',
        'Dirección', 'Teléfono', 'Correo', 'Clasificación', 'Tipo Persona',
        'Total Autorretención', 'Sanciones', 'Intereses Mora',
        'Autorretención en Exceso', 'Subtotal', 'Total a Pagar',
        'Firma Verificada', 'Usuario',
    ]

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', wrap_text=True)

    autos = DeclaracionAutoRetencion.objects.select_related('user', 'municipio', 'departamento').order_by('-fecha_diligenciamiento')
    fd = _parse_fecha(request.GET.get('fecha_desde', ''))
    fh = _parse_fecha(request.GET.get('fecha_hasta', ''))
    if fd:
        autos = autos.filter(fecha_diligenciamiento__date__gte=fd)
    if fh:
        autos = autos.filter(fecha_diligenciamiento__date__lte=fh)

    for row_num, a in enumerate(autos, 2):
        data = [
            a.id,
            a.fecha_diligenciamiento.strftime('%Y-%m-%d %H:%M') if a.fecha_diligenciamiento else '',
            a.anio_gravable,
            a.get_bimestre_display(),
            a.get_opcion_uso_display(),
            str(a.municipio) if a.municipio else '',
            str(a.departamento) if a.departamento else '',
            a.nombre_razon_social or '',
            a.get_tipo_documento_display() if a.tipo_documento else '',
            a.numero_documento or '',
            a.dv or '',
            a.direccion_notificacion or '',
            a.telefono or '',
            a.correo_electronico or '',
            a.get_clasificacion_contribuyente_display() if a.clasificacion_contribuyente else '',
            a.get_tipo_persona_display() if a.tipo_persona else '',
            a.total_valor_autorretencion or 0,
            a.sanciones or 0,
            a.intereses_mora or 0,
            a.autorretencion_exceso or 0,
            a.subtotal or 0,
            a.total_a_pagar or 0,
            'Sí' if a.firma_otp_verificada else 'No',
            a.user.username if a.user else '',
        ]
        for col, value in enumerate(data, 1):
            cell = ws.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 15

    # Hoja 2: actividades
    ws2 = wb.create_sheet("Actividades AUTO")
    act_headers = ['AUTO ID', 'Año Gravable', 'Bimestre', 'Documento',
                   'Código Actividad', 'Nombre Actividad',
                   'Ingreso Total Bimestre', 'Ingreso Excluido', 'Ingreso Gravable',
                   'Tarifa Aplicada', 'Valor Autorretención']
    for col, h in enumerate(act_headers, 1):
        cell = ws2.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    for row_num, act in enumerate(DeclaracionActividadAuto.objects.select_related('declaracion', 'actividad').all(), 2):
        data = [
            act.declaracion_id,
            act.declaracion.anio_gravable if act.declaracion else '',
            act.declaracion.get_bimestre_display() if act.declaracion else '',
            act.declaracion.numero_documento if act.declaracion else '',
            act.actividad.codigo if act.actividad else '',
            act.actividad.nombre if act.actividad else '',
            act.ingreso_total_bimestre or 0,
            act.ingreso_excluido or 0,
            act.ingreso_gravable or 0,
            float(act.tarifa_aplicada) if act.tarifa_aplicada else 0,
            act.valor_autorretencion or 0,
        ]
        for col, value in enumerate(data, 1):
            cell = ws2.cell(row=row_num, column=col, value=value)
            cell.border = thin_border

    for col in range(1, len(act_headers) + 1):
        ws2.column_dimensions[get_column_letter(col)].width = 18

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="Reporte_AUTO_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response


@login_required
@user_passes_test(is_admin)
def exportar_csv_auto(request):
    """Exporta Autorreteción a CSV."""
    import csv

    fd = _parse_fecha(request.GET.get('fecha_desde', ''))
    fh = _parse_fecha(request.GET.get('fecha_hasta', ''))

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Reporte_AUTO_{timezone.now().strftime("%Y%m%d")}.csv"'
    response.write('﻿')

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Fecha', 'Año Gravable', 'Bimestre', 'Opción Uso', 'Municipio',
        'Nombre/Razón Social', 'Tipo Doc', 'Número Doc',
        'Total Autorretención', 'Sanciones', 'Intereses Mora',
        'Autorretención en Exceso', 'Subtotal', 'Total a Pagar',
        'Firma Verificada', 'Usuario',
    ])

    autos = DeclaracionAutoRetencion.objects.select_related('user', 'municipio').order_by('-fecha_diligenciamiento')
    if fd:
        autos = autos.filter(fecha_diligenciamiento__date__gte=fd)
    if fh:
        autos = autos.filter(fecha_diligenciamiento__date__lte=fh)

    for a in autos:
        writer.writerow([
            a.id,
            a.fecha_diligenciamiento.strftime('%Y-%m-%d %H:%M') if a.fecha_diligenciamiento else '',
            a.anio_gravable,
            a.get_bimestre_display(),
            a.get_opcion_uso_display(),
            str(a.municipio) if a.municipio else '',
            a.nombre_razon_social or '',
            a.get_tipo_documento_display() if a.tipo_documento else '',
            a.numero_documento or '',
            a.total_valor_autorretencion or 0,
            a.sanciones or 0,
            a.intereses_mora or 0,
            a.autorretencion_exceso or 0,
            a.subtotal or 0,
            a.total_a_pagar or 0,
            'Sí' if a.firma_otp_verificada else 'No',
            a.user.username if a.user else '',
        ])

    return response


# ─────────────────────────────────────────────────────────────────────────────
# PDF ACTA DE VISITA — App Móvil
# ─────────────────────────────────────────────────────────────────────────────

def _autenticar_jwt_o_sesion(request):
    """Autentica usando Bearer JWT (app móvil) o sesión Django (web)."""
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        from rest_framework_simplejwt.authentication import JWTAuthentication
        try:
            jwt_auth = JWTAuthentication()
            user, _ = jwt_auth.authenticate(request)
            if user and user.is_active:
                return user
        except Exception:
            pass
    if request.user.is_authenticated:
        return request.user
    return None


def generar_pdf_visita_movil(request, visita_id):
    """Genera el Acta de Visita de Campo a partir de un registro de la app móvil."""
    import qrcode
    from api_movil.models import VisitaRIT as VisitaRITMovil

    user = _autenticar_jwt_o_sesion(request)
    if user is None:
        from django.http import HttpResponse as _HR
        return _HR('No autorizado', status=401)

    visita = get_object_or_404(VisitaRITMovil, id=visita_id)

    request.user = user  # para que is_admin/is_revisor funcionen correctamente
    if not (is_admin(user) or is_revisor(user) or visita.funcionario == user or visita.contribuyente == user):
        messages.error(request, 'No tienes permiso para ver este documento.')
        return redirect('tasks_completed')

    config = get_pdf_config()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.4 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )
    styles = get_pdf_styles(config)
    elements = []

    # ── Encabezado ──────────────────────────────────────────────────────────
    numero_acta = f"VISITA-{visita.id:05d}"
    es_no_atendida = visita.estado == 'no_atendida'
    titulo_acta = "ACTA DE VISITA NO ATENDIDA — RIT" if es_no_atendida else "ACTA DE VISITA DE CAMPO — RIT"
    extra_info = {
        'Fecha visita': visita.fecha_visita.strftime('%Y-%m-%d %H:%M'),
        'Funcionario':  visita.funcionario.get_full_name() or visita.funcionario.username,
        'Estado':       visita.get_estado_display(),
    }
    elements.extend(get_pdf_header(
        styles,
        titulo_acta,
        numero_acta,
        config,
        extra_info=extra_info,
    ))

    # ── QR ──────────────────────────────────────────────────────────────────
    # Para visita no atendida el QR apunta al formulario de registro pre-llenado
    import urllib.parse as _up
    if es_no_atendida:
        params = {}
        if numero_acta:    params['ref']    = numero_acta
        if visita.nombre_establecimiento: params['est'] = visita.nombre_establecimiento
        if visita.direccion:              params['dir'] = visita.direccion
        if visita.municipio:              params['mun'] = visita.municipio
        if visita.actividad_economica:    params['act'] = visita.actividad_economica
        if visita.nombre_propietario:     params['nombre'] = visita.nombre_propietario
        signup_url = 'https://segovia.portalterritorial.com.co/signup/?' + _up.urlencode(params)
        qr_data = signup_url
    elif visita.registro_rit_id:
        # QR apunta al PDF público del RIT (sin login, token firmado)
        _tok = _rit_public_token(visita.registro_rit_id)
        qr_data = f"https://segovia.portalterritorial.com.co/pdf/rit/{visita.registro_rit_id}/pub/{_tok}/"
    else:
        qr_data = (
            f"ACTA: {numero_acta}\n"
            f"Fecha: {visita.fecha_visita.strftime('%Y-%m-%d %H:%M')}\n"
            f"Establecimiento: {visita.nombre_establecimiento}\n"
            f"Propietario: {visita.nombre_propietario}\n"
            f"Doc: {visita.tipo_documento} {visita.numero_documento}\n"
            f"Municipio: {visita.municipio}\n"
            f"Actividad: {visita.actividad_economica} {visita.descripcion_actividad}\n"
            f"GPS: {visita.latitud},{visita.longitud}\n"
            f"Funcionario: {visita.funcionario.username}"
        )
    qr_img = qrcode.make(qr_data)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_rl = Image(qr_buf, width=1.4 * inch, height=1.4 * inch)

    acta_info_data = [
        [Paragraph(f'<b>N° ACTA</b>', ParagraphStyle('ai1', alignment=TA_CENTER, fontSize=8, textColor=colors.white))],
        [Paragraph(f'<b>{numero_acta}</b>', ParagraphStyle('ai2', alignment=TA_CENTER, fontSize=13, textColor=colors.white, fontName='Helvetica-Bold'))],
        [Paragraph(f'<font size="7">{visita.fecha_visita.strftime("%Y-%m-%d %H:%M")}</font>', ParagraphStyle('ai3', alignment=TA_CENTER, fontSize=7, textColor=colors.HexColor('#c8e6c9')))],
    ]
    acta_table = Table(acta_info_data, colWidths=[2.5 * inch])
    acta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(config['color_primario'])),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 10),
        ('BOX', (0, 0), (-1, -1), 2, colors.HexColor('#004d26')),
        ('ROUNDEDCORNERS', [4, 4, 4, 4]),
    ]))

    qr_row = Table([[acta_table, '', qr_rl]], colWidths=[2.5 * inch, 3.5 * inch, 1.5 * inch])
    qr_row.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(qr_row)
    elements.append(Spacer(1, 0.12 * inch))

    col_header = colors.HexColor(config['color_secundario'])
    tbl_style_base = [
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#dee2e6')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
    ]

    # ── A. Datos del contribuyente ───────────────────────────────────────────
    elements.append(Paragraph("A. DATOS DEL CONTRIBUYENTE", styles['PDF_Section']))
    data_a = [
        ['Nombre / Razón social:', visita.nombre_propietario or '-',
         'Tipo doc.:', f"{visita.tipo_documento} {visita.numero_documento}".strip() or '-'],
        ['Dirección:', visita.direccion or '-',
         'Municipio:', visita.municipio or '-'],
        ['Teléfono:', visita.telefono or '-',
         'Correo:', visita.correo or '-'],
    ]
    t = Table(data_a, colWidths=[1.4 * inch, 2.5 * inch, 1.2 * inch, 2.4 * inch])
    t.setStyle(TableStyle(tbl_style_base))
    elements.append(t)
    elements.append(Spacer(1, 0.08 * inch))

    # ── B. Datos del establecimiento ─────────────────────────────────────────
    elements.append(Paragraph("B. DATOS DEL ESTABLECIMIENTO", styles['PDF_Section']))
    data_b = [
        ['Nombre establecimiento:', visita.nombre_establecimiento or '-', '', ''],
        ['Actividad económica:',
         f"{visita.actividad_economica} — {visita.descripcion_actividad}".strip(' — ') or '-',
         '', ''],
    ]
    t2 = Table(data_b, colWidths=[1.6 * inch, 3.0 * inch, 1.0 * inch, 1.9 * inch])
    t2.setStyle(TableStyle(tbl_style_base + [
        ('SPAN', (1, 0), (3, 0)),
        ('SPAN', (1, 1), (3, 1)),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 0.08 * inch))

    # ── C. Datos del registro RIT (solo visita atendida) ────────────────────
    if not es_no_atendida:
        elements.append(Paragraph("C. DATOS DEL REGISTRO RIT", styles['PDF_Section']))

        from api_movil.models import VisitaRIT as _VM
        opcion_uso_val   = getattr(visita, 'opcion_uso', None)   or 'INSCRIPCION'
        clase_contrib    = getattr(visita, 'clase_contribuyente', None) or '-'
        es_retenedor     = getattr(visita, 'es_retenedor', None)
        es_autorreten    = getattr(visita, 'es_autorretenedor', None)
        tipo_persona     = getattr(visita, 'tipo_persona', None) or '-'
        num_establ       = getattr(visita, 'num_establecimientos', None) or '1'

        data_c = [
            ['Opción de uso:', opcion_uso_val,     'Tipo persona:', tipo_persona],
            ['Retenedor ICA:', 'Sí' if es_retenedor else 'No',
             'Autorretenedor:', 'Sí' if es_autorreten else 'No'],
            ['N° establecimientos:', str(num_establ), '', ''],
        ]
        t3 = Table(data_c, colWidths=[1.6 * inch, 2.0 * inch, 1.4 * inch, 2.5 * inch])
        t3.setStyle(TableStyle(tbl_style_base))
        elements.append(t3)
        elements.append(Spacer(1, 0.08 * inch))

    # ── D. Ubicación GPS ────────────────────────────────────────────────────
    elements.append(Paragraph("D. UBICACIÓN GPS", styles['PDF_Section']))
    if visita.latitud and visita.longitud:
        lat  = float(visita.latitud)
        lon  = float(visita.longitud)
        prec = f"{visita.precision_gps:.0f} m" if visita.precision_gps else 'N/D'
        maps_url = f"https://maps.google.com/?q={lat},{lon}"
        data_d = [
            ['Latitud:', f"{lat:.6f}", 'Longitud:', f"{lon:.6f}"],
            ['Precisión GPS:', prec, 'Enlace mapa:', maps_url],
        ]
    else:
        data_d = [['Coordenadas GPS:', 'No capturadas', '', '']]
    t4 = Table(data_d, colWidths=[1.2 * inch, 2.3 * inch, 1.2 * inch, 2.8 * inch])
    t4.setStyle(TableStyle(tbl_style_base + [
        ('FONTSIZE', (3, 1), (3, 1), 7),
        ('TEXTCOLOR', (3, 1), (3, 1), colors.HexColor(config['color_secundario'])),
    ]))
    elements.append(t4)
    elements.append(Spacer(1, 0.08 * inch))

    # ── E. Observaciones (solo visita atendida) ──────────────────────────────
    if not es_no_atendida and visita.observaciones:
        elements.append(Paragraph("E. OBSERVACIONES DEL FUNCIONARIO", styles['PDF_Section']))
        elements.append(Paragraph(
            visita.observaciones,
            ParagraphStyle('Obs', fontSize=9, leading=12, leftIndent=6, spaceBefore=4, spaceAfter=4,
                           textColor=colors.HexColor('#2c3e50'))
        ))
        elements.append(Spacer(1, 0.08 * inch))

    # ── F. Datos del funcionario (solo visita atendida) ──────────────────────
    if not es_no_atendida:
        elements.append(Paragraph("F. DATOS DEL FUNCIONARIO", styles['PDF_Section']))
        try:
            perfil = visita.funcionario.perfil_funcionario
            cargo      = perfil.cargo or '-'
            dependencia = perfil.dependencia or '-'
        except Exception:
            cargo = dependencia = '-'

        data_f = [
            ['Nombre funcionario:', visita.funcionario.get_full_name() or visita.funcionario.username,
             'Usuario:', visita.funcionario.username],
            ['Cargo:', cargo, 'Dependencia:', dependencia],
            ['Fecha visita:', visita.fecha_visita.strftime('%d/%m/%Y %H:%M'),
             'Sincronizado:', 'Sí'],
        ]
        t5 = Table(data_f, colWidths=[1.4 * inch, 2.8 * inch, 1.1 * inch, 2.2 * inch])
        t5.setStyle(TableStyle(tbl_style_base))
        elements.append(t5)

    # ── Fotos del establecimiento ────────────────────────────────────────────
    fotos_qs = visita.fotos.order_by('orden').all()
    fotos_validas = []
    for foto in fotos_qs:
        try:
            if foto.imagen and foto.imagen.path:
                import os as _os
                if _os.path.exists(foto.imagen.path):
                    fotos_validas.append(foto)
        except Exception:
            pass

    if fotos_validas:
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph("FOTOS DEL ESTABLECIMIENTO", styles['PDF_Section']))
        elements.append(Spacer(1, 0.06 * inch))

        foto_w = 3.4 * inch
        foto_h = 2.5 * inch
        caption_style = ParagraphStyle('FotoCaption', alignment=TA_CENTER,
                                       fontSize=7, textColor=colors.HexColor('#666666'))
        # Agrupa en filas de 2
        for i in range(0, len(fotos_validas), 2):
            fila_celdas = []
            for foto in fotos_validas[i:i+2]:
                try:
                    img_obj = Image(foto.imagen.path, width=foto_w, height=foto_h)
                    img_obj.hAlign = 'CENTER'
                    desc = foto.descripcion or f'Foto {foto.orden + 1}'
                    celda = [img_obj, Paragraph(desc, caption_style)]
                except Exception:
                    celda = [Paragraph('(imagen no disponible)', caption_style)]
                fila_celdas.append(celda)
            # Rellena con celda vacía si hay número impar
            if len(fila_celdas) == 1:
                fila_celdas.append([Paragraph('', caption_style)])
            foto_row = Table([fila_celdas], colWidths=[3.75 * inch, 3.75 * inch])
            foto_row.setStyle(TableStyle([
                ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN',  (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(foto_row)
        elements.append(Spacer(1, 0.1 * inch))

    # ── Sección exclusiva para visita NO ATENDIDA ────────────────────────────
    if es_no_atendida:
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(Paragraph("G. MOTIVO DE NO ATENCIÓN", styles['PDF_Section']))
        motivo_label = dict(visita.MOTIVO_CHOICES).get(visita.motivo_no_atencion, visita.motivo_no_atencion or '-')
        data_motivo = [
            ['Motivo:', motivo_label],
        ]
        if visita.motivo_descripcion:
            data_motivo.append(['Descripción:', visita.motivo_descripcion])
        t_motivo = Table(data_motivo, colWidths=[1.4 * inch, 6.1 * inch])
        t_motivo.setStyle(TableStyle([
            ('FONTSIZE',    (0, 0), (-1, -1), 9),
            ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
            ('BACKGROUND',  (0, 0), (-1, -1), colors.HexColor('#fff3cd')),
            ('LINEBELOW',   (0, 0), (-1, -1), 0.4, colors.HexColor('#ffc107')),
            ('TOPPADDING',  (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t_motivo)
        elements.append(Spacer(1, 0.15 * inch))

        # Aviso QR para que el contribuyente se registre
        aviso_qr = Table([[
            Paragraph(
                '<b>Para el contribuyente / propietario:</b> Escanea el código QR '
                'para registrarte en el Portal Tributario con tus datos pre-llenados.',
                ParagraphStyle('AvisoQR', fontSize=9, leading=13,
                               textColor=colors.HexColor('#004085'))
            )
        ]], colWidths=[7.5 * inch])
        aviso_qr.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#cce5ff')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#004085')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(aviso_qr)
        elements.append(Spacer(1, 0.08 * inch))

        # Pie y fin para visita no atendida (sin sección de firmas)
        elements.extend(get_pdf_footer(styles, config))
        elements.append(Paragraph(
            f"<i>Acta generada electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} "
            f"— UUID: {visita.uuid_local}</i>",
            styles['PDF_Small']
        ))
        doc.build(elements)
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Acta_NoAtendida_{numero_acta}.pdf"'
        return response

    # ── G. Firmas (solo para visitas atendidas) ───────────────────────────────
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#bdc3c7'),
                               spaceBefore=4, spaceAfter=4))
    elements.append(Paragraph("G. FIRMAS", styles['PDF_Section']))
    elements.append(Spacer(1, 0.1 * inch))

    import base64 as _b64
    firma_style = ParagraphStyle('FirmaLabel', alignment=TA_CENTER, fontSize=8,
                                 textColor=colors.HexColor('#555555'))
    linea = '_' * 42

    # — Firma contribuyente —
    celda_contribuyente = []
    if visita.firma_contribuyente:
        try:
            firma_img_bytes = _b64.b64decode(visita.firma_contribuyente)
            firma_buf = io.BytesIO(firma_img_bytes)
            firma_img = Image(firma_buf, width=2.0 * inch, height=0.8 * inch)
            firma_img.hAlign = 'CENTER'
            celda_contribuyente.append(firma_img)
        except Exception:
            celda_contribuyente.append(Paragraph(linea, firma_style))
    else:
        celda_contribuyente.append(Spacer(1, 0.6 * inch))
        celda_contribuyente.append(Paragraph(linea, firma_style))

    celda_contribuyente.append(Paragraph(
        f"<b>Firma del Contribuyente</b><br/>"
        f"Nombre: {visita.nombre_propietario or '________________________________'}<br/>"
        f"Doc: {visita.tipo_documento} {visita.numero_documento}",
        firma_style
    ))

    tf = Table(
        [[celda_contribuyente]],
        colWidths=[7 * inch]
    )
    tf.setStyle(TableStyle([
        ('ALIGN',   (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',  (0, 0), (-1, -1), 'BOTTOM'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(tf)

    # ── Pie ──────────────────────────────────────────────────────────────────
    config_pie = dict(config)
    config_pie['mostrar_instructivo'] = False
    elements.extend(get_pdf_footer(styles, config_pie))
    elements.append(Paragraph(
        f"<i>Acta generada electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"— UUID: {visita.uuid_local}</i>",
        styles['PDF_Small']
    ))

    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    disp = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disp}; filename="Acta_Visita_{numero_acta}.pdf"'
    return response


def generar_pdf_formulario_rit_movil(request, visita_id):
    """Genera el Formulario RIT (estilo inscripción) a partir de un registro de la app móvil.
    Accesible por el contribuyente vinculado, el funcionario, admin y revisor.
    """
    import qrcode
    from api_movil.models import VisitaRIT as VisitaRITMovil

    user = _autenticar_jwt_o_sesion(request)
    if user is None:
        from django.http import HttpResponse as _HR
        return _HR('No autorizado', status=401)

    visita = get_object_or_404(VisitaRITMovil, id=visita_id)

    if not (is_admin(user) or is_revisor(user)
            or visita.funcionario == user
            or visita.contribuyente == user):
        messages.error(request, 'No tienes permiso para ver este documento.')
        return redirect('tasks_completed')

    config = get_pdf_config()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.4 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
    )
    styles = get_pdf_styles(config)
    elements = []

    # ── Encabezado ──────────────────────────────────────────────────────────────
    numero_acta = f"ACTA-{visita.id:05d}"
    extra_info = {
        'Fecha visita':  visita.fecha_visita.strftime('%d/%m/%Y %H:%M'),
        'Opción de uso': 'Inscripción RIT',
        'Estado':        visita.get_estado_display(),
    }
    elements.extend(get_pdf_header(
        styles,
        "ACTA DE VISITA — INSCRIPCIÓN RIT",
        numero_acta,
        config,
        extra_info=extra_info,
    ))

    # ── QR + caja de fecha ──────────────────────────────────────────────────────
    qr_data = (
        f"ACTA: {numero_acta}\n"
        f"Contribuyente: {visita.nombre_propietario}\n"
        f"Doc: {visita.tipo_documento} {visita.numero_documento}\n"
        f"Establecimiento: {visita.nombre_establecimiento}\n"
        f"Actividad: {visita.actividad_economica}\n"
        f"Municipio: {visita.municipio}\n"
        f"Fecha: {visita.fecha_visita.strftime('%Y-%m-%d')}"
    )
    qr_img = qrcode.make(qr_data)
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format='PNG')
    qr_buf.seek(0)
    qr_rl = Image(qr_buf, width=1.3 * inch, height=1.3 * inch)

    fecha_info_data = [
        [Paragraph('<b>FECHA DE VISITA</b>',
                   ParagraphStyle('fi1', alignment=TA_CENTER, fontSize=7, textColor=colors.white))],
        [Paragraph(f'<b>{visita.fecha_visita.strftime("%d/%m/%Y")}</b>',
                   ParagraphStyle('fi2', alignment=TA_CENTER, fontSize=13, textColor=colors.white, fontName='Helvetica-Bold'))],
        [Paragraph(visita.fecha_visita.strftime('%H:%M'),
                   ParagraphStyle('fi3', alignment=TA_CENTER, fontSize=10, textColor=colors.HexColor('#c8e6c9')))],
    ]
    fecha_table = Table(fecha_info_data, colWidths=[1.8 * inch])
    fecha_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(config['color_primario'])),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
        ('BOX',        (0, 0), (-1, -1), 2, colors.HexColor('#004d26')),
    ]))
    qr_row = Table([[fecha_table, '', qr_rl]], colWidths=[1.8 * inch, 4.2 * inch, 1.5 * inch])
    qr_row.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (0, 0), 'LEFT'),
        ('ALIGN',  (2, 0), (2, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(qr_row)
    elements.append(Spacer(1, 0.12 * inch))

    col_label = 'Helvetica-Bold'
    tbl_style = [
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING',  (0, 0), (-1, -1), 3),
        ('FONTNAME',    (0, 0), (0, -1), col_label),
        ('FONTNAME',    (2, 0), (2, -1), col_label),
        ('LINEBELOW',   (0, 0), (-1, -1), 0.4, colors.HexColor('#dee2e6')),
        ('BACKGROUND',  (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
    ]

    # ── A. Datos del registro ────────────────────────────────────────────────────
    elements.append(Paragraph("A. DATOS DEL REGISTRO", styles['PDF_Section']))
    data_a = [
        ['Opción de uso:', 'Inscripción RIT (Visita de Campo)',
         'Tipo registro:', 'App Móvil — Funcionario'],
        ['Estado:', visita.get_estado_display(),
         'Fuente:', 'Visita presencial'],
    ]
    t = Table(data_a, colWidths=[1.4 * inch, 2.6 * inch, 1.2 * inch, 2.3 * inch])
    t.setStyle(TableStyle(tbl_style))
    elements.append(t)
    elements.append(Spacer(1, 0.1 * inch))

    # ── B. Datos del contribuyente ───────────────────────────────────────────────
    elements.append(Paragraph("B. DATOS DEL CONTRIBUYENTE", styles['PDF_Section']))
    data_b = [
        ['Nombre / Razón social:', visita.nombre_propietario or '-'],
        ['Tipo y N° Documento:', f"{visita.tipo_documento} {visita.numero_documento}".strip() or '-'],
        ['Dirección:', visita.direccion or '-'],
        ['Municipio:', visita.municipio or '-'],
        ['Teléfono:', visita.telefono or '-'],
        ['Correo electrónico:', visita.correo or '-'],
    ]
    t2 = Table(data_b, colWidths=[2.0 * inch, 5.5 * inch])
    t2.setStyle(TableStyle([
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',  (0, 0), (-1, -1), 2),
        ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
        ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW',   (0, 0), (-1, -2), 0.5, colors.HexColor('#ecf0f1')),
        ('BACKGROUND',  (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 0.1 * inch))

    # ── C. Datos del establecimiento ─────────────────────────────────────────────
    elements.append(Paragraph("C. DATOS DEL ESTABLECIMIENTO", styles['PDF_Section']))
    data_c = [
        ['Nombre establecimiento:', visita.nombre_establecimiento or '-'],
        ['Código actividad econ.:', visita.actividad_economica or '-'],
        ['Descripción actividad:', visita.descripcion_actividad or '-'],
    ]
    t3 = Table(data_c, colWidths=[2.0 * inch, 5.5 * inch])
    t3.setStyle(TableStyle([
        ('FONTSIZE',    (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING',  (0, 0), (-1, -1), 2),
        ('FONTNAME',    (0, 0), (0, -1), 'Helvetica-Bold'),
        ('LINEBELOW',   (0, 0), (-1, -2), 0.5, colors.HexColor('#ecf0f1')),
        ('BACKGROUND',  (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
    ]))
    elements.append(t3)
    elements.append(Spacer(1, 0.1 * inch))

    # ── D. Ubicación GPS ─────────────────────────────────────────────────────────
    if visita.latitud and visita.longitud:
        elements.append(Paragraph("D. UBICACIÓN GPS DEL ESTABLECIMIENTO", styles['PDF_Section']))
        lat  = float(visita.latitud)
        lon  = float(visita.longitud)
        prec = f"{visita.precision_gps:.0f} m" if visita.precision_gps else 'N/D'
        data_d = [
            ['Latitud:', f"{lat:.6f}", 'Longitud:', f"{lon:.6f}"],
            ['Precisión GPS:', prec, 'Google Maps:', f"https://maps.google.com/?q={lat},{lon}"],
        ]
        t4 = Table(data_d, colWidths=[1.2 * inch, 2.3 * inch, 1.2 * inch, 2.8 * inch])
        t4.setStyle(TableStyle(tbl_style + [
            ('FONTSIZE', (3, 1), (3, 1), 7),
            ('TEXTCOLOR', (3, 1), (3, 1), colors.HexColor(config['color_secundario'])),
        ]))
        elements.append(t4)
        elements.append(Spacer(1, 0.1 * inch))

    # ── E. Observaciones ─────────────────────────────────────────────────────────
    if visita.observaciones:
        elements.append(Paragraph("E. OBSERVACIONES", styles['PDF_Section']))
        elements.append(Paragraph(
            visita.observaciones,
            ParagraphStyle('Obs2', fontSize=9, leading=12, leftIndent=6,
                           spaceBefore=4, spaceAfter=4, textColor=colors.HexColor('#2c3e50'))
        ))
        elements.append(Spacer(1, 0.08 * inch))

    # ── F. Datos del visitador ───────────────────────────────────────────────────
    elements.append(Paragraph("F. DATOS DEL VISITADOR", styles['PDF_Section']))
    try:
        perfil_f = visita.funcionario.perfil_funcionario
        cargo_f  = perfil_f.cargo or '-'
        dep_f    = perfil_f.dependencia or '-'
    except Exception:
        cargo_f = dep_f = '-'

    data_f = [
        ['Nombre funcionario:', visita.funcionario.get_full_name() or visita.funcionario.username,
         'Fecha visita:', visita.fecha_visita.strftime('%d/%m/%Y %H:%M')],
        ['Cargo:', cargo_f, 'Dependencia:', dep_f],
    ]
    t5 = Table(data_f, colWidths=[1.5 * inch, 2.5 * inch, 1.2 * inch, 2.3 * inch])
    t5.setStyle(TableStyle(tbl_style))
    elements.append(t5)

    # ── G. Firmas ────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 0.3 * inch))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#bdc3c7'),
                               spaceBefore=4, spaceAfter=4))
    elements.append(Paragraph("G. FIRMAS", styles['PDF_Section']))
    elements.append(Spacer(1, 0.1 * inch))

    import base64 as _b64
    firma_style = ParagraphStyle('FirmaLabel2', alignment=TA_CENTER, fontSize=8,
                                 textColor=colors.HexColor('#555555'))
    linea = '_' * 42

    # Firma contribuyente
    celda_c = []
    if visita.firma_contribuyente:
        try:
            img_bytes = _b64.b64decode(visita.firma_contribuyente)
            img_buf   = io.BytesIO(img_bytes)
            img_obj   = Image(img_buf, width=2.0 * inch, height=0.8 * inch)
            img_obj.hAlign = 'CENTER'
            celda_c.append(img_obj)
        except Exception:
            celda_c.append(Paragraph(linea, firma_style))
    else:
        celda_c.append(Spacer(1, 0.6 * inch))
        celda_c.append(Paragraph(linea, firma_style))
    celda_c.append(Paragraph(
        f"<b>Firma del Contribuyente</b><br/>"
        f"Nombre: {visita.nombre_propietario or '________________________________'}<br/>"
        f"Doc: {visita.tipo_documento} {visita.numero_documento}",
        firma_style
    ))

    tf = Table([[celda_c]], colWidths=[7 * inch])
    tf.setStyle(TableStyle([
        ('ALIGN',  (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(tf)

    # ── Fotos del establecimiento ────────────────────────────────────────────────
    import os as _os
    fotos_qs = visita.fotos.order_by('orden').all()
    fotos_validas = []
    for foto in fotos_qs:
        try:
            if foto.imagen and foto.imagen.path and _os.path.exists(foto.imagen.path):
                fotos_validas.append(foto)
        except Exception:
            pass

    if fotos_validas:
        elements.append(Spacer(1, 0.15 * inch))
        elements.append(Paragraph("FOTOS DEL ESTABLECIMIENTO", styles['PDF_Section']))
        elements.append(Spacer(1, 0.06 * inch))
        foto_w = 3.4 * inch
        foto_h = 2.5 * inch
        cap_style = ParagraphStyle('FotoCap2', alignment=TA_CENTER,
                                   fontSize=7, textColor=colors.HexColor('#666666'))
        for i in range(0, len(fotos_validas), 2):
            fila = []
            for foto in fotos_validas[i:i+2]:
                try:
                    img_obj = Image(foto.imagen.path, width=foto_w, height=foto_h)
                    img_obj.hAlign = 'CENTER'
                    desc = foto.descripcion or f'Foto {foto.orden + 1}'
                    fila.append([img_obj, Paragraph(desc, cap_style)])
                except Exception:
                    fila.append([Paragraph('(imagen no disponible)', cap_style)])
            if len(fila) == 1:
                fila.append([Paragraph('', cap_style)])
            foto_row = Table([fila], colWidths=[3.75 * inch, 3.75 * inch])
            foto_row.setStyle(TableStyle([
                ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING',    (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(foto_row)

    # ── Nota de descarga RIT ─────────────────────────────────────────────────────
    elements.append(Spacer(1, 0.2 * inch))
    nota_rit = Table([[
        Paragraph(
            '<b>¿Desea consultar o descargar su Formulario RIT?</b><br/>'
            'Ingrese al Portal de Servicios Tributarios: '
            '<font color="#0d6efd">segovia.portalterritorial.com.co</font><br/>'
            'Allí encontrará su inscripción RIT, podrá actualizarla o cancelarla.',
            ParagraphStyle('NotaRIT', fontSize=9, leading=13,
                           textColor=colors.HexColor('#004085'))
        )
    ]], colWidths=[7.5 * inch])
    nota_rit.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), colors.HexColor('#e8f4fd')),
        ('BOX',           (0, 0), (-1, -1), 1, colors.HexColor('#0d6efd')),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
    ]))
    elements.append(nota_rit)

    # ── Pie ──────────────────────────────────────────────────────────────────────
    config_pie_f = dict(config)
    config_pie_f['mostrar_instructivo'] = False
    elements.extend(get_pdf_footer(styles, config_pie_f))
    elements.append(Paragraph(
        f"<i>Acta de visita generada electrónicamente el {timezone.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"— UUID: {visita.uuid_local}</i>",
        styles['PDF_Small']
    ))

    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    disp = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disp}; filename="Acta_Visita_{numero_acta}.pdf"'
    return response
