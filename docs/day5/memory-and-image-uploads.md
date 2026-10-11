# Memoria conversacional y fotografías — verificación

## Causas confirmadas

Las plantillas concatenaban observaciones e incertidumbres completas, consultaban
solo la última foto y repetían preguntas sin registrar respuestas. Las comprobaciones
del cliente podían perderse al salir de las ocho declaraciones recientes. DemoAI
no reconocía algunas contracciones y preguntas contextuales. La deduplicación de
guías dependía del idioma. El frontend representaba correctamente el texto recibido.

## Cambios y archivos

- `conversations/context.py`: estado estructurado persistido en metadatos del
  asistente; declaraciones no verificadas, equipo, comprobaciones, preguntas,
  idioma, servicio, guías y referencias a fotos. Diagnóstico y ticket se consultan
  nuevamente en Django, sin convertir declaraciones o fotografías en resultados técnicos.
- `conversations/ai.py`: clasificación de preguntas fotográficas, comparación,
  respuestas a aclaraciones, contracciones e idioma; foco visual acotado.
- `conversations/services.py`: historial breve, registro de aclaraciones y
  comprobaciones, reutilización de contexto y deduplicación de guías por tema.
- `conversations/photos.py`: WebP, validación real y fallback HEIC/HEIF.
- `conversations/static/conversations/demo-core.js`, `demo.js` y
  `conversations/templates/conversations/demo.html`: selector y errores de formato.
- `conversations/test_memory_uploads.py`, `test_language_ux.py` y
  `tests/frontend.test.cjs`: regresiones nuevas y adaptación de la comprobación
  bilingüe para exigir una solicitud explícita al repetir la guía.
- `README.md` y este informe: documentación. Capturas nuevas en este directorio.

No se añadieron dependencias ni migraciones. No se modificaron reglas de red,
servicios de tickets, autenticación, autorización, CSRF, catálogo ni diseño CSS.

## Memoria y reutilización visual

El resumen conserva ocho declaraciones, cuatro comprobaciones, seis respuestas,
tres preguntas pendientes, veinte referencias de guías y seis fotos discutidas.
Consulta las últimas tres fotografías, con tres observaciones y dos incertidumbres
por foto (180 caracteres por elemento). Conserva estado y origen simulado.
El proveedor recibe hasta cuatro mensajes recientes de 2000 caracteres y un resumen;
los informes de análisis fotográfico se excluyen del historial textual breve.

Las respuestas citan una observación pertinente y conservan incertidumbre. Comparar
dos fotos reutiliza sus observaciones guardadas: no realiza una nueva comparación
visual ni confirma que ambas representen el mismo dispositivo. Una última foto
fallida no se sustituye silenciosamente por una anterior exitosa. El cambio de idioma
no vuelve a insertar automáticamente las cuatro tarjetas; una petición explícita sí.

## Formatos y protección

JPEG/JPG, PNG y WebP estático: máximo 5 MiB, 4096 píxeles por lado y 12 megapíxeles.
Se comprueba el formato decodificado contra extensión y MIME, corrupción, animación
y descompresión excesiva. Pillow corrige orientación EXIF, convierte a RGB y guarda
JPEG sin metadatos. El almacenamiento y la recuperación siguen siendo privados.
No se descargan URLs arbitrarias. SVG y GIF se rechazan.

Pillow 12.3.0 funciona con Python 3.14.5 y dispone de WebP. No hay decodificador
HEIC/HEIF instalado: se devuelve un error en inglés solicitando exportar a JPEG,
PNG o WebP. No se instalaron bibliotecas adicionales.

## Resultados

- `.venv\Scripts\python.exe manage.py check`: sin problemas.
- `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`: sin cambios.
- `.venv\Scripts\python.exe manage.py test`: **158 pruebas aprobadas**.
- `node --test tests/frontend.test.cjs`: **8 pruebas aprobadas**.
- `node --check conversations/static/conversations/demo.js`: correcto.
- `git diff --check`: sin errores de formato; avisos de conversión CRLF de Git.

Las pruebas cubren permisos, aislamiento, errores del proveedor, incertidumbre,
formatos inválidos, límites de tamaño/dimensiones, orientación, contexto fotográfico,
idiomas, continuidad, comprobaciones persistentes y conservación del mismo ticket.
Se mantienen los casos anteriores. Todas las llamadas externas de pruebas son mocks.

Se reprodujo la secuencia solicitada en navegador, con DemoAI y base SQLite aislada:
falta de Internet, foto frontal PNG, “Is this good?”, trasera WebP, “What about the
back?”, luces verdes, cables revisados y persistencia del problema. Se creó el
ticket ficticio `ISP-20DEECAA4867` OPEN y se reutilizó; recargar mantuvo conversación,
dos imágenes cargadas y solo cuatro tarjetas originales. Escritorio y móvil
390 × 844 no mostraron desbordamiento horizontal. Las capturas son
`memory-uploads-desktop.jpg` y `memory-uploads-mobile.jpg`.

Los hashes SHA-256 de los **16 archivos** de `conversations/instruction_assets/`
coinciden con la medición anterior a los cambios. Se preservaron fotografías JPEG,
metadatos, licencia y SVG existentes. No se reemplazó ni regeneró el manual.

## Ejemplos y prueba manual

Tras “I already checked the cables.”: “Thank you for completing those accessible
checks. The new simulated diagnostic still receives no response from the CPE.”
La respuesta comunica escalamiento y número de ticket sin repetir la guía.
Tras “I still don't have Internet.” reconoce el problema registrado, conserva el
ticket y explica que no es necesario repetir las comprobaciones.

1. En desarrollo, seleccionar `AI_PROVIDER=demo` en la configuración local.
2. Ejecutar `python manage.py migrate`, `python manage.py seed_demo` y
   `python manage.py runserver`; entrar con el operador autorizado en `/demo/`.
3. Seleccionar inglés y DEMO-SERVICE-001. Reproducir la secuencia anterior con
   fotografías ficticias; comprobar vista previa PNG/WebP y respuestas breves.
4. Recargar, continuar y verificar el mismo ticket. Solicitar la guía explícitamente
   para verla otra vez. Cambiar al español para comprobar continuidad del idioma.
5. Intentar HEIC, SVG y archivo superior a 5 MiB; comprobar errores claros.

## Límites

DemoAI no interpreta píxeles: lo declara explícitamente, sin inventar luces o puertos.
Las observaciones visuales distintas se probaron mediante mocks. No se llamó a
OpenAI ni se consumió API; la integración real y su calidad semántica quedan pendientes
de una prueba autorizada. Las respuestas siguen plantillas seguras, con clasificación
contextual; no son generación libre. Las observaciones guardadas pueden conservar
su idioma original. La comparación usa resultados previos, sin llamadas visuales
adicionales ni costos adicionales de comparación. HEIC/HEIF requiere conversión.
No quedan fallos de pruebas pendientes. No se inició el Día 6.
