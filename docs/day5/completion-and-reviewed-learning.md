# Finalización inteligente y aprendizaje mediante casos revisados

## Inspección inicial

El problema no provenía únicamente de DemoAI: el historial anterior mostró nueve
respuestas de OpenAI y dos respaldos de Django. La corrección previa ya conservaba
intentos, fotografías y parte de las preguntas respondidas. Aun así:

- El progreso no retenía categorías concretas de información aportada ni agotamiento
  semántico. La revisión inconclusa dependía fundamentalmente de dos fotografías.
- No existía una preferencia persistente de soporte humano ni un estado terminal de
  entrega. Una nueva queja podía volver a activar la investigación.
- Los respaldos podían repetir orientación o pedir aclaración de información ya aportada.
- Ticket contenía estado, fechas e historial, pero no causa técnica validada, aprobación
  de reutilización ni resumen minimizado. CLOSED no garantizaba una solución real.
- El buscador existente recuperaba documentos aprobados con alcance y autorización
  externa; no recuperaba incidentes resueltos ni tenía un ámbito de ISP para casos.

El simulador existente soporta HEALTHY, CPE_OFFLINE, WEAK_SIGNAL, LOW_THROUGHPUT y
ADMIN_SUSPENDED. No existen mediciones específicas de Wi-Fi, alimentación o
intermitencia. Esta entrega no inventa esas capacidades.

## Checkpoint A: finalización y entrega humana

La interpretación estructurada incorpora preferencia de humano/autoservicio, solicitud
voluntaria de explicación, agotamiento de evidencia, categoría del problema e información
aportada sobre recorrido de cables, puertos, alimentación, indicadores y función del equipo.

El resumen conserva respuestas, preguntas realizadas, informes por categoría, fotografías
analizadas, intentos no verificados, diagnóstico actual, ticket y comprobaciones pendientes.
Los mensajes originales siguen en la BD; el contexto de generación permanece acotado.
El presupuesto de salida de clasificación pasó de 256 a 768 tokens para acomodar el
esquema ampliado sin truncarlo. No se ha validado con llamadas reales en este encargo.

La política de revisión acepta ahora información estructurada suficiente cuando el cliente
no puede aportar más, además de las vías existentes. No basta frustración: se conserva
el requisito de incidencia sin Internet, guía presentada, intentos reportados, medición
simulada reciente de CPE inaccesible y dos mediciones fallidas. La información agotada
debe incluir al menos tres categorías técnicas. La herramienta autorizada conserva límites,
aislamiento y reutilización de resultados. No se cambió el motor ni la prioridad de tickets.

Las peticiones explícitas de humano siguen el servicio existente de escalamiento sin
esperar respuestas a preguntas ajenas. Si hay ticket autorizado activo se conserva
HANDOFF_PENDING, se informa su número/estado y se evita reiniciar diagnósticos.
Las comprobaciones voluntarias se registran sin volver a medir. Es posible pedir una
explicación segura o retomar explícitamente autoservicio.

La indisponibilidad del clasificador no bloquea una petición explícita de humano: un
respaldo limitado interpreta esa preferencia y Django mantiene los permisos y reglas.
Si la política no permite crear ticket, o falla la operación, no se confirma uno: se
deriva al operador autorizado de demo. Una solicitud sin evidencia de falla en un
servicio saludable sigue sin generar ticket. Las incidencias sin herramienta específica
no desencadenan mediciones inventadas para satisfacer la solicitud.

Antes de publicar una pregunta del modelo, el servidor comprueba preguntas respondidas,
progreso y entrega humana. Puede pedir una sola reparación de respuesta. Las respuestas
naturales válidas se conservan; se registran fallos y sustituciones. Los respaldos locales
usan la información estructurada para reconocer informes sin repetir toda la guía.

El checkpoint inicial pasó 256 pruebas Django y 10 JavaScript. Después se añadieron
pruebas adicionales de fallos, ayuda voluntaria y capacidades no disponibles.

### Transcripción obtenida mediante los endpoints

La transcripción completa está en `completion-learning-transcript.json`. Se exportó con
DemoAI forzado, clave vacía y el SDK OpenAI bloqueado. Los identificadores mostrados
pertenecen exclusivamente a la base aislada de pruebas.

> Cliente: The lights are green and orange.
>
> Nexo: I have retained your indicator report; local router lights do not prove outdoor CPE connectivity. The latest simulated check still cannot reach the outdoor equipment; the cause is unconfirmed.
>
> Cliente: The PoE connects to the outdoor antenna and then to my router.
>
> Nexo: I have retained your reports about cable routing, equipment roles; they are not independently verified. The latest simulated check still cannot reach the outdoor equipment; the cause is unconfirmed.
>
> Cliente: I already gave you all the information I have.
>
> Nexo: The simulated network check still cannot reach your outdoor equipment. Your troubleshooting attempts provide enough information for technical review; further uncertain checks are not required now. Your issue is recorded under ticket ISP-20FD37D6C4BF. No visit or repair has been confirmed.

