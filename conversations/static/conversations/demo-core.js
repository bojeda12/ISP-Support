/* Contratos y transporte sin dependencias; compartidos con las pruebas Node. */
(function (root) {
  "use strict";
  class RequestError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }
  function chatPayload(message, language, serviceId, conversationId) {
    if (typeof message !== "string" || !message.trim() || message.trim().length > 2000) throw new Error("invalid_message");
    if (language != null && !["es", "en"].includes(language)) throw new Error("invalid_language");
    const id = conversationId || serviceId;
    if (!Number.isSafeInteger(id) || id < 1) throw new Error("invalid_reference");
    return { message: message.trim(), ...(language ? {language} : {}), [conversationId ? "conversation_id" : "service_id"]: id };
  }
  function safePath(path, origin) {
    const url = new URL(path, origin);
    if (url.origin !== origin || !/^\/(api|demo)\//.test(url.pathname) || url.username || url.password) throw new Error("unsafe_url");
    return url.pathname + url.search;
  }
  function validPhoto(file) {
    return Boolean(file && ["image/jpeg", "image/png"].includes(file.type) && file.size > 0 && file.size <= 5 * 1024 * 1024);
  }
  async function requestJSON(path, options, transport, csrfToken, origin) {
    const headers = { Accept: "application/json", ...options.headers };
    if (options.method && options.method !== "GET") headers["X-CSRFToken"] = csrfToken;
    let response;
    try {
      response = await transport(safePath(path, origin), { ...options, headers, credentials: "same-origin", redirect: "error" });
    } catch (error) { throw new RequestError(0, "network_error"); }
    if (!response.ok) throw new RequestError(response.status, "http_error");
    if (!(response.headers.get("content-type") || "").includes("application/json")) throw new RequestError(0, "invalid_response");
    try { return await response.json(); } catch (error) { throw new RequestError(0, "invalid_response"); }
  }
  const core = { chatPayload, safePath, validPhoto, requestJSON, RequestError };
  if (typeof module !== "undefined" && module.exports) module.exports = core;
  else root.ISPSupportCore = core;
})(globalThis);
