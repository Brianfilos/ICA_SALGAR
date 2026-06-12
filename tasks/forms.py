from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
import re

from django.contrib.auth.models import User

from .models import (
    RegistroRIT,
    RepresentanteLegalRIT,
    EstablecimientoRIT,
    ActividadEconomicaRIT,
    DeclaracionICA,
    DeclaracionActividad,
    AutoRetencionICA,
    DeclaracionAutoRetencion,
    RetencionICA,
    PerfilContribuyente,
)


class RITForm(forms.ModelForm):
    """Formulario para Registro de Información Tributaria (RIT)."""

    class Meta:
        model = RegistroRIT
        fields = "__all__"
        exclude = [
            "user", "fecha", "departamento_notificacion", "fecha_recepcion",
            "estado", "radicado",
            "clasificacion_contribuyente", "otra_clasificacion",
        ]
        widgets = {
            'fecha_inicio_actividades': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}
            ),
        }

    def __init__(self, *args, perfil=None, opcion_uso=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Guardar referencias
        self.perfil = perfil
        self.opcion_uso_param = opcion_uso

        # Campos que vienen del perfil (Sección C)
        # NOTA: numero_establecimientos NO se bloquea para permitir edición
        campos_perfil = [
            'nombre_razon_social', 'tipo_documento', 'numero_documento',
            'dv', 'cual_documento', 'direccion_notificacion',
            'municipio_notificacion', 'telefono', 'correo_electronico',
            'tipo_persona', 'tipo_juridica', 'otro_tipo_juridica'
        ]

        # Si hay perfil, marcar campos de Sección C como readonly/disabled
        # y hacerlos no requeridos (se llenarán en clean desde el perfil)
        if perfil:
            for campo in campos_perfil:
                if campo in self.fields:
                    self.fields[campo].required = False
                    widget = self.fields[campo].widget
                    widget.attrs['readonly'] = True
                    if widget.__class__.__name__ in ['Select', 'SelectMultiple']:
                        widget.attrs['disabled'] = True

        # Si es inscripción, mostrar el campo opcion_uso como readonly (no disabled)
        # para que el valor se envíe en el POST
        if opcion_uso == "INSCRIPCION" and "opcion_uso" in self.fields:
            self.fields["opcion_uso"].initial = "INSCRIPCION"
            # Usar un widget readonly con JavaScript para prevenir cambios visuales
            self.fields["opcion_uso"].widget.attrs['readonly'] = True
            self.fields["opcion_uso"].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'

        # Aplicar clases Bootstrap a todos los campos
        for name, field in self.fields.items():
            widget_name = field.widget.__class__.__name__

            if widget_name == "CheckboxInput":
                field.widget.attrs.update({"class": "form-check-input"})
            elif widget_name in ["Select", "SelectMultiple"]:
                field.widget.attrs.update({"class": "form-select"})
            elif widget_name == "ClearableFileInput":
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})

        # Teléfono: solo números, 10 dígitos
        if "telefono" in self.fields:
            self.fields["telefono"].widget.attrs.update({
                "inputmode": "numeric",
                "pattern": r"[0-9]*",
                "maxlength": "10",
            })

        # DV: solo números, máximo 2 dígitos
        if "dv" in self.fields:
            self.fields["dv"].widget.attrs.update({
                "maxlength": "2",
                "inputmode": "numeric",
                "pattern": r"[0-9]*",
            })

    def clean(self):
        cleaned = super().clean()

        # Si hay perfil, copiar valores del perfil a cleaned_data
        # NOTA: numero_establecimientos NO se copia para permitir edición
        if self.perfil:
            perfil_fields = {
                'nombre_razon_social': self.perfil.nombre_razon_social,
                'tipo_documento': self.perfil.tipo_documento,
                'numero_documento': self.perfil.numero_documento,
                'dv': self.perfil.dv if self.perfil.dv is not None else cleaned.get('dv'),
                'cual_documento': self.perfil.cual_documento,
                'direccion_notificacion': self.perfil.direccion_notificacion,
                'municipio_notificacion': self.perfil.municipio_notificacion,
                'telefono': self.perfil.telefono,
                'correo_electronico': self.perfil.correo_electronico,
                'tipo_persona': self.perfil.tipo_persona,
                'tipo_juridica': self.perfil.tipo_juridica,
                'otro_tipo_juridica': self.perfil.otro_tipo_juridica,
            }
            for campo, valor in perfil_fields.items():
                if campo in self.fields:
                    cleaned[campo] = valor

        # Si opcion_uso está deshabilitado, forzar el valor
        if self.opcion_uso_param == "INSCRIPCION":
            cleaned['opcion_uso'] = "INSCRIPCION"

        # Validar campos de cancelación
        opcion_uso = cleaned.get('opcion_uso')
        if opcion_uso == "CANCELACION":
            if not cleaned.get('tipo_cancelacion'):
                self.add_error('tipo_cancelacion', 'Debe seleccionar el tipo de cancelación.')
            if not cleaned.get('motivo_cancelacion'):
                self.add_error('motivo_cancelacion', 'Debe seleccionar el motivo de cancelación.')

        return cleaned


# -------------------------
# FORMSETS PARA RIT
# -------------------------
class RepresentanteLegalRITForm(forms.ModelForm):
    """Formulario para representación legal."""

    class Meta:
        model = RepresentanteLegalRIT
        fields = ['tipo_representante', 'nombre', 'tipo_documento', 'numero_documento', 'correo_electronico', 'orden']
        widgets = {
            'tipo_representante': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre completo'
            }),
            'tipo_documento': forms.Select(attrs={'class': 'form-select'}),
            'numero_documento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número de documento'
            }),
            'correo_electronico': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'correo@ejemplo.com'
            }),
            'orden': forms.HiddenInput(),
        }


RepresentanteLegalRITFormSet = inlineformset_factory(
    RegistroRIT,
    RepresentanteLegalRIT,
    form=RepresentanteLegalRITForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


class EstablecimientoRITForm(forms.ModelForm):
    """Formulario para establecimientos."""

    class Meta:
        model = EstablecimientoRIT
        fields = [
            'nombre', 'direccion', 'telefono',
            'fecha_inicio_actividades', 'tiene_avisos_tableros',
            'fecha_cancelacion', 'orden'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del establecimiento'
            }),
            'direccion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dirección del establecimiento'
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Teléfono',
                'maxlength': '10'
            }),
            'fecha_inicio_actividades': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'tiene_avisos_tableros': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'fecha_cancelacion': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'orden': forms.HiddenInput(),
        }


