# Verificación de RAG y respuestas técnicas breves

## Resultado y límites de la evidencia

El manual está indexado realmente: 16 páginas, 29 secciones; solo las páginas 3–9 están revisadas para el chat. Es material genérico de demostración, no un manual verificado del fabricante. La recuperación es local con Django ORM y coincidencia léxica; no utiliza embeddings.

La configuración principal identifica OpenAI y `gpt-4.1-mini`, con clave configurada (no mostrada). El manual tiene `allow_external_ai=False`. Por tanto, recuperar un documento **no significa** que OpenAI lo haya leído. Se conservan ambos controles: autorización por documento y `KNOWLEDGE_ALLOW_EXTERNAL_AI`.

Ahora Django puede añadir una cita literal local también a una respuesta OpenAI cuando el envío documental está deshabilitado. La traza diferencia `citation_origin=django_local` de `model_validated`; no atribuye esa lectura al modelo. Los extractos compartidos requieren ambos controles habilitados. La prueba automatizada del adaptador oficial verifica que los extractos autorizados llegan al input y que sus citas coinciden exactamente. No se realizaron llamadas reales nuevas a OpenAI ni se enviaron fotos/documentos privados al exterior.

## Rastreo en navegador

Servidor aislado en loopback, SQLite y archivos privados temporales; proveedor DemoAI. Se utilizó una imagen sintética, no fotografías de clientes. No se verificó identificación de píxeles de un router real. El escenario mantiene el diagnóstico simulado previo CPE_UNREACHABLE.

Documento de esta prueba: **ISP Support — Bilingual Troubleshooting Photo Manual**, revisión 1.0, ID `91961b51-64ce-4c10-a7ab-be9347a0e4ac`. Los IDs cambian entre bases de datos.

| Consulta | Intent | Primera sección recuperada | Páginas recuperadas | Contexto al modelo | Respuesta final / fallback |
|---|---|---|---|---|---|
| is it good? + adjunto | PHOTO_QUESTION | `b953fafe-e552-40ad-85bf-ef278a77c50b`, STEP 3, Ethernet | 5, 7, 3 | No; demo y salida documental deshabilitada | Demo + cita local; sin fallback |
| yellow wire is green and orange | REPORT_INDICATORS | `a4da9c57-15fa-4724-bba5-77f78dfa7f88`, STEP 2, indicador | 4, 6, 3 | No | Demo + cita local; sin fallback |
| is this device + adjunto | EQUIPMENT_CLARIFICATION | `58d96afc-0898-4f39-bdde-17742926f631`, mapa de equipos | 3, 4, 8 | No | Demo + cita local; sin fallback |

La explicación general sobre colores no está verificada para un modelo específico. La cita de la página 4 respalda observar indicadores; no establece que verde/naranja signifique una velocidad determinada. Se pide la etiqueta LAN/WAN. Las citas literales se muestran como referencia genérica separada.

## Qué provocaba las respuestas débiles y el fallback

- El clasificador demo no reconocía las frases de colores ni “is this device”. Ahora hay interpretación estrecha de estas consultas, sin convertirlas en acciones de diagnóstico o tickets.
- Preguntas cortas no proporcionaban palabras suficientes para recuperar la sección pertinente. Se expande solo la consulta de búsqueda; esas palabras no se usan como evidencia de marca/modelo.
- El contexto documental recuperado quedaba fuera de OpenAI por autorización deshabilitada. Sigue protegido; ahora puede presentarse una cita local revisada sin enviar el documento.
- El validador rechazaba palabras de acciones incluso dentro de advertencias negativas. Ahora permite negaciones concretas como “without unplugging”, conservando el rechazo de órdenes y de una orden añadida después de una advertencia.
- El límite de salida de 512 tokens podía truncar el JSON con respuesta y citas. Se amplió a 900 y se distingue `output_incomplete`. Es una causa posible, no demostrada para los fallos históricos.
- Las excepciones de generación perdían su motivo. Se conservan categorías seguras: timeout, upstream_error, configuration_missing, invalid_output, output_incomplete, unsupported_action, invalid_citation y unverified_manual_claim. No se registra el cuerpo de excepciones, claves, fotos ni extractos.

Se encontraron dos respuestas históricas `reply_error_fallback/reply_unavailable`; los metadatos antiguos no permiten determinar su causa exacta. No se fabricó una atribución retrospectiva.

## Antes / después

| Caso | Antes | Después (orientación local resumida) |
|---|---|---|
| is it good? | Valoración genérica de luces o advertencia del pipeline | Usa una observación pertinente si existe; cable asentado/luz de enlace solo sugieren conexión local, contrasta con el diagnóstico y pregunta la etiqueta del puerto. Demo aclara que no interpretó la imagen. |
| yellow wire is green and orange | OTHER o respuesta genérica | “Si hablas de las luces junto al cable Ethernet amarillo, pueden indicar enlace, actividad o velocidad negociada según el modelo; no prueban Internet. ¿Está junto a LAN o WAN?” |
| is this device | OTHER o agradecimiento por una identidad no aportada | Usa la observación visual disponible con incertidumbre; distingue router/módem/gateway de inyector PoE y pregunta marca/modelo. No inventa identidad en demo. |

