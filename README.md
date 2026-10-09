# ISP Support

Backend modular para la demo de soporte técnico de un proveedor de Internet.
Día 2: estructura, configuración, endpoint de salud, modelos de soporte y
administración de tickets. No contiene datos reales, integraciones con el ISP ni IA.

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

Los modelos y sus migraciones están en cada aplicación; `tickets/services.py`
centraliza creación y cambios de estado. El Admin utiliza estos servicios.
No existen endpoints públicos para modificar clientes o tickets.

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

Las pruebas cubren salud, relaciones, mensajes, tickets, transiciones, permisos,
historial, restricciones de duplicados y datos demo. No se requieren pytest ni
servicios externos.

## Modelos del Día 2

| Modelo | Relaciones y propósito |
| --- | --- |
| Customer | UUID interno, external_id único ficticio, nombre, contacto opcional y fechas |
| InternetService | Varios por cliente; identificador único, plan, velocidad y CPE opcional |
| Conversation | Cliente obligatorio, servicio opcional, idioma es/en, estado y fechas |
| Message | Varios por conversación; emisor, contenido y fecha; orden cronológico |
| DiagnosticRun | Servicio obligatorio, conversación opcional, escenario, resultado, JSON, fuente y fechas |
| Ticket | UUID, referencia ISP única, cliente, servicio, conversación opcional, incidencia, prioridad, estado, técnico y fechas |
| TicketEvent | Historial cronológico por ticket, usuario opcional y estados anterior/nuevo |

`InternetService.status` es administrativo (ACTIVE/SUSPENDED/CANCELLED);
`connectivity_status` es técnico (UNKNOWN/ONLINE/OFFLINE/DEGRADED). Una suspensión
no prueba un fallo de conectividad. Las relaciones principales usan PROTECT para
conservar referencias; borrar usuarios deja sus asignaciones y eventos con usuario
nulo. Los mensajes y eventos dependen de su conversación y ticket respectivamente.
La validación de modelos rechaza conversaciones, diagnósticos y tickets que
mezclen clientes o servicios. No utilizar actualizaciones masivas del ORM para
eludir estas validaciones o los servicios de negocio.

## Tickets y transiciones

Utilizar `create_ticket(...)` y `change_ticket_status(...)` de
`tickets/services.py`. Cada creación/cambio y su evento se guardan en una
transacción. Ejemplo desde `manage.py shell` con objetos ficticios existentes:

```python
from tickets.services import create_ticket, change_ticket_status

ticket = create_ticket(
    customer=customer, internet_service=service, conversation=conversation,
    incident_key="poe-disconnected", title="PoE desconectado",
    description="Incidencia ficticia para la demo",
)
ticket = change_ticket_status(ticket=ticket, new_status="IN_PROGRESS")
```

`incident_key` es una clave estable de la incidencia, normalizada a minúsculas.
Con conversación, repetir creación para la misma clave devuelve el ticket OPEN
o IN_PROGRESS existente sin sobrescribirlo ni duplicar su evento. Una restricción
única condicional protege también la base de datos. Sin conversación, cada llamada
crea un ticket independiente. Incidencias resueltas permiten un ticket nuevo;
reabrir el anterior se rechaza si ya existe otro activo para la misma clave.

| Estado actual | Siguientes estados permitidos |
| --- | --- |
| OPEN | IN_PROGRESS |
| IN_PROGRESS | OPEN, RESOLVED |
| RESOLVED | IN_PROGRESS, CLOSED |
| CLOSED | Ninguno |

Resolver fija `resolved_at`; reabrir lo limpia; cerrar conserva la fecha.
Cerrar requiere un usuario autenticado con permiso `tickets.close_ticket`.
El servicio se puede invocar internamente sin usuario para las demás operaciones;
un futuro adaptador público deberá aplicar autenticación y autorización.
Las garantías de transición e historial requieren utilizar el servicio, no
`Ticket.objects.update(...)` ni escrituras directas de estado.

## Datos ficticios

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py seed_demo
```

Cada ejecución conserva registros existentes. Crea como máximo tres clientes,
tres servicios y tres escenarios DiagnosticRun con source=simulation:

- DEMO-CUSTOMER-001: activo, sin conexión, PoE desconectado.
- DEMO-CUSTOMER-002: activo, conectividad degradada, señal débil y 8 Mbps simulados.
- DEMO-CUSTOMER-003: suspendido administrativamente, conectividad desconocida.

Los external_id y service_identifier DEMO-* son diferentes de los UUID/IDs
internos. El comando no crea tickets, conversaciones ni usuarios. No ejecuta
diagnósticos ni accede a equipos. Si un identificador reservado pertenece a otro
registro, aborta y revierte toda la ejecución sin modificar datos ajenos. No
restablece ediciones manuales de los datos demo.

## Django Admin

Crear un superusuario local de forma interactiva y arrancar el servidor:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

Entrar en `http://127.0.0.1:8000/admin/` con las credenciales elegidas. No guardar
contraseñas en el repositorio. Los siete modelos están registrados con búsquedas
y filtros. En Tickets se puede crear, asignar técnico, editar prioridad y cambiar
estado respetando las transiciones. El historial aparece en la ficha y es de solo
lectura; UUID, referencia y fechas calculadas tampoco se editan. Se registra el
usuario de cada cambio de estado y de las ediciones de campos en Admin.
Para delegar el cierre a personal sin superusuario, conceder `close_ticket`
además de los permisos habituales de acceso y cambio de tickets. El Admin
deshabilita la eliminación de tickets e historial.

