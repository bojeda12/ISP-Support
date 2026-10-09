# ISP Support

Backend modular para la demo de soporte técnico de un proveedor de Internet.
Primera entrega: estructura, configuración y endpoint de salud. No contiene datos
reales, integraciones con el ISP, IA ni modelos de negocio completos.

## Requisitos y dependencias

Windows 11, PowerShell y Python 3.14.5. Se conserva el entorno `.venv` existente.
Django 5.2 LTS admite Python 3.14 desde 5.2.8. Las versiones exactas instaladas
están fijadas en `requirements.txt`; DRF proporciona la API y asgiref, sqlparse y
tzdata son dependencias de Django (tzdata es necesaria en Windows).

## Inicio local

Desde la raíz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver
```

No es necesario activar el entorno virtual ni cambiar la política de ejecución.
Visitar `http://127.0.0.1:8000/api/health/` o ejecutar:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/
```

Devuelve HTTP 200, `application/json` y `{"status": "ok"}`. Es público y no
consulta la base de datos: verifica que la aplicación responde, no la disponibilidad
de servicios externos. POST devuelve HTTP 405.

## Estructura

- `config/`: configuración, selección de base de datos y rutas principales.
- `api/`: rutas HTTP, vista y pruebas de salud.
- `customers/`: futura lógica de clientes.
- `conversations/`: futuras conversaciones.
- `diagnostics/`: futuros diagnósticos.
- `tickets/`: futura gestión de tickets.
- `messaging/`: futura integración de mensajería.

Cada aplicación incluye `apps.py`, `models.py`, `admin.py`, `views.py`, `tests.py`
y `migrations/__init__.py`, generados por Django. Los modelos están vacíos.
Al implementar funcionalidades, ubicar los adaptadores HTTP en `api/` de cada
aplicación y la lógica de negocio en `services.py`, evitando lógica en vistas o
en configuración. No se crean abstracciones vacías adicionales en esta entrega.

## Variables de entorno

`.env.example` documenta las variables; no contiene secretos. **Los archivos
`.env` no se cargan automáticamente**: se utiliza `os.environ` para evitar otra
dependencia. Definir las variables en PowerShell antes de iniciar Django:

```powershell
$env:DJANGO_DEBUG = 'true'
$env:DJANGO_ALLOWED_HOSTS = 'localhost,127.0.0.1,[::1]'
$env:DB_ENGINE = 'sqlite'
```

SQLite guarda datos locales en `db.sqlite3`, excluido de Git. En desarrollo se
genera una clave efímera en cada proceso si `DJANGO_SECRET_KEY` está vacía; las
sesiones firmadas pueden invalidarse al reiniciar. Para una clave local estable:

```powershell
$env:DJANGO_SECRET_KEY = & .\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Con `DJANGO_DEBUG=false`, una clave explícita es obligatoria. El servidor de
desarrollo no es un despliegue de producción. Las futuras APIs requieren
autenticación por defecto; salud permite acceso anónimo.

## PostgreSQL posteriormente

La selección está preparada, pero no se instala un controlador ni se conecta
PostgreSQL en el día 1. Cuando exista una base autorizada, instalar una versión
de `psycopg[binary]` compatible con Python 3.14, fijarla en requirements.txt y
definir `DB_ENGINE=postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`
y `DB_PORT`. Todas son obligatorias en ese modo. Obtener credenciales por un
canal seguro y ejecutar migraciones sobre la base autorizada. Cambiar de motor
no transfiere automáticamente los datos de SQLite.

## Validación

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test --verbosity 2
```

Las pruebas comprueban respuesta HTTP, JSON, acceso anónimo, ausencia de acceso
a base de datos y rechazo de POST. No se requieren pytest ni servicios externos.
