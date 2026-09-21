"use strict";

// Continue's socket timeout is in seconds, but its OpenAI adapter passes the
// same number to an SDK timer in milliseconds. Zero also falls back to the
// SDK's ten-minute default. Disable that timer only for our explicitly
// unlimited local model. Keep AbortSignal cancellation for the entire body.
function configureLongWait(client, config) {
  let url;
  try { url = new URL(config.apiBase); } catch { return false; }
  if (config.requestOptions?.timeout !== 0 || url.protocol !== "http:" ||
      !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) return false;
  client.maxRetries = 0; // A timeout/disconnect never resubmits a browser prompt.
  client.fetchWithTimeout = async function (url, init, _ms, controller) {
    const { signal, method, ...options } = init || {};
    const combined = signal ? AbortSignal.any([signal, controller.signal]) : controller.signal;
    combined.throwIfAborted();
    const readable = (globalThis.ReadableStream && options.body instanceof globalThis.ReadableStream) ||
      (typeof options.body === "object" && options.body !== null && Symbol.asyncIterator in options.body);
    return this.fetch.call(undefined, url, {
      ...(readable ? { duplex: "half" } : {}),
      ...options,
      method: (method || "GET").toUpperCase(),
      signal: combined,
    });
  };
  return true;
}

module.exports = { configureLongWait };
