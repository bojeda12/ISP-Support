# Diagnóstico conversacional adaptativo — verificación

## Causa y corrección

El orquestador convertía `CONFIRM_PHYSICAL_CHECK` directamente en diagnóstico y
escalamiento. Una clasificación errónea de «I already tried that, but I'm not sure
if the connection is good.» podía contar una duda como comprobación completada.
Además, el enrutador de frases cortas podía sustituir una interpretación válida de
OpenAI y algunas respuestas se generaban antes de disponer del diagnóstico.

El control negativo automatizado reproduce la ruta anterior desactivando solamente
la nueva barrera de evidencia: dos diagnósticos y un ticket después de esa frase.
Con la barrera activa: un diagnóstico inicial, una duda guardada y ningún ticket.
No se cambiaron prioridades, transiciones, deduplicación ni servicios de tickets o
reglas del simulador. Se corrigió la evidencia conversacional que recibe ese flujo.

## Estado y decisiones

El estado se conserva en los metadatos existentes del mensaje del asistente;
no hay migraciones ni dependencias nuevas. Se distinguen:

- `customer_reported_checks`, `confirmed_completed_checks` y `uncertain_checks`.
  Incluso una comprobación declarada completa conserva `verified: false`:
  no equivale a verificación independiente.
- `troubleshooting_stage`, `next_recommended_action` y `pending_questions`.
- Diagnóstico y ticket consultados mediante ORM, observaciones de hasta tres
  fotos, incertidumbres, equipo observado y guías ya presentadas.

OpenAI propone una acción estructurada: preguntar, solicitar una vista útil,
recheck o recomendar escalamiento. Las instrucciones exigen usar observaciones,
preguntas pendientes y resultados reales; no asumir que dos fotos son del mismo
equipo; y pedir otra vista solo cuando sea útil. La salida válida del modelo
conserva su redacción. La selección determinista de frases cortas queda en DemoAI.
La barrera local detecta negaciones e incertidumbre explícita en inglés/español,
además del campo semántico `check_evidence` del modelo.

Se reutiliza el catálogo y la búsqueda documental existentes, con aprobación y
permisos de envío externo intactos. Una guía genérica no respalda afirmaciones
específicas de modelo. Para observar conectores o explicar enlace Ethernet no se
exige identificar fabricante; colores y asignación de puertos requieren evidencia.
Las fotos no demuestran acceso a Internet ni completan comprobaciones físicas.

## Herramienta autorizada

`authorized_recheck()` es una función interna de Django: no es un endpoint público
ni permite comandos arbitrarios. Valida sesión, operador, cliente, servicio y
conversación abierta. Serializa mediante bloqueos ORM, reutiliza resultados sin
evidencia nueva y aplica dos ejecuciones por conversación en 30 segundos y seis
por servicio en una hora. Solo admite origen `simulation`; no conecta equipos.

El simulador local tiene un presupuesto de cinco segundos: si lo excede, la
transacción revierte su resultado y se devuelve un error controlado. Esta medida
comprueba duración al regresar; no interrumpe un proceso Python bloqueado. Una
integración externa futura necesitará timeout real de transporte y ejecución.
Las llamadas OpenAI conservan sus límites de tiempo existentes y cero reintentos
automáticos. El resultado o la razón de reutilización se pasan al generador antes
de redactar la explicación. La traza segura de desarrollo incluye `tool_result`.

