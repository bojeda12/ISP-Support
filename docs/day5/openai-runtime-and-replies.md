# Respuestas conversacionales y proveedor efectivo

## Investigación y configuración

Un proceso Django nuevo, con el entorno actual, informa `AI_PROVIDER=openai`,
`OPENAI_MODEL=gpt-4.1-mini`, `OPENAI_VISION_MODEL=gpt-4.1-mini`, clave configurada,
DEBUG activo y entorno development. No se leyó ni imprimió el secreto ni se hizo
ninguna llamada externa. `.env` continúa ignorado por Git y se carga sin reemplazar
variables del proceso. Un servidor que ya estaba iniciado puede tener otro entorno:
el comando no demuestra retrospectivamente qué proceso atendió mensajes antiguos.

Antes de esta corrección, OpenAI **solo clasificaba** intención, idioma y foco.
Las instrucciones exigían explícitamente no generar respuestas para el cliente.
`contextual_reply()` y `photo_reply()` producían todo el texto visible. La frase
“The saved observations have not changed” era una plantilla que reemplazaba una
observación después de discutir una foto. Las plantillas también agregaban el código
CPE_UNREACHABLE y una advertencia genérica sin adaptar los pasos a la pregunta.

Ruta anterior: `demo.js` → POST `/api/chat/` → autenticación/serializer → `chat()` →
`get_provider().interpret()` → clasificación validada → reglas Django → plantilla →
mensaje persistido → representación con `textContent`. El frontend no resumía ni
reescribía las respuestas. La subida de fotos sí usaba un adaptador visual separado.

| Pregunta | Ruta anterior reproducible con DemoAI | Causa |
| --- | --- | --- |
| Is it good? | PHOTO_QUESTION → plantilla fotográfica | OpenAI no redactaba la respuesta |
| How do I know if it is properly connected? | OTHER → plantilla contextual si había incidencia | Faltaba clasificación demo y respuesta práctica |
| The wires are good? | OTHER → plantilla contextual si había incidencia | Igual; foco no reconocía wires |
| I already checked everything and still have no Internet. | CONFIRM_PHYSICAL_CHECK → diagnóstico/escalamiento | Se conserva esta ruta |

Con OpenAI, la intención histórica concreta no se puede reconstruir sin registros.
Si la configuración era openai, se intentaba la clasificación externa antes de la
plantilla; eso no demuestra que una petición específica tuviera éxito. No existe
fallback silencioso a DemoAI: los errores de clasificación usan la respuesta local
de indisponibilidad. Las pruebas anteriores y actuales usan DemoAI o SDK simulado.

## Corrección mínima

- `conversations/ai.py`: `generate_reply()` mediante Responses API y salida Pydantic
  `ConversationalReply`, con texto limitado a 1400 caracteres y una sola pregunta.
  Clasifica también el tipo de aclaración para conservarla en memoria. Instrucciones
  compartidas de soporte técnico, sin una plantilla por cada pregunta. Se mantienen
  modelo configurado, timeout existente, `store=False`, cero reintentos y ausencia
  de herramientas. La generación admite hasta 512 tokens de salida; clasificación,
  256. Las fotografías conservan su límite de 1000 tokens y detalle bajo.
- `conversations/services.py`: genera texto solo para preguntas/comparaciones de
  fotos, indicadores, equipo y aclaraciones, con AI_PROVIDER=openai. Usa el mensaje
  actual y el resumen estructurado acotado, sin historial completo ni bytes de fotos.
  Llama fuera de la transacción. Si cambió el contexto mientras esperaba, descarta
  el texto obsoleto. Diagnósticos, cuentas, tickets y guías conservan sus reglas.
- `conversations/context.py`: elimina la frase de observaciones invariables y añade
  orientación local compartida para comprobar visualmente conectores y luces de enlace.
- `conversations/photos.py`, `config/settings.py`: trazas de desarrollo de visión y
  chat sin contenido, fotos, claves, nombres o datos de contacto.
- `conversations/management/commands/ai_runtime.py`: muestra configuración efectiva
  y presencia de clave como booleano; no hace llamadas externas.
- `conversations/test_runtime_replies.py`: doce regresiones nuevas.
- `README.md` y este informe: instrucciones.

No se cambiaron UI, endpoints protegidos, modelos, dependencias, migraciones ni
reglas de tickets/diagnósticos. El texto generado no contiene campos ejecutables.
Validación rechaza salidas con campos extra, preguntas múltiples, HTML, URLs,
comandos y determinados términos de acciones no soportadas. El prompt limita
recomendaciones a comprobaciones visuales accesibles; estos controles no constituyen
una garantía de exactitud semántica del modelo, que requiere evaluación real.

