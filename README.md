# Portal Tributario - Municipio de Ciudad Bolívar

Sistema de gestión tributaria para el Municipio de Ciudad Bolívar, Antioquia.
Desarrollado con Django 6.0.

---

## Requisitos

- Python 3.11 o superior
- Git
- Nginx
- Ubuntu / Debian

---

## Desarrollo local

### 1. Clonar el repositorio

```bash
git clone https://github.com/Brianfilos/ICA_CIUDADBOLIVAR.git
cd TU_REPO
```

### 2. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
source venv/bin/activate          # Linux/Mac
venv\Scripts\activate             # Windows

pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita el archivo `.env` con tus valores:

```
SECRET_KEY=tu-clave-secreta
DEBUG=True
SENDGRID_API_KEY=SG.tu-api-key
DEFAULT_FROM_EMAIL=noreply@portalterritorial.com.co
```

### 4. Ejecutar migraciones y arrancar el servidor

```bash
python manage.py migrate
python manage.py runserver
```

El portal estará disponible en `http://127.0.0.1:8000`

---

## Despliegue en producción (VPS Ubuntu/Debian via SSH)

### 1. Conectarse al servidor

```bash
ssh usuario@cbolivar.portalterritorial.com.co
```

### 2. Instalar dependencias del sistema

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv nginx git
```

### 3. Clonar el repositorio

```bash
cd /var/www
sudo mkdir cbolivar
sudo chown $USER:$USER cbolivar
cd cbolivar
git clone https://github.com/Brianfilos/ICA_CIUDADBOLIVAR.git .
```

### 4. Crear entorno virtual e instalar paquetes

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 5. Crear el archivo `.env` en el servidor

```bash
nano /var/www/cbolivar/.env
```

Contenido:

```
SECRET_KEY=tu-clave-secreta-de-produccion
DEBUG=False
SENDGRID_API_KEY=SG.tu-api-key
DEFAULT_FROM_EMAIL=noreply@portalterritorial.com.co
```

Guardar con `Ctrl+O`, `Enter`, `Ctrl+X`.

### 6. Migraciones y archivos estáticos

```bash
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
```

### 7. Configurar Gunicorn como servicio

Crear el archivo de servicio:

```bash
sudo nano /etc/systemd/system/cbolivar.service
```

Contenido:

```ini
[Unit]
Description=Gunicorn para Portal Tributario Ciudad Bolivar
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/cbolivar
ExecStart=/var/www/cbolivar/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/var/www/cbolivar/cbolivar.sock \
    djangocrud.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Activar el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl start cbolivar
sudo systemctl enable cbolivar
sudo systemctl status cbolivar
```

### 8. Configurar Nginx

```bash
sudo nano /etc/nginx/sites-available/cbolivar
```

Contenido:

```nginx
server {
    listen 80;
    server_name cbolivar.portalterritorial.com.co www.cbolivar.portalterritorial.com.co;

    location = /favicon.ico { access_log off; log_not_found off; }

    location /static/ {
        root /var/www/cbolivar/staticfiles;
    }

    location /media/ {
        root /var/www/cbolivar;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/cbolivar/cbolivar.sock;
    }
}
```

Activar el sitio:

```bash
sudo ln -s /etc/nginx/sites-available/cbolivar /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### 9. Certificado SSL (HTTPS)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d cbolivar.portalterritorial.com.co
```

Certbot configura HTTPS automáticamente y renueva el certificado solo.

---

## Actualizar en producción

Cada vez que se hagan cambios, ejecutar en el servidor:

```bash
cd /var/www/cbolivar
git pull origin main
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart cbolivar
```

---

## Variables de entorno

| Variable | Descripción | Requerida en producción |
|---|---|---|
| `SECRET_KEY` | Clave secreta de Django | Si |
| `DEBUG` | Modo debug (`True` / `False`) | Si (debe ser `False`) |
| `SENDGRID_API_KEY` | API Key de SendGrid para envío de correos | Si |
| `DEFAULT_FROM_EMAIL` | Correo remitente de los emails | Si |

---

## Tecnologías

- [Django 6.0](https://www.djangoproject.com/)
- [ReportLab](https://www.reportlab.com/) — Generación de PDFs
- [SendGrid](https://sendgrid.com/) — Envío de correos
- [django-import-export](https://django-import-export.readthedocs.io/) — Exportación Excel/CSV
- [Gunicorn](https://gunicorn.org/) — Servidor WSGI
- [Nginx](https://nginx.org/) — Servidor web

---

Desarrollado por [Legal Developments S.A.S.](https://legaldev.com.co)
