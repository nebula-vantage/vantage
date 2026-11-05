"use strict";

// Shared browser transport. A deadline covers both headers and response-body reads.
// Requests are never retried here: a timed-out POST may still finish on the server.
(() => {
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
      const response = await fetch(path, options);
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

  globalThis.VantageAPI = Object.freeze({ request });
})();
