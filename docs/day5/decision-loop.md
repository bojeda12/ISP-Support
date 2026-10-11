# Decisión operacional y regresión sin facturación

## Investigación local

Se consultó la conversación **17**, vinculada al ticket **ISP-66A7779A7A27**.
No se exportaron fotografías, claves ni identificadores de almacenamiento privado.
La traza seleccionada está en `decision-loop-local-trace.json`. La base local no fue modificada.

Todas las ocho respuestas registran OpenAI, clasificación y generación intentadas. Las seis
primeras fueron respuestas de OpenAI aceptadas. Las dos últimas terminaron en Django por
`invalid_citation`. El modelo concreto no se guardaba históricamente; no puede deducirse
del modelo configurado hoy. Los indicadores históricos `reply_succeeded/model_call_succeeded`
se asignaban antes de validar citas: no prueban aceptación completa.

| Mensaje del asistente | Propuesta antigua | Ejecución | Edad del diagnóstico (s) | Pregunta pendiente guardada | Fallback |
|---|---|---|---:|---|---|
| 148 | ask_question | diagnóstico inicial 39 | 1.24 | ninguna | no |
| 150 | ask_question | ninguna | 13.76 | other_photo | no |
| 152 | ask_question | ninguna | 62.23 | ninguna | no |
| 154 | ask_question | ninguna | 115.48 | indicator_label | no |
| 156 | ask_question | ninguna | 150.81 | ninguna | no |
| 158 | ask_question | ninguna | 228.41 | ninguna | no |
| 160 | ask_question | ninguna | 251.65 | ninguna | invalid_citation |
| 162 | recommend_escalation | diagnóstico 40 y ticket | 1.56 | ninguna | invalid_citation |

Los dos diagnósticos fueron simulaciones CPE_UNREACHABLE. Hubo una foto y un ticket.
La primera guía ya estaba registrada. Desde 152 había intentos declarados, `indicators`
y `cable_path`; no se registraron comprobaciones físicas verificadas. La memoria de preguntas
no correspondía consistentemente con las preguntas en texto libre. Hasta 160 faltaban una
segunda medición y el predicado de evidencia suficiente; el resultado seguía fresco (límite 300 s).
El detalle por turno conserva progreso, predicados originales y recuperación documental.

La causa no fue omitir OpenAI: el modelo eligió preguntar repetidamente. El prompt anterior
pedía una pregunta de etiqueta para «is it good?». La validación controlaba tipos de pregunta,
pero no su utilidad operacional. La incertidumbre podía convertir una propuesta de recheck
en ask_question. El avance automático dependía de dos fotos o agotamiento más tres categorías;
una explicación de cables no daba prioridad a una medición. El error de citas activaba una
plantilla que volvía a pedir conexiones sin aprovechar el intento ya registrado.

En los ocho turnos hubo recuperación local, pero `context_injected=False` y
`injection_reason=external_sharing_disabled`: los documentos no estaban autorizados para
enviarse a OpenAI. Las citas guardadas entre 150 y 160 eran `django_local`, no prueba de uso
del manual por el modelo. El conjunto de fuentes autorizadas enviado era vacío; cualquier
cita del modelo fue por tanto rechazada como `invalid_citation`. No se conservó la cita
rechazada, por lo que no podemos identificar qué sección inventó o reutilizó. Se mantiene la
validación y se explicita que sin fuentes las citas deben estar vacías.

## Flujo corregido

Antes: clasificación/next_action → guardas que podían sustituir la acción → preguntas o
herramienta condicional → generación → fallback genérico.

Ahora: interpretación con `decision` validada → evaluación Django de utilidad/evidencia →
herramienta autorizada o reutilización → elegibilidad existente de revisión → generación con
`authorized_decision`, resultado real y ticket real → validación y como máximo una reparación
de pregunta redundante → resumen de hechos si falla la respuesta.

El contrato contiene ANSWER_CUSTOMER, REQUEST_NECESSARY_EVIDENCE,
RUN_AUTHORIZED_RECHECK, REQUEST_TECHNICAL_REVIEW, REPORT_EXISTING_TICKET y
VERIFY_CUSTOMER_CONNECTIVITY. Una solicitud de evidencia necesita `required_fact` y `reason`.
Para la incidencia genérica sólo se admiten hechos materiales: alimentación, recorrido y acceso;
se rechazan los ya suministrados y detalles de puertos/modelos que no cambian la acción.
Las explicaciones de conexión al ordenador se conservan como `equipment_role`.

Se conserva compatibilidad con proveedores/pruebas antiguos sin `decision`: su ruta operacional
anterior permanece. El esquema estructurado enviado a OpenAI exige una decisión no nula
(`DecisionInterpretation`); la regresión comprueba
explícitamente ese contrato con un proveedor simulado. No demuestra que un modelo real vaya
a emitir siempre una decisión adecuada. Un fallo de clasificación en una conversación que ya
usa el contrato conserva los hechos y permite evaluar acciones bajo las mismas políticas.

Permisos, simulador, frecuencia, deduplicación, prioridad y transiciones de tickets permanecen
en sus servicios actuales. La elegibilidad no se relaja: exige los predicados anteriores.
Una foto aislada no crea ticket. El ticket confirmado establece HANDOFF_PENDING y detiene el
cuestionario. No se modificaron interfaz, fotografías, manual, RAG ni aprendizaje de casos.

