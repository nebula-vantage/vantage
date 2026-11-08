const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const source = readFileSync(join(__dirname, "../../vantage/web/api.js"), "utf8");

function transport(fetch) {
  const timers = new Map();
  let nextTimer = 0;
  const context = {
    AbortController,
    fetch,
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  };
  runInNewContext(source, context);
  return { request: context.VantageAPI.request, timers };
}

function response(payload, status = 200) {
  return { ok: status < 400, status, json: async () => payload };
}

function waitForAbort(signal) {
  return new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  });
}

test("GET and POST preserve their API contract and release timers", async () => {
  const calls = [];
  const { request, timers } = transport(async (...args) => {
    calls.push(args);
    return response({ success: true });
  });
  assert.equal((await request("/api/config")).success, true);
  assert.equal(calls[0][1].method, undefined);
  assert.equal(calls[0][1].headers.Accept, "application/json");
  await request("/api/report", { focus: "placement" });
  assert.equal(calls[1][1].method, "POST");
  assert.equal(calls[1][1].headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[1][1].body), { focus: "placement" });
  assert.equal(timers.size, 0);
});

test("HTTP failures retain status even with malformed error payloads", async () => {
  for (const payload of [null, {}, { error: {} }, { error: "" }, { error: "Unavailable" }]) {
    const { request, timers } = transport(async () => response(payload, 404));
    await assert.rejects(request("/missing"), (error) => {
      assert.equal(error.status, 404);
      assert.equal(error.message, payload?.error === "Unavailable"
        ? "Unavailable" : "That request could not be completed. Try again.");
      return true;
    });
    assert.equal(timers.size, 0);
  }
});

test("invalid JSON and network failures release timers", async () => {
  const invalid = transport(async () => ({ json: async () => { throw new SyntaxError(); } }));
  await assert.rejects(invalid.request("/invalid"), /unreadable response/);
  assert.equal(invalid.timers.size, 0);
  const offline = transport(async () => { throw new Error("offline"); });
  await assert.rejects(offline.request("/offline"), /Couldn't reach Vantage/);
  assert.equal(offline.timers.size, 0);
});

test("stalled headers abort at the deadline without retrying a POST", async () => {
  let calls = 0;
  const { request, timers } = transport((path, { signal }) => {
    calls++;
    return waitForAbort(signal);
  });
  const pending = request("/api/analysis/job/start", {});
  const rejection = assert.rejects(pending, /took too long/);
  const timer = [...timers.values()][0];
  assert.equal(timer.delay, 30_000);
  timer.callback();
  await rejection;
  assert.equal(calls, 1);
  assert.equal(timers.size, 0);
});

test("deadline also aborts a stalled response body with the chat allowance", async () => {
  let bodyStarted;
  const started = new Promise((resolve) => { bodyStarted = resolve; });
  const { request, timers } = transport(async (path, { signal }) => ({
    ok: true,
    json() {
      bodyStarted();
      return waitForAbort(signal);
    },
  }));
  const pending = request("/api/coach/game/chat", {}, { timeoutMs: 210_000 });
  const rejection = assert.rejects(pending, /took too long/);
  await started;
  const timer = [...timers.values()][0];
  assert.equal(timer.delay, 210_000);
  timer.callback();
  await rejection;
  assert.equal(timers.size, 0);
});

test("signed-out responses carry their code and notify the app once per request", async () => {
  const context = {
    AbortController, setTimeout, clearTimeout,
    fetch: async () => response({ error: "Sign in to continue.", code: "signed_out" }, 401),
  };
  runInNewContext(source, context);
  let notified = 0;
  context.VantageAPI.onSignedOut(() => { notified += 1; });
  await assert.rejects(context.VantageAPI.request("/api/sessions"), (error) => {
    assert.equal(error.status, 401);
    assert.equal(error.code, "signed_out");
    return true;
  });
  assert.equal(notified, 1);
  // Other failures, including other 401s, don't sign the app out.
  context.fetch = async () => response({ error: "That email and password don't match." }, 401);
  await assert.rejects(context.VantageAPI.request("/api/account/sign-in", {}));
  assert.equal(notified, 1);
});

test("account form errors keep the field they belong to", async () => {
  const { request } = transport(async () =>
    response({ error: "Enter a valid email address.", field: "email" }, 400));
  await assert.rejects(request("/api/account/create", {}), (error) => {
    assert.equal(error.field, "email");
    assert.equal(error.message, "Enter a valid email address.");
    return true;
  });
});

test("an unreachable server gets plain words instead of the browser's fetch error", async () => {
  const { request, timers } = transport(async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(request("/api/account"), (error) => {
    assert.equal(error.message, "Couldn't reach Vantage. Check that it's running, then try again.");
    assert.equal(error.status, undefined);
    return true;
  });
  assert.equal(timers.size, 0);
});

