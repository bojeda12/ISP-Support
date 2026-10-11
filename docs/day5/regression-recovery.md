# Recuperación de diagnóstico e historial — 10 octubre 2026

## Causa comprobada

La base actual tenía seis diagnósticos del servicio DEMO-SERVICE-001 dentro de una hora: 43–48 (20:49:05–20:53:52 UTC). Las conversaciones 22 y 23 conservaron los mensajes 185–188, pero no ejecutaron diagnósticos. La llamada directa a `authorized_recheck()` reprodujo `django.core.exceptions.ValidationError: ['Diagnostic frequency limit reached.']` en adaptive.py, antigua línea 214. Véase regression-before-trace.txt. El simulador no llegó a invocarse: el límite por servicio también protege la evaluación inicial de una conversación nueva. El manejador convertía esta condición esperada en un mensaje incorrecto de fallo del simulador.

No había terminal del servidor original adjunta; la excepción se obtuvo mediante reproducción directa, de solo lectura, sobre su base y configuración. No se atribuye a un traceback del servidor que no pudimos consultar.

Git HEAD es 1c17515. El límite y el flujo adaptativo pertenecen al trabajo local sin commit; no se identificó una modificación de mensajes/progreso que rompiera el simulador. No sería correcto revertir indiscriminadamente ese trabajo. Se conserva la cuota de seis por hora y las demás reglas.

El historial permanecía almacenado. `DJANGO_SECRET_KEY` estaba vacío: settings generaba una clave aleatoria por proceso, comportamiento ya presente en HEAD. Tras reiniciar, las sesiones firmadas anteriores no podían decodificarse. Además, la expiración demo devolvía un estado sin servicio, que el cliente interpretaba como cambio de conversación y vaciaba la pantalla. La reconexión también eliminaba el identificador anterior.

## Correcciones mínimas

- conversations/adaptive.py: excepción específica de cuota con tiempo de espera; límites intactos.
- conversations/services.py: respuesta bilingüe precisa para cuota, sin afirmar una medición; traceback completo para fallos esperados del diagnóstico. No se añade captura general de errores de programación.
- conversations/web.py: reconectar el mismo servicio conserva la conversación abierta del operador autorizado; después de iniciar sesión puede recuperar su último turno del servicio. Se verifica cliente, servicio y operador.
- conversations/static/conversations/demo.js: sesión vencida conserva mensajes visibles y permite reconectar; refrescar no borra el aviso. No confirma un cambio de servicio cuando solo se renueva la sesión.
- conversations/templates/conversations/demo.html: versión de caché de recursos.
- conversations/test_recovery_regression.py y tests/frontend.test.cjs: regresiones.
- .env local, excluido de Git: clave Django persistente generada sin mostrarla. Dos procesos independientes cargan la misma clave. No se cambió proveedor ni modelo.

## Antes y después en navegador

Antes, base original: «Your message was saved, but the simulated diagnostic could not be completed…», sin nuevo diagnóstico.

Después, réplica SQLite de esa base: primer mensaje muestra el límite real, aclara que no hubo medición y permanece al recargar. Se simula el vencimiento de la cuota adelantando una hora **únicamente el reloj del servidor de pruebas**. No se alteran fechas ni cuotas originales.

Conversación aislada 24:

1. «I don't have Internet.» → diagnóstico 49, FAILED/CPE_UNREACHABLE, guía visible.
2. «I checked the cables, router and PoE power. Everything is connected but Internet still doesn't work.» → diagnóstico autorizado 50, FAILED; ticket ISP-27E63FECA7C9, OPEN. Respuesta reconoce comprobaciones y explica el nuevo recheck.
3. Recargar → seis mensajes y ticket conservados.
4. Repetir confirmación → ocho mensajes, mismos dos diagnósticos y un solo ticket; respuesta identifica reutilización.

Timestamps del reloj de prueba: 49 = 2026-10-10 22:36:03.000008 UTC; 50 = 22:36:07.031330 UTC. Provider DemoAI; constructor OpenAI bloqueado para impedir consumo. Los IDs de esta aceptación pertenecen a la réplica, no se añadieron a la base original. Evidencia: regression-recovery-proof.json y recovery-ticket-refresh.jpg.

## Validación y conservación

- Suite Django completa: 329 pruebas, OK (28.129 s).
- Suite JavaScript completa: 14 pruebas, OK, repetida después del último ajuste JS.
- `node --check conversations/static/conversations/demo.js`: OK.
- `manage.py check`: sin incidencias.
- `manage.py makemigrations --check --dry-run`: sin cambios.

La prueba que reproduce exactamente la cuota del fallo es `RecoveryRegressionTests.test_actual_six_runs_then_new_conversation_reports_limit_not_broken_simulator`. Además se prueban excepción inicial, refresco, reintento exitoso, mismo conversation_id, ticket único, reconexión, recuperación por operador y CSRF. Las suites anteriores permanecen activas.

Se compararon hashes de **cada fila** de todas las tablas del dominio antes y después: todas intactas, incluidos 23 conversaciones, 188 mensajes, 22 fotografías, 48 diagnósticos y 13 tickets. Véanse regression-preservation-before.json y regression-preservation-after.json. Fotografías, manuales, modelos, elegibilidad y autenticación existentes conservados; sin nuevas dependencias ni migraciones.

## Aplicar al servidor local

Reiniciar una vez el servidor Django para cargar la clave persistente y los cambios Python; iniciar sesión nuevamente y seleccionar el mismo servicio. La sesión antigua firmada con una clave aleatoria no es recuperable, pero los mensajes sí permanecen y se recupera la conversación abierta autorizada. Abrir http://127.0.0.1:8000/demo/.

La cuota original sigue vigente hasta que sus mediciones salgan de la ventana horaria (primera expiración 21:49:05 UTC). No se eludió para hacer pasar la demo. No se realizaron llamadas facturables ni se inició desarrollo adicional.
