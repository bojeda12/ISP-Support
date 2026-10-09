# ISP Support

Backend modular para la demo de soporte técnico de un proveedor de Internet.
Día 3: modelos de soporte, administración de tickets y motor de diagnóstico con
simulación determinista. No contiene datos reales, integraciones con el ISP ni IA.

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

Cada ejecución conserva registros existentes. Crea como máximo cinco clientes,
cinco servicios y una ejecución inicial por servicio sin historial simulado:

- DEMO-CUSTOMER-001: activo, sin conexión, PoE desconectado.
- DEMO-CUSTOMER-002: activo, conectividad degradada y señal débil.
- DEMO-CUSTOMER-003: suspendido administrativamente, conectividad desconocida.
- DEMO-CUSTOMER-004: activo, conexión aparentemente normal.
- DEMO-CUSTOMER-005: activo, señal aceptable y rendimiento bajo.

Los external_id y service_identifier DEMO-* son diferentes de los UUID/IDs
internos. El comando no crea tickets, conversaciones ni usuarios. No ejecuta
diagnósticos ni accede a equipos. Si un identificador reservado pertenece a otro
registro, aborta y revierte toda la ejecución sin modificar datos ajenos. No
restablece ediciones manuales de los datos demo.

Los escenarios se guardan en `diagnostics.SimulationState`, uno por servicio.
Repetir el seed no cambia el escenario actual ni añade diagnósticos si ya existe
historial simulado. Los diagnósticos del Día 2 se conservan tal como estaban;
sus campos nuevos `result_code` y `assessment` quedan vacíos. Las nuevas
ejecuciones tienen métricas y evaluaciones completas.

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

## Motor de diagnóstico del Día 3

- `diagnostics/simulation.py`: cinco escenarios deterministas y `NetworkMetrics`.
  No contiene llamadas de red. La descarga se calcula respecto al plan contratado.
- `diagnostics/thresholds.py`: RSSI mínimo -75 dBm, SNR mínimo 20 dB, descarga
  mínima 70% del plan, latencia máxima 100 ms y pérdida máxima 3%. Son valores
  exclusivos de la simulación, no criterios universales ni recomendaciones para
  infraestructura real. Los valores en el límite se consideran aceptables.
- `diagnostics/engine.py`: primero distingue suspensión/inactividad administrativa;
  después evalúa ausencia de respuesta, señal y rendimiento, en ese orden.
  Datos incompletos no bastan para afirmar recuperación. Devuelve código, resumen,
  hallazgos, recomendaciones, siguiente acción y sugerencia de escalamiento.
- `diagnostics/services.py`: relee el estado administrativo desde el ORM, consulta
  únicamente servicios inscritos en la demo y guarda una nueva ejecución atómica.
  Un servicio suspendido/cancelado no invoca el simulador técnico. No modifica el
  estado administrativo ni `InternetService.connectivity_status`; el diagnóstico
  conserva su propia instantánea de métricas.
- `diagnostics/api.py` y `serializers.py`: adaptación HTTP, validación y permisos.

La migración `diagnostics/0002_alter_diagnosticrun_options_diagnosticrun_assessment_and_more`
añade `SimulationState`, `result_code`, `assessment` y el permiso interno sin
eliminar ni reinterpretar resultados previos. `result` conserva las categorías
UNKNOWN/PASSED/FAILED/DEGRADED. El Admin permite consultar los diagnósticos como
historial de solo lectura.

| Servicio ficticio | Escenario inicial | Código esperado |
| --- | --- | --- |
| DEMO-SERVICE-001 | CPE_OFFLINE | CPE_UNREACHABLE |
| DEMO-SERVICE-002 | WEAK_SIGNAL | SIGNAL_DEGRADED |
| DEMO-SERVICE-003 | ADMIN_SUSPENDED | SERVICE_SUSPENDED |
| DEMO-SERVICE-004 | HEALTHY | NO_FAULT_DETECTED |
| DEMO-SERVICE-005 | LOW_THROUGHPUT | PERFORMANCE_DEGRADED |

