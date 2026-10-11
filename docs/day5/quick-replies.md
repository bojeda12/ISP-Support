# Respuestas rápidas opcionales de Nexo

Implementadas opciones bilingües dentro de la conversación: Sin Internet, Internet lento, conexión intermitente, equipo sin energía y hablar con un técnico. Según la pregunta vigente se ofrecen confirmación de revisiones, ayuda, incertidumbre, imposibilidad de comprobar y asistencia humana.

No se añadieron respuestas predefinidas del asistente ni operaciones de diagnóstico/tickets en JavaScript. Las declaraciones de las opciones son mensajes del cliente. Django resuelve la opción, valida su referencia al último mensaje del asistente de la conversación autorizada y la entrega al mismo orquestador y adaptador de IA que el texto libre. La selección estructurada aparece en el contexto `customer_response` y en los metadatos del mensaje del cliente. La confirmación nunca se convierte en una medición verificada.

## Contrato compatible

`POST /api/chat/turn/` multipart acepta el campo opcional `quick_reply`: JSON con `id` y `question_message_id` (null para seleccionar una incidencia). El servidor produce el texto; el widget envía `message` vacío para una opción. Puede adjuntarse una foto en el mismo turno. El cliente no envía flags de autorización ni de comprobaciones completadas. Se conservan UUID de solicitud, CSRF, permisos, límites, almacenamiento privado y deduplicación existentes. Los reintentos devuelven el resultado guardado incluso si la pregunta ya fue respondida; cambiar la selección con el mismo UUID se rechaza. Se conserva también la huella original para solicitudes sin opciones.

Chat e historial incluyen `quick_replies` con etiquetas EN/ES y referencia a la pregunta. Solo el último mensaje del asistente tiene controles activos. Tras un ticket no se ofrecen otra vez las comprobaciones. Escribir un borrador deshabilita temporalmente las opciones para evitar perderlo; el compositor y el adjunto conservan su funcionamiento habitual. Los recursos del widget tienen una versión nueva para evitar JavaScript antiguo en caché.

## Evidencia de ejecución

Prueba de navegador con DemoAI, base SQLite temporal y constructor OpenAI bloqueado, sin llamadas facturables. Conversación 1:

1. Botón **No Internet**: diagnóstico 6, `CPE_UNREACHABLE`, 2026-10-10 20:36:38.184100 UTC. Una guía, sin ticket.
2. Botón **Yes, I checked**, pulsado en móvil: diagnóstico 7, `CPE_UNREACHABLE`, 2026-10-10 20:37:09.318611 UTC. Ticket **ISP-C3A8E07DA711**, estado **OPEN**. Sin nueva guía.
3. Texto libre **I still don't have Internet.**: mismo ticket; sin otro diagnóstico.

Comprobación directa de la base de prueba: 3 ChatTurn, 6 mensajes, 2 DiagnosticRun asociados y 1 Ticket. Esto demuestra operaciones ejecutadas, además de la respuesta visible. Datos completos en `quick-replies-proof.json`. La base principal no se modificó para estas pruebas.

Escritorio comprobado a 1366 × 900. Móvil solicitado a 390 × 844: ancho útil 375 px, scrollWidth 375 px, sin desbordamiento horizontal, opciones visibles, texto y adjunto habilitados. No hubo errores de consola. Capturas `quick-replies-mobile.jpg` y `quick-replies-ticket.jpg`.

OpenAI conserva su adaptador, configuración y decisión conversacional; esta verificación usa DemoAI y mocks. No se verificó una llamada facturable a OpenAI.

## Verificación manual en tres turnos

1. Reiniciar el servidor habitual: `.venv\Scripts\python.exe manage.py runserver`. Abrir http://127.0.0.1:8000/demo/ e iniciar sesión con un operador autorizado (`use_demo_chat`). Elegir English, seleccionar **DEMO-SERVICE-001** y pulsar **Connect to assistant**. Para una conversación nueva, si existe una anterior, cambiar a otro servicio y volver al 001 aceptando el aviso. El escenario debe ser el ficticio original de CPE sin respuesta.
2. Turno 1: pulsar **No Internet**. Esperar diagnóstico simulado y guía; recorrer la guía hasta las opciones finales.
3. Turno 2: en la demo, pulsar **Yes, I checked** para simular la confirmación de alimentación accesible, PoE si existe y cables de Internet. Debe aparecer un ticket **OPEN** con número real guardado y no otra guía completa.
4. Turno 3: escribir **I still don't have Internet.** y pulsar Send. Debe conservar el mismo número y estado, sin pedir las mismas comprobaciones. En español equivalen a **Sin Internet**, **Sí, lo revisé** y **Sigo sin Internet**.
5. Revisar los diagnósticos de la conversación y el ticket en Django Admin con los permisos correspondientes; deben existir dos mediciones y un ticket, no uno por cada clic o mensaje. El ticket anterior citado fue creado en una base temporal, por lo que el número de una nueva prueba será diferente.

## Pruebas

- `.venv\Scripts\python.exe manage.py test --noinput`: **314 pruebas aprobadas**, incluidas las anteriores y 11 nuevas.
- `node --check conversations/static/conversations/demo.js`: correcto.
- `node --test tests/frontend.test.cjs`: **12 pruebas aprobadas**.
- `.venv\Scripts\python.exe manage.py check`: sin incidencias.
- `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`: sin cambios.

Cobertura nueva: turno único e idempotente, recheck/ticket reales del simulador, persistencia de pregunta/contexto en el adaptador, texto libre después de opciones, foto y opción juntas, rechazo de preguntas antiguas/ajenas y datos falsificados, CSRF y autenticación, español, métricas de señal para Internet lento, ausencia de pruebas remotas de rendimiento ante falta de energía y solicitud directa de técnico.

## Archivos de esta ampliación

- `conversations/quick_replies.py`, `conversations/test_quick_replies.py` (nuevos).
- `conversations/serializers.py`, `api.py`, `turns.py`, `services.py`, `context.py`, `history_api.py`, `web.py`.
- `conversations/static/conversations/demo-core.js`, `demo.js`, `demo.css`.
- `conversations/templates/conversations/demo.html`.
- `tests/frontend.test.cjs`.
- Este informe, JSON de evidencia y capturas en `docs/day5/`.

No se añadieron dependencias ni migraciones. Se conservaron fotografías, manual, conocimiento indexado, zoom, reglas de tickets y diagnósticos, autenticación y autorización. No se inició SMS.

