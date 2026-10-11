# Corrección del bucle conversacional — 10 de octubre de 2026

## Evidencia real y límites de la verificación

Inspeccioné la conversación local 14, mensajes 95–116, sin abrir ni copiar fotografías.
Contiene la secuencia descrita con errores ortográficos del navegador. La transcripción
completa anterior y la reproducción posterior con DemoAI están en
`repeated-questions-transcript.json`. No se modificó esta conversación histórica.

| Turno | Respuesta real | Fuente | Respaldo y motivo |
|---|---|---|---|
| 1 | OpenAI | openai_generated | No |
| 2 | OpenAI | openai_generated | No |
| 3 | OpenAI | openai_generated | No |
| 4 | OpenAI | openai_generated | No |
| 5 | Django | reply_error_fallback | invalid_output |
| 6 | OpenAI | openai_generated | No |
| 7 | OpenAI | openai_generated | No |
| 8 | OpenAI | openai_generated | No |
| 9 | OpenAI | openai_generated | No |
| 10 | Django | reply_error_fallback | redundant_evidence_request |
| 11 | OpenAI | openai_generated | No |

Los once mensajes registran intentos de clasificación y generación. Nueve conservaron
la respuesta validada de OpenAI. El código invalidó la salida del turno 5; el registro
histórico no conserva el detalle que permita determinar cuál validación falló.
En el turno 10 rechazó una solicitud redundante y su propio respaldo volvió a pedir
la parte frontal. DemoAI no generó esas once respuestas. No debe inferirse lo contrario
por el estilo repetitivo. Los campos nuevos de éxito y acción propuesta no existían
entonces: no se reconstruyen como si hubieran sido registrados.

`ai_runtime` actual: openai / gpt-4.1-mini para texto y visión, clave configurada,
registro de desarrollo activo. La configuración CLI tiene revisión inconclusa activada.
No había listener en 8000–8010 al inspeccionar; la pestaña disponible era el login
administrativo de 127.0.0.1:8000. Esto no demuestra el entorno de un proceso anterior.
Las últimas migraciones de knowledge están aplicadas. No hubo nuevas migraciones.

## Causa y condiciones de escalamiento

La interpretación clasificaba reiteradamente `attempted_uncertain`. La barrera
convertía propuestas de recheck en preguntas. La segunda vista solo forzaba recheck
si NO existía incertidumbre. Se guardaron intentos, pero ninguna pregunta respondida:
solo ANSWER_CLARIFICATION consumía pendientes, mientras los reportes llegaban como
PHOTO_QUESTION o EQUIPMENT_CLARIFICATION. El clasificador siguió marcando
additional_checks=available. Las instrucciones antiguas pedían una etiqueta para
«is it good?», aun cuando ya existían respuestas. El respaldo también podía repetirla.

| Condición al finalizar el historial real | Valor |
|---|---|
| Política activada en proceso histórico | No registrada; CLI actual true |
| CPE_UNREACHABLE, simulación | true |
| Incidencia NO_INTERNET retenida | true |
| Guías previamente mostradas | true |
| Intentos reportados retenidos | true |
| Dos análisis fotográficos completados | true |
| Dos mediciones fallidas consecutivas | **false: solo diagnóstico 35** |
| Resultado fresco dentro de 300 segundos | **false al final** |
| Comprobaciones adicionales declaradas no disponibles | false |
| Ticket | Ninguno |

La conversación duró 435.53 segundos. No aparece un rechazo por frecuencia en los
mensajes: después del diagnóstico inicial, tool_result.reason=not_requested.
La falta de una segunda medición y, finalmente, la caducidad impidieron elegibilidad.

## Cambios

- `conversations/ai.py`: campo semántico answers_pending, interpretación contextual de
  respuestas breves/negativas, intentos visuales y agotamiento; instrucciones para evitar
  exigir modelo o repetir evidencia.
- `conversations/adaptive.py`: progreso basado en estado estructurado, incidencia,
  guía, intentos y análisis completados; memoria acotada de respuestas; traza separada
  de cada predicado. No se decide agotamiento solo mediante patrones de texto.
- `conversations/context.py`: conserva más respuestas y progreso; responder una pregunta
  sobre modelo no se presenta como haber confirmado un modelo exacto.
- `conversations/services.py`: con evidencia suficiente solicita recheck autorizado aun
  con incertidumbre, conserva límites y servicio de tickets; permite una reparación
  de respuesta por el modelo si repite una pregunta. Respuestas naturales válidas se
  conservan. Se registran proveedor final, llamadas, éxito estructurado, respaldo,
  acción propuesta, acción ejecutada y condiciones de revisión.
