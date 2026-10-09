# Integración de referencias fotográficas de demostración

Se aplicó el brief autorizado por el usuario. Se revisaron visualmente y mediante
extracción de texto las páginas 2, 4–7 y 12–15 del manual suministrado, además del
manifiesto y avisos del ZIP. No se modificó el manual ni se extrajeron imágenes
de sus páginas para utilizarlas en la aplicación.

## Mapeo conservando IDs y rutas

| Paso | IDs existentes | Archivo servido desde instruction_assets/ | MIME |
| --- | --- | --- | --- |
| 1 | `poe-en`, `poe-es` | `demo_photos/poe_locate_demo.jpg` | image/jpeg |
| 2 | `lights-en`, `lights-es` | `demo_photos/poe_power_indicator_demo.jpg` | image/jpeg |
| 3 | `ethernet-en`, `ethernet-es` | `demo_photos/ethernet_inspection_demo.jpg` | image/jpeg |
| 4 | `recheck-en`, `recheck-es` | `recheck-en.svg`, `recheck-es.svg` | image/svg+xml |

Las rutas siguen siendo `/api/instructions/<id>/`. Los SVG antiguos de los pasos
1–3 se conservaron, pero el catálogo ya no los selecciona. La referencia
`router-en/es` conserva su ilustración; no se convirtió en un inyector PoE.

## Alcance y seguridad

Los JPG se copiaron íntegros desde el ZIP, sin recortes, regeneración ni
descargas. Se revisaron los tres: son JPEG válidos y no contienen EXIF.
Conservan las dimensiones originales: 457×340, 451×354 y 447×329 píxeles.

El catálogo identifica las fotografías como `supplied_ai_generated_demo`, con
`production_approved=false`, `verified_model=null` y autorización para uso demo.
No se les atribuye la licencia CC0 de los SVG originales. Se conservaron el
manifiesto y los avisos suministrados y se aclaró el alcance de LICENSE.txt.

Las descripciones, pies y textos alternativos son bilingües. Indican que las
etiquetas y conexiones del ejemplo podrían ser inexactas y que no constituye
una guía de cableado. Distinguen router/módem, inyector PoE y CPE exterior.
Los indicadores no demuestran acceso a Internet; su significado requiere el
manual del modelo real. No se agregaron instrucciones para cambiar puertos,
voltaje, cableado eléctrico, abrir equipos o subir a techos.

El endpoint conserva autenticación, `private, no-store`, `nosniff` y CSP sandbox;
únicamente selecciona el MIME del catálogo local. Los archivos no están bajo
static/ y no se agregó una ruta pública. La carga del widget y el zoom existentes
ya admitían JPEG. `object-fit: contain` permite ver las referencias completas.

No se modificaron HTML, CSS, JavaScript, navegación, autenticación, fotografías
del cliente, estado conversacional, proveedores IA, motor de diagnóstico ni
servicios de tickets. No se agregaron dependencias ni migraciones. Tampoco SMS.
Una futura fotografía autorizada se sustituye en el catálogo y los archivos,
sin modificar el orquestador o el motor de red.

## Archivos modificados o creados en esta integración

Modificados:

- `conversations/instructions.py`: mapeo, MIME, procedencia y texto bilingüe.
- `conversations/media_api.py`: entrega con el MIME correspondiente.
- `conversations/instruction_assets/LICENSE.txt`: alcance de CC0 y avisos de demo.
- `conversations/test_language_ux.py`: verifica la nueva procedencia, conservando
  la comprobación de idioma y los cuatro pasos.

Creados:

- `conversations/test_instruction_photos.py`: cuatro pruebas de integración.
- `conversations/instruction_assets/demo_photos/poe_locate_demo.jpg`.
- `conversations/instruction_assets/demo_photos/poe_power_indicator_demo.jpg`.
- `conversations/instruction_assets/demo_photos/ethernet_inspection_demo.jpg`.
- `conversations/instruction_assets/demo_photos/README_ASSETS.txt`.
- `conversations/instruction_assets/demo_photos/manifest.json`.
- `docs/day5/visual-guide-integration.md` (este informe).
- `docs/day5/photo-guides-desktop.jpg`.
- `docs/day5/photo-guides-mobile.jpg`.
- `docs/day5/photo-guides-mobile-step3.jpg`.
- `docs/day5/photo-guide-zoom-mobile.jpg`.
- `docs/day5/photo-guides-spanish-mobile.jpg`.
- `docs/day5/photo-guide-recheck-mobile.jpg`.

Los cambios anteriores del repositorio se conservaron. Los archivos temporales
de revisión y el servidor/base de QA se retiraron al terminar.

## Verificación

```powershell
.\.venv\Scripts\python.exe manage.py test --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
node --test tests/frontend.test.cjs
```

Resultado: **140 pruebas Django aprobadas** (136 anteriores más 4 nuevas),
**7 pruebas JavaScript aprobadas**, system check sin incidencias y ninguna
migración pendiente. Las nuevas pruebas verifican IDs/rutas, bytes y MIME,
autenticación, cabeceras privadas, ausencia de acceso por ruta de archivo y
avisos bilingües sin atribuir verificación de equipos.

En navegador se utilizó un servidor temporal en 127.0.0.1:8005 con SQLite
aislada y DemoAI, sin llamadas OpenAI. Se comprobó:

1. Servicio ficticio 001 → No Internet → cuatro pasos en orden y JPG cargados.
2. Escritorio: mismas tarjetas y apariencia, imágenes completas.
3. Móvil a 390×844: sin desbordamiento horizontal (clientWidth=scrollWidth=390),
   cuatro imágenes cargadas y ajuste contain; ampliación de PoE y Ethernet.
4. Cambio a español y solicitud expresa de guía: texto español con navegación
   inglesa. El paso 4 amplía el gráfico neutro de comprobación.
5. Confirmación de comprobaciones: diagnóstico persistente y ticket OPEN;
   no se agregan nuevas tarjetas (las ocho existentes corresponden a las dos
   guías solicitadas, una inglesa y una española).

## Omisiones y límites

No se omitieron tareas del brief. Por indicación explícita, no se importó
`reference_infographic.jpg` como tarjeta y no se usó la fotografía de módem del
manual para el paso 4. Se conservó la deduplicación existente; no se agregó un
control nuevo de interfaz sugerido como ejemplo en el manual, porque el brief
solicita conservar la interfaz.

Las imágenes suministradas tienen resolución modesta; el zoom no añade detalle
inexistente. Son referencias generadas con IA para demostración interna. Para
producción deben reemplazarse por fotografías autorizadas y verificadas contra
el modelo y documentación del ISP. No quedan errores de pruebas pendientes.

Para abrir la demo habitual, reiniciar el servidor con el código actualizado y
visitar `http://127.0.0.1:8000/demo/` con un operador autorizado. La configuración
habitual de IA no se modificó; usar DemoAI explícitamente si se desea evitar
consumo del proveedor real.
