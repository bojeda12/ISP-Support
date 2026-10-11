# Base documental privada y turnos con fotografías

Se añadieron `knowledge.ReferenceDocument` y `KnowledgeSection`, con PDF o texto estructurado, metadatos de equipo/idioma/revisión, propietario opcional para demo, aprobación y almacenamiento privado. Los manuales operativos requieren propietario y modelo/familia. Solo se recuperan documentos activos, vigentes, aprobados, indexados y revisados para clientes. Las coincidencias de modelo/versiones incompatibles se excluyen y los conflictos impiden elegir instrucciones específicas.

El Admin permite cargar, indexar, revisar secciones, aprobar y descargar el original con permiso. Modificar contenido revoca la aprobación; reemplazar una revisión retira la anterior. La salida de extractos a OpenAI requiere autorización del documento y del entorno. Los documentos se tratan como datos no confiables. No se envía el PDF completo.

Dependencia añadida: `pypdf==6.20.0`, compatible en el entorno Python 3.14.5 verificado. Migraciones aplicadas: `knowledge/0001_initial.py` y `conversations/0006_chatturn.py`.

Importación idempotente del manual existente, desde PowerShell en el proyecto:

```powershell
.venv\Scripts\python.exe manage.py import_demo_manual 'C:\Users\bojeda\Desktop\ISP_Support_Bilingual_Troubleshooting_Photo_Manual.pdf' --approve-pages 3,4,5,6,7,8,9
```

Resultado: 16 páginas, 29 secciones, sin páginas vacías ni fallos. Solo 3–9 están revisadas para el chat; las páginas de fotografía, desarrollo y entrega no se usan como instrucciones del cliente. Se conserva el original y una copia privada ignorada por Git. La advertencia de pypdf sobre índices xref no impidió la lectura y no reescribió el original. No hay OCR: PDF escaneado/vacío queda parcial o fallido, sin aprobación automática. Límites: 10 MiB, 100 páginas; recuperación acotada a tres extractos de hasta 1400 caracteres.

`POST /api/chat/turn/` recibe multipart con `request_id` UUID, `message` opcional, `photo` opcional y exactamente una referencia `service_id` o `conversation_id`. Requiere sesión autorizada y CSRF. Acepta texto, foto o ambos; guarda un mensaje del cliente y una respuesta. La foto conserva validación real de formato, normalización, límites y recuperación privada. La pregunta viaja al análisis visual en el mismo turno. Los endpoints anteriores siguen disponibles.

El mismo request_id y contenido devuelve el resultado guardado; cambiar contenido con el mismo ID se rechaza. Una falla inesperada revierte los registros y compensa el archivo de ese turno. Un fallo del proveedor se registra como análisis fallido con respuesta local coherente. El frontend conserva el borrador ante errores y revisa historial tras resultados inciertos. La transacción abarca llamadas acotadas al proveedor: SQLite puede devolver 409 por concurrencia; no se reintenta una mutación automáticamente. Un archivo aún no enviado no sobrevive a una recarga del navegador.

La guía CPE conserva los IDs, rutas, metadatos bilingües y fotografías existentes: PoE, luz, Ethernet, nueva comprobación. Falta de un activo no activa silenciosamente SVG antiguos. El procedimiento separado de router conserva su propia ilustración. La memoria evita repetir guías completas salvo petición explícita o procedimiento distinto. Zoom y diseño permanecen.

Validación de esta ampliación antes de las respuestas breves: 199 pruebas Django, 10 JavaScript, system check y migraciones sin cambios pendientes. Navegador: pregunta+foto en un turno, cita real página 5, recarga de historial, ampliación de guía, escalamiento OPEN sin repetir pasos y reutilización del mismo ticket. Móvil 390×844 sin desbordamiento horizontal. Las capturas `knowledge-combined-desktop.jpg` y `knowledge-combined-mobile.jpg` conservan la evidencia. El informe posterior `rag-short-answers-verification.md` incluye las correcciones y el total de pruebas actualizado.
