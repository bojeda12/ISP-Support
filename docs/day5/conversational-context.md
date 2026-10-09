# Correcciones de contexto conversacional — Día 5

Verificación: 9 de octubre de 2026. No se inició el Día 6.

## Causas y proveedor real

La configuración efectiva inspeccionada selecciona `AI_PROVIDER=openai` para
chat **y** fotografías. Ambos llaman a `get_provider()`; no existen selectores
separados. `OPENAI_MODEL` y `OPENAI_VISION_MODEL` son `gpt-4.1-mini`.
La clave está configurada; su valor no se mostró ni se modificó `.env`.

OpenAI clasificaba únicamente intención e idioma y recibía mensajes de texto
acotados. Las observaciones JSON de las fotos no se incorporaban al chat; el
mensaje del historial solo contenía el aviso de seguridad. DemoAI ignoraba el
historial. No había memoria de guías mostradas y OTHER reiniciaba la pregunta
general. Las respuestas del cliente usan plantillas seguras, no texto libre del
modelo; ampliar solo el historial sin ampliar intenciones no era suficiente.

Se mantiene Responses con salida Pydantic validada, sin herramientas ni acciones
delegadas al modelo, conforme al patrón de
[Structured Outputs de OpenAI](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
No se hicieron llamadas al modelo real ni se cambió el proveedor configurado.

## Estado y fotografías

`context.py` reconstruye un resumen estructurado de la conversación autorizada:
incidencia, idioma, hasta 20 referencias de guías, ocho declaraciones de hasta
300 caracteres, equipo declarado, preguntas pendientes y último diagnóstico,
ticket y foto. El resumen se persiste en `Message.metadata.context` del asistente.
No necesita tablas, dependencias ni migraciones nuevas. Las conversaciones
anteriores reconstruyen la incidencia y guías a partir de sus últimos 50 mensajes.

Cada turno consulta nuevamente el diagnóstico y ticket, para no conservar un
estado administrativo obsoleto. También consulta la última `ConversationPhoto`
de esa conversación: estado del análisis, indicador de simulación, hasta cinco
observaciones y cinco incertidumbres de 300 caracteres. La foto continúa en su
almacenamiento privado; el clasificador de texto recibe únicamente ese resumen,
sin bytes, rutas de almacenamiento, claves ni URLs externas. Una foto fallida
conserva la incertidumbre; DemoAI dice expresamente que no interpretó la imagen.

El resumen ocupa una entrada del historial enviado al proveedor. Permanecen los
límites configurados de mensajes y caracteres de texto; el resumen tiene sus
propios límites fijos. Se vuelve a consultar dentro de la transacción antes de
guardar el siguiente estado. Las declaraciones incluyen `verified: false`.
Los diagnósticos mantienen su `source`; una simulación nunca verifica una red real.

## Comportamiento

- Intenciones nuevas para aclarar equipo, indicadores, PoE desconocido, fotos,
  comprobaciones ambiguas y solicitudes explícitas de guía.
- OpenAI interpreta semánticamente mensaje e historial estructurado. DemoAI es
  un simulador limitado: reglas reproducibles, correcciones ortográficas acotadas
  y referencias al estado; no pretende comprender cualquier lenguaje natural.
- Router, módem, inyector y CPE exterior se distinguen; una identidad declarada
  no se convierte en identidad visual verificada. Se solicita modelo/indicador.
- Luces verdes no confirman conectividad ni equivalen a comprobaciones completas.
- “I already tried that” solicita detalles. La confirmación explícita conserva
  el diagnóstico y escalamiento existentes; no inventa una revisión de PoE.
- Las guías se recuerdan por ID/idioma: la primera versión pertinente se muestra;
  una solicitud expresa puede repetirla. Cambiar de equipo puede mostrar una guía
  distinta. No se reinicia la guía automática después de registrar el ticket.
- Repetir la incidencia conserva la política de diagnóstico; cambia únicamente
  la presentación y mantiene la referencia del ticket. Los umbrales, escenarios,
  transiciones y deduplicación no se modificaron.
- Se eliminó “Django will repeat…” de las instrucciones del cliente.

## Archivos de esta corrección

`conversations/context.py`, `conversations/ai.py`, `conversations/services.py`,
`conversations/replies.py`, `conversations/history_api.py`,
`conversations/instructions.py`, `conversations/test_context.py`, este documento
y su referencia en `README.md`. Evidencia: `context-escalation-desktop.jpg`.
Los cambios previos del proyecto se conservaron.

## Validación

```powershell
.\.venv\Scripts\python.exe manage.py test --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
node --test tests/frontend.test.cjs
git check-ignore .env
```

Resultado: **136 pruebas Django aprobadas**, incluidas las 122 anteriores y 14
nuevas; **7 pruebas JavaScript aprobadas**. System check sin incidencias y sin
migraciones pendientes. `.env` permanece excluido de Git. Las pruebas mantienen
autenticación, permisos, CSRF, aislamiento entre conversaciones, tipos/tamaños
de fotos, fallos de proveedor y deduplicación. Las llamadas OpenAI se simularon.

Se corrigieron durante el desarrollo una expectativa histórica de texto de PoE,
la presentación de guías al cambiar idioma y un nombre incorrecto de escenario
en una prueba nueva. No quedan errores de pruebas pendientes.

## Verificación manual y reproducción

Se usó un servidor temporal en `127.0.0.1:8005`, con SQLite aislada, operador
temporal y `AI_PROVIDER=demo` solo en ese proceso. Se cerró al terminar. El
proveedor y la base habituales no fueron sustituidos.

Para repetir en la demo habitual, reiniciar el servidor con el código nuevo y
abrir `http://127.0.0.1:8000/demo/` con un operador autorizado. Si se desea evitar
consumo, seleccionar **explícitamente** `AI_PROVIDER=demo` en el entorno del
proceso antes de iniciarlo. La configuración habitual actualmente es OpenAI.

1. Elegir English y el servicio ficticio `DEMO-SERVICE-001`.
2. Enviar “No Internet”: diagnóstico simulado CPE_UNREACHABLE y guía inicial.
3. Adjuntar una foto sintética JPEG/PNG y pulsar Send photo: análisis simulado.
4. Enviar “It's a Frontier router.”: aclara equipo y mantiene incidencia/foto.
5. Enviar “I still have no Internet.”: no repite la guía completa.
6. Enviar “All the lights are green.”: distingue indicadores de conectividad.
7. Enviar “I checked all accessible connections and the lights are green.”:
   repite diagnóstico, agradece comprobaciones declaradas y registra ticket OPEN.
8. Recargar y enviar “What does that light mean?”: conserva análisis, incertidumbre
   y referencia del ticket. El historial y la foto privada se recuperan correctamente.

La captura muestra el paso 8. La validación de visión real y calidad semántica
del modelo con una cuenta real queda pendiente por decisión de no consumir API.
No se implementaron SMS, nuevos endpoints públicos ni acciones sobre redes reales.
