from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin

from .models import Departamento, Municipio, ActividadEconomica


# ---------- RESOURCES (definen qué campos se importan/exportan) ----------

class DepartamentoResource(resources.ModelResource):
    class Meta:
        model = Departamento
        fields = ("id", "nombre", "activo")
        import_id_fields = ("nombre",)  # evita duplicados por nombre


class MunicipioResource(resources.ModelResource):
    class Meta:
        model = Municipio
        fields = ("id", "nombre", "departamento", "activo")
        import_id_fields = ("nombre", "departamento")


class ActividadEconomicaResource(resources.ModelResource):
    class Meta:
        model = ActividadEconomica
        fields = ("id", "codigo", "nombre", "tipo", "tarifa", "activo")
        import_id_fields = ("codigo",)


# ---------- ADMIN con botones Import/Export ----------

@admin.register(Departamento)
class DepartamentoAdmin(ImportExportModelAdmin):
    resource_class = DepartamentoResource
    list_display = ("nombre", "activo")
    search_fields = ("nombre",)
    list_filter = ("activo",)


@admin.register(Municipio)
class MunicipioAdmin(ImportExportModelAdmin):
    resource_class = MunicipioResource
    list_display = ("nombre", "departamento", "activo")
    search_fields = ("nombre",)
    list_filter = ("departamento", "activo")


@admin.register(ActividadEconomica)
class ActividadEconomicaAdmin(ImportExportModelAdmin):
    resource_class = ActividadEconomicaResource
    list_display = ("codigo", "nombre", "tipo", "tarifa", "activo")
    search_fields = ("codigo", "nombre")
    list_filter = ("tipo", "activo")