Resultado: una fotografía, dos mediciones y un ticket. En el flujo separado de humano,
«Please open a support ticket» y «I already answered that» devolvieron el mismo ticket
OPEN, sin diagnósticos adicionales ni preguntas. Los números de prueba varían al repetir.

## Checkpoint B: conocimiento técnico revisado

Arquitectura mínima añadida, sin dependencias nuevas:

| Modelo | Función |
|---|---|
| SupportOrganization | ISP, miembros autorizados y plazo de conservación |
| Customer.organization | Alcance del aprendizaje; nullable para conservar datos existentes |
| TroubleshootingCategory | Evidencia, capacidades, comprobaciones seguras y fuentes configurables |
| CaseResolution | Resumen técnico minimizado, ticket opcional, causa y solución verificadas |
| CaseAudit | Verificación, aprobación, retirada y revisiones |
| CaseUsage | Casos recuperados, revisión, relevancia, conversación e inyección externa |

CaseResolution separa síntomas del cliente, intentos, observaciones no sensibles,
hipótesis de IA, hallazgos técnicos y causa verificada. Conserva confirmación de
restauración, técnico verificador, aprobación independiente, confianza, aplicabilidad,
revisión, fechas, política de reutilización y permiso externo independiente.

No hay importación automática de conversaciones, fotografías ni sugerencias de IA.
El resumen se introduce y revisa manualmente desde Admin. El vínculo al ticket queda
restringido a personal autorizado. Ni RESOLVED ni CLOSED aprueban conocimiento.

Cambiar contenido invalida aprobación y verificación, incrementa revisión y exige repetir
el control. Se conserva historial de las aprobaciones y cambios. Un caso retirado,
caducado, no aprobado, no verificado o con huella inconsistente queda excluido.

La recuperación léxica local clasifica por categoría, síntomas, diagnóstico, intentos,
hallazgos, causa y resolución, con compatibilidad estricta para fabricante/modelo cuando
el caso tiene ese alcance. Recupera hasta tres patrones y marca causas contradictorias.
Cada patrón afirma explícitamente que no prueba la causa actual.

Los patrones se incorporan al contexto de generación únicamente si están autorizados
para compartir externamente y KNOWLEDGE_ALLOW_EXTERNAL_AI=true. Se envía el resumen
técnico, nunca el ticket original, nombres, cuentas ni fotografías. La recuperación local
puede auditarse aun con compartir externamente desactivado; eso no significa que OpenAI
recibió o utilizó el contenido. No se altera ni se reentrena automáticamente ningún modelo.

La auditoría distingue recuperación de inyección. Los detalles de casos se ocultan en
debug salvo permiso de consulta y pertenencia al ISP, también al reproducir respuestas
idempotentes. El cliente no recibe referencias internas de otros incidentes.

### Dos problemas recurrentes verificados

En bases aisladas se aprobaron patrones ficticios de PoE defectuoso y antena desalineada.
Las conversaciones usaron los escenarios reales del simulador:

| Nueva incidencia simulada | Resultado real del simulador | Patrón recuperado |
|---|---|---|
| Falta de Internet, servicio DEMO-SERVICE-001 | CPE_UNREACHABLE | Caso NO_INTERNET de alimentación PoE |
| Internet lento, DEMO-SERVICE-002 | SIGNAL_DEGRADED | Caso SLOW_INTERNET de señal débil |

El segundo caso no recuperó el primero. Se comprobó también con un adaptador OpenAI
simulado que el patrón autorizado llega a generación y produce una hipótesis incierta,
sin mostrar número de caso ni afirmar que la causa actual está demostrada.

## Taxonomía y capacidades

La migración carga seis categorías configurables, sin sobrescribir configuraciones futuras:

- NO_INTERNET: conectividad simulada, alimentación y cableado accesible.
- SLOW_INTERNET: rendimiento/señal simulados y comparación cable/Wi-Fi; no impone PoE.
- INTERMITTENT_CONNECTION: horarios y dispositivos afectados; herramienta específica no disponible.
- NO_POWER: observación segura de alimentación; no mediciones de rendimiento.
- WIFI_ISSUE: dispositivos/distancia; herramienta Wi-Fi no disponible.
- ADMIN_SUSPENDED: estado administrativo y atención de cuentas, sin presentarlo como fallo físico.

Los datos describen capacidades y evidencia, no guiones separados. OpenAI recibe la
estrategia pertinente y decide su explicación; Django sigue controlando toda operación.

## Configuración y flujo de Admin

1. Ejecutar `python manage.py migrate` en el entorno virtual. Las tres migraciones nuevas
   ya están aplicadas en la base local de este proyecto.
2. Como superusuario, crear un ISP en `/admin/knowledge/supportorganization/`, definir
   miembros autorizados y retention_days (365 por defecto).
3. Asignar los clientes ficticios correspondientes desde `/admin/customers/customer/`.
   Los clientes existentes permanecen sin organización hasta asignación explícita; no
   reciben casos compartidos. Esto afecta al nuevo conocimiento, no convierte toda la
   aplicación actual en una plataforma multitenant de producción.
