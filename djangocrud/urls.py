"""
URL configuration for djangocrud project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from tasks import views
from django.conf.urls.static import static
urlpatterns = [
    path('admin/', admin.site.urls),
    path('',views.home,name='home'),
    path('signup/',views.signup,name='signup'),
    path('bienvenida/', views.bienvenida, name='bienvenida'),
    path('gestion/', views.admin_panel, name='admin_panel'),
    path('gestion/usuarios/', views.admin_usuarios, name='admin_usuarios'),
    path('gestion/usuarios/<int:user_id>/accesos/', views.admin_accesos, name='admin_accesos'),
    path('gestion/configuracion-pdf/', views.admin_config_pdf, name='admin_config_pdf'),
    path('gestion/reportes/', views.admin_reportes, name='admin_reportes'),
    path("proceso/RIT/", views.proceso_rit, name="proceso_rit"),
    path("proceso/RIT/verificar-firma/<int:registro_id>/", views.verificar_firma_rit, name="verificar_firma_rit"),
    path("proceso/ICA/", views.proceso_ica, name="proceso_ica"),
    path("proceso/ICA/verificar-firma/<int:declaracion_id>/", views.verificar_firma_ica, name="verificar_firma_ica"),
    path("proceso/ICA/reiniciar-firma/<int:declaracion_id>/", views.reiniciar_firma_ica, name="reiniciar_firma_ica"),
    path("proceso/AUTO/", views.proceso_auto, name="proceso_auto"),
    path("proceso/AUTO/verificar-firma/<int:declaracion_id>/", views.verificar_firma_auto, name="verificar_firma_auto"),
    path("proceso/AUTO/reiniciar-firma/<int:declaracion_id>/", views.reiniciar_firma_auto, name="reiniciar_firma_auto"),
    path("pdf/auto/<int:auto_id>/", views.generar_pdf_auto, name="pdf_auto"),
    path("proceso/RETE/", views.proceso_rete, name="proceso_rete"),
    path('tasks/',views.tasks,name='tasks'),
    path('tasks/completed',views.tasks_completed,name='tasks_completed'),
    path('tasks/<int:task_id>/',views.task_detail,name='task_detail'),
    path('tasks/<int:task_id>/complete',views.complete_task,name='complete_task'),
    path('tasks/<int:task_id>/delete', views.delete_task, name='delete_task'),
    path('logout/',views.signout,name='logout'),
    path('signin/', views.signin, name='signin'),
    path('recuperar-contrasena/', views.recuperar_contrasena, name='recuperar_contrasena'),
    path('password-reset/', RedirectView.as_view(url='/recuperar-contrasena/', permanent=True)),
    path('verificar-codigo/', views.verificar_codigo, name='verificar_codigo'),
    path('nueva-contrasena/', views.nueva_contrasena, name='nueva_contrasena'),
    path('cambiar-contrasena/', views.cambiar_contrasena, name='cambiar_contrasena'),
    # PDFs
    path('pdf/rit/<int:rit_id>/', views.generar_pdf_rit, name='pdf_rit'),
    path('pdf/rit/<int:rit_id>/pub/<str:token>/', views.generar_pdf_rit_publico, name='pdf_rit_publico'),
    path('pdf/ica/<int:ica_id>/', views.generar_pdf_ica, name='pdf_ica'),
    path('mis-visitas/',          views.mis_visitas,              name='mis_visitas'),
    path('mis-visitas/nueva/',    views.nueva_visita_web,         name='nueva_visita_web'),
    path('mis-visitas/json/actividades/', views.json_actividades_visita, name='json_actividades_visita'),
    path('mis-visitas/json/municipios/',  views.json_municipios_visita,  name='json_municipios_visita'),
    path('pdf/visita/<int:visita_id>/', views.generar_pdf_visita_movil, name='pdf_visita_movil'),
    path('pdf/visita/<int:visita_id>/formulario/', views.generar_pdf_formulario_rit_movil, name='pdf_formulario_rit_movil'),
    # API móvil
    path('api/movil/', include('api_movil.urls')),
    # Exportación Excel/CSV
    path('gestion/reportes/exportar/visitas/excel/', views.exportar_visitas_excel, name='exportar_visitas_excel'),
    path('gestion/reportes/exportar/rit/excel/', views.exportar_excel_rit, name='exportar_excel_rit'),
    path('gestion/reportes/exportar/ica/excel/', views.exportar_excel_ica, name='exportar_excel_ica'),
    path('gestion/reportes/exportar/rit/csv/', views.exportar_csv_rit, name='exportar_csv_rit'),
    path('gestion/reportes/exportar/ica/csv/', views.exportar_csv_ica, name='exportar_csv_ica'),
    path('gestion/reportes/exportar/auto/excel/', views.exportar_excel_auto, name='exportar_excel_auto'),
    path('gestion/reportes/exportar/auto/csv/', views.exportar_csv_auto, name='exportar_csv_auto'),
]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)