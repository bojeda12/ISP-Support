# Verificación del Día 5

Entorno: Windows, Python 3.14.5, Django 5.2.18 y DemoAI.

- `manage.py test`: 114 pruebas aprobadas, incluidas las 104 anteriores.
- `manage.py check`: sin problemas.
- `manage.py makemigrations --check --dry-run`: sin cambios.
- `manage.py migrate`: sin migraciones pendientes.
- `node --check conversations/static/conversations/demo.js`: correcto.
- `node --test tests/frontend.test.cjs`: 6 pruebas aprobadas.
- Bootstrap 5.3.8 local: SHA-384 coincide con la distribución oficial.

Se verificó en el navegador el inicio de sesión, selección de servicio,
conversación en español e inglés, ilustraciones autorizadas, repetición de
diagnóstico tras revisar PoE, ticket OPEN y consulta de su estado. Se subió una
PNG sintética y se comprobó su vista previa y análisis simulado con incertidumbre.
La recarga conservó contexto, idioma e historial. El texto HTML se mostró como
texto; no creó elementos ejecutables. No se observaron errores de JavaScript en
estos recorridos.

En viewport móvil de 390 × 844 se verificaron controles utilizables y ausencia
de desbordamiento horizontal (375 px de contenido y ancho disponible tras la
barra de desplazamiento). Capturas: `desktop.jpg` y `mobile.jpg` en esta carpeta.
No sustituye pruebas en teléfonos físicos ni en todos los navegadores.

La verificación usó una SQLite separada, operador temporal y contraseña aleatoria.
Se detuvo el servidor de prueba y se eliminaron sus registros, fotografías y
archivos temporales. No se llamó a OpenAI ni a infraestructura del ISP.

Se corrigió un error de limpieza en Windows cerrando FileResponse explícitamente
en la prueba de recuperación de fotografías. No quedan fallos en las suites.
Los HTTP 400/401/403/404/413 del registro de pruebas son casos negativos esperados.