## Secuencia comprobada

`decision-loop-regression.json` conserva respuestas y decisiones de cada paso para cuatro
variantes: proveedor simulado correcto, fallo de redacción, fallo de clasificación final,
cita inválida, pregunta redundante, resultado caducado y restauración simulada.
No hubo llamadas externas; el constructor SDK estaba bloqueado.

| Paso | Propuesta del proveedor de prueba | Decisión/ejecución Django |
|---|---|---|
| No tengo Internet | intención antigua NO_INTERNET | diagnóstico inicial CPE_UNREACHABLE |
| Foto trasera + Is this connection good? | REQUEST_NECESSARY_EVIDENCE: indicator_label | ANSWER_CUSTOMER; rechaza detalle irrelevante |
| Yellow cable connected to Internet port | misma propuesta | RUN_AUTHORIZED_RECHECK; segunda medición real del simulador |
| Other cable is for my computer | misma propuesta | reutiliza segunda medición; conserva equipment_role |
| The lights are on | misma propuesta | reutiliza; conserva indicators, no certifica Internet |
| No, Internet still does not work | misma propuesta | reutiliza medición; no repite preguntas |
| I already gave you all the information I have | misma propuesta | REQUEST_TECHNICAL_REVIEW; ticket único |
| Queja posterior | intención de continuación | REPORT_EXISTING_TICKET; sin otro diagnóstico |

Hechos retenidos: `ports` con la explicación del cable amarillo, `equipment_role` con el
destino al ordenador, `indicators` con luces encendidas, intento declarado, incidencia
NO_INTERNET, guía presentada, foto simulada, agotamiento de evidencia, dos resultados del
simulador, ticket y estado terminal. Todos los reportes permanecen `verified=False`;
`trusted_verified_checks` queda vacío. Resultado: **2 diagnósticos, 1 foto, 1 ticket**.
Con recheck saludable: **2 diagnósticos, 0 tickets**; se debe confirmar navegación con el cliente.
Si caduca el resultado durante la conversación se permite una medición fresca, conservando
los límites existentes: la variante caducada comprueba **3 diagnósticos, 1 ticket**.

Se añadieron pruebas de pregunta material de alimentación, acceso imposible, separación de
incidencia lenta, estado saludable y fallos del proveedor. La suite previa sigue cubriendo español,
handoff explícito, aislamiento de cliente, autenticación, límites, manual y deduplicación.

## Verificación real pendiente, sólo tras autorización

1. Reiniciar el servidor local para cargar este código. Entrar mediante el acceso demo controlado
   existente; seleccionar servicio ficticio CPE_OFFLINE y proveedor OpenAI configurado en backend.
2. Abrir `/demo/`, una conversación nueva en inglés y DevTools → Network. Enviar exactamente
   los siete mensajes de la tabla; adjuntar una foto de demostración trasera en el segundo.
3. En las respuestas de `/api/chat/turn/` o `/api/chat/`, revisar `debug.chat.decision`:
   propuesta, decisión autorizada, ejecución y `tool_result`. Comprobar `model`, llamadas,
   `reply_validated` y motivos de fallback. No compartir imágenes ni claves.
4. Comprobar segundo diagnóstico o reutilización justificada, resultado disponible para la
   respuesta, ticket único al agotarse evidencia y ausencia de preguntas de etiquetas repetidas.
5. Repetir una queja después del ticket: debe presentar el mismo número sin otra medición.
   Detener la prueba si falta `decision`, aparece otra solicitud de puerto o la traza contradice
   la herramienta. Guardar sólo metadatos sanitizados para investigar.

No se ejecutó esta prueba facturable. Quedan sin verificar la calidad real del modelo,
su adhesión al contrato, las observaciones de una fotografía real y los errores reales de API.

## Archivos de esta intervención

- `conversations/decisions.py`: contrato, selección y resumen de fallback.
- `conversations/ai.py`: campo estructurado, instrucciones y categoría de cable al ordenador.
- `conversations/services.py`: integración, ejecución anterior a redacción, progreso y trazas.
- `conversations/context.py`: persistencia del uso del contrato.
- `conversations/test_decisions.py`: regresiones de decisiones y herramientas.
- `conversations/test_chat.py`: mantiene la prueba SDK y exige el nuevo esquema con decisión obligatoria.
- Este informe y los dos JSON de evidencia sanitizada.

## Validaciones ejecutadas

```powershell
.venv\Scripts\python.exe manage.py test --noinput
node --test tests/frontend.test.cjs
.venv\Scripts\python.exe manage.py check
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Resultado final: **289 pruebas Django aprobadas**, **10 pruebas JavaScript aprobadas**,
system check sin problemas y ninguna migración pendiente. No se eliminaron ni deshabilitaron
pruebas anteriores; la aserción del formato SDK se actualizó para exigir el contrato nuevo.
Se corrigieron las incompatibilidades encontradas durante el desarrollo antes de esta ejecución.
No hay errores de verificación pendientes. La prueba real OpenAI queda pendiente de autorización.
