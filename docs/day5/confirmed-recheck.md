# Confirmación, recheck y ticket: ejecución comprobada

## Lo que ocurrió en la conversación real 18

Se inspeccionó la conversación local más reciente, sin enviar imágenes ni mensajes a OpenAI.
Los metadatos originales se conservan en `confirmed-recheck-proof.json`.

| Respuesta | Proveedor / modelo | Propuesta estructurada | Operación real | Resultado / bloqueo |
|---|---|---|---|---|
| 164 | OpenAI / gpt-4.1-mini | REQUEST_NECESSARY_EVIDENCE | authorized_recheck: diagnóstico 41 | CPE_UNREACHABLE; fallback redundant_evidence_request |
| 166 | OpenAI / gpt-4.1-mini | RUN_AUTHORIZED_RECHECK | authorized_recheck: diagnóstico 42 | CPE_UNREACHABLE; confirmación registrada como attempted_uncertain; fallback redundant_evidence_request |
| 168 | OpenAI / gpt-4.1-mini | RUN_AUTHORIZED_RECHECK | authorized_recheck: reutiliza 42 | no_new_evidence; respuesta OpenAI aceptada, pero anuncia el recheck como futuro |
| 170 | OpenAI / gpt-4.1-mini | RUN_AUTHORIZED_RECHECK | authorized_recheck: reutiliza 42 | no_new_evidence; respuesta OpenAI aceptada, vuelve a proponer recheck |

El diagnóstico 41 terminó el **2026-10-10 19:01:41.500031 UTC**; el 42 terminó el
**19:02:10.620903 UTC**. Por tanto, sí hubo una segunda medición. No fue un límite de
frecuencia ni una autorización denegada: después se reutilizó un resultado fresco.

Se intentó clasificar y generar con OpenAI en los cuatro turnos. La clasificación fue
exitosa en todos; la redacción fue rechazada en 164/166 y aceptada en 168/170. El fallback
no perdió el recheck de 166. El bloqueo real fue doble:

1. Una confirmación explícita de comprobaciones guiadas quedó como intento incierto.
   Se usó la política de revisión inconclusa, cuyo predicado `available_evidence_reviewed`
   seguía siendo falso con una foto y sin agotamiento de evidencia. Aunque ya había dos
   mediciones fallidas, no se llamó al servicio de tickets. Resultado: **2 diagnósticos,
   0 tickets** en esa conversación.
2. La validación de la redacción no rechazaba hablar de una operación futura cuando
   Django ya la había ejecutado o reutilizado. Se mostraba una propuesta como siguiente paso.

## Cambio mínimo de orquestación

Se reutiliza la comprobación existente `explicit_completed_report`: ante un reporte explícito
de comprobaciones guiadas, sin incertidumbre expresada por el cliente, la interpretación
alcanza `CONFIRM_PHYSICAL_CHECK` aunque OpenAI la clasifique como comentario sobre una foto.
Se registra `customer_reported_complete` con `verified=False`; no se certifica cableado ni Internet.

Esta es la ruta de confirmación que ya existía: llama a `authorized_recheck`, aplica sus
permisos y límites y llama a la escalación existente cuando la evaluación lo permite.
No se cambiaron `review_eligibility`, el simulador ni los servicios de tickets. La política
inconclusa sigue exigiendo sus predicados anteriores; la confirmación completa utiliza la
política existente de comprobaciones declaradas completas, no una relajación de aquella.

La respuesta se genera con el diagnóstico y ticket reales después de las operaciones.
Las trazas distinguen `confirmed_report_existing_policy` de `inconclusive_review_existing_policy`.
Se rechazan respuestas que omiten un ticket confirmado o presentan una medición disponible
como recheck pendiente; el fallback conserva el resultado y número reales.
La reutilización incluye ID, timestamp, frescura y motivo. Un resultado caducado bloqueado
por frecuencia no autoriza escalamiento por la ruta de confirmación.

Timeout o salida inválida de clasificación conservan el reporte explícito y pueden alcanzar
la misma ruta autorizada. Se actualizó una prueba previa que exigía no ejecutar nada ante
timeout: ahora verifica recheck, ticket e historial, conforme al comportamiento solicitado.
No se eliminó ni deshabilitó ninguna prueba.

## Prueba real de navegador con DemoAI

Se utilizó una base temporal nueva, servidor sólo en loopback, operador temporal con el
permiso normal `use_demo_chat`, CSRF activo, `AI_PROVIDER=demo`, clave vacía y constructor
del SDK bloqueado. La base habitual no se modificó. No se usaron fotografías privadas.

Secuencia introducida por la interfaz:

1. `I don't have Internet.`
2. `Yes, I checked the power and cables. The PoE has power and everything is connected.`
3. `I still don't have Internet.`

