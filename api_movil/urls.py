from django.urls import path
from . import views

urlpatterns = [
    # ── Auth ──────────────────────────────────────
    path('auth/login/',   views.login_funcionario, name='api_login'),
    path('auth/refresh/', views.refresh_token,     name='api_refresh'),
    path('auth/perfil/',  views.perfil_funcionario, name='api_perfil'),

    # ── Visitas ───────────────────────────────────
    path('visitas/',          views.visitas_list_create, name='api_visitas'),
    path('visitas/<int:pk>/', views.visita_detalle,      name='api_visita_detalle'),

    # ── Fotos ─────────────────────────────────────
    path('visitas/<int:pk>/fotos/',       views.subir_fotos,       name='api_fotos'),

    # ── OTP Firma ─────────────────────────────────
    path('visitas/<int:pk>/enviar_otp/',  views.enviar_otp_visita,  name='api_enviar_otp'),
    path('visitas/<int:pk>/verificar_otp/', views.verificar_otp_visita, name='api_verificar_otp'),

    # ── Sync offline batch ────────────────────────
    path('sync/', views.sync_batch, name='api_sync'),

    # ── Catálogos ─────────────────────────────────
    path('catalogos/actividades/', views.actividades_economicas, name='api_actividades'),
    path('catalogos/municipios/',  views.municipios,             name='api_municipios'),

    # ── Visitas Precargadas ───────────────────────
    path('precargadas/',                     views.precargadas_list,       name='api_precargadas'),
    path('precargadas/<int:pk>/completar/',  views.completar_precargada,   name='api_completar_precargada'),

    # ── Censo de Establecimientos ─────────────────
    path('censo/consultar/',  views.consultar_nit,  name='api_censo_consultar'),
    path('censo/catalogo/',   views.catalogo_censo, name='api_censo_catalogo'),
]
