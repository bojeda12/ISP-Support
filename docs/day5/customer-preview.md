# Vista del cliente y herramientas internas

La vista del cliente está en `/demo/customer/`. Django omite del HTML el selector de servicios ficticios, Conversaciones anteriores, Retomar chat, Nuevo chat y los identificadores internos. No se ocultan mediante CSS. `/demo/` conserva estas herramientas para el operador autorizado.

La vista previa requiere un operador activo con acceso de personal y permiso `conversations.use_demo_chat`, en desarrollo con la demo habilitada. No constituye todavía autenticación pública de clientes. Los endpoints de selección e historial administrativo mantienen esa autorización; el historial de mensajes y las fotografías mantienen sus permisos existentes.

## Verificación local

1. Ejecutar `.\.venv\Scripts\python.exe manage.py runserver`.
2. Entrar con un operador autorizado en `http://127.0.0.1:8000/demo/` y conectar un servicio ficticio.
3. Abrir **Customer preview / Vista del cliente**, que lleva a `http://127.0.0.1:8000/demo/customer/`.
4. Comprobar que no hay selección de servicios, chats anteriores, Retomar, Nuevo chat ni identificadores internos visibles.
5. Enviar varios mensajes y actualizar la página: se restaura la conversación de la sesión autorizada, con sus fotografías, guías y tarjetas.
6. Si caduca la sesión, usar Reconectar: recupera el servicio previamente autorizado; no admite elegir otra identidad desde la vista del cliente.
7. Consultar conversaciones anteriores desde `/demo/`, exclusivamente como operador autorizado.

## Cambios y pruebas

- `config/urls.py`, `conversations/web.py`: rutas separadas de vista previa, estado y reconexión autorizada.
- `conversations/templates/conversations/demo.html`: separación del HTML del cliente y herramientas internas.
- `conversations/static/conversations/demo.js`: restauración del chat activo, conservación de mensajes paginados y protección contra sustitución silenciosa por otra conversación.
- `conversations/static/conversations/demo.css`: adaptación del contenedor sin barra lateral; conserva el diseño del chat.
- `conversations/test_customer_mode.py`, `tests/frontend.test.cjs`: permisos, continuidad, reconexión, fotografías, guías y tickets.

Última ejecución: **338 pruebas Django y 20 pruebas JavaScript aprobadas**. `manage.py check` sin problemas; `makemigrations --check --dry-run` sin cambios.

Durante la verificación previa en navegador con una copia aislada y DemoAI, la conversación mantuvo diez mensajes, las guías y el mismo ticket tras actualizar y reconectar. Se comprobó un ancho móvil de 375 px sin desbordamiento horizontal. La última reapertura del servidor auxiliar no estuvo disponible (timeout); no se modificó el servidor principal para forzarla.

La comparación por registro de las 19 tablas conservó los datos existentes de clientes, conversaciones, mensajes, fotografías, diagnósticos, tickets y conocimiento. Solo difirió un registro de sesión demo temporal. No se eliminaron datos históricos ni se hicieron llamadas facturables a OpenAI. No se modificaron las reglas de IA, diagnóstico o tickets para esta corrección.
