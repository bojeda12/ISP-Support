# Continuidad, escenarios y tickets — 10 octubre 2026

## Identificación previa a los cambios

La solicitud reportada está almacenada como mensaje 211 («no tengo internet»), respuesta 212 y ChatTurn 74. Operador autenticado: **bojeda**. Cliente autorizado: **DEMO-CUSTOMER-002**, UUID 00000000-0000-4000-8000-000000000002. Servicio interno **2 / DEMO-SERVICE-002**. Conversación **29**, creada el 2026-10-10 a las **22:18:19.649387 UTC**: era nueva, con solo ese par de mensajes; no una recuperación de mensajes anteriores.

El diagnóstico **54**, creado a las **22:18:21.283041 UTC**, fue una ejecución nueva, escenario **WEAK_SIGNAL**, resultado **SIGNAL_DEGRADED/DEGRADED**. Métricas: CPE en línea, RSSI −82 dBm, SNR 9 dB, latencia 85 ms, pérdida 6 %, descarga 25 Mbps. Coincide con SimulationState del servicio 002. El síntoma NO_INTERNET no transforma esas mediciones en CPE_UNREACHABLE.

Ticket **ISP-8714A9714CB0**, cliente/servicio/conversación anteriores, creado a las **22:18:21.285235 UTC**, estado actual **OPEN**. Fue creado en ese turno, no reutilizado. DiagnosticRun.assessment registra `requires_escalation=True`, `follow_up=TECHNICAL_REVIEW`, prioridad MEDIUM. El orquestador ya escalaba automáticamente SIGNAL_DEGRADED/PERFORMANCE_DEGRADED. No hubo hechos físicos heredados: completed_checks, shown_guides y customer_claims estaban vacíos. Se conserva esa elegibilidad, como exige la restricción de no cambiar reglas de tickets. Para retrasar ese ticket sería necesario un cambio explícito de política, fuera de esta corrección.

La respuesta original provino de **OpenAI gpt-4.1-mini**, sin fallback, según su metadata persistida; no se realizaron nuevas llamadas reales. Su frase «en proceso de revisión técnica» excedía el estado OPEN: no hay asignación confirmada. Las nuevas instrucciones de contexto recuerdan esta diferencia y la causa real de escalación, sin reemplazar el modelo ni añadir llamadas.

No mostrar PoE en WEAK_SIGNAL es correcto: el catálogo excluye esa guía para degradación de radio. La falta de fotografías no fue consecuencia de estado compartido en la conversación 29.

## Causa del historial aparentemente perdido

Los chats previos del servicio 002 siguen almacenados: conversación **26**, mensajes **203–204**; conversación **28**, mensajes **209–210**. El chat 29 contiene **211–212**. No se borraron mensajes. El endpoint muestra el historial de un ID concreto y pagina 50 mensajes; no debe mezclar chats independientes.

La interfaz carecía de selección explícita de chat anterior y de Nuevo chat. Además, al cambiar de servicio con una sesión previa, el código solo intentaba recuperar el último turno si no existía ningún demo_session_id. Por ello podía abrir un chat nuevo sin recuperar el anterior del servicio seleccionado. Los registros no conservan un evento de clic que permita afirmar qué gesto concreto produjo el cambio del usuario.

La clave persistente de Django configurada en la corrección anterior se conserva. No se volvió a cambiar. El navegador de pruebas mantuvo sesión, conversación y mensajes tras reiniciar Django.

## Cambios acotados

- **conversations/web.py**: recuperación por operador y servicio al volver a ese servicio; listado paginado de conversaciones asociadas a turnos del operador; selección explícita y chat nuevo diferido. Valida operador, cliente y servicio. Chats cerrados se pueden leer.
- **config/urls.py**: GET `/demo/conversations/`, POST `/demo/conversation/`; protección demo, login y CSRF existentes.
- **conversations/templates/conversations/demo.html**: selector Previous chats / Conversaciones anteriores, Retomar, Nuevo chat y Más; conserva diseño y recursos.
- **conversations/static/conversations/demo.js**: selección por endpoint autorizado, historial completo con su paginación existente, estado de solo lectura para chats cerrados y actualización del selector después del envío. Un error no vacía mensajes ni reintenta mutaciones.
- **conversations/quick_replies.py**: opción voluntaria de continuar para degradación con ticket, seguida de opciones del síntoma. El texto no pide «quiero un ticket», evitando la clasificación accidental como solicitud de técnico. Todas usan el endpoint multipart actual.
- **conversations/services.py**: contexto de presentación para señal degradada y continuación segura; distingue equipo alcanzable de acceso a Internet. Recupera el ticket de esa misma conversación/cliente/servicio para devolver su estado verificado al continuar. No crea ni cambia tickets por este ajuste.
- **conversations/test_continuity.py**, **tests/frontend.test.cjs**: regresiones.
- README e informe/evidencias.