El fallback comienza, cuando corresponde, con “I can give limited guidance based on the information currently available” y después contesta la pregunta. Una falla de recuperación no impide responder con el contexto disponible. No se repite la guía completa ni se modifican reglas de diagnóstico/tickets.

## Observabilidad de desarrollo

Con `DEBUG=true` y `DJANGO_ENV=development`, la respuesta autenticada de `/api/chat/turn/` o `/api/chat/` incluye `debug.chat` y `debug.knowledge`. También se registran `chat_runtime` y `knowledge_runtime` y se guardan metadatos de mensaje.

- `answer_provider`: openai/demo/django; `response_source` distingue generación y fallback.
- `retrieval_attempted`, `retrieval_succeeded`, `retrieval_error`.
- `retrieved_sources`: ID, título, sección, página y carácter genérico.
- `context_injected`, `injection_reason` y `citation_origin`.
- `fallback_used`, `fallback_reason`.

Una cita local no equivale a contexto inyectado ni a respuesta generada desde el documento. Una cita validada prueba procedencia literal; no garantiza por sí sola que cada afirmación de la respuesta esté sustentada. Revisar material técnico y modelo antes de autorizarlo.

## Pasos exactos para reproducir

1. En PowerShell, dentro del proyecto, ejecutar `.venv\Scripts\python.exe manage.py migrate` y `.venv\Scripts\python.exe manage.py check`.
2. Para una prueba sin consumo, definir `$env:AI_PROVIDER='demo'`, `$env:ENABLE_DEMO_CHAT='true'`, `$env:DEBUG='true'` y `$env:DJANGO_ENV='development'` en esa terminal. El `.env` no sobrescribe variables ya definidas.
3. Si faltan datos ficticios: `.venv\Scripts\python.exe manage.py seed_demo`. Si falta el manual, importar con el comando mostrado en el documento de base de conocimiento.
4. Ejecutar `.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000`. Entrar en `http://127.0.0.1:8000/admin/` con un operador autorizado; crear uno si hace falta con `manage.py createsuperuser`. No hay credenciales fijas públicas.
5. Abrir `http://127.0.0.1:8000/demo/`, elegir English, seleccionar DEMO-SERVICE-001 y conectar. Abrir DevTools → Network, filtrar `turn`.
6. Enviar “No Internet”. Deben aparecer cuatro pasos en orden y diagnóstico simulado de equipo no accesible.
7. Adjuntar una foto JPEG/PNG/WebP segura de la parte trasera, escribir “is it good?” y pulsar Send una vez. Verificar un mensaje del cliente con foto y una respuesta, cita de referencia y una pregunta útil.
8. Enviar “yellow wire is green and orange”. Verificar explicación de enlace/actividad/velocidad dependiente del modelo y ausencia de afirmación de Internet confirmado.
9. Adjuntar una foto segura de router/módem y enviar “is this device”. En demo debe declarar que no interpreta píxeles y pedir marca/modelo; con visión real debe basarse únicamente en observaciones disponibles y mantener incertidumbre.
10. Inspeccionar Response → `debug`: comprobar intent, páginas, answer_provider, context_injected y fallback_reason. En demo `context_injected=false` es correcto. Recargar: el historial mantiene foto y pregunta juntas.
11. Para comprobar **RAG en OpenAI**, usar únicamente fotografías autorizadas y autorizar explícitamente extractos del documento en Admin (`allow_external_ai`) y `KNOWLEDGE_ALLOW_EXTERNAL_AI=true` en el entorno. Guardar/reaprobar el documento si el Admin revoca su aprobación al editarlo. Seleccionar AI_PROVIDER=openai, configurar modelos y clave exclusivamente en backend, reiniciar el servidor y repetir. Esto realiza llamadas facturables. Esperar `answer_provider=openai`, `context_injected=true`, `citation_origin=model_validated` y citas verificadas. Si falla, leer la categoría segura en debug; no asumir que la clave configurada prueba una llamada exitosa.

## Validación

210 pruebas Django y 10 pruebas JavaScript aprobadas. `manage.py check`: sin problemas. `makemigrations --check --dry-run`: sin cambios. `.env` sigue ignorado. No se modificaron activos fotográficos, reglas de tickets ni diagnósticos. Se conservaron las pruebas anteriores; solo se actualizaron expectativas de redacción, límite de salida y citas locales para el comportamiento solicitado.

Pruebas cubren observaciones guardadas, respuestas cortas, recuperación exitosa/ausente/fallida, autorización de extractos, fallo de proveedor, JSON incompleto, citas inventadas y acciones inseguras. OpenAI está simulado en todas las pruebas automatizadas. No se ha demostrado la disponibilidad de la API real de la cuenta en esta ejecución.

Documentación oficial consultada: [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), que exige manejar rechazos y salidas incompletas.

Archivos de esta corrección: `conversations/short_answers.py`, `services.py`, `ai.py`, `api.py`, `knowledge/services.py`, `test_short_answers.py`, `test_runtime_replies.py`, `test_memory_uploads.py`, `test_knowledge_chat.py`, este informe y `short-answers-rag.jpg`. No requiere migraciones ni dependencias nuevas sobre la ampliación anterior.
