# Conocimiento interno, avance proactivo y revisión técnica

## Problemas encontrados

El orquestador construía una cita local con el primer resultado recuperado y añadía
título, página, revisión y texto literal al mensaje, incluso cuando el fragmento no
había salido de Django. `customer_safe` autorizaba su uso, pero no existía una
política separada para mostrar la fuente. El historial y las respuestas idempotentes
guardadas podían conservar esos apéndices.

Las plantillas de aclaración pedían el modelo exacto por defecto. Además, la política
conservadora previa exigía declarar comprobaciones completas para escalar una falla
de CPE. Un intento inconcluso podía quedar atrapado entre preguntas y fotografías,
aunque un nuevo diagnóstico siguiera fallando.

## Visibilidad independiente de autorización

`ReferenceDocument.visibility` distingue cuatro políticas:

| Valor | Uso visible para el cliente |
| --- | --- |
| `internal` | Contexto autorizado y auditoría; sin referencias públicas |
| `generic_demo` | Orientación genérica de demostración; sin referencias públicas |
| `manufacturer` | Referencia concisa solo si la categoría también es manual de fabricante |
| `customer_approved` | Referencia concisa aprobada expresamente para mostrar |

La migración `knowledge.0002_referencedocument_visibility` asigna `internal` a los
documentos existentes. Se aplicó correctamente. No reindexa ni modifica los PDF,
secciones, páginas aprobadas, fotografías o permisos de envío externo.

Se conservan todos los filtros de recuperación: cliente, aprobación, secciones
revisadas, `customer_safe`, vigencia y alcance del equipo. La visibilidad no concede
permiso para recuperar otro documento ni acceder a su PDF. Tampoco autoriza enviar
fragmentos a OpenAI: siguen siendo necesarios el permiso del documento y
`KNOWLEDGE_ALLOW_EXTERNAL_AI`.

En Admin, solo quien tiene `knowledge.approve_reference` puede cambiar la política
de visibilidad; los cambios requieren reaprobación mediante el flujo existente.
Para una fuente pública se devuelve una referencia breve, sin extracto, página o
revisión. No se publica el PDF ni se añade una URL de descarga.

Las citas completas y su procedencia se conservan en `Message.metadata`, junto con
`citation_origin`, páginas y resultados recuperados. En desarrollo, los identificadores
y títulos del debug solo se muestran al operador con
`knowledge.view_referencedocument`; el resto recibe esos arrays vacíos. Se añaden
`customer_displayed` e `internal_citations_retained` para distinguir ambas cosas.

La generación recibe instrucciones de parafrasear. Una validación adicional rechaza
títulos internos y extractos literales detectables, y usa el fallback seguro. Las
citas antiguas se ocultan al presentar historial y repetir respuestas idempotentes,
sin borrar su auditoría. También se limpia el historial enviado al adaptador.

Si una fuente permanece local, la traza indica `django_local` y
`context_injected: false`; no se atribuye su consulta a OpenAI. Cuando el envío
externo no está autorizado, el modelo no recibe ese manual: conserva orientación
general y el backend registra la recuperación local. La validación de citas no
garantiza por sí sola que toda frase del modelo esté sustentada.

## Cambio explícito de elegibilidad

Esta ampliación **sí cambia la elegibilidad conversacional** para revisión técnica,
conforme a la solicitud. No cambia `tickets/services.py`, `diagnostics/services.py`,
prioridades, transiciones, permisos ni la clave de deduplicación.

`CHAT_ALLOW_INCONCLUSIVE_REVIEW=true` habilita la nueva política, activada por defecto.
Puede desactivarse en el entorno y reiniciar Django para recuperar el comportamiento
conservador anterior. No se modificó `.env`; se documentó en `.env.example`.

`review_eligibility()` exige conjuntamente:

1. Caída de Internet reportada y guía ya presentada.
2. Los dos últimos diagnósticos de la conversación deben ser simulados y devolver
   `CPE_UNREACHABLE`. Un resultado saludable interrumpe esa evidencia de persistencia.
3. El último resultado debe haberse completado en los últimos 300 segundos.
4. Debe existir un intento relevante declarado por el cliente o comprobaciones
   declaradas completas. Una duda sola o «I haven't checked anything» no basta.
5. Dos fotografías con análisis completado ya revisadas como evidencia disponible,
   o una declaración de que las comprobaciones adicionales son inaccesibles.