El contrato usa propuestas JSON del adaptador existente; no incorpora un bucle
general de function calling. Django decide y ejecuta las operaciones permitidas.
Véase el patrón de [ejecución de herramientas por la aplicación de OpenAI](https://developers.openai.com/api/docs/guides/function-calling).

## Antes y después del escenario exacto

| Turno | Antes: ruta defectuosa reproducida | Después |
| --- | --- | --- |
| «Hello, I don't have Internet. Can you help me?» | Diagnóstico inicial | `CPE_UNREACHABLE`, cuatro tarjetas en el orden existente |
| Foto posterior + «I already tried that, but I'm not sure if the connection is good.» | Si el clasificador devuelve confirmación: recheck y ticket inmediato | Guarda intento incierto, explica los límites de la foto y pide una vista frontal útil; ningún ticket ni recheck |
| Foto frontal | Sin continuidad adaptativa fiable | Conserva ambas fotos; una propuesta autorizada ejecuta recheck; el resultado llega al generador; ningún ticket solo por la foto |
| «I already checked the power and cables.» | — | Con falla persistente, el servicio existente crea/reutiliza el ticket; comunica revisión técnica sin repetir la guía |
| Repetir esa confirmación | Podía repetir mediciones innecesarias | Reutiliza diagnóstico y ticket; distingue resultado disponible de medición nueva |

Respuesta comprobada con OpenAI **simulado en pruebas** para la foto posterior:
«The rear plugs and lights suggest a local link, but not Internet access.
Could you show the front indicators?» Para la frontal, el generador recibe
`cpe_online: false` y ambas observaciones, y explica que los indicadores no
demuestran que el equipo exterior responda.

DemoAI declara que no interpretó los píxeles. Su respuesta final de recheck evita
repetir instrucciones: «The new simulated check still cannot reach the outdoor
CPE. The photo cannot confirm Internet connectivity or the cause. Which
accessible checks can you confirm you completed?» La redacción se ajustó después
de detectar la repetición durante la prueba de navegador y quedó cubierta por
una aserción automatizada.

El resumen del ticket contiene diagnóstico y métricas, comprobaciones declaradas
por el cliente, dudas anteriores y observaciones visuales con su origen. En Demo
se rotulan como simuladas; no se inventan comprobaciones realizadas.

## Validación

- `python manage.py test --noinput`: **226 pruebas aprobadas**, 7,617 segundos;
  incluye las 210 anteriores y 16 pruebas adaptativas nuevas. Se ajustó únicamente
  la expectativa de cantidad de diagnósticos del test de problema repetido: dos
  pasaron a uno, conservando sus comprobaciones sobre guías y mensajes.
- `node --test tests/frontend.test.cjs`: **10 aprobadas**.
- `python manage.py check`: sin incidencias.
- `python manage.py makemigrations --check --dry-run`: sin cambios.
- `python -m pip check`: sin dependencias rotas.
- `.env` sigue ignorado por Git; no se modificó su contenido.

Las pruebas adaptativas cubren el escenario exacto, fotos combinadas con texto,
dos vistas, incertidumbre EN/ES, clasificación errónea, propuesta OpenAI y contexto
del resultado, resultado saludable, falla persistente, solicitud inmediata de
ticket, reutilización, límites, rollback por tiempo, aislamiento de conversación,
origen externo rechazado, proveedor fallido y fallo de generación tras escalamiento.
Las regresiones existentes de permisos, manual, citas y fotografías siguen pasando.

Navegador real en `127.0.0.1:8005`, con base SQLite, almacenamiento y operador
temporales aislados, **DemoAI** y dos imágenes sintéticas de prueba:

1. Saludo con falta de Internet: un diagnóstico y cuatro tarjetas.
2. Foto posterior con la frase exacta: aclaración, cero tickets, sin otro diagnóstico.
3. Recarga: historial, foto y pregunta pendientes conservados.
4. Segunda foto sin texto: segundo diagnóstico, cero tickets, sin repetir tarjetas.
5. Confirmación explícita: tercer diagnóstico y un ticket `OPEN`.
6. Repetición: mismo ticket, tres diagnósticos totales, dos fotos, diez mensajes y
   cuatro imágenes de guía. Los dos eventos del ticket no se duplicaron.

Los pasos tardaron más de 30 segundos en navegador; por eso la confirmación pudo
ejecutar el tercer diagnóstico. El test rápido reutiliza el segundo debido al
límite de frecuencia. Ambos casos están cubiertos.

Capturas: [duda sin ticket](adaptive-uncertain-desktop.jpg) y
[ticket tras confirmación](adaptive-verification-ticket-desktop.jpg).
No hubo llamadas facturables a OpenAI: el SDK se simuló en las pruebas automáticas.
No se validó en vivo la calidad variable de un modelo real ni el reconocimiento
de fotografías de equipos reales. La barrera de frases no es un analizador
semántico exhaustivo; complementa la interpretación estructurada del modelo.
La búsqueda documental y sus restricciones de envío externo no se ampliaron.

## Reproducción manual en tu demo

1. Ejecutar `.\.venv\Scripts\python.exe manage.py runserver` y abrir
   `http://127.0.0.1:8000/demo/` con un operador autorizado del mecanismo existente.
2. Elegir English y `DEMO-SERVICE-001`; conectar.
3. Enviar exactamente «Hello, I don't have Internet. Can you help me?».
4. Adjuntar una foto posterior y enviar en el mismo turno «I already tried that,
   but I'm not sure if the connection is good.».
5. Verificar la aclaración, ausencia de ticket y conservación de las cuatro tarjetas.
6. Recargar. Confirmar que persisten el historial y la foto. Adjuntar la vista
   frontal cuando se solicite y enviar: debe explicarse el resultado del recheck,
   sin inferir conectividad por luces ni crear ticket solamente por la foto.
7. Enviar «I already checked the power and cables.». Con falla persistente aparece
   el ticket. Repetir: debe conservar el mismo número.
8. Consultar Django Admin para comprobar diagnósticos y resumen factual del ticket.

DemoAI permite reproducir el flujo sin claves. Para probar razonamiento real,
usar la configuración OpenAI existente exclusivamente en el backend; verificar
el proveedor con `python manage.py ai_runtime`. El consumo real tiene costo.
El servidor y usuario temporales de QA se eliminan al finalizar esta verificación.

## Archivos de esta ampliación

- `conversations/adaptive.py`: evidencia, propuestas Demo y herramienta autorizada.
- `conversations/ai.py`: esquema e instrucciones de interpretación/generación.
- `conversations/context.py`: memoria persistente acotada y contexto visual.
- `conversations/services.py`: integración y explicación posterior al resultado.
- `config/settings.py`: límites de frecuencia y duración del diagnóstico.
- `conversations/test_adaptive.py`, `conversations/test_context.py`: regresiones.
- Este informe, enlace en `README.md` y dos capturas nuevas de QA.

No se reemplazaron manuales, fotografías, catálogo, endpoints protegidos ni UI.
No se modificaron los servicios de negocio de tickets/diagnósticos, autenticación
o autorización. No hay nuevas dependencias, migraciones ni desarrollo de SMS.
