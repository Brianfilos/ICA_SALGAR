import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0042_actividadeconomicarit_establecimiento'),
        ('catalogos', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeclaracionRetencionICA',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anio_gravable', models.PositiveIntegerField(verbose_name='Año gravable')),
                ('bimestre', models.CharField(choices=[('01', 'Bimestre 01'), ('02', 'Bimestre 02'), ('03', 'Bimestre 03'), ('04', 'Bimestre 04'), ('05', 'Bimestre 05'), ('06', 'Bimestre 06')], max_length=2, verbose_name='Bimestre')),
                ('opcion_uso', models.CharField(choices=[('INICIAL', 'Declaración inicial'), ('CORRECCION', 'Corrección')], default='INICIAL', max_length=20)),
                ('fecha_diligenciamiento', models.DateTimeField(auto_now_add=True)),
                ('nombre_razon_social', models.CharField(blank=True, max_length=255, null=True)),
                ('tipo_documento', models.CharField(blank=True, choices=[('CC', 'Cédula de ciudadanía'), ('NIT', 'NIT'), ('PASAPORTE', 'Pasaporte'), ('CE', 'Cédula de extranjería'), ('OTRO', 'Otro')], max_length=10, null=True)),
                ('numero_documento', models.CharField(blank=True, max_length=30, null=True)),
                ('dv', models.CharField(blank=True, max_length=2, null=True)),
                ('cual_documento', models.CharField(blank=True, max_length=60, null=True)),
                ('direccion_notificacion', models.CharField(blank=True, max_length=255, null=True)),
                ('telefono', models.CharField(blank=True, max_length=30, null=True)),
                ('correo_electronico', models.EmailField(blank=True, max_length=254, null=True)),
                ('numero_establecimientos', models.PositiveIntegerField(blank=True, null=True)),
                ('clasificacion_contribuyente', models.CharField(blank=True, choices=[('REGIMEN_COMUN', 'Régimen común de ICA'), ('REGIMEN_SIMPLE', 'Régimen simplificado'), ('OTRA', 'Otra')], max_length=30, null=True)),
                ('otra_clasificacion', models.CharField(blank=True, max_length=80, null=True)),
                ('tipo_persona', models.CharField(blank=True, choices=[('NATURAL', 'Natural'), ('JURIDICA', 'Jurídica')], max_length=10, null=True)),
                ('tipo_juridica', models.CharField(blank=True, choices=[('SOCIEDAD', 'Sociedad'), ('CONSORCIO', 'Consorcio'), ('UNION_TEMPORAL', 'Unión temporal'), ('PATRIMONIO_AUTONOMO', 'Patrimonio autónomo'), ('OTRO', 'Otro')], max_length=30, null=True)),
                ('otro_tipo_juridica', models.CharField(blank=True, max_length=100, null=True)),
                ('tipo_sancion', models.CharField(blank=True, choices=[('NINGUNA', 'Ninguna'), ('EXTEMPORANEIDAD', 'Extemporaneidad'), ('CORRECCION', 'Corrección'), ('INEXACTITUD', 'Inexactitud'), ('OTRA', 'Otra')], default='NINGUNA', max_length=20, null=True)),
                ('cual_sancion', models.CharField(blank=True, max_length=100, null=True)),
                ('sanciones', models.BigIntegerField(default=0)),
                ('intereses_mora', models.BigIntegerField(default=0)),
                ('devoluciones', models.BigIntegerField(default=0, verbose_name='Devoluciones, anulaciones, rescisiones, retenciones practicadas en exceso')),
                ('total_valor_retencion', models.BigIntegerField(default=0)),
                ('subtotal_retenciones', models.BigIntegerField(default=0, verbose_name='Subtotal retenciones menos devoluciones')),
                ('total_a_pagar', models.BigIntegerField(default=0)),
                ('tiene_contador', models.BooleanField(default=False)),
                ('tiene_revisor_fiscal', models.BooleanField(default=False)),
                ('contador_email', models.EmailField(blank=True, max_length=254, null=True)),
                ('revisor_email', models.EmailField(blank=True, max_length=254, null=True)),
                ('contador_firma_verificada', models.BooleanField(default=False)),
                ('revisor_firma_verificada', models.BooleanField(default=False)),
                ('contador_nombre', models.CharField(blank=True, max_length=120, null=True)),
                ('contador_tipo_documento', models.CharField(blank=True, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], max_length=3, null=True)),
                ('contador_numero_documento', models.CharField(blank=True, max_length=30, null=True)),
                ('contador_tarjeta_profesional', models.CharField(blank=True, max_length=30, null=True)),
                ('revisor_nombre', models.CharField(blank=True, max_length=120, null=True)),
                ('revisor_tipo_documento', models.CharField(blank=True, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], max_length=3, null=True)),
                ('revisor_numero_documento', models.CharField(blank=True, max_length=30, null=True)),
                ('revisor_tarjeta_profesional', models.CharField(blank=True, max_length=30, null=True)),
                ('rep_legal_email', models.EmailField(blank=True, max_length=254, null=True)),
                ('rep_legal_nombre', models.CharField(blank=True, max_length=120, null=True)),
                ('rep_legal_tipo_documento', models.CharField(blank=True, choices=[('CC', 'C.C.'), ('CE', 'C.E.'), ('TI', 'T.I.')], max_length=3, null=True)),
                ('rep_legal_numero_documento', models.CharField(blank=True, max_length=30, null=True)),
                ('firma_otp_verificada', models.BooleanField(default=False)),
                ('firma_timestamp', models.DateTimeField(blank=True, null=True)),
                ('firma_hash', models.CharField(blank=True, max_length=64, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('corrige_a', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='correcciones', to='tasks.declaracionretencionica')),
                ('departamento', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='retes_departamento', to='catalogos.departamento')),
                ('departamento_notificacion', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='retes_departamento_notificacion', to='catalogos.departamento')),
                ('municipio', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='retes_municipio', to='catalogos.municipio')),
                ('municipio_notificacion', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='retes_municipio_notificacion', to='catalogos.municipio')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Declaración Retención ICA',
                'verbose_name_plural': 'Declaraciones Retención ICA',
            },
        ),
        migrations.CreateModel(
            name='DeclaracionActividadRete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('valor_base', models.BigIntegerField(default=0)),
                ('tarifa', models.DecimalField(decimal_places=6, default=0, max_digits=10)),
                ('valor_retencion', models.BigIntegerField(default=0)),
                ('orden', models.PositiveSmallIntegerField(default=1)),
                ('actividad', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='catalogos.actividadeconomica')),
                ('declaracion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='actividades', to='tasks.declaracionretencionica')),
            ],
            options={
                'ordering': ['orden'],
            },
        ),
        migrations.CreateModel(
            name='FirmaOTPRete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=6)),
                ('creado_en', models.DateTimeField(auto_now_add=True)),
                ('usado', models.BooleanField(default=False)),
                ('tipo', models.CharField(choices=[('declarante', 'Declarante'), ('contador', 'Contador'), ('revisor', 'Revisor Fiscal')], default='declarante', max_length=20)),
                ('declaracion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='otps_firma', to='tasks.declaracionretencionica')),
            ],
            options={
                'ordering': ['-creado_en'],
            },
        ),
    ]