El mínimo de fotos y la antigüedad máxima son ajustes del servidor en
`config/settings.py`. Esta política considera que repetir las vistas genéricas ya
aportadas no justifica mantener al cliente en el mismo bucle: una revisión técnica
puede investigar lo que sigue inconcluso. No diagnostica integridad del cable a
partir de una imagen ni certifica que dos fotografías correspondan al mismo equipo.
En Demo, el análisis completado significa simulación explícita del flujo, no examen
real de píxeles; esa diferencia se conserva en el resumen del ticket.

Se distinguen `trusted_verified_checks` (vacío: ningún instrumento actual verifica
comprobaciones físicas), declaraciones completas del cliente, intentos, dudas,
observaciones visuales y resultados de red. Los informes del cliente siguen teniendo
`verified: false`. `additional_checks` registra disponibilidad o incertidumbre;
las propuestas estructuradas no sustituyen los requisitos del servidor.

Una segunda vista permite avanzar al recheck sin volver a exigir modelo o foto.
Se mantienen sesión autorizada, alcance del servicio, bloqueo ORM, simulación,
límites de frecuencia y presupuesto temporal. Django crea/reutiliza el ticket antes
de pedir a OpenAI la explicación final. El modelo recibe el resultado real y el
ticket confirmado; un número de ticket inventado se rechaza.

Si el servicio está saludable, se pregunta si el cliente puede navegar y no se
abre ticket. Si todavía falta el intento relevante, se pregunta por esa comprobación
sin volver a pedir todas las vistas. La solicitud explícita de técnico y las otras
condiciones legítimas del flujo previo siguen funcionando.

Las aclaraciones de equipo se conservan, incluida Frontier; no se exige nuevamente
un modelo para comprobaciones genéricas. Una pregunta específica sobre significado
de indicadores puede justificar consultar el modelo. Las instrucciones del modelo
priorizan observaciones disponibles y evitan pedir vistas ya aportadas. La respuesta
válida de OpenAI conserva su redacción; el fallback no finge reconocimiento visual.

## Transcripción antes/después

Antes, el flujo de tres turnos terminaba así:

1. Cliente: «Hello, I don't have Internet.» → diagnóstico inicial y cuatro tarjetas.
2. Foto posterior + intento incierto → orientación, solicitud frontal y apéndice
   con título del manual, página, revisión y cita textual.
3. Foto frontal → nuevo fallo simulado, pero se seguían pidiendo comprobaciones
   completas; no se habilitaba revisión por el intento inconcluso existente.

Después, transcripción del navegador con DemoAI y fotos sintéticas:

1. Cliente: «Hello, I don't have Internet.»

   Nexo: «The CPE is not responding in the simulation; the cause is unconfirmed.
   Check the PoE injector power and indicators and safely accessible cables and
   connectors. PoE is only one possible cause. Do not climb onto the roof or handle
   electrical wiring. Tell me when you have completed the checks so I can run the
   diagnostic again.» Se conservan las cuatro tarjetas existentes.

2. Cliente: foto posterior + «I already tried that, but I'm not sure if the
   connection is good.»

   Nexo: «This is simulated analysis: the photo was not interpreted. I can provide
   general guidance, but cannot verify the visible lights or connections. Visually
   check accessible Ethernet plugs for a seated connector and obvious cable damage,
   then observe the labeled link indicator without unplugging unfamiliar wiring.
   A connected plug does not prove cable integrity or Internet access. Could you
   show the front of that device, without private information, so we can inspect
   its labeled indicators?» Sin cita interna, recheck adicional ni ticket.

3. Cliente: foto frontal sin texto adicional.

   Django: segundo diagnóstico simulado fallido; política satisfecha; ticket `OPEN`.

   Nexo: «The simulated network check still cannot reach your outdoor equipment.
   Your troubleshooting attempts provide enough information for technical review;
   further uncertain checks are not required now. Your issue is recorded under
   ticket ISP-9C43BB992E93. No visit or repair has been confirmed.»

El número corresponde a la base temporal de QA, eliminada al terminar. El resumen
incluye la duda del cliente, observaciones explícitamente simuladas, diagnóstico y
motivo de elegibilidad; no afirma que completó o verificó todos los controles.

## Verificación y proveedores

