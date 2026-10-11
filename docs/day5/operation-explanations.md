# Explicación de operaciones confirmadas de Nexo

## Caso real inspeccionado (solo lectura)

Conversación 21, cliente 183 con texto y fotografía en un solo turno. No se ejecutó otra operación en esta conversación ni se modificaron sus mensajes históricos.

| Diagnóstico | Fecha UTC | Resultado |
|---|---|---|
| 47 | 2026-10-10 20:53:27.850885 | CPE_UNREACHABLE |
| 48 | 2026-10-10 20:53:52.554226 | CPE_UNREACHABLE |

Ticket **ISP-40016FEEB70A — OPEN**, creado 2026-10-10 20:53:52.556911 UTC.
La traza del mensaje 184 confirma `tool_result.executed=true`, `reason=authorized_simulation`, diagnóstico 48 y `ticket_created_this_turn=true`. Fue una medición nueva y un ticket nuevo; no se dedujo a partir de la mera presencia del ticket.
El proveedor configurado era OpenAI. La respuesta generada se rechazó por `missing_ticket_result`: faltaba el número confirmado del ticket. El texto final fue `django_template`, `answer_provider=django`, `fallback_used=true`. El fallback posterior sustituyó la respuesta que contenía el agradecimiento por un resumen de evidencias que omitía el reconocimiento y no distinguía claramente la nueva comprobación.
El mensaje inicial 182 sí fue de OpenAI y anunció un recheck planificado pese a que ya existía el diagnóstico 47. El validador de presentación también rechaza ahora ese tipo de anuncio futuro después de una operación confirmada.

## Antes / después

Cliente: “I checked the cables, router and PoE power. Everything is connected but Internet still doesn't work.” + fotografía.

Antes, mensaje histórico 184:

> The photo provides limited visual evidence; it cannot confirm Internet connectivity. You reported cable path, power, device/cable purpose. These local observations do not prove Internet access. The available simulated check cannot reach the outdoor equipment; the cause remains unconfirmed. Ticket ISP-40016FEEB70A: OPEN.

Después, respuesta realmente obtenida en una regresión aislada, con proveedor de clasificación/generación simulado que reproduce el rechazo `missing_ticket_result` (no es una nueva llamada real a OpenAI ni una modificación del historial 21):

> Thank you for completing the accessible checks you reported. In the photo: SIMULATED example: an equipment photo was received; its content was not interpreted. A photo cannot confirm working hardware or Internet connectivity. I checked your connection again in the simulator. The outdoor equipment is still not responding; the cause is not confirmed. Since the issue persists after your reported checks, I opened a support ticket for technical review. Ticket ISP-2BB7A2C34250: OPEN. You do not need to repeat the same checks. No visit or repair has been confirmed.

Operaciones de esa regresión:
- Diagnóstico 6: 2026-10-10 21:04:31.537584+00:00 UTC, CPE_UNREACHABLE.
- Diagnóstico 7: 2026-10-10 21:04:31.571240+00:00 UTC, CPE_UNREACHABLE.
- Ticket ISP-2BB7A2C34250 — OPEN; un recheck autorizado, una creación de ticket. La tercera intervención conserva ese ticket sin otra medición ni guía.
- Proveedor del texto final: Django, fallback `missing_ticket_result`. La foto de esta regresión es ficticia y su análisis contiene marcadores explícitos de simulación.

Cuando se reutiliza una medición:

> Thank you for completing the accessible checks you reported. I used the latest available simulated network check; no new measurement was taken. The outdoor equipment is still not responding; the cause is not confirmed. The recheck rate limit was reached. Since the issue persists after your reported checks, I opened a support ticket for technical review. Ticket ISP-7AD28BF51136: OPEN. You do not need to repeat the same checks. No visit or repair has been confirmed.

En esa regresión solo existe el diagnóstico 6, fecha 2026-10-10 21:04:31.396396+00:00. `executed=false`, `reason=frequency_limit`, `fresh=true`. La elegibilidad existente permite el ticket con ese resultado reciente; no se cambió esa regla.

## Cambios de presentación

- `operation_outcome` expone únicamente hechos confirmados a la respuesta, historial y trazas: ID/fecha/resultado/origen, ejecución `new` o `reused`, ticket `created` o `existing`, número y estado. Está sujeto a los permisos de conversación existentes.
- OpenAI recibe esos hechos y la indicación de reconocer las comprobaciones reportadas y la incertidumbre visual. Una respuesta válida de OpenAI se conserva; no se añade otra llamada para mejorar la redacción.
- El fallback explica reconocimiento, foto, resultado y escalamiento en inglés/español. Una foto jamás verifica hardware, energía o conectividad. No se prometen visitas, asignaciones ni reparaciones.
- El validador rechaza mediciones nuevas inventadas sobre resultados reutilizados y creación inventada de un ticket ya existente. No altera umbrales ni acciones autorizadas.
- La API multipart es síncrona: no hay eventos SSE/WebSocket, canal de progreso ni etapas consultables mientras trabaja. Se reutiliza el indicador existente con “Reviewing your message and connection-check request…” / “Revisando tu mensaje y la solicitud de comprobación…”. Es un estado de solicitud en curso, no una afirmación de ejecución. Aparece al enviar y termina al resolver/error; no hay temporizador artificial, turno adicional ni operación paralela.
- Una medición nueva solo se anuncia cuando Django la confirma. Se mantiene la deduplicación por request_id y la ruta combinada de texto/foto.
- Las reglas vigentes de handoff impiden reiniciar cuestionarios; la redacción respeta ese estado. Texto libre, opciones rápidas, fotografías, manual, zoom y estilo se conservan.

## Verificación

`.venv\Scripts\python.exe manage.py test --noinput`: **324 pruebas Django**, incluidas las anteriores y 10 nuevas.
`node --test tests/frontend.test.cjs`: **13 pruebas aprobadas**.
`node --check conversations/static/conversations/demo.js`: correcto.
`manage.py check`: sin incidencias. `manage.py makemigrations --check --dry-run`: sin cambios.
Pruebas nuevas: foto + comprobaciones, nuevo recheck fallido, reutilización reciente, resultado saludable, fallo/timeout de herramienta, ticket nuevo/existente, respuesta inválida, inglés/español, reintentos sin duplicados y salida válida de IA con una clasificación y una generación. OpenAI real no se invocó; SDK bloqueado en la exportación de evidencia.
La evidencia exacta está en `operation-explanations-proof.json`. Las fechas de regresión corresponden a una base temporal de pruebas. La prueba del indicador es de integración de JavaScript/código; no se capturaron en este cambio eventos de progreso intermedio del servidor, porque no existen.

## Archivos modificados

- Nuevos: `conversations/operation_explanations.py`, `conversations/test_operation_explanations.py`.
- `conversations/services.py`, `conversations/decisions.py`, `conversations/adaptive.py` (solo validación del texto), `conversations/ai.py`, `conversations/history_api.py`.
- `conversations/static/conversations/demo.js`, `conversations/templates/conversations/demo.html`, `tests/frontend.test.cjs`.
- Este informe y `docs/day5/operation-explanations-proof.json`.

No se añadieron dependencias ni migraciones. No se modificaron diagnósticos, elegibilidad, deduplicación, autenticación, autorización ni fotografías. Sin errores pendientes. Reiniciar el servidor habitual y recargar `/demo/` para cargar el código y los recursos versionados.