- `conversations/web.py`: GET protegido `/demo/state/` muestra runtime seguro solo en
  desarrollo: proveedor, modelos, presencia de clave, PID, política y versión 2.
- `conversations/test_progress.py`: siete regresiones nuevas.

No se cambiaron UI, fotografías, catálogo, manuales, permisos, prioridad, transiciones,
deduplicación ni reglas del motor de diagnóstico. Se usa el servicio autorizado existente.
Un resultado saludable impide ticket; imágenes o frustración por sí solas no bastan.

## Antes y después

Antes, turno 8: vuelve a pedir la etiqueta junto al puerto 4.
Antes, turno 10: respaldo pide frontal pese a la fotografía recién enviada.
Antes, turno 11: OpenAI pide otra imagen posterior con etiquetas.

Después, la reproducción exacta con DemoAI conserva informes como declaraciones no
verificadas, registra respuestas y utiliza la segunda fotografía para ejecutar la
segunda medición. Si persiste el CPE inaccesible crea una revisión técnica y comunica
el número realmente devuelto. El turno final y su repetición reutilizan un solo ticket.
El proveedor OpenAI simulado recibe el ticket confirmado antes de redactar su explicación
natural. Esto verifica integración, no calidad de un modelo real.

| Ejecución | Diagnósticos | Fotografías | Tickets |
|---|---:|---:|---:|
| Historial real previo, conservado | 1 | 2 | 0 |
| Reproducción aislada exacta DemoAI | 2 | 2 | 1 |
| Reproducción aislada OpenAI simulado | 2 | 2 | 1 |
| Recheck saludable, misma secuencia | 2 | 2 | 0 |

Transcripción completa y trazas por turno: `repeated-questions-transcript.json`.
La reproducción posterior corresponde a turnos 2–11; el inicial crea el diagnóstico
de CPE inaccesible y presenta las guías existentes. No se reproducen fotos en el informe.

## Validación

252 pruebas Django aprobadas, conservando las anteriores; 10 pruebas JavaScript aprobadas.
`manage.py check`: sin problemas. `makemigrations --check --dry-run`: sin cambios.
Las regresiones existentes cubren aislamiento de servicios, proveedor fallido, español,
archivos privados, manual y deduplicación. Las nuevas cubren once turnos, persistencia,
saludable, OpenAI simulado, respuesta semántica, runtime protegido y reparación natural.

Incidencia durante la exportación: un primer script auxiliar no activó el decorador
de clase del test y cargó OpenAI desde configuración. Intentó llamadas externas que
fallaron con upstream_error; no hubo respuestas exitosas registradas y no se puede
certificar consumo. Se corrigió antes de generar el archivo final usando DemoAI
explícito y activando setUpClass. La suite automatizada final pasó con DemoAI/mocks.

## Verificación local y propuesta de prueba real

1. Abrir PowerShell en el proyecto y ejecutar `.\.venv\Scripts\python.exe manage.py check`.
2. Para probar sin llamadas facturables: `$env:AI_PROVIDER='demo'` y después
   `.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000`.
3. Abrir http://127.0.0.1:8000/demo/, iniciar sesión con operador autorizado,
   seleccionar DEMO-SERVICE-001 y comenzar una conversación nueva en inglés.
4. Con esa misma sesión abrir `/demo/state/`: verificar runtime.provider=demo,
   inconclusive_review=true, progress_policy_version=2 y el PID del proceso esperado.
5. Seguir los once turnos del encargo, adjuntando fotografías de ejemplo seguras en
   los turnos 2 y 10. En DevTools → Network revisar `/api/chat/turn/` o `/api/chat/`.
   En JSON → debug.chat inspeccionar todos los campos de procedencia y review_predicates.
6. Tras la segunda vista esperar una segunda medición simulada y un ticket OPEN si
   persiste la falla. Repetir turno 11, recargar y comprobar mismo ticket y conversación.
7. Para una conversación histórica caducada, comenzar una nueva para la reproducción
   controlada; no atribuir su antigüedad a una llamada nueva ni inventar medidas.

Prueba real pendiente de autorización explícita: reiniciar el servidor con OpenAI,
comprobar `/demo/state/` y realizar UN envío de foto ficticia + texto en una conversación
controlada ya preparada. Ese envío puede realizar visión, clasificación, generación y
una reparación adicional de respuesta. Revisar debug.chat para confirmar invocación,
salida validada y proveedor final, sin publicar clave ni imagen. Esta prueba aún no
se ha completado ni se presenta como aprobada. No modificar `.env` para el modo demo;
el override de PowerShell prevalece y se elimina con `Remove-Item Env:AI_PROVIDER`.