- `python manage.py makemigrations knowledge`: migración de visibilidad creada.
- `python manage.py migrate`: aplicada `knowledge.0002`.
- `python manage.py test --noinput`: **245 pruebas aprobadas**; 226 anteriores y
  19 nuevas. Ninguna prueba eliminada.
- `node --test tests/frontend.test.cjs`: **10 aprobadas**.
- `python manage.py check`: sin incidencias.
- `python manage.py makemigrations --check --dry-run`: sin cambios pendientes.
- `python -m pip check`: sin dependencias rotas.

Se actualizaron expectativas de presentación que exigían citas extensas, modelos
obligatorios y códigos internos. Las 16 pruebas adaptativas previas siguen activas
con la nueva revisión por intentos inconclusos deshabilitada explícitamente; las nuevas cubren la
política proactiva activa y su desactivación. No se deshabilitaron pruebas.

Las regresiones nuevas cubren visibilidad interna/pública, auditoría autorizada,
historial y repetición de respuestas antiguas, citas inventadas, títulos/fragmentos
internos en salida del modelo, intento frente a mera incertidumbre, dos fotos sin
intento, inaccesibilidad, EN/ES, Frontier, recheck saludable, falla persistente,
idempotencia, antigüedad de mediciones, contexto real de ticket enviado al generador
y fallback después de escalamiento. Los límites, permisos, aislamiento y orden de
guías siguen cubiertos por las pruebas existentes.

Navegador real en una demo aislada de loopback con **DemoAI**: dos fotos sintéticas,
dos diagnósticos, seis mensajes, cuatro tarjetas y un único ticket. La recarga
conservó todo y el título del manual no apareció. La auditoría retuvo tres fuentes
en la respuesta posterior y dos en la frontal, ambas `django_local` y
`customer_displayed: false`. Se verificó la [captura](proactive-review-desktop.jpg).
El servidor, usuario y almacenamiento temporales se retiraron al terminar.

La validación automatizada final emplea DemoAI y adaptadores/SDK simulados. En un
primer pase, dos casos nuevos no habían aislado el adaptador visual e intentaron
la ruta OpenAI, que falló; se corrigieron para simular también visión. Esos intentos
no constituyen validación con OpenAI real. No se verificó consumo remoto de esos
intentos fallidos ni calidad en vivo del modelo. El acceso inicial del navegador
al servidor dentro del sandbox falló; el servidor aislado autorizado fuera del
sandbox permitió completar la prueba. El PDF emitió su aviso de tabla xref habitual,
pero indexó correctamente 16 páginas y 29 secciones en la base de QA.

## Archivos y límites

Cambios de esta ampliación:

- `knowledge/models.py`, `knowledge/admin.py`, `knowledge/services.py` y migración
  `0002_referencedocument_visibility.py`.
- `conversations/ai.py`, `adaptive.py`, `context.py`, `services.py`, `short_answers.py`,
  `history_api.py` y `turns.py`.
- `config/settings.py`, `.env.example`, `README.md`.
- `conversations/test_proactive.py` y ajustes de expectativas en `test_adaptive.py`,
  `test_context.py`, `test_knowledge_chat.py` y `test_short_answers.py`.
- Este informe y una captura nueva de QA. Sin dependencias nuevas ni cambios de UI.

Los límites de lenguaje y visibilidad son defensas conservadoras; no equivalen a
una garantía semántica completa sobre texto generado. La selección de vistas usa
el contexto existente y su estado de análisis, no reconocimiento geométrico de
frontal/posterior. La identidad del equipo sigue siendo incierta cuando corresponda.
DemoAI no interpreta imágenes. Falta evaluación con OpenAI real y equipos reales
autorizados. La revisión técnica no programa visitas ni confirma reparaciones.
El presupuesto temporal del simulador sigue siendo comprobación al retornar,
sin interrupción forzada de procesos bloqueados. No se inició SMS.

Para reproducir: reiniciar Django, abrir `http://127.0.0.1:8000/demo/`, elegir English
y `DEMO-SERVICE-001`, y seguir los tres turnos anteriores. No hace falta editar
`.env` para activar la nueva política por defecto. Para volver al modo conservador,
establecer `CHAT_ALLOW_INCONCLUSIVE_REVIEW=false` y reiniciar. En Admin se pueden
revisar el ticket y los metadatos con los permisos existentes.