El historial seleccionable exige evidencia de pertenencia al operador mediante ChatTurn. Los chats antiguos creados fuera de ese flujo, sin asociación verificable al operador, no se atribuyen automáticamente a alguien. No se amplió autorización para adivinar su propietario.

## Validación automatizada final

`python manage.py test --noinput`: **333 pruebas, OK, 29.452 s**. `node --test tests/frontend.test.cjs`: **17 pruebas, OK**. Se conservaron las anteriores. `manage.py check`: sin incidencias; `makemigrations --check --dry-run`: sin cambios; `node --check` correcto.

Las cuatro pruebas Django nuevas cubren:

1. Chat nuevo, recuperación, fotografía, más de 50 mensajes, refresco y cambio de servicio.
2. WEAK_SIGNAL real con síntoma NO_INTERNET, ticket nuevo frente a reutilizado, sin PoE ni hechos heredados, y respuesta rápida multipart real para continuar con el mismo ticket.
3. Sesión expirada y reconexión, operador distinto rechazado, lectura de chat cerrado, rechazo de escritura y CSRF.
4. HEALTHY y suspensión administrativa, sin inventar fallo CPE ni ejecutar hardware sobre cuenta suspendida.

Tres pruebas JavaScript nuevas ejecutan el manejador de selección: un POST por acción, sincronización posterior y conservación de mensajes ante HTTP 403.

## Navegador: resultados observados

Se utilizó copia SQLite aislada, configuración de escenarios original, sin reseed, cuotas intactas, DemoAI y constructor OpenAI bloqueado. La contraseña temporal del operador existió únicamente en la copia. No se cambió su contraseña original.

- Servicio 002: al conectar recupera chat 29 y ticket original; selector permite 28 y 26. Recuperar 26 cambia a inglés y muestra su ticket con estado actual CLOSED. El texto histórico se conserva tal como se emitió, aunque mencionara OPEN en su momento.
- Recargar conserva chat 26. Nuevo chat limpia solo la presentación/puntero; conserva los chats anteriores en el selector y la base.
- Chat nuevo **30** sobre servicio 002: resultado SIGNAL_DEGRADED y ticket **ISP-EF7DB1923488** conforme a la política existente; sin PoE. Continuar con el botón corregido mantiene ese ticket y pregunta si la pérdida es total, intermitente o lenta; no crea otra medición ni ticket en ese turno final. La prueba preliminar del texto anterior sí causó un recheck adicional, lo que identificó la clasificación errónea corregida. La evidencia SQL conserva ambos hechos: diagnósticos 55 y 56, un ticket.
- Reiniciar el servidor aislado y recargar conserva autenticación, chat 30 e historial.
- Cambiar al servicio 001 recupera chat 27 con su propio diagnóstico/historial. Nuevo chat **31** → «No tengo internet.» → diagnóstico **57**, CPE_OFFLINE/CPE_UNREACHABLE, cuatro imágenes en orden y **sin ticket heredado**, aunque existen tickets de otros chats del mismo servicio.
- Recuperar chat **21** muestra cuatro mensajes, fotografía enviada, guía y ticket histórico con su estado actual; no mezcla contenido del servicio 002.

Evidencias: continuity-signal.jpg, continuity-cpe.jpg, continuity-history-photo.jpg y continuity-browser-proof.json. Los IDs 30/31 y 55–57 anteriores pertenecen a la copia de prueba.

## Conservación y uso

Comparación SHA256 de cada fila de todas las tablas del dominio: **sin cambios** en la base original. Conserva **29 conversaciones, 212 mensajes, 22 fotografías, 54 diagnósticos y 17 tickets**. Ver continuity-before.json y continuity-preservation.json. No se borraron ni regeneraron fotografías, manuales o conocimiento. Sin nuevas dependencias, migraciones, SMS ni cambio del modelo OpenAI.

Reiniciar el servidor local para cargar Python y abrir http://127.0.0.1:8000/demo/. Elegir el servicio correcto: **001 = CPE_OFFLINE; 002 = WEAK_SIGNAL**. Utilizar el selector y Retomar para recuperar un chat concreto; Nuevo chat para empezar sin hechos heredados. El ticket inmediato de señal degradada sigue siendo una decisión válida de la política existente, no una regresión de aislamiento.
