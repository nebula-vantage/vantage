"use strict";

// Shared browser transport. A deadline covers both headers and response-body reads.
// Requests are never retried here: a timed-out POST may still finish on the server.
// An expired or missing session ("signed_out") is reported once to the app's handler.
(() => {
  let signedOutHandler = null;

  async function request(path, body, { timeoutMs = 30_000 } = {}) {
    const controller = new AbortController();
    const options = {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    };
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      let response;
      try {
        response = await fetch(path, options);
      } catch (error) {
        if (controller.signal.aborted) throw error;
        // fetch rejects with a bare "Failed to fetch" / "Load failed" when the server is gone.
        throw new Error("Couldn't reach Vantage. Check that it's running, then try again.");
      }
      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new Error("Vantage returned an unreadable response. Try again.");
      }
      if (!response.ok) {
        const message = typeof payload?.error === "string" && payload.error.trim()
          ? payload.error
          : "That request could not be completed. Try again.";
        const error = new Error(message);
        error.status = response.status;
        if (typeof payload?.code === "string") error.code = payload.code;
        // Account forms show the message under the field the server names.
        if (typeof payload?.field === "string") error.field = payload.field;
        if (response.status === 401 && error.code === "signed_out") signedOutHandler?.(error);
        throw error;
      }
      return payload;
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error("The request took too long. Check the current status before trying again.");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  globalThis.VantageAPI = Object.freeze({
    request,
    onSignedOut(handler) {
      signedOutHandler = typeof handler === "function" ? handler : null;
    },
  });
})();
