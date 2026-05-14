import csv
import io
from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from .models import (
    Proceso, AccesoProceso,
    RegistroRIT,
    DeclaracionICA, DeclaracionActividad,
    AutoRetencionICA, RetencionICA,
    ConfiguracionPDF, PerfilContribuyente
)


# ─────────────────────────────────────────────
# Acción genérica de exportar CSV (sábana completa)
# ─────────────────────────────────────────────
def exportar_csv(modeladmin, request, queryset):
    """Exporta todos los campos del queryset seleccionado a CSV."""
    meta = modeladmin.model._meta
    field_names = [f.name for f in meta.fields]

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{meta.model_name}_export.csv"'

    writer = csv.writer(response)
    # Cabecera con nombres de campo
    writer.writerow([f.verbose_name.upper() if hasattr(f, 'verbose_name') else f.name for f in meta.fields])

    for obj in queryset:
        row = []
        for field in field_names:
            val = getattr(obj, field, '')
            # Campos con choices: mostrar el texto legible
            display = getattr(obj, f'get_{field}_display', None)
            if display:
                val = display()
            if val is None:
                val = ''
            row.append(str(val))
        writer.writerow(row)

    return response

exportar_csv.short_description = "📥 Exportar seleccionados a CSV"


class TaskAdmin(admin.ModelAdmin):
    readonly_fields = ("created",)


@admin.register(ConfiguracionPDF)
class ConfiguracionPDFAdmin(admin.ModelAdmin):
    """Admin personalizado para configuración de PDFs."""

    list_display = ('nombre', 'nombre_entidad', 'activo_badge', 'preview_colores', 'updated_at')
    list_filter = ('activo',)
    search_fields = ('nombre', 'nombre_entidad', 'nombre_municipio')
    actions = [exportar_csv]

    fieldsets = (
        ('Estado', {
            'fields': ('nombre', 'activo'),
            'classes': ('wide',),
        }),
        ('Logos', {
            'fields': ('logo_izquierdo', 'logo_derecho'),
            'description': 'Suba los logos que aparecerán en el encabezado de los PDFs.',
        }),
        ('Información de la Entidad', {
            'fields': ('nombre_entidad', 'nombre_municipio', 'slogan'),
        }),
        ('Colores del PDF', {
            'fields': ('color_primario', 'color_secundario', 'color_radicado', 'color_exito'),
            'description': 'Configure los colores usando formato hexadecimal (#RRGGBB).',
        }),
        ('Instructivo (pie de página)', {
            'fields': ('mostrar_instructivo', 'texto_instructivo'),
            'classes': ('collapse',),
        }),
        ('Instructivo ICA – Página 2 del PDF', {
            'fields': ('instructivo_ica_col_izquierda', 'instructivo_ica_col_derecha'),
            'classes': ('collapse',),
            'description': (
                'Textos de la segunda página del PDF de Declaración ICA. '
                'Use ## TÍTULO para encabezados en negrita. Separe bloques con una línea en blanco.'
            ),
        }),
        ('Pie de Página', {
            'fields': ('texto_pie_pagina',),
            'classes': ('collapse',),
        }),
        ('Datos de Contacto', {
            'fields': ('direccion_entidad', 'telefono_entidad', 'email_entidad', 'sitio_web'),
            'classes': ('collapse',),
        }),
    )

    def activo_badge(self, obj):
        if obj.activo:
            return format_html(
                '<span style="background-color: #27ae60; color: white; padding: 3px 10px; '
                'border-radius: 3px; font-weight: bold;">✓ ACTIVA</span>'
            )
        return format_html(
            '<span style="background-color: #95a5a6; color: white; padding: 3px 10px; '
            'border-radius: 3px;">Inactiva</span>'
        )
    activo_badge.short_description = 'Estado'

    def preview_colores(self, obj):
        return format_html(
            '<span style="display: inline-block; width: 20px; height: 20px; '
            'background-color: {}; border: 1px solid #ccc; margin-right: 3px;" title="Primario"></span>'
            '<span style="display: inline-block; width: 20px; height: 20px; '
            'background-color: {}; border: 1px solid #ccc; margin-right: 3px;" title="Secundario"></span>'
            '<span style="display: inline-block; width: 20px; height: 20px; '
            'background-color: {}; border: 1px solid #ccc; margin-right: 3px;" title="Radicado"></span>'
            '<span style="display: inline-block; width: 20px; height: 20px; '
            'background-color: {}; border: 1px solid #ccc;" title="Éxito"></span>',
            obj.color_primario, obj.color_secundario, obj.color_radicado, obj.color_exito
        )
    preview_colores.short_description = 'Colores'


@admin.register(PerfilContribuyente)
class PerfilContribuyenteAdmin(admin.ModelAdmin):
    list_display = ('user', 'nombre_razon_social', 'tipo_documento', 'numero_documento', 'municipio_notificacion')
    search_fields = ('user__username', 'nombre_razon_social', 'numero_documento')
    list_filter = ('tipo_documento', 'tipo_persona', 'clasificacion_contribuyente')
    actions = [exportar_csv]


@admin.register(RegistroRIT)
class RegistroRITAdmin(admin.ModelAdmin):
    list_display = ('radicado', 'nombre_razon_social', 'numero_documento', 'opcion_uso', 'estado', 'fecha')
    search_fields = ('radicado', 'nombre_razon_social', 'numero_documento')
    list_filter = ('opcion_uso', 'estado', 'clase_contribuyente')
    date_hierarchy = 'fecha'
    ordering = ('-fecha',)
    actions = [exportar_csv]


@admin.register(DeclaracionICA)
class DeclaracionICAAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'municipio', 'anio_gravable', 'opcion_uso', 'total_a_pagar_fmt', 'fecha_diligenciamiento')
    search_fields = ('user__username', 'numero_documento', 'nombre_razon_social')
    list_filter = ('anio_gravable', 'opcion_uso', 'municipio')
    date_hierarchy = 'fecha_diligenciamiento'
    ordering = ('-fecha_diligenciamiento',)
    actions = [exportar_csv]

    def total_a_pagar_fmt(self, obj):
        return f"${obj.total_a_pagar:,.0f}".replace(',', '.')
    total_a_pagar_fmt.short_description = 'Total a Pagar'


@admin.register(DeclaracionActividad)
class DeclaracionActividadAdmin(admin.ModelAdmin):
    list_display = ('declaracion', 'actividad', 'ingresos_gravados', 'tarifa_aplicada', 'impuesto')
    search_fields = ('declaracion__nombre_razon_social', 'actividad__nombre')
    list_filter = ('actividad',)
    actions = [exportar_csv]


@admin.register(AutoRetencionICA)
class AutoRetencionICAAdmin(admin.ModelAdmin):
    actions = [exportar_csv]


@admin.register(RetencionICA)
class RetencionICAAdmin(admin.ModelAdmin):
    actions = [exportar_csv]


admin.site.register(Proceso)
admin.site.register(AccesoProceso)