EstablecimientoRITFormSet = inlineformset_factory(
    RegistroRIT,
    EstablecimientoRIT,
    form=EstablecimientoRITForm,
    extra=1,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


class ActividadEconomicaRITForm(forms.ModelForm):
    """Formulario para actividades económicas del RIT."""

    class Meta:
        model = ActividadEconomicaRIT
        fields = ['actividad', 'base_gravable_mensual', 'orden']
        widgets = {
            'actividad': forms.Select(attrs={'class': 'form-select actividad-select'}),
            'base_gravable_mensual': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'placeholder': '0'
            }),
            'orden': forms.HiddenInput(),
        }


class BaseActividadRITFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()

        count = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            actividad = form.cleaned_data.get("actividad")
            if actividad:
                count += 1

        if count < 1:
            raise ValidationError("Debe registrar al menos 1 actividad económica.")
        if count > 15:
            raise ValidationError("Máximo 15 actividades permitidas.")


ActividadEconomicaRITFormSet = inlineformset_factory(
    RegistroRIT,
    ActividadEconomicaRIT,
    form=ActividadEconomicaRITForm,
    formset=BaseActividadRITFormSet,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


# -------------------------
# REGISTRO (SIGNUP)
# -------------------------
class SignupForm(forms.Form):
    """Formulario para datos de acceso del usuario."""
    username = forms.CharField(
        max_length=150,
        label="Usuario",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre de usuario',
            'autocomplete': 'username'
        })
    )
    password1 = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contraseña',
            'autocomplete': 'new-password'
        })
    )
    password2 = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirmar contraseña',
            'autocomplete': 'new-password'
        })
    )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso.")
        return username

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get('password1')
        password2 = cleaned.get('password2')

        if password1 and password2 and password1 != password2:
            self.add_error('password2', "Las contraseñas no coinciden.")

        return cleaned


class PerfilContribuyenteForm(forms.ModelForm):
    """Formulario para datos del perfil del contribuyente."""

    class Meta:
        model = PerfilContribuyente
        exclude = ['user', 'departamento_notificacion', 'created_at', 'updated_at', 'must_change_password']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Aplicar clases Bootstrap a todos los campos
        for name, field in self.fields.items():
            widget_name = field.widget.__class__.__name__

            if widget_name == "CheckboxInput":
                field.widget.attrs.update({"class": "form-check-input"})
            elif widget_name in ["Select", "SelectMultiple"]:
                field.widget.attrs.update({"class": "form-select"})
            else:
                field.widget.attrs.update({"class": "form-control"})

        # Teléfono: solo números, 10 dígitos
        if "telefono" in self.fields:
            self.fields["telefono"].widget.attrs.update({
                "inputmode": "numeric",
                "pattern": r"[0-9]*",
                "maxlength": "10",
                "placeholder": "Ej: 3001234567",
            })

        # Número de documento
        if "numero_documento" in self.fields:
            self.fields["numero_documento"].widget.attrs.update({
                "maxlength": "30",
                "placeholder": "Número de documento"
            })

        # DV: solo números, máximo 2 dígitos
        if "dv" in self.fields:
            self.fields["dv"].widget.attrs.update({
                "maxlength": "2",
                "inputmode": "numeric",
                "pattern": r"[0-9]*",
                "placeholder": "DV"
            })

        # Placeholders
        if "nombre_razon_social" in self.fields:
            self.fields["nombre_razon_social"].widget.attrs.update({
                "placeholder": "Nombres y apellidos o razón social"
            })

        if "direccion_notificacion" in self.fields:
            self.fields["direccion_notificacion"].widget.attrs.update({
                "placeholder": "Dirección completa"
            })

        if "correo_electronico" in self.fields:
            self.fields["correo_electronico"].widget.attrs.update({
                "placeholder": "correo@ejemplo.com"
            })

        if "cual_documento" in self.fields:
            self.fields["cual_documento"].widget.attrs.update({
                "placeholder": "Especifique el tipo de documento"
            })

        if "otra_clasificacion" in self.fields:
            self.fields["otra_clasificacion"].widget.attrs.update({
                "placeholder": "Especifique la clasificación"
            })

        if "otro_tipo_juridica" in self.fields:
            self.fields["otro_tipo_juridica"].widget.attrs.update({
                "placeholder": "Especifique el tipo jurídico"
            })

    def clean_telefono(self):
        telefono = (self.cleaned_data.get("telefono") or "").strip()
        if telefono == "":
            raise forms.ValidationError("El teléfono es obligatorio.")

        telefono = re.sub(r"\D", "", telefono)

        if len(telefono) != 10:
            raise forms.ValidationError(
                "El teléfono debe tener exactamente 10 dígitos numéricos."
            )
        return telefono

    def clean_dv(self):
        dv = (self.cleaned_data.get("dv") or "").strip()
        if dv == "":
            return dv
        if not dv.isdigit():
            raise forms.ValidationError("El DV solo puede contener números.")
        if len(dv) > 2:
            raise forms.ValidationError("El DV no puede tener más de 2 dígitos.")
        return dv

    def clean(self):
        cleaned = super().clean()

        tipo_documento = cleaned.get("tipo_documento")
        tipo_persona = cleaned.get("tipo_persona")
        tipo_juridica = cleaned.get("tipo_juridica")
        otro_tipo = cleaned.get("otro_tipo_juridica")
        clasificacion = cleaned.get("clasificacion_contribuyente")

        # DV solo aplica si tipo_documento es NIT
        if tipo_documento != "NIT":
            cleaned["dv"] = None

        # cual_documento solo aplica si tipo_documento es OTRO
        if tipo_documento != "OTRO":
            cleaned["cual_documento"] = None
        elif tipo_documento == "OTRO" and not cleaned.get("cual_documento"):
            self.add_error("cual_documento", "Debe especificar el tipo de documento.")

        # otra_clasificacion solo aplica si clasificacion es OTRA
        if clasificacion != "OTRA":
            cleaned["otra_clasificacion"] = None
        elif clasificacion == "OTRA" and not cleaned.get("otra_clasificacion"):
            self.add_error("otra_clasificacion", "Debe especificar la clasificación.")

        # Natural: NO aplica jurídica
        if tipo_persona == "NATURAL":
            cleaned["tipo_juridica"] = None
            cleaned["otro_tipo_juridica"] = None

        # Jurídica: exige tipo_juridica
        if tipo_persona == "JURIDICA":
            if not tipo_juridica:
                self.add_error(
                    "tipo_juridica", "Este campo es obligatorio para persona jurídica."
                )
            else:
                if tipo_juridica != "OTRO":
                    cleaned["otro_tipo_juridica"] = None
                if tipo_juridica == "OTRO" and not (otro_tipo and otro_tipo.strip()):
                    self.add_error(
                        "otro_tipo_juridica",
                        "Debe especificar el tipo jurídico cuando selecciona 'Otro'.",
                    )

        return cleaned


