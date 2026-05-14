from django.contrib import admin
from .models import VisitaRIT, PerfilFuncionario, CensoEstablecimientos
from . import views as censo_views


@admin.register(CensoEstablecimientos)
class CensoEstablecimientosAdmin(admin.ModelAdmin):
    list_display  = ('descripcion', 'archivo', 'actualizado')
    readonly_fields = ('actualizado',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        censo_views._censo_cache.clear()  # invalidar caché en memoria


@admin.register(PerfilFuncionario)
class PerfilFuncionarioAdmin(admin.ModelAdmin):
    list_display = ('user', 'cargo', 'dependencia', 'activo')
    list_filter  = ('activo',)