| Momento | Diagnósticos de la conversación | Ticket |
|---|---:|---|
| Antes | 0 | ninguno |
| Reporte inicial | 1 | ninguno |
| Confirmación | 2 | ISP-DDD8F12242C1 · OPEN |
| Queja posterior | 2 | mismo ticket, sin duplicados |

Diagnóstico **6**: CPE_UNREACHABLE, completado **2026-10-10 19:55:02.438135 UTC**.
Diagnóstico **7**: CPE_UNREACHABLE, completado **2026-10-10 19:55:06.899650 UTC**.
Ticket creado **2026-10-10 19:55:06.908363 UTC**.

DemoAI propuso la intención CONFIRM_PHYSICAL_CHECK por su contrato de compatibilidad;
Django ejecutó el recheck y el servicio de tickets. Las pruebas del adaptador simulado
OpenAI proponen explícitamente RUN_AUTHORIZED_RECHECK y reproducen la clasificación errónea
PHOTO_QUESTION/attempted_uncertain observada en la conversación 18.

Respuesta visible tras la confirmación:

> Thank you for completing those accessible checks. The new simulated diagnostic still
> receives no response from the CPE. The issue has been escalated for technical review;
> you do not need to repeat the same checks now. Your issue is recorded under ticket
> ISP-DDD8F12242C1. No visit or repair has been confirmed.

La queja posterior mostró `Ticket ISP-DDD8F12242C1: OPEN`, sin repetir la guía ni preguntar
por modelos o etiquetas. La captura está en `confirmed-recheck-browser.jpg`.

Las primeras instancias de QA encontraron restricciones de sockets del sandbox; el navegador
tuvo esperas largas. La ejecución final fuera del sandbox funcionó. Esos fallos fueron del
entorno de prueba, no de OpenAI; no se hicieron llamadas facturables.

## Regresiones y archivos

`confirmed-recheck-proof.json` contiene respuestas, proveedor efectivo, fallback, decisiones,
IDs/timestamps antes y después y contadores de llamadas reales al simulador y creación de tickets
envolviendo los servicios existentes, sin sustituir su implementación.

Se prueban confirmación con/sin foto, estado saludable inicial y después del recheck,
acceso físico inseguro tras un intento, inglés/español, timeout, salida inválida, frecuencia,
resultado caducado, fallo de herramienta, redacción futura incorrecta y ticket único.
La suite completa conserva las pruebas de autenticación, aislamiento y solicitud humana.

Archivos de código intervenidos:

- `conversations/adaptive.py`: enlaza confirmación con ruta existente, metadatos de reutilización y validación de resultado redactado.
- `conversations/services.py`: conserva la operación ante fallo del proveedor, entrega resultado/ticket al generador, bloquea reutilización caducada y registra política aplicada.
- `conversations/decisions.py`: explica la reutilización por límite en el fallback existente.
- `conversations/test_confirmed_recheck.py`: integración y evidencia de operaciones.
- `conversations/test_context.py`: fortalece la regresión de confirmación durante timeout.

No se modificaron diseño, fotografías, catálogo, manual, modelo OpenAI, conocimiento,
aprendizaje, permisos, límites ni deduplicación. No hay migraciones nuevas ni trabajo SMS.

## Prueba mínima con OpenAI, pendiente de autorización

1. Reiniciar el servidor habitual para cargar el código actual, manteniendo el modelo y
   configuración existentes. Abrir `http://127.0.0.1:8000/demo/` con el operador autorizado.
2. Elegir servicio ficticio 001 y conversación nueva en inglés. Enviar los tres mensajes
   exactos de la prueba de navegador; la foto de demostración es opcional en el segundo.
3. En Network, abrir las respuestas de `/api/chat/turn/`. Verificar `debug.chat.decision`,
   `tool_result.diagnostic_id/completed_at`, `escalation_policy`, proveedor y fallback.
4. Confirmar dos diagnósticos (o reutilización fresca justificada por límites), ticket OPEN
   con número real y ausencia de cuestionario tras la tercera intervención. El asistente
   debe informar el resultado, no pedir que se ejecute una acción ya realizada.
5. Si falla, conservar sólo metadatos sanitizados y el número de conversación. No compartir
   claves ni fotografías privadas. Detener ahí la prueba para limitar consumo.

Esta prueba real no se ejecutó. La reproducción visual fue DemoAI y las llamadas OpenAI
de regresión fueron mocks; no prueban por sí solas la calidad del proveedor real.

## Resultado final de validación

```powershell
.venv\Scripts\python.exe manage.py test --noinput
node --test tests/frontend.test.cjs
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

**303 pruebas Django aprobadas, 10 JavaScript aprobadas**, system check sin problemas y
ninguna migración pendiente. No quedaron fallos funcionales de las verificaciones ejecutadas.
El servidor y las bases temporales se retiraron después de guardar la evidencia.