4. Otorgar al técnico permisos de añadir/cambiar/ver CaseResolution. Otorgar al revisor
   permiso `knowledge.review_caseresolution`, además de consulta/cambio y pertenencia al ISP.
5. Resolver un ticket mediante el flujo existente y registrar un resumen minimizado en
   `/admin/knowledge/caseresolution/`, seleccionando source_ticket cuando corresponda.
   No copiar conversaciones ni fotografías. Registrar hallazgo real, causa, solución,
   aplicabilidad y restauración confirmada.
6. El revisor revisa privacidad y política, marca privacy_reviewed/reuse_authorized y
   policy_reference. Compartir con IA externa sigue desactivado salvo autorización expresa.
7. El técnico ejecuta «Verificar hallazgos y restauración como técnico».
8. Un usuario diferente ejecuta «Aprobar resumen para recuperación interna». Un mismo
   usuario no puede verificar y aprobar el caso. Si el contenido cambia después de la
   verificación, esta queda invalidada y debe repetirse.
9. Usar las acciones de retirar/rechazar para conocimiento incorrecto. Las auditorías de
   revisiones y uso aparecen como secciones de solo lectura en el registro.

Los casos aprobados o borradores tienen caducidad según el ISP. La recuperación excluye
casos vencidos inmediatamente. `python manage.py expire_case_knowledge` retira aprobados
vencidos y registra EXPIRED, conservando auditoría. Opcionalmente se puede limitar con
`--organization CODIGO`. El borrado físico exige `--delete --organization CODIGO` y elimina
también auditorías/usos de esos casos vencidos: usarlo solo según la política de conservación.
No se ejecutó ningún borrado físico durante esta entrega ni se instaló un programador.

## Migraciones, archivos y verificaciones

Migraciones creadas y aplicadas:

- `knowledge/0003_troubleshootingcategory_caseresolution_caseaudit_and_more.py`
- `customers/0003_customer_organization.py`
- `knowledge/0004_seed_troubleshooting_categories.py`

Archivos modificados en esta entrega:

- `conversations/ai.py`, `adaptive.py`, `context.py`, `services.py`, `short_answers.py`,
  `web.py`, `test_progress.py`; nuevo `test_completion.py`.
- `customers/models.py`, `admin.py` y la migración indicada.
- `knowledge/models.py`, `admin.py`, `services.py`; nuevos `cases.py`, `strategies.py`,
  `test_cases.py`, `management/commands/expire_case_knowledge.py` y migraciones indicadas.
- `README.md` y este informe con su transcripción JSON.

Resultado final: **276 pruebas Django y 10 JavaScript aprobadas**. Se conservaron las
252 pruebas anteriores. `manage.py check`: sin problemas. `makemigrations --check
--dry-run`: sin cambios. `git diff --check`: sin errores de espacios; Git solo informa
la conversión habitual LF/CRLF de Windows.

Comandos de validación: `manage.py test --noinput`, `node --test tests/frontend.test.cjs`,
`manage.py check`, `manage.py makemigrations --check --dry-run`, `manage.py migrate`.
Las pruebas cubren privacidad, aprobación independiente, fuente resuelta, cierre sin
restauración, retiro/caducidad/corrección, fabricante/modelo, contradicciones, permisos,
aislamiento, autorización externa, escenarios, fallos y conservación de la interfaz anterior.

Para comprobar sin API: en PowerShell definir `$env:AI_PROVIDER='demo'`, iniciar
`python manage.py runserver 127.0.0.1:8000`, entrar en `/demo/` como operador autorizado
y seleccionar servicio ficticio. `/demo/state/` permite verificar completion_policy_version=1.
Reproducir la secuencia del encargo, luego una conversación con «I need a human».
En Network revisar `debug.chat.handoff_state`, `handoff_result`, `tool_result` y
`review_predicates`. Confirmar un único ticket y que recargar conserva la conversación.

## Límites

- No se hicieron llamadas facturables de verificación OpenAI en este encargo. La
  generación real y su calidad requieren una prueba expresamente autorizada.
- La recuperación es léxica, no semántica mediante embeddings. No garantiza identidad de
  causas y no ejecuta reparaciones sugeridas por casos históricos.
- Los filtros detectan identificadores conocidos, contactos, IP, cuentas e instrucciones,
  pero no sustituyen la revisión humana de privacidad, direcciones o datos indirectos.
- La base local no recibió casos aprobados ni asignaciones de ISP automáticamente: el
  flujo exige revisión autorizada; los ejemplos se crearon únicamente en pruebas aisladas.
- No se construyeron herramientas reales para Wi-Fi, alimentación o intermitencia, ni
  integración de SMS. No se cambiaron fotografías, manuales, catálogo, HTML, CSS o JS.
- Las fallas encontradas durante pruebas (memoria excedida, prioridad administrativa y
  bloqueo de entrega humana ante fallo del proveedor) quedaron corregidas. No quedan
  errores conocidos de las verificaciones ejecutadas.