# -------------------------
# ICA (CABECERA)
# -------------------------
class ICAForm(forms.ModelForm):
    class Meta:
        model = DeclaracionICA
        fields = "__all__"
        exclude = [
            "user",
            "fecha_diligenciamiento",
            "created_at",
            "valor_ica",
            "avisos_tableros",
            "sobretasa_bomberil",
            "total_a_pagar",
            "departamento",  # lo llenas automático
            "firma_declarante",        # reemplazada por OTP
            "firma_contador",          # reemplazada por OTP de contador
            "firma_revisor_fiscal",    # reemplazada por OTP de revisor
            "firma_otp_verificada",
            "firma_timestamp",
            "firma_hash",
            "contador_firma_verificada",
            "revisor_firma_verificada",
        ]

    def __init__(self, *args, perfil=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Guardar referencia al perfil y usuario para usar en validación
        self.perfil = perfil
        self.user = user

        # Campos que vienen del perfil (sección A)
        campos_perfil = [
            'nombre_razon_social', 'tipo_documento', 'numero_documento',
            'dv', 'cual_documento', 'direccion_notificacion',
            'municipio_notificacion', 'telefono', 'correo_electronico',
            'clasificacion_contribuyente',
            'otra_clasificacion', 'tipo_persona', 'tipo_juridica',
            'otro_tipo_juridica'
        ]

        # Si hay perfil, marcar campos de sección A como readonly/disabled
        if perfil:
            for campo in campos_perfil:
                if campo in self.fields:
                    widget = self.fields[campo].widget
                    widget.attrs['readonly'] = True
                    # Para selects usamos disabled ya que readonly no funciona
                    if widget.__class__.__name__ in ['Select', 'SelectMultiple']:
                        widget.attrs['disabled'] = True

        # -------------------------
        # 1) Bootstrap classes
        # -------------------------
        for name, field in self.fields.items():
            widget_name = field.widget.__class__.__name__

            if widget_name == "CheckboxInput":
                field.widget.attrs.update({"class": "form-check-input"})
            elif widget_name in ["Select", "SelectMultiple"]:
                field.widget.attrs.update({"class": "form-select"})
            elif widget_name == "ClearableFileInput":
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})

        # -------------------------
        # 2) Ajustes puntuales
        # -------------------------
        if "municipio" in self.fields:
            self.fields["municipio"].widget.attrs.update({"class": "form-select"})

        if "otro_tipo_juridica" in self.fields:
            self.fields["otro_tipo_juridica"].widget.attrs.update(
                {"placeholder": "Especifique el tipo jurídico"}
            )

        # -------------------------
        # 3) Teléfono numérico (frontend)
        # -------------------------
        if "telefono" in self.fields:
            self.fields["telefono"].widget.attrs.update(
                {
                    "inputmode": "numeric",
                    "pattern": r"[0-9]*",
                    "maxlength": "10",
                    "placeholder": "Ej: 3001234567",
                }
            )

        if "numero_documento" in self.fields:
            self.fields["numero_documento"].widget.attrs.update({"maxlength": "30"})

        if "dv" in self.fields:
            self.fields["dv"].widget.attrs.update(
                {"maxlength": "2", "inputmode": "numeric", "pattern": r"[0-9]*"}
            )

        # -------------------------
        # 4) Base gravable como TEXTO (clave para permitir 1.234.567)
        # -------------------------
        base_gravable_fields = [
            "b8_total_ingresos_pais",
            "b9_menos_ingresos_fuera_municipio",
            "b11_menos_devoluciones_rebajas_descuentos",
            "b12_menos_exportaciones_venta_activos_fijos",
            "b13_menos_otras_actividades_excluidas_no_sujetas",
            "b14_menos_actividades_exentas_por_acuerdo",
        ]

        for fname in base_gravable_fields:
            if fname in self.fields:
                self.fields[fname].widget = forms.TextInput()
                self.fields[fname].widget.attrs.update(
                    {
                        "class": "form-control",
                        "inputmode": "numeric",
                        "autocomplete": "off",
                    }
                )

        # -------------------------
        # 5) Bloque C (18-19) y D (22-32) como TEXTO para formato contable
        # -------------------------
        money_fields = [
            "imp_ley_56_1981",
            "d22_sector_financiero",
            "d24_sobretasa_seguridad",
            "d26_exencion",
            "d27_retenciones",
            "d28_autorretenciones",
            "d29_anticipo_anterior",
            "d30_anticipo_siguiente",
            "d31_valor",
            "d32_saldo_favor_anterior",
            "e36_descuento_pronto_pago",
            "e37_intereses_mora",
        ]

        for fname in money_fields:
            if fname in self.fields:
                self.fields[fname].widget = forms.TextInput()
                self.fields[fname].widget.attrs.update(
                    {
                        "class": "form-control",
                        "inputmode": "numeric",
                        "autocomplete": "off",
                    }
                )

        # 18 - generador energía
        if "es_generador_energia" in self.fields:
            self.fields["es_generador_energia"].widget.attrs.update({"class": "form-select"})

        # Campos condicionales (solo se muestran si es generador de energía)
        # Deben ser NO requeridos para que el formulario se pueda enviar cuando están ocultos
        if "capacidad_instalada_kw" in self.fields:
            self.fields["capacidad_instalada_kw"].required = False
            self.fields["capacidad_instalada_kw"].widget = forms.TextInput()
            self.fields["capacidad_instalada_kw"].widget.attrs.update(
                {
                    "class": "form-control",
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            )

        if "imp_ley_56_1981" in self.fields:
            self.fields["imp_ley_56_1981"].required = False

        # 21 - avisos y tableros
        if "tiene_avisos_tableros" in self.fields:
            self.fields["tiene_avisos_tableros"].required = False
            self.fields["tiene_avisos_tableros"].widget.attrs.update({"class": "form-select"})

        # -------------------------
        # F) Ajustes firmas: placeholders y selects
        # -------------------------
        # Selects tipo documento contador/revisor/rep_legal
        for fname in ["contador_tipo_documento", "revisor_tipo_documento", "rep_legal_tipo_documento"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"class": "form-select"})

        # Placeholders
        placeholders = {
            "contador_nombre": "Nombre completo del contador",
            "contador_numero_documento": "Número de documento",
            "contador_tarjeta_profesional": "Tarjeta profesional (T.P.)",
            "revisor_nombre": "Nombre completo del revisor fiscal",
            "revisor_numero_documento": "Número de documento",
            "revisor_tarjeta_profesional": "Tarjeta profesional (T.P.)",
            "rep_legal_nombre": "Nombre completo del representante legal",
            "rep_legal_numero_documento": "Número de documento",
            "rep_legal_email": "Correo electrónico del representante legal",
        }

        for fname, ph in placeholders.items():
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"placeholder": ph})

        # Documento solo números (opcional)
        for fname in ["contador_numero_documento", "revisor_numero_documento", "rep_legal_numero_documento"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update(
                    {"inputmode": "numeric", "pattern": r"[0-9]*"}
                )

    # -------------------------
    # Validación fuerte backend
    # -------------------------
    def clean_telefono(self):
        telefono = (self.cleaned_data.get("telefono") or "").strip()

        if telefono == "":
            return telefono  # opcional según tu modelo

        telefono = re.sub(r"\D", "", telefono)

        if len(telefono) != 10:
            raise forms.ValidationError(
                "El teléfono debe tener exactamente 10 dígitos numéricos."
            )

        return telefono

    def clean_numero_documento(self):
        val = (self.cleaned_data.get("numero_documento") or "").strip()
        if val == "":
            return val
        return val

    def clean_dv(self):
        dv = (self.cleaned_data.get("dv") or "").strip()
        if dv == "":
            return dv
        if not dv.isdigit():
            raise forms.ValidationError("El DV solo puede contener números.")
        if len(dv) > 2:
            raise forms.ValidationError("El DV no puede tener más de 2 dígitos.")
        return dv

    def __init__(self, *args, perfil=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Guardar referencia al perfil y usuario para usar en validación
        self.perfil = perfil
        self.user = user

        # Campos que vienen del perfil (sección A)
        campos_perfil = [
            'nombre_razon_social', 'tipo_documento', 'numero_documento',
            'dv', 'cual_documento', 'direccion_notificacion',
            'municipio_notificacion', 'telefono', 'correo_electronico',
            'clasificacion_contribuyente',
            'otra_clasificacion', 'tipo_persona', 'tipo_juridica',
            'otro_tipo_juridica'
        ]

        # Si hay perfil, marcar campos de sección A como readonly/disabled
        if perfil:
            for campo in campos_perfil:
                if campo in self.fields:
                    widget = self.fields[campo].widget
                    widget.attrs['readonly'] = True
                    # Para selects usamos disabled ya que readonly no funciona
                    if widget.__class__.__name__ in ['Select', 'SelectMultiple']:
                        widget.attrs['disabled'] = True

        # -------------------------
        # 1) Bootstrap classes
        # -------------------------
        for name, field in self.fields.items():
            widget_name = field.widget.__class__.__name__

            if widget_name == "CheckboxInput":
                field.widget.attrs.update({"class": "form-check-input"})
            elif widget_name in ["Select", "SelectMultiple"]:
                field.widget.attrs.update({"class": "form-select"})
            elif widget_name == "ClearableFileInput":
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})

        # -------------------------
        # 2) Ajustes puntuales
        # -------------------------
        if "municipio" in self.fields:
            self.fields["municipio"].widget.attrs.update({"class": "form-select"})

        if "otro_tipo_juridica" in self.fields:
            self.fields["otro_tipo_juridica"].widget.attrs.update(
                {"placeholder": "Especifique el tipo jurídico"}
            )

        # -------------------------
        # 3) Teléfono numérico (frontend)
        # -------------------------
        if "telefono" in self.fields:
            self.fields["telefono"].widget.attrs.update(
                {
                    "inputmode": "numeric",
                    "pattern": r"[0-9]*",
                    "maxlength": "10",
                    "placeholder": "Ej: 3001234567",
                }
            )

        if "numero_documento" in self.fields:
            self.fields["numero_documento"].widget.attrs.update({"maxlength": "30"})

        if "dv" in self.fields:
            self.fields["dv"].widget.attrs.update(
                {"maxlength": "2", "inputmode": "numeric", "pattern": r"[0-9]*"}
            )

        # -------------------------
        # 4) Base gravable como TEXTO (clave para permitir 1.234.567)
        # -------------------------
        base_gravable_fields = [
            "b8_total_ingresos_pais",
            "b9_menos_ingresos_fuera_municipio",
            "b11_menos_devoluciones_rebajas_descuentos",
            "b12_menos_exportaciones_venta_activos_fijos",
            "b13_menos_otras_actividades_excluidas_no_sujetas",
            "b14_menos_actividades_exentas_por_acuerdo",
        ]

        for fname in base_gravable_fields:
            if fname in self.fields:
                self.fields[fname].widget = forms.TextInput()
                self.fields[fname].widget.attrs.update(
                    {
                        "class": "form-control",
                        "inputmode": "numeric",
                        "autocomplete": "off",
                    }
                )

        # -------------------------


        # 5) Bloque C (18-19) y D (22-32) como TEXTO para formato contable
        # -------------------------
        money_fields = [
            "imp_ley_56_1981",
            "d22_sector_financiero",
            "d24_sobretasa_seguridad",
            "d26_exencion",
            "d27_retenciones",
            "d28_autorretenciones",
            "d29_anticipo_anterior",
            "d30_anticipo_siguiente",
            "d31_valor",
            "d32_saldo_favor_anterior",
            "e36_descuento_pronto_pago",
            "e37_intereses_mora",
        ]

        for fname in money_fields:
            if fname in self.fields:
                self.fields[fname].widget = forms.TextInput()
                self.fields[fname].widget.attrs.update(
                    {
                        "class": "form-control",
                        "inputmode": "numeric",
                        "autocomplete": "off",
                    }
                )

        # 18 - generador energía
        if "es_generador_energia" in self.fields:
            self.fields["es_generador_energia"].widget.attrs.update({"class": "form-select"})

        # Campos condicionales (solo se muestran si es generador de energía)
        if "capacidad_instalada_kw" in self.fields:
            self.fields["capacidad_instalada_kw"].required = False
            self.fields["capacidad_instalada_kw"].widget = forms.TextInput()
            self.fields["capacidad_instalada_kw"].widget.attrs.update(
                {
                    "class": "form-control",
                    "inputmode": "numeric",
                    "autocomplete": "off",
                }
            )

        if "imp_ley_56_1981" in self.fields:
            self.fields["imp_ley_56_1981"].required = False

        # 21 - avisos y tableros
        if "tiene_avisos_tableros" in self.fields:
            self.fields["tiene_avisos_tableros"].required = False
            self.fields["tiene_avisos_tableros"].widget.attrs.update({"class": "form-select"})

        # -------------------------
        # F) Ajustes firmas: placeholders y selects
        # -------------------------
        # Selects tipo documento contador/revisor/rep_legal
        for fname in ["contador_tipo_documento", "revisor_tipo_documento", "rep_legal_tipo_documento"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"class": "form-select"})

        # Placeholders
        placeholders = {
            "contador_nombre": "Nombre completo del contador",
            "contador_numero_documento": "Número de documento",
            "contador_tarjeta_profesional": "Tarjeta profesional (T.P.)",
            "revisor_nombre": "Nombre completo del revisor fiscal",
            "revisor_numero_documento": "Número de documento",
            "revisor_tarjeta_profesional": "Tarjeta profesional (T.P.)",
            "rep_legal_nombre": "Nombre completo del representante legal",
            "rep_legal_numero_documento": "Número de documento",
            "rep_legal_email": "Correo electrónico del representante legal",
        }

        for fname, ph in placeholders.items():
            if fname in self.fields:
                self.fields[fname].widget.attrs.update({"placeholder": ph})

        # Documento solo números (opcional)
        for fname in ["contador_numero_documento", "revisor_numero_documento", "rep_legal_numero_documento"]:
            if fname in self.fields:
                self.fields[fname].widget.attrs.update(
                    {"inputmode": "numeric", "pattern": r"[0-9]*"}
                )

        # -------------------------
        # Declaracion que corrige: solo las propias del usuario
        # -------------------------
        if "corrige_a" in self.fields and user:
            from .models import DeclaracionICA as _DICA
            qs = _DICA.objects.filter(user=user).order_by("-anio_gravable", "-fecha_diligenciamiento")
            self.fields["corrige_a"].queryset = qs
            self.fields["corrige_a"].label_from_instance = lambda obj: (
                f"ICA-{obj.anio_gravable}-{obj.id:06d} - {obj.get_opcion_uso_display()}"
            )

    # -------------------------
    # Validación fuerte backend
    # -------------------------
    def clean_telefono(self):
        telefono = (self.cleaned_data.get("telefono") or "").strip()

        if telefono == "":
            return telefono  # opcional según tu modelo

        telefono = re.sub(r"\D", "", telefono)

        if len(telefono) != 10:
            raise forms.ValidationError(
                "El teléfono debe tener exactamente 10 dígitos numéricos."
            )

        return telefono

    def clean_numero_documento(self):
        val = (self.cleaned_data.get("numero_documento") or "").strip()
        if val == "":
            return val
        return val

    def clean_dv(self):
        dv = (self.cleaned_data.get("dv") or "").strip()
        if dv == "":
            return dv
        if not dv.isdigit():
            raise forms.ValidationError("El DV solo puede contener números.")
        if len(dv) > 2:
            raise forms.ValidationError("El DV no puede tener más de 2 dígitos.")
        return dv

    def clean_anio_gravable(self):
        anio = self.cleaned_data.get("anio_gravable")
        if anio is None:
            return anio
        if anio < 2000 or anio > 2099:
            raise forms.ValidationError("El año gravable debe tener 4 dígitos (ej: 2025).")
        return anio

    def _limpiar_valor_monetario(self, valor):
        """Convierte un valor formateado (1.234.567) a entero."""
        if valor is None or valor == '':
            return 0
        if isinstance(valor, int):
            return valor
        # Remover puntos de miles y comas decimales, convertir a entero
        val_str = str(valor).replace('.', '').replace(',', '').strip()
        if val_str == '':
            return 0
        try:
            return int(val_str)
        except ValueError:
            return 0

    def clean(self):
        cleaned = super().clean()

        # Limpiar todos los campos monetarios (convertir "1.234.567" a 1234567)
        money_fields = [
            "b8_total_ingresos_pais",
            "b9_menos_ingresos_fuera_municipio",
            "b11_menos_devoluciones_rebajas_descuentos",
            "b12_menos_exportaciones_venta_activos_fijos",
            "b13_menos_otras_actividades_excluidas_no_sujetas",
            "b14_menos_actividades_exentas_por_acuerdo",
            "imp_ley_56_1981",
            "d22_sector_financiero",
            "d24_sobretasa_seguridad",
            "d26_exencion",
            "d27_retenciones",
            "d28_autorretenciones",
            "d29_anticipo_anterior",
            "d30_anticipo_siguiente",
            "d31_valor",
            "d32_saldo_favor_anterior",
            "e36_descuento_pronto_pago",
            "e37_intereses_mora",
            "capacidad_instalada_kw",
        ]

        for fname in money_fields:
            if fname in cleaned:
                cleaned[fname] = self._limpiar_valor_monetario(cleaned.get(fname))

        # Si hay perfil, copiar valores del perfil a cleaned_data
        # (los campos disabled no se envían en POST)
        if self.perfil:
            perfil_fields = {
                'nombre_razon_social': self.perfil.nombre_razon_social,
                'tipo_documento': self.perfil.tipo_documento,
                'numero_documento': self.perfil.numero_documento,
                'dv': self.perfil.dv if self.perfil.dv is not None else cleaned.get('dv'),
                'cual_documento': self.perfil.cual_documento,
                'direccion_notificacion': self.perfil.direccion_notificacion,
                'municipio_notificacion': self.perfil.municipio_notificacion,
                'telefono': self.perfil.telefono,
                'correo_electronico': self.perfil.correo_electronico,
                'numero_establecimientos': self.perfil.numero_establecimientos,
                'clasificacion_contribuyente': self.perfil.clasificacion_contribuyente,
                'otra_clasificacion': self.perfil.otra_clasificacion,
                'tipo_persona': self.perfil.tipo_persona,
                'tipo_juridica': self.perfil.tipo_juridica,
                'otro_tipo_juridica': self.perfil.otro_tipo_juridica,
            }
            for campo, valor in perfil_fields.items():
                if campo in self.fields:
                    cleaned[campo] = valor

        tipo_persona = cleaned.get("tipo_persona")
        tipo_juridica = cleaned.get("tipo_juridica")
        otro_tipo = cleaned.get("otro_tipo_juridica")
        opcion_uso = cleaned.get("opcion_uso")
        corrige_a = cleaned.get("corrige_a")
        tipo_doc = cleaned.get("tipo_documento")
        anio_gravable = cleaned.get("anio_gravable")

        # --- Corrección exige corrige_a ---
        if opcion_uso == "CORRECCION" and not corrige_a:
            self.add_error(
                "corrige_a",
                "Si es Corrección, debes seleccionar la declaración que corriges.",
            )

        # --- Validar que no exista declaración INICIAL para el mismo año gravable ---
        _es_alcaldia = self.user and self.user.groups.filter(name='ALCALDIA_GESTION').exists()
        if opcion_uso == "INICIAL" and anio_gravable and self.user and not _es_alcaldia:
            from .models import DeclaracionICA
            existe_inicial = DeclaracionICA.objects.filter(
                user=self.user,
                anio_gravable=anio_gravable,
                opcion_uso='INICIAL'
            ).exists()
            if existe_inicial:
                self.add_error(
                    "anio_gravable",
                    f"Ya existe una declaración INICIAL para el año {anio_gravable}. "
                    "Si desea modificarla, seleccione la opción 'Corrección'."
                )

        # --- DV solo aplica si tipo_documento es NIT ---
        if tipo_doc != "NIT":
            cleaned["dv"] = None

        # --- Natural: NO aplica jurídica ---
        if tipo_persona == "NATURAL":
            cleaned["tipo_juridica"] = None
            cleaned["otro_tipo_juridica"] = None

        # --- Jurídica: exige tipo_juridica ---
        if tipo_persona == "JURIDICA":
            if not tipo_juridica:
                self.add_error(
                    "tipo_juridica", "Este campo es obligatorio para persona jurídica."
                )
            else:
                if tipo_juridica != "OTRO":
                    cleaned["otro_tipo_juridica"] = None
                if tipo_juridica == "OTRO" and not (otro_tipo and otro_tipo.strip()):
                    self.add_error(
                        "otro_tipo_juridica",
                        "Debes especificar el tipo jurídico cuando seleccionas 'Otro'.",
                    )

        return cleaned