El resultado generado sustituye la plantilla solo tras validación. No se le concatena
automáticamente el código interno de diagnóstico. Una falla se identifica en el texto
como orientación local limitada y devuelve `provider_status=reply_unavailable`;
el navegador ya muestra aviso para estados distintos de ok. No cambia a DemoAI.

## Antes y después (ejemplos de pruebas con SDK simulado)

Estos ejemplos son respuestas **mock**, no resultados observados en OpenAI real.

| Pregunta | Antes | Ejemplo posterior validado en integración |
| --- | --- | --- |
| Is it good? | Advertencia genérica/foto sin confirmar | Reconoce luz de alimentación verde como indicio positivo de energía, explica que no prueba Internet, relaciona la CPE inaccesible simulada y pregunta por el indicador de enlace |
| How do I know if it is properly connected? | Solicitud genérica de aclaración o repetición de observaciones | Comprobar visualmente asentamiento de conectores accesibles, daños evidentes e indicador de enlace identificado; distinguir enlace local de Internet |
| The wires are good? | Respuesta genérica sobre el contexto | Cita conectores insertados de la foto trasera, aclara que no confirma integridad del cable y propone comprobación visual e indicadores |

Las pruebas verifican contenido útil, observaciones de ambas vistas enviadas, foco,
idioma, persistencia, ruta de generación, presupuesto, ausencia de herramientas,
errores honestos, comandos rechazados y falta de efectos de negocio por preguntas.
El escenario de comprobaciones completadas crea/reutiliza un único ticket OPEN,
sin generación libre ni repetición de la guía.

## Verificación

- `python manage.py check`: sin problemas.
- `python manage.py makemigrations --check --dry-run`: sin cambios.
- `python manage.py test`: **170 pruebas aprobadas** (158 anteriores + 12 nuevas).
- `node --test tests/frontend.test.cjs`: **8 aprobadas**.
- `python manage.py ai_runtime`: openai / gpt-4.1-mini / clave presente / ninguna llamada.

Se preservan JPEG, PNG, WebP y fallback HEIC/HEIF, pruebas de aislamiento, permisos
del manual y fotografías privadas. Los recursos instructivos no se editaron.

## Confirmar la ruta en el navegador

1. Ejecutar `.venv\Scripts\python.exe manage.py ai_runtime` en la misma terminal que
   arrancará el servidor. No imprimir `.env`. Las variables del proceso tienen prioridad.
2. Reiniciar el servidor local con `.venv\Scripts\python.exe manage.py runserver`
   para cargar código/configuración actuales. Usar el operador autorizado existente
   en `http://127.0.0.1:8000/demo/`; seleccionar inglés y un servicio ficticio.
3. Una vez autorizadas llamadas reales, iniciar “I don't have Internet.”, adjuntar una
   sola fotografía ficticia no sensible y preguntar “Is it good?”. Cada pregunta
   conversacional OpenAI puede realizar clasificación y generación: son dos llamadas.
4. Observar consola: `photo_runtime` debe mostrar `openai_vision`; `chat_runtime`
   debe mostrar `effective_provider=openai`, `classification_call_attempted=True`,
   `reply_call_attempted=True`, `response_source=openai_generated`, `fallback_used=False`
   para esa pregunta. `django_template` en diagnóstico/escalamiento es esperado.
   Las trazas no incluyen texto del cliente ni imagen. La procedencia también queda
   en metadatos internos del mensaje; no se publica un endpoint de configuración.
5. Si aparece `provider_error` o `reply_error_fallback`, no hubo respuesta generada
   exitosa. `key_configured=True` demuestra presencia, no validez, saldo ni acceso.
   `*_call_attempted=True` demuestra intento; la fuente generated/vision completada
   distingue éxito de un timeout o rechazo. En pruebas, estas mismas rutas son mocks.

## Prueba real pendiente de aprobación

No se han realizado llamadas reales. Propuesta mínima: una conversación de servicio
ficticio, una foto genérica autorizada del catálogo y una pregunta; **máximo cuatro
solicitudes** (clasificación inicial, análisis visual, clasificación y generación),
**2024 tokens de salida máximos en total**, sin reintentos ni lotes. El costo real
incluye tokens de entrada y la imagen; no se puede prometer un importe fijo solo
con ese límite de salida. No se cambiará el proveedor en silencio.

Si credenciales o red fallan, detener la prueba y registrar únicamente la categoría
sanitizada. La calidad y utilidad de las respuestas reales siguen sin verificarse.
HEIC/HEIF sigue requiriendo conversión; la comparación visual usa observaciones
guardadas. No se inició SMS ni Día 6.

Referencia: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