## Ejecutar y presentar los escenarios

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-001
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-002
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-003
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-004
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-005
```

Cada comando devuelve JSON y añade un DiagnosticRun. Para presentar recuperación:

```powershell
# Preparar desconexión ficticia y registrar el antes.
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-001 --scenario CPE_OFFLINE
# Tras confirmar la intervención ficticia del cliente, registrar el después.
.\.venv\Scripts\python.exe manage.py demo_diagnostic DEMO-SERVICE-001 --scenario HEALTHY
```

La intervención solo cambia el escenario simulado. No confirma que el PoE fuera
la causa original ni toca equipos. El comando requiere acceso local de operador;
no es una operación disponible mediante la API. `ADMIN_SUSPENDED` requiere que
el servicio ya esté suspendido en su estado administrativo y el comando no cambia
ese estado. Los operadores pueden cambiarlo conscientemente desde el Admin.

## API interna

`POST /api/diagnostics/run/` exige autenticación, `is_staff=True` y el permiso
`diagnostics.run_simulated_diagnostic` (o superusuario). No basta con ser personal
sin el permiso. El acceso es global a los servicios de la demo para ese personal.
Utiliza la autenticación existente de DRF: sesión con CSRF o autenticación básica
para desarrollo local. No se añade un sistema de tokens.

El cuerpo utiliza el ID entero real de InternetService, visible en Admin o shell,
y el ID entero opcional de Conversation. No utiliza el UUID del cliente ni el
identificador externo en lugar de ese ID. Consultar los IDs locales:

```powershell
.\.venv\Scripts\python.exe manage.py shell -c "from customers.models import InternetService; print(list(InternetService.objects.values('id', 'service_identifier')))"
```

Ejemplo de cuerpo (sustituir 1 por el ID local):

```json
{"service_id": 1}
```

Respuesta HTTP 201; extracto de una CPE sin respuesta:

```json
{
  "service_id": 1,
  "scenario": "CPE_OFFLINE",
  "result": "FAILED",
  "result_code": "CPE_UNREACHABLE",
  "source": "simulation",
  "metrics": {
    "cpe_online": false,
    "rssi_dbm": null,
    "snr_db": null,
    "latency_ms": null,
    "packet_loss_percent": null,
    "download_mbps": null,
    "ap_identifier": null
  }
}
```

Extracto tras recuperación con plan de 100 Mbps:

```json
{
  "scenario": "HEALTHY",
  "result_code": "NO_FAULT_DETECTED",
  "metrics": {
    "cpe_online": true,
    "rssi_dbm": -58,
    "snr_db": 30,
    "latency_ms": 12,
    "packet_loss_percent": 0,
    "download_mbps": 95.0,
    "ap_identifier": "DEMO-AP-01"
  }
}
```

La respuesta completa también incluye `id`, `conversation_id`, `result`, `source`,
`assessment` con las explicaciones y `started_at`, `completed_at`, `created_at`.
Una suspensión devuelve SERVICE_SUSPENDED, métricas completamente nulas y acción
CONTACT_ADMINISTRATION, sin escalamiento técnico. No ofrece reactivación automática.

Sin autenticación o permiso responde 403 con la configuración actual de sesión;
entradas inválidas, IDs inexistentes, servicio fuera de la demo o conversación
incompatible responden 400. GET responde 405 para personal autorizado. Campos
adicionales, incluido `scenario`, se rechazan: no se pueden inyectar métricas ni
seleccionar escenarios desde HTTP. No crea tickets automáticamente.

## Escalamiento explícito

`escalation_payload(run)` entrega cliente/servicio, ejecución, código, resumen,
mediciones, acciones recomendadas y prioridad. Devuelve None cuando no corresponde
escalamiento técnico. Para CPE_UNREACHABLE recomienda primero comprobar alimentación
y cables accesibles y repetir el diagnóstico; el PoE es solo una posible causa.
Señal débil y rendimiento bajo proponen revisión técnica con prioridad MEDIUM;
ausencia de respuesta propone HIGH. No hay escalamiento técnico por suspensión.

`escalate_diagnostic(run=run, user=operator)` es una decisión explícita del operador
o de un futuro orquestador. Reutiliza `tickets.services.create_ticket` y requiere
que la ejecución tenga conversación para garantizar su control de duplicados.
La clave estable es `diagnostic-<service_id>-<result_code en minúsculas>`. Repetir el escalamiento
para la misma conversación/servicio/clasificación reutiliza el ticket activo y no añade
otro evento. Sin conversación se rechaza; no crea conversaciones artificiales.
No cambia ni cierra tickets después de una recuperación.

## Límites de esta entrega

No hay mediciones reales, IA, SMS, adaptadores de red ni automatización completa
del diálogo. El éxito simulado confirma únicamente las métricas de la demo. Las
reglas y umbrales requieren validación del ISP antes de usarse con datos reales.
La siguiente entrega podrá integrar el flujo conversacional sobre estos servicios;
el Día 4 no está implementado.