# -------------------------
# ICA (DETALLE ACTIVIDADES)
# -------------------------
class DeclaracionActividadForm(forms.ModelForm):
    # Sobrescribir ingresos_gravados para aceptar texto formateado
    ingresos_gravados = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "inputmode": "numeric",
            "autocomplete": "off",
        })
    )

    class Meta:
        model = DeclaracionActividad
        fields = ["orden", "actividad", "ingresos_gravados"]
        widgets = {
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
            "actividad": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_ingresos_gravados(self):
        val = self.cleaned_data.get("ingresos_gravados") or "0"
        # Convertir valor formateado (1.234.567) a entero
        if isinstance(val, int):
            num_val = val
        else:
            val_str = str(val).replace('.', '').replace(',', '').strip()
            if val_str == '':
                num_val = 0
            else:
                try:
                    num_val = int(val_str)
                except ValueError:
                    raise forms.ValidationError(
                        "Los ingresos gravados deben ser un número válido."
                    )
        if num_val < 0:
            raise forms.ValidationError(
                "Los ingresos gravados no pueden ser negativos."
            )
        return num_val


class BaseDeclaracionActividadFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()

        count = 0
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            actividad = form.cleaned_data.get("actividad")
            ingresos = form.cleaned_data.get("ingresos_gravados")

            if actividad or (ingresos not in (None, "", 0)):
                count += 1

        if count < 1:
            raise ValidationError("Debes registrar mínimo 1 actividad económica.")
        if count > 15:
            raise ValidationError("Máximo 15 actividades permitidas.")


DeclaracionActividadFormSet = inlineformset_factory(
    DeclaracionICA,
    DeclaracionActividad,
    form=DeclaracionActividadForm,
    formset=BaseDeclaracionActividadFormSet,
    extra=1,
    can_delete=True,
)

DeclaracionActividadFormSetEdicion = inlineformset_factory(
    DeclaracionICA,
    DeclaracionActividad,
    form=DeclaracionActividadForm,
    formset=BaseDeclaracionActividadFormSet,
    extra=0,
    can_delete=True,
)


# -------------------------
# AUTORRETENCIÓN / RETENCIÓN
# -------------------------
class AutoForm(forms.ModelForm):
    """Legacy form for AutoRetencionICA (kept for reference)."""
    class Meta:
        model = AutoRetencionICA
        fields = "__all__"
        exclude = ["user", "fecha"]


class DeclaracionAutoRetencionForm(forms.ModelForm):
    """Formulario completo para Declaración Bimestral de Autorretención ICA."""

    # Monetary fields as text for formatting
    sanciones = forms.CharField(required=False, initial='0')
    intereses_mora = forms.CharField(required=False, initial='0')
    autorretencion_exceso = forms.CharField(required=False, initial='0')

    tipo_sancion = forms.ChoiceField(
        choices=[
            ("NINGUNA", "Ninguna"),
            ("EXTEMPORANEIDAD", "Extemporaneidad"),
            ("CORRECCION", "Corrección"),
            ("INEXACTITUD", "Inexactitud"),
            ("OTRA", "Otra"),
        ],
        required=False,
        initial="NINGUNA",
    )
    cual_sancion = forms.CharField(required=False, max_length=100)

    class Meta:
        model = DeclaracionAutoRetencion
        exclude = [
            'user', 'fecha_diligenciamiento', 'created_at',
            'total_valor_autorretencion', 'subtotal', 'total_a_pagar',
            'departamento',
            'contador_firma_verificada', 'revisor_firma_verificada',
            'firma_otp_verificada', 'firma_timestamp', 'firma_hash',
        ]

    def __init__(self, *args, **kwargs):
        self.perfil = kwargs.pop('perfil', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Municipio choices
        from catalogos.models import Municipio
        municipios = Municipio.objects.select_related('departamento').order_by('nombre')
        choices_mun = [('', 'Escribe o pega un municipio...')] + [(m.id, m.nombre) for m in municipios]
        self.fields['municipio'].widget = forms.Select(attrs={'class': 'form-select select2-municipio'})
        self.fields['municipio'].choices = choices_mun
        self.fields['municipio_notificacion'].widget = forms.Select(attrs={'class': 'form-select select2-municipio-notif'})
        self.fields['municipio_notificacion'].choices = choices_mun
        self.fields['municipio_notificacion'].required = False

        # corrige_a queryset - only signed INICIAL declarations of this user
        if self.user:
            self.fields['corrige_a'].queryset = DeclaracionAutoRetencion.objects.filter(
                user=self.user, firma_otp_verificada=True
            ).order_by('-anio_gravable', '-bimestre')
        else:
            self.fields['corrige_a'].queryset = DeclaracionAutoRetencion.objects.none()
        self.fields['corrige_a'].required = False

        # Bootstrap classes for all fields
        for fname, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.Select):
                w.attrs.setdefault('class', 'form-select')
            elif isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault('class', 'form-check-input')
            else:
                w.attrs.setdefault('class', 'form-control')

        # Pre-fill from perfil
        if self.perfil and not self.instance.pk:
            p = self.perfil
            self.fields['nombre_razon_social'].initial = p.nombre_razon_social or ''
            self.fields['tipo_documento'].initial = p.tipo_documento or ''
            self.fields['numero_documento'].initial = p.numero_documento or ''
            self.fields['dv'].initial = p.dv or ''
            self.fields['direccion_notificacion'].initial = p.direccion_notificacion or ''
            self.fields['municipio_notificacion'].initial = p.municipio_notificacion_id or ''
            self.fields['telefono'].initial = p.telefono or ''
            self.fields['correo_electronico'].initial = p.correo_electronico or ''
            self.fields['tipo_persona'].initial = p.tipo_persona or ''
            self.fields['clasificacion_contribuyente'].initial = p.clasificacion_contribuyente or ''

    def _parse_money(self, value):
        if not value:
            return 0
        cleaned = str(value).replace('.', '').replace(',', '').replace(' ', '').strip()
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def clean_anio_gravable(self):
        val = self.cleaned_data.get('anio_gravable')
        if val and (val < 2000 or val > 2099):
            raise forms.ValidationError('El año gravable debe estar entre 2000 y 2099.')
        return val

    def clean_telefono(self):
        val = self.cleaned_data.get('telefono', '') or ''
        digits = val.replace(' ', '').replace('-', '')
        if digits and len(digits) != 10:
            raise forms.ValidationError('El teléfono debe tener exactamente 10 dígitos.')
        return digits

    def clean_corrige_a(self):
        opcion = self.cleaned_data.get('opcion_uso')
        corrige = self.cleaned_data.get('corrige_a')
        if opcion == 'CORRECCION' and not corrige:
            raise forms.ValidationError('Debe seleccionar la declaración que corrige.')
        return corrige

    def clean_sanciones(self):
        return self._parse_money(self.cleaned_data.get('sanciones'))

    def clean_intereses_mora(self):
        return self._parse_money(self.cleaned_data.get('intereses_mora'))

    def clean_autorretencion_exceso(self):
        return self._parse_money(self.cleaned_data.get('autorretencion_exceso'))

    def clean(self):
        cleaned = super().clean()
        # Validate no duplicate INICIAL for same year+bimestre
        opcion = cleaned.get('opcion_uso')
        anio = cleaned.get('anio_gravable')
        bimestre = cleaned.get('bimestre')
        if opcion == 'INICIAL' and anio and bimestre and self.user:
            qs = DeclaracionAutoRetencion.objects.filter(
                user=self.user, anio_gravable=anio, bimestre=bimestre, opcion_uso='INICIAL',
                firma_otp_verificada=True,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Ya existe una declaración inicial firmada para el Bimestre {bimestre} del año {anio}.'
                )
        return cleaned


class DeclaracionActividadAutoForm(forms.Form):
    actividad_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    ingreso_total_bimestre = forms.CharField(required=False, initial='0')
    ingreso_excluido = forms.CharField(required=False, initial='0')

    def _parse(self, val):
        if not val:
            return 0
        try:
            return int(str(val).replace('.', '').replace(',', '').strip())
        except (ValueError, TypeError):
            return 0

    def clean_ingreso_total_bimestre(self):
        return self._parse(self.cleaned_data.get('ingreso_total_bimestre'))

    def clean_ingreso_excluido(self):
        return self._parse(self.cleaned_data.get('ingreso_excluido'))


class ReteForm(forms.ModelForm):
    """Formulario para Declaración Bimestral de Retención ICA."""

    sanciones = forms.CharField(required=False, initial='0')
    intereses_mora = forms.CharField(required=False, initial='0')
    devoluciones = forms.CharField(required=False, initial='0')

    tipo_sancion = forms.ChoiceField(
        choices=[
            ("NINGUNA", "Ninguna"),
            ("EXTEMPORANEIDAD", "Extemporaneidad"),
            ("CORRECCION", "Corrección"),
            ("INEXACTITUD", "Inexactitud"),
            ("OTRA", "Otra"),
        ],
        required=False,
        initial="NINGUNA",
    )
    cual_sancion = forms.CharField(required=False, max_length=100)

    class Meta:
        from .models import DeclaracionRetencionICA as _Mod
        model = _Mod
        exclude = [
            'user', 'fecha_diligenciamiento', 'created_at',
            'total_valor_retencion', 'subtotal_retenciones', 'total_a_pagar',
            'departamento',
            'contador_firma_verificada', 'revisor_firma_verificada',
            'firma_otp_verificada', 'firma_timestamp', 'firma_hash',
        ]

    def __init__(self, *args, **kwargs):
        self.perfil = kwargs.pop('perfil', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        from catalogos.models import Municipio
        from .models import DeclaracionRetencionICA as _Mod
        municipios = Municipio.objects.select_related('departamento').order_by('nombre')
        choices_mun = [('', 'Escribe o pega un municipio...')] + [(m.id, m.nombre) for m in municipios]
        self.fields['municipio'].widget = forms.Select(attrs={'class': 'form-select select2-municipio'})
        self.fields['municipio'].choices = choices_mun
        self.fields['municipio_notificacion'].widget = forms.Select(attrs={'class': 'form-select select2-municipio-notif'})
        self.fields['municipio_notificacion'].choices = choices_mun
        self.fields['municipio_notificacion'].required = False

        if self.user:
            self.fields['corrige_a'].queryset = _Mod.objects.filter(
                user=self.user, firma_otp_verificada=True
            ).order_by('-anio_gravable', '-bimestre')
        else:
            self.fields['corrige_a'].queryset = _Mod.objects.none()
        self.fields['corrige_a'].required = False

        for fname, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.Select):
                w.attrs.setdefault('class', 'form-select')
            elif isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault('class', 'form-check-input')
            else:
                w.attrs.setdefault('class', 'form-control')

        if self.perfil and not self.instance.pk:
            p = self.perfil
            self.fields['nombre_razon_social'].initial = p.nombre_razon_social or ''
            self.fields['tipo_documento'].initial = p.tipo_documento or ''
            self.fields['numero_documento'].initial = p.numero_documento or ''
            self.fields['dv'].initial = p.dv or ''
            self.fields['direccion_notificacion'].initial = p.direccion_notificacion or ''
            self.fields['municipio_notificacion'].initial = p.municipio_notificacion_id or ''
            self.fields['telefono'].initial = p.telefono or ''
            self.fields['correo_electronico'].initial = p.correo_electronico or ''
            self.fields['tipo_persona'].initial = p.tipo_persona or ''
            self.fields['clasificacion_contribuyente'].initial = p.clasificacion_contribuyente or ''

    def _parse_money(self, value):
        if not value:
            return 0
        cleaned = str(value).replace('.', '').replace(',', '').replace(' ', '').strip()
        try:
            return int(cleaned)
        except (ValueError, TypeError):
            return 0

    def clean_anio_gravable(self):
        val = self.cleaned_data.get('anio_gravable')
        if val and (val < 2000 or val > 2099):
            raise forms.ValidationError('El año gravable debe estar entre 2000 y 2099.')
        return val

    def clean_telefono(self):
        val = self.cleaned_data.get('telefono', '') or ''
        digits = val.replace(' ', '').replace('-', '')
        if digits and len(digits) != 10:
            raise forms.ValidationError('El teléfono debe tener exactamente 10 dígitos.')
        return digits

    def clean_corrige_a(self):
        opcion = self.cleaned_data.get('opcion_uso')
        corrige = self.cleaned_data.get('corrige_a')
        if opcion == 'CORRECCION' and not corrige:
            raise forms.ValidationError('Debe seleccionar la declaración que corrige.')
        return corrige

    def clean_sanciones(self):
        return self._parse_money(self.cleaned_data.get('sanciones'))

    def clean_intereses_mora(self):
        return self._parse_money(self.cleaned_data.get('intereses_mora'))

    def clean_devoluciones(self):
        return self._parse_money(self.cleaned_data.get('devoluciones'))

    def clean(self):
        cleaned = super().clean()
        from .models import DeclaracionRetencionICA as _Mod
        opcion = cleaned.get('opcion_uso')
        anio = cleaned.get('anio_gravable')
        bimestre = cleaned.get('bimestre')
        if opcion == 'INICIAL' and anio and bimestre and self.user:
            qs = _Mod.objects.filter(
                user=self.user, anio_gravable=anio, bimestre=bimestre, opcion_uso='INICIAL',
                firma_otp_verificada=True,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Ya existe una declaración inicial firmada para el Bimestre {bimestre} del año {anio}.'
                )
        return cleaned


class DeclaracionActividadReteForm(forms.Form):
    actividad_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    valor_base = forms.CharField(required=False, initial='0')
    tarifa = forms.CharField(required=False, initial='0')

    def _parse_money(self, val):
        if not val:
            return 0
        try:
            return int(str(val).replace('.', '').replace(',', '').strip())
        except (ValueError, TypeError):
            return 0

    def _parse_tarifa(self, val):
        if not val:
            return 0
        try:
            return float(str(val).replace(',', '.').strip())
        except (ValueError, TypeError):
            return 0

    def clean_valor_base(self):
        return self._parse_money(self.cleaned_data.get('valor_base'))

    def clean_tarifa(self):
        return self._parse_tarifa(self.cleaned_data.get('tarifa'))


# -------------------------
# CONFIGURACIÓN PDF
# -------------------------
from .models import ConfiguracionPDF


class ConfiguracionPDFForm(forms.ModelForm):
    """Formulario para configuración de PDFs."""

    class Meta:
        model = ConfiguracionPDF
        exclude = ['activo', 'created_at', 'updated_at']
        widgets = {
            'texto_instructivo': forms.Textarea(attrs={
                'rows': 6,
                'class': 'form-control',
                'placeholder': 'Una instrucción por línea...'
            }),
            'texto_pie_pagina': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Texto que aparecerá al final del PDF'
            }),
            'color_primario': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'style': 'width: 80px; height: 40px;'
            }),
            'color_secundario': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'style': 'width: 80px; height: 40px;'
            }),
            'color_radicado': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'style': 'width: 80px; height: 40px;'
            }),
            'color_exito': forms.TextInput(attrs={
                'type': 'color',
                'class': 'form-control form-control-color',
                'style': 'width: 80px; height: 40px;'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Aplicar clases Bootstrap a todos los campos
        for name, field in self.fields.items():
            if name.startswith('color_'):
                continue  # Ya tienen estilos especiales
            widget_name = field.widget.__class__.__name__
            if widget_name == "CheckboxInput":
                field.widget.attrs.update({"class": "form-check-input"})
            elif widget_name in ["Select", "SelectMultiple"]:
                field.widget.attrs.update({"class": "form-select"})
            elif widget_name == "Textarea":
                pass  # Ya tiene clase
            elif widget_name == "ClearableFileInput":
                field.widget.attrs.update({"class": "form-control"})
            else:
                if 'class' not in field.widget.attrs:
                    field.widget.attrs.update({"class": "form-control"})
