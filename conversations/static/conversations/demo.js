/* Widget local: texto seguro, sesiones en servidor y ninguna clave o token público. */
(function () {
  "use strict";
  const core = window.ISPSupportCore;
  const customerMode = document.body.dataset.chatMode === "customer";
  const byId = (id) => document.getElementById(id);
  const state = { service: null, conversationId: null, language: "en", confirmed:false, manualLanguage:false, timeZone:"UTC", history: [], before: null, busy: false, review: false, photo: null, preview: null, generation: 0, blobs: new Set() };
  const strings = {
    es: {
      skip:"Ir al chat", workspace:"ESPACIO DE SOPORTE", support:"Atención al cliente", techPanel:"Panel técnico", demoSpace:"Un espacio de demostración", demoNote:"Servicios ficticios. Diagnósticos simulados. Ninguna conexión a equipos reales.", operator:"Operador autorizado", supportCenter:"Centro de atención", localDemo:"Demo local", hereToHelp:"ESTAMOS PARA AYUDARTE", headline:"Tu conexión, en buenas manos.", subtitle:"Revisa tu servicio, resuelve dudas y recibe orientación paso a paso.", language:"Idioma", assistant:"· Asistente de soporte", guidedSupport:"SOPORTE GUIADO", conversation:"TU CONVERSACIÓN", older:"Ver mensajes anteriores", processing:"Nexo está procesando…", noInternet:"No tengo Internet", slowInternet:"Internet lento", myTicket:"Consultar mi ticket", photoWarning:"No incluyas contraseñas ni datos personales.", sendPhoto:"Enviar foto", attach:"Adjuntar fotografía", send:"Enviar", privateChat:"◇ Conversación privada · Solo datos de demostración", yourService:"Tu servicio", selectService:"Selecciona un servicio ficticio", chooseService:"Elegir servicio…", connect:"Conectar al asistente", plan:"Plan", session:"Sesión", notStarted:"Sin iniciar", diagnostic:"Diagnóstico", readyToCheck:"Listo para revisar tu conexión", diagnosticHint:"Cuéntale al asistente qué ocurre para iniciar una comprobación.", technicalFollowup:"Seguimiento técnico", ticketHint:"Si hace falta una revisión técnica, encontrarás aquí el número de tu ticket.", safetyTitle:"Tu seguridad es primero", safetyText:"Revisa solo conexiones accesibles. No subas al techo ni manipules instalaciones eléctricas.", footer:"Soporte cercano. Información clara.", refresh:"Actualizar conversación", placeholder:"Escribe tu mensaje…", connected:"Sesión activa · Datos de demostración", disconnected:"Selecciona un servicio para empezar", offline:"Sin conexión con el servidor", introTitle:"Hola, soy Nexo.", intro:"Estoy aquí para ayudarte con tu conexión. Selecciona un servicio de demostración y cuéntame qué sucede.", introActive:"Tu sesión está lista. Cuéntame qué ocurre con tu conexión y lo revisamos paso a paso.", customer:"Tú", observations:"Observaciones", uncertainties:"Lo que no podemos confirmar", recommendations:"Recomendaciones seguras", analysis:"Análisis de fotografía", simulated:"SIMULACIÓN", analysisFailed:"Análisis no disponible", analysisPending:"Análisis pendiente", imageFailed:"No se pudo cargar la imagen. Actualiza la conversación.", invalidPhoto:"Selecciona JPEG, PNG o WebP de hasta 5 MiB. Convierte HEIC/HEIF a JPEG o PNG primero.", firstMessage:"Envía primero un mensaje para iniciar la conversación y poder adjuntar una fotografía.", expired:"La sesión no está disponible. Vuelve a conectar el servicio; si cerraste sesión en Django, inicia sesión otra vez.", denied:"No se pudo autorizar la petición. Recarga la página y comprueba tus permisos.", invalid:"No se pudo aceptar la petición. Revisa el mensaje, archivo o servicio seleccionado.", networkError:"No pudimos confirmar la operación. No se reenviará automáticamente. Actualiza la conversación para revisar lo que quedó guardado antes de volver a enviar.", providerError:"El proveedor de IA no está disponible. El intercambio se guardó; puedes volver a intentarlo cuando esté disponible.", photoFailed:"La foto se guardó, pero no se pudo analizar. El resultado no confirma el estado de tu conexión.", choose:"Selecciona un servicio ficticio.", switchService:"Cambiar de servicio abrirá otra sesión. La conversación actual quedará guardada. ¿Continuar?", sessionActive:"Activa · 1 hora", latency:"Latencia", download:"Descarga", signal:"Señal", unavailable:"Sin medición", simulatedDiagnostic:"Mediciones simuladas", noTicket:"Aún no hay un ticket", ticketRegistered:"Incidencia registrada", noVisit:"Sin visita ni reparación confirmada.", photoUploaded:"Fotografía enviada.", photoReceived:"Fotografía recibida.", offlinePrompt:"No tengo Internet", slowPrompt:"Internet lento", ticketPrompt:"Estado de mi ticket", OPEN:"Abierto", IN_PROGRESS:"En progreso", RESOLVED:"Resuelto", CLOSED:"Cerrado", CPE_UNREACHABLE:"Equipo sin respuesta", SIGNAL_DEGRADED:"Señal débil", PERFORMANCE_DEGRADED:"Rendimiento bajo", NO_FAULT_DETECTED:"Sin falla detectada", SERVICE_SUSPENDED:"Servicio suspendido", SERVICE_INACTIVE:"Servicio no activo", INSUFFICIENT_DATA:"Mediciones insuficientes"
    },
    en: {
      skip:"Skip to chat", workspace:"SUPPORT WORKSPACE", support:"Customer support", techPanel:"Technical panel", demoSpace:"A demonstration space", demoNote:"Fictional services. Simulated diagnostics. No connection to real equipment.", operator:"Authorized operator", supportCenter:"Support center", localDemo:"Local demo", hereToHelp:"WE ARE HERE TO HELP", headline:"Your connection, in good hands.", subtitle:"Check your service, ask questions and get step-by-step guidance.", language:"Language", assistant:"· Support assistant", guidedSupport:"GUIDED SUPPORT", conversation:"YOUR CONVERSATION", older:"View earlier messages", processing:"Nexo is processing…", noInternet:"No Internet", slowInternet:"Slow Internet", myTicket:"Check my ticket", photoWarning:"Do not include passwords or personal data.", sendPhoto:"Send photo", attach:"Attach photograph", send:"Send", privateChat:"◇ Private conversation · Demonstration data only", yourService:"Your service", selectService:"Select a fictional service", chooseService:"Choose service…", connect:"Connect to assistant", plan:"Plan", session:"Session", notStarted:"Not started", diagnostic:"Diagnostic", readyToCheck:"Ready to check your connection", diagnosticHint:"Tell the assistant what is happening to start a check.", technicalFollowup:"Technical follow-up", ticketHint:"If technical review is needed, your ticket number will appear here.", safetyTitle:"Your safety comes first", safetyText:"Check only accessible connections. Do not climb onto the roof or handle electrical wiring.", footer:"Personal support. Clear information.", refresh:"Refresh conversation", placeholder:"Write your message…", connected:"Session active · Demonstration data", disconnected:"Select a service to begin", offline:"No connection to server", introTitle:"Hello, I’m Nexo.", intro:"I am here to help with your connection. Select a demonstration service and tell me what is happening.", introActive:"Your session is ready. Tell me what is happening with your connection and we will check it step by step.", customer:"You", observations:"Observations", uncertainties:"What we cannot confirm", recommendations:"Safe recommendations", analysis:"Photo analysis", simulated:"SIMULATION", analysisFailed:"Analysis unavailable", analysisPending:"Analysis pending", imageFailed:"The image could not be loaded. Refresh the conversation.", invalidPhoto:"Choose JPEG, PNG or WebP up to 5 MiB. For HEIC/HEIF, export as JPEG or PNG first.", firstMessage:"Send a message first to start the conversation before attaching a photograph.", expired:"The session is unavailable. Reconnect the service; if you signed out of Django, sign in again.", denied:"The request could not be authorized. Reload the page and check your permissions.", invalid:"The request was not accepted. Check the message, file or selected service.", networkError:"We could not confirm the operation. It will not be resent automatically. Refresh the conversation to review what was saved before sending again.", providerError:"The AI provider is unavailable. The exchange was saved; you can try again when it becomes available.", photoFailed:"The photo was saved, but analysis failed. This does not confirm the state of your connection.", choose:"Select a fictional service.", switchService:"Switching service will open another session. Your current conversation will remain saved. Continue?", sessionActive:"Active · 1 hour", latency:"Latency", download:"Download", signal:"Signal", unavailable:"Not measured", simulatedDiagnostic:"Simulated measurements", noTicket:"No ticket yet", ticketRegistered:"Issue recorded", noVisit:"No visit or repair confirmed.", photoUploaded:"Photo uploaded.", photoReceived:"Photo received.", offlinePrompt:"No Internet", slowPrompt:"Slow Internet", ticketPrompt:"Check my ticket status", OPEN:"Open", IN_PROGRESS:"In progress", RESOLVED:"Resolved", CLOSED:"Closed", CPE_UNREACHABLE:"Equipment not responding", SIGNAL_DEGRADED:"Weak signal", PERFORMANCE_DEGRADED:"Low performance", NO_FAULT_DETECTED:"No fault detected", SERVICE_SUSPENDED:"Service suspended", SERVICE_INACTIVE:"Service inactive", INSUFFICIENT_DATA:"Insufficient measurements"
    }
  };
  const customerLabels = {
    es: {expired:'Tu sesión venció. Reconecta para continuar; si es necesario, vuelve a iniciar sesión.', disconnected:'Reconecta tu sesión para continuar', choose:'Necesitas una sesión de soporte autorizada.', reconnect:'Reconectar'},
    en: {expired:'Your session expired. Reconnect to continue; sign in again if needed.', disconnected:'Reconnect your session to continue', choose:'An authorized support session is required.', reconnect:'Reconnect'}
  };
  const t = (key) => (customerMode ? customerLabels[state.language][key] || strings[state.language][key] : strings.en[key]) || key;
  const ct = (key) => (customerMode ? customerLabels[state.language][key] : null) || strings[state.language][key] || key;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function notice(message) { byId("notice").textContent = message || ""; byId("notice").hidden = !message; }
  function connection(online = true) {
    const active = online && navigator.onLine && state.service;
    byId("connection-label").textContent = !online || !navigator.onLine ? t("offline") : active ? t("connected") : t("disconnected");
    byId("connection-dot").className = "status-dot" + (active ? " connected" : !online ? " error" : "");
  }
  function controls() {
    const unavailable = state.busy || !state.confirmed || !state.service || state.review || !navigator.onLine;
    byId("message-input").disabled = unavailable;
    byId("send-button").disabled = unavailable || (!byId("message-input").value.trim() && !state.photo);
    byId("photo-input").disabled = unavailable;
    byId("language").disabled = state.busy;
    if (byId("service-select")) byId("service-select").disabled = state.busy;
    if (byId("connect-button")) byId("connect-button").disabled = state.busy;
    byId("refresh-history").disabled = state.busy;
    byId("load-older").disabled = state.busy;
    byId("cancel-photo").disabled = state.busy;
    ["previous-chats","resume-chat","new-chat","more-chats"].forEach(id => { if (byId(id)) byId(id).disabled = state.busy || !state.service; });
    document.querySelectorAll("[data-prompt], [data-quick-reply]").forEach((button) => { button.disabled = unavailable || Boolean(byId('message-input').value.trim()); });
    if (byId("reconnect-chat")) { byId("reconnect-chat").hidden = Boolean(state.service); byId("reconnect-chat").disabled = state.busy; }
    byId("typing").hidden = !state.busy;
    byId("language").parentElement.hidden = !state.confirmed;
  }
  function busy(value, chatPending = false) {
    state.busy = value;
    const label = byId('typing').querySelector('[data-i18n="processing"]');
    label.textContent = chatPending
      ? (state.language === 'es' ? 'Revisando tu mensaje y la solicitud de comprobación…' : 'Reviewing your message and connection-check request…')
      : ct('processing');
    controls();
  }
  function applyLanguage(language, render = true) {
    state.language = language;
    document.documentElement.lang = customerMode ? language : "en-US";
    document.title = "ISP Support · " + t("supportCenter");
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
    document.querySelectorAll("[data-label]").forEach((node) => { node.setAttribute("aria-label", t(node.dataset.label)); });
    byId("language").value = language;
    byId("message-input").placeholder = t("placeholder");
    byId("message-input").setAttribute("aria-label", "Message");
    byId("attach-label").title = t("attach");
    if (byId("session-summary")) byId("session-summary").textContent = state.service ? t("sessionActive") : t("notStarted");
    connection();
    if (render) renderMessages();
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 190000);
    try {
      return await core.requestJSON(path, { ...options, signal: controller.signal }, window.fetch.bind(window), document.querySelector("[name=csrfmiddlewaretoken]").value, window.location.origin);
    } finally { clearTimeout(timer); }
  }
  function errorMessage(error) {
    if (error.status === 401) return t("expired");
    if (error.status === 403) return t("denied");
    if ([400, 404, 415].includes(error.status)) return t("invalid");
    if (error.status === 413) return t("invalidPhoto");
    return t("networkError");
  }
  async function protectedImage(path, img, parent, generation) {
    try {
      const response = await fetch(core.safePath(path, location.origin), { credentials: "same-origin", redirect: "error" });
      if (!response.ok || !["image/jpeg", "image/png", "image/svg+xml"].includes((response.headers.get("content-type") || "").split(";")[0])) throw new Error("image_error");
      const blob = await response.blob();
      if (generation !== state.generation || !img.isConnected) return;
      const url = URL.createObjectURL(blob);
      state.blobs.add(url);
      img.src = url;
    } catch (error) {
      if (generation === state.generation && parent.isConnected) { img.remove(); parent.append(element("p", "media-error", t("imageFailed"))); }
    }
  }
  function instructionCards(images, body, generation) {
    if (!images || !images.length) return;
    const grid = element("div", "illustration-grid");
    for (const item of images) {
      const card = element("section", "instruction-card");
      const image = element("img"); image.alt = item.alt_text || item.title; image.loading = "lazy";
      const zoom = element("button", "guide-image-button"); zoom.type="button"; zoom.setAttribute("aria-label", "Enlarge image: " + item.title); zoom.append(image);
      zoom.addEventListener("click", () => {
        if (!image.src.startsWith("blob:")) return;
        byId("zoom-image").src=image.src; byId("zoom-image").alt=image.alt;
        byId("zoom-title").textContent=item.title; byId("zoom-description").textContent=item.description + " " + item.safety_instructions;
        byId("image-zoom").showModal();
      });
      card.lang=item.language;
      card.append(element("span", "guide-step", (item.language === "es" ? "Paso " : "Step ") + item.step_number), zoom,
                  element("h3", "", item.title), element("p", "guide-description", item.description), element("p", "guide-safety", item.safety_instructions)); grid.append(card);
      queueMicrotask(() => protectedImage(item.url, image, card, generation));
    }
    body.append(grid);
  }
  function photoAnalysis(photo, parent) {
    const card = element("div", "analysis-card");
    card.append(element("span", "small-badge", photo.simulated ? t("simulated") : "OPENAI"));
    card.append(element("h3", "", photo.status === "FAILED" ? t("analysisFailed") : photo.status === "PENDING" ? t("analysisPending") : t("analysis")));
    for (const [key, label] of [["observations", "observations"], ["uncertainties", "uncertainties"], ["recommendations", "recommendations"]]) {
      const items = key === "recommendations" ? photo.recommendations : photo.analysis[key];
      if (items && items.length) {
        card.append(element("h4", "", t(label)));
        const list = element("ul"); items.forEach((text) => list.append(element("li", "", text))); card.append(list);
      }
    }
    card.append(element("p", "summary-caption", photo.disclaimer)); parent.append(card);
  }
  function ticketCard(ticket, parent) {
    const card = element("div", "ticket-inline");
    card.append(element("span", "", "▤"), element("strong", "", ticket.number), element("span", "ticket-state", t(ticket.status)));
    parent.append(card);
  }
  function renderMessages() {
    state.generation += 1;
    const generation = state.generation;
    state.blobs.forEach((url) => URL.revokeObjectURL(url)); state.blobs.clear();
    const messages = byId("messages"); messages.replaceChildren();
    if (!state.history.length) {
      const row = element("div", "message-row"); const body = element("div", "message-body");
      const bubble = element("div", "bubble welcome-note"); bubble.append(element("strong", "", ct("introTitle")), element("span", "", state.service ? ct("introActive") : customerMode ? (state.language === "es" ? "Reconecta tu sesión para continuar con tu conversación." : "Reconnect your session to continue your conversation.") : ct("intro")));
      body.append(element("div", "message-label", "Nexo"), bubble); row.append(element("span", "mini-avatar", "N"), body); messages.append(row);
      renderQuickReplies(state.issueReplies, body);
    }
    for (const message of state.history) {
      const customer = message.sender === "customer";
      const row = element("article", "message-row" + (customer ? " customer" : "")); row.dataset.messageId = String(message.id);
      const body = element("div", "message-body");
      body.append(element("div", "message-label", customer ? t("customer") : "Nexo"));
      body.append(element("div", "bubble", message.content));
      if (message.photo) {
        if (customer) {
          const image = element("img", "photo-image"); image.alt = t("photoUploaded"); body.append(image);
          queueMicrotask(() => protectedImage(message.photo.content_url, image, body, generation));
        } else photoAnalysis(message.photo, body);
      }
      if (message.diagnostic) body.append(element("div", "diagnostic-inline", t(message.diagnostic.result_code) + " · " + t("simulatedDiagnostic")));
      if (message.ticket) ticketCard(message.ticket, body);
      instructionCards(message.images, body, generation);
      if (!customer) renderQuickReplies(message.quick_replies, body);
      const date = new Date(message.created_at);
      body.append(element("div", "message-time", Number.isNaN(date.valueOf()) ? "" : date.toLocaleTimeString("en-US", {hour:"2-digit",minute:"2-digit",timeZone:state.timeZone})));
      if (!customer) row.append(element("span", "mini-avatar", "N")); row.append(body); messages.append(row);
    }
    byId("load-older").hidden = !state.before;
    renderSummary();
    controls();
  }
  function renderQuickReplies(choices, parent) {
    if (!choices?.length) return;
    const group = element('div', 'quick-prompts contextual-replies');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', state.language === 'es' ? 'Respuestas rápidas opcionales' : 'Optional quick replies');
    if (choices.some(choice => choice.scope === 'basic_checks')) {
      group.append(element('span', 'summary-caption', state.language === 'es'
        ? '¿Revisaste la alimentación accesible, el PoE si lo hay y los cables de Internet?'
        : 'Have you checked accessible power, PoE if present, and Internet cables?'));
    }
    for (const choice of choices) {
      const button = element('button', '', choice.labels?.[state.language] || choice.label);
      button.type = 'button'; button.dataset.quickReply = choice.id;
      button.addEventListener('click', () => { void sendMessage('', choice); });
      group.append(button);
    }
    parent.append(group);
  }
  function renderSummary() {
    const diagnostic = [...state.history].reverse().find((message) => message.diagnostic)?.diagnostic;
    const ticket = [...state.history].reverse().find((message) => message.ticket)?.ticket;
    const diagnosticPanel = byId("diagnostic-summary"); diagnosticPanel.replaceChildren();
    if (diagnostic) {
      diagnosticPanel.className = "";
      diagnosticPanel.append(element("span", "small-badge", t("simulated")), element("div", "diagnostic-state" + (diagnostic.result_code === "NO_FAULT_DETECTED" ? " healthy" : ""), t(diagnostic.result_code)));
      const metrics = element("div", "metric-grid");
      for (const [key, label, unit] of [["rssi_dbm","signal","dBm"],["latency_ms","latency","ms"],["download_mbps","download","Mbps"]]) {
        const cell = element("div", "metric"); const value = diagnostic.metrics[key];
        cell.append(element("span", "", t(label)), element("strong", "", value === null || value === undefined ? "—" : String(value) + " " + unit)); metrics.append(cell);
      }
      diagnosticPanel.append(metrics, element("p", "summary-caption", t("simulatedDiagnostic")));
    } else {
      diagnosticPanel.className = "empty-summary";
      diagnosticPanel.append(element("span", "empty-icon", "⌁"), element("strong", "", t("readyToCheck")), element("p", "", t("diagnosticHint")));
    }
    const ticketPanel = byId("ticket-summary"); ticketPanel.replaceChildren();
    if (ticket) ticketPanel.append(element("span", "small-badge", t("ticketRegistered")), element("div", "summary-ticket-number", ticket.number), element("span", "ticket-state", t(ticket.status)), element("p", "summary-caption", t("noVisit")));
    else ticketPanel.append(element("p", "muted-note", t("ticketHint")));
  }
  function scrollBottom() { const scroll = byId("chat-scroll"); scroll.scrollTo({top:scroll.scrollHeight, behavior:"instant"}); }
  async function loadHistory(older = false) {
    if (!state.conversationId) { renderMessages(); return; }
    const path = "/api/conversations/" + state.conversationId + "/messages/" + (older && state.before ? "?before=" + state.before : "");
    const data = await api(path);
    if (data.conversation_id !== state.conversationId) throw new Error('History belongs to a different conversation.');
    const merged = new Map(state.history.map((message) => [message.id, message]));
    data.messages.forEach((message) => merged.set(message.id, message));
    if (state.pendingTurn && data.messages.some(message => message.request_id === state.pendingTurn.id)) {
      state.pendingTurn=null; clearPhoto(); byId('message-input').value=''; byId('character-count').textContent='0 / 2000';
    }
    state.history = [...merged.values()].sort((a, b) => a.id - b.id);
    if (older || state.history.length === data.messages.length) state.before = data.next_before;
    renderMessages();
    if (!older) {
      const latest = data.messages.at(-1);
      const guide = latest?.images?.length ? document.querySelector('[data-message-id="' + latest.id + '"] .illustration-grid') : null;
      if (guide) {
        const scroll=byId("chat-scroll");
        scroll.scrollTo({top:scroll.scrollTop + guide.getBoundingClientRect().top - scroll.getBoundingClientRect().top - 12,behavior:"instant"});
      } else scrollBottom();
    }
  }
  let chatOffset = null;
  async function loadChats(append = false) {
    if (!state.service || !byId("previous-chats")) return;
    const data = await api('/demo/conversations/' + (append ? '?offset=' + chatOffset : ''));
    const select = byId('previous-chats');
    if (!append) select.replaceChildren(element('option', '', 'Choose chat / Elegir chat'));
    if (!append) select.options[0].value = '';
    data.conversations.forEach(chat => {
      const option = element('option', '', '#' + chat.id + ' · ' + chat.language.toUpperCase() + ' · ' + new Date(chat.created_at).toLocaleString() + ' · ' + chat.status);
      option.value = String(chat.id); select.append(option);
    });
    select.value = state.conversationId ? String(state.conversationId) : '';
    chatOffset = data.next_offset; byId('more-chats').hidden = chatOffset === null;
  }
  async function sync() {
    const data = await api(customerMode ? "/demo/customer/state/" : "/demo/state/");
    const changed = state.conversationId !== data.conversation_id || Boolean(state.service && data.service && state.service.id !== data.service.id);
    // Una sesión vencida no significa que el historial se haya borrado.
    // Conservar lo ya cargado; la reconexión al mismo servicio recupera su referencia.
    if (!data.service && state.history.length) {
      state.service = null; notice(ct('expired')); connection(); controls(); return false;
    }
    if (customerMode && state.history.length && changed) {
      state.review = true; notice(state.language === 'es' ? 'La sesión activa cambió. Tu conversación permanece visible; vuelve a autenticarte para continuar con el caso correcto.' : 'The active session changed. Your conversation remains visible; sign in again to continue the correct case.');
      controls(); return false;
    }
    state.service = data.service; state.conversationId = data.conversation_id;
    state.issueReplies = data.quick_replies || [];
    state.confirmed = data.language_confirmed; state.timeZone = data.time_zone || "UTC";
    byId("welcome-screen").hidden = state.confirmed; byId("support-workspace").hidden = !state.confirmed;
    if (changed) { state.history = []; state.before = null; state.manualLanguage=false; }
    if (data.language) applyLanguage(data.language, false);
    if (byId("service-select")) byId("service-select").value = state.service ? String(state.service.id) : "";
    if (byId("service-plan")) byId("service-plan").textContent = state.service?.plan || "—";
    if (byId("session-summary")) byId("session-summary").textContent = state.service ? t("sessionActive") : t("notStarted");
    state.review = data.conversation_status === "CLOSED";
    await loadHistory();
    await loadChats();
    connection();
  }
  async function sendMessage(message, quickReply = null) {
    if (state.busy || !state.confirmed || !state.service || state.review || (quickReply && byId('message-input').value.trim()) || (!message.trim() && !state.photo && !quickReply)) return;
    let payload;
    try {
      if (!state.pendingTurn || state.pendingTurn.text !== message || state.pendingTurn.photo !== state.photo || JSON.stringify(state.pendingTurn.quickReply) !== JSON.stringify(quickReply)) {
        state.pendingTurn = {id:crypto.randomUUID(),text:message,photo:state.photo,quickReply,
          language:state.manualLanguage ? state.language : null,serviceId:state.service.id,conversationId:state.conversationId};
      }
      const turn=state.pendingTurn;
      payload=core.turnPayload(turn.text,turn.photo,turn.language,turn.serviceId,turn.conversationId,turn.id,turn.quickReply);
    } catch (error) { notice(t("invalid")); return; }
    busy(true, true); notice(""); scrollBottom();
    try {
      const data = await api("/api/chat/turn/", {method:"POST",body:payload});
      if (state.conversationId && data.conversation_id !== state.conversationId) throw new Error('Conversation reference changed unexpectedly. Refresh to review saved messages.');
      state.conversationId = data.conversation_id; state.manualLanguage = false; applyLanguage(data.language, false);
      byId("message-input").value = ""; byId("character-count").textContent = "0 / 2000";
      state.pendingTurn=null; clearPhoto();
      await loadHistory(); await loadChats(); connection();
      if (data.provider_status !== "ok") notice(t("providerError"));
    } catch (error) {
      notice(errorMessage(error)); connection(error.status > 0);
      if (!error.status || error.status === 409 || error.status >= 500) state.review = true;
      if (error.status === 401) state.service = null;
    } finally { busy(false); if (!state.review && state.service) byId("message-input").focus(); }
  }
  function clearPhoto() {
    if (state.preview) URL.revokeObjectURL(state.preview);
    state.photo = null; state.preview = null;
    byId("photo-preview").hidden = true; byId("photo-input").value = ""; byId("preview-image").removeAttribute("src"); controls();
  }
  byId("chat-form").addEventListener("submit", (event) => { event.preventDefault(); void sendMessage(byId("message-input").value); });
  byId("message-input").addEventListener("input", () => { byId("character-count").textContent = byId("message-input").value.length + " / 2000"; controls(); });
  byId("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); void sendMessage(byId("message-input").value); } });
  byId("language").addEventListener("change", async (event) => {
    applyLanguage(event.target.value); state.manualLanguage = true;
    if (!state.conversationId && state.confirmed) {
      busy(true);
      try { await api("/demo/language/", {method:"POST",body:new URLSearchParams({language:state.language})}); }
      catch (error) { state.confirmed=false; notice(errorMessage(error)); }
      finally { busy(false); }
    }
  });
  byId("welcome-form").addEventListener("change", () => { byId("welcome-continue").disabled = !document.querySelector("[name=initial-language]:checked"); });
  byId("welcome-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (state.busy) return;
    const selected = document.querySelector("[name=initial-language]:checked"); if (!selected) return;
    busy(true); byId("welcome-continue").disabled = true;
    try {
      await api("/demo/language/", {method:"POST",body:new URLSearchParams({language:selected.value})});
      state.confirmed=true; applyLanguage(selected.value); byId("welcome-screen").hidden=true; byId("support-workspace").hidden=false; notice("");
    } catch(error) { notice(errorMessage(error)); }
    finally { busy(false); byId("welcome-continue").disabled=false; }
  });
  byId('reconnect-chat')?.addEventListener('click', async () => {
    if (state.busy) return; busy(true);
    try { await api('/demo/customer/reconnect/', {method:'POST'}); const restored = await sync(); if (restored !== false) notice(''); }
    catch(error) { notice(errorMessage(error)); } finally { busy(false); }
  });
  byId("close-zoom").addEventListener("click", () => byId("image-zoom").close());
  byId("service-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); if (state.busy) return;
    const id = Number(byId("service-select").value);
    if (!id) { notice(t("choose")); return; }
    if (state.service?.id === id && !state.review) { byId("message-input").focus(); return; }
    if (state.conversationId && state.service && state.service.id !== id && !window.confirm(t("switchService"))) return;
    busy(true); notice("");
    try {
      await api("/demo/session/", {method:"POST",body:new URLSearchParams({service_id:String(id)})});
      state.history = []; state.before = null; state.review = false; state.pendingTurn=null; clearPhoto(); await sync();
    } catch (error) { notice(errorMessage(error)); } finally { busy(false); }
  });
  async function chooseChat(body) {
    if (state.busy || !state.service) return;
    busy(true); notice('');
    try {
      await api('/demo/conversation/', {method:'POST',body:new URLSearchParams(body)});
      state.pendingTurn = null; clearPhoto(); byId('message-input').value = '';
      await sync();
    } catch (error) { notice(errorMessage(error)); } finally { busy(false); }
  }
  byId('new-chat')?.addEventListener('click', () => chooseChat({action:'new'}));
  byId('resume-chat')?.addEventListener('click', () => {
    const id = byId('previous-chats').value;
    if (id) chooseChat({conversation_id:id});
  });
  byId('more-chats')?.addEventListener('click', async () => {
    if (state.busy || chatOffset === null) return;
    busy(true); try { await loadChats(true); } catch(error) { notice(errorMessage(error)); } finally { busy(false); }
  });
  byId("refresh-history").addEventListener("click", async () => {
    if (state.busy) return; busy(true);
    try { const restored = await sync(); if (restored !== false) notice(""); } catch (error) { notice(errorMessage(error)); } finally { busy(false); }
  });
  byId("load-older").addEventListener("click", async () => {
    if (state.busy) return; busy(true);
    try { await loadHistory(true); } catch (error) { notice(errorMessage(error)); } finally { busy(false); }
  });
  byId("attach-label").addEventListener("click", (event) => {
    if (!state.service || state.busy || state.review) { event.preventDefault(); if (!state.service) notice(t("choose")); }
  });
  byId("attach-label").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (!state.busy && state.service && !state.review) byId("photo-input").click(); else notice(t("choose")); } });
  byId("photo-input").addEventListener("change", (event) => {
    const file = event.target.files[0]; clearPhoto();
    if (!file) return;
    if (!core.validPhoto(file)) { notice(t("invalidPhoto")); return; }
    state.photo = file; state.preview = URL.createObjectURL(file);
    byId("preview-image").src = state.preview; byId("preview-name").textContent = file.name;
    byId("photo-preview").hidden = false; notice(""); controls();
  });
  byId("cancel-photo").addEventListener("click", clearPhoto);
  window.addEventListener("offline", () => { connection(false); controls(); notice(t("networkError")); });
  window.addEventListener("online", () => { connection(); controls(); });
  window.addEventListener("pagehide", () => { state.blobs.forEach((url) => URL.revokeObjectURL(url)); if (state.preview) URL.revokeObjectURL(state.preview); });
  applyLanguage("en"); busy(true);
  sync().catch((error) => notice(errorMessage(error))).finally(() => busy(false));
})();
