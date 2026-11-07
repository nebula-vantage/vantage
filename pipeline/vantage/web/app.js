"use strict";

// The browser owns presentation, local video playback, and practice checkmarks.
// Reports and answers come from the same versioned API a future mobile client can use.
const $ = (id) => document.getElementById(id);
const state = {
  session: null,
  report: null,
  focus: "consistency",
  sessions: [],
  temporarySessions: new Map(),
  gameSnapshots: new Map(),
  chatEntries: [],
  videoFile: null,
  pendingResume: null,
  route: null,
  routeError: "",
  libraryError: false,
  booting: true,
  reportGeneration: 0,
  reportLoading: false,
  reportError: "",
  aiAvailable: false,
  generation: 0,
  chatGeneration: 0,
  history: [],
  chatBusy: false,
  videoURL: null,
  hasVideo: false,
  pendingSeek: null,
  completed: new Set(),
};
// The AI video coach belongs to saved games only. Its status is server-owned; the
// browser keeps one game's copy, guarded by `generation` and request `seq` numbers.
const COACH_ENGINE_KEY = "vantage.coach.engine";
const COACH_RUNNING = new Set(["queued", "preparing", "coaching"]);
const COACH_POLL_MS = 2000;
const COACH_LEAD_IN_S = 1;
const COACH_SUGGESTIONS = [
  "What’s the #1 thing I should work on?",
  "How was our positioning at the kitchen line?",
  "Which moment should I rewatch first?",
];
const COACH_STAGES = {
  queued: "Waiting for your coach to start…",
  preparing: "Picking key moments from your video",
  coaching: "Your coach is watching the key moments",
};
const MOMENT_KINDS = {
  rally_start: "Rally start", shot: "Shot", bounce: "Bounce",
  rally_end: "Rally end", positioning: "Positioning", overview: "Overview",
};
const PRIORITIES = ["high", "medium", "low"];
const coach = {
  configured: false,
  engines: [],
  defaultEngine: null,
  status: null,
  statusFor: null,
  receivedAt: 0,
  error: "",
  pollError: "",
  actionBusy: false,
  actionError: "",
  cancelling: false,
  editing: false,
  generation: 0,
  seq: 0,
  appliedSeq: 0,
  pollTimer: null,
  tickTimer: null,
  formFor: null,
  reviewKey: "",
  chatMode: "",
};
let toastTimer;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function replace(id, nodes) {
  $(id).replaceChildren(...nodes);
}
function number(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}
function percent(value) {
  return `${Math.round(Math.max(0, Math.min(1, number(value))) * 100)}%`;
}
function time(value) {
  const seconds = Math.max(0, Math.floor(number(value)));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function notice(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 4500);
}
function showError(message) {
  $("error-banner").textContent = message;
  $("error-banner").hidden = !message;
}

const api = globalThis.VantageAPI.request;

function gamePath(id, tab = "overview") {
  const key = id === "demo" ? "sample" : id;
  return `/games/${encodeURIComponent(key)}${tab === "overview" ? "" : `/${tab}`}`;
}

function readRoute() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  if (path === "/" || path === "/games") return { kind: "games" };
  const match = /^\/games\/(sample|[a-f0-9]{20})(?:\/(coaching|replay))?$/.exec(path);
  if (!match) return { kind: "missing" };
  return { kind: "game", id: match[1] === "sample" ? "demo" : match[1], tab: match[2] || "overview" };
}

async function navigate(path, replace = false) {
  if (window.location.pathname !== path) {
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  }
  const opened = await applyRoute();
  $("main").focus({ preventScroll: true });
  window.scrollTo({ top: 0, behavior: "instant" });
  return opened;
}

async function applyRoute() {
  state.route = readRoute();
  state.routeError = "";
  showError("");
  if (state.route.kind === "games") {
    $("session-video").pause();
    stopCoachPolling();
    renderLibrary();
    applyAppLayout();
    return true;
  }
  if (state.route.kind === "missing") {
    ++state.generation;
    ++state.reportGeneration;
    ++state.chatGeneration;
    resetCoach();
    clearVideo();
    state.session = null;
    state.report = null;
    state.routeError = "This game link is not valid. Choose a game from your library.";
    applyAppLayout();
    loading(false);
    return false;
  }
  if (state.session?.id === state.route.id) {
    applyAppLayout();
    // Returning to a game resumes a review that kept running while it was closed.
    if (coachRunning()) void loadCoachStatus();
    return true;
  }
  const id = state.route.id;
  return openSession(() => state.temporarySessions.has(id)
    ? Promise.resolve(state.temporarySessions.get(id))
    : api(id === "demo" ? "/api/demo" : `/api/sessions/${encodeURIComponent(id)}`));
}

function applyAppLayout() {
  const route = state.route || { kind: "games" };
  const home = route.kind === "games";
  const ready = route.kind === "game" && state.session?.id === route.id && !state.routeError;
  const coaching = ready && route.tab === "coaching";
  const replaying = ready && route.tab === "replay";
  $("games-page").hidden = !home;
  $("workspace").hidden = !ready;
  $("game-unavailable").hidden = !state.routeError;
  $("game-unavailable-copy").textContent = state.routeError;
  $("game-breadcrumb").hidden = home;
  $("game-navigation").hidden = !ready;
  $("header-upload").hidden = !home;
  $("export-control").hidden = !ready;
  $("export-button").disabled = !state.report || state.reportLoading;
  $("page-title").textContent = home ? "Games" : state.routeError ? "Game unavailable"
    : coaching ? "Game coaching" : replaying ? "3D replay" : "Game review";
  $("page-description").textContent = home
    ? "Your game. A clearer picture. A next step."
    : coaching ? "Review the evidence. Plan your next session."
      : replaying ? "Watch the whole game from any angle, and see how you moved with the play."
        : "Your replay, measurements, and coaching in one place.";
  $("breadcrumb-name").textContent = ready ? state.session.name : "Game";
  document.title = home ? "Games · Vantage"
    : `${ready ? state.session.name : "Game"} · ${coaching ? "Coaching · " : replaying ? "3D replay · " : ""}Vantage`;
  $("games-nav").classList.toggle("active", home);
  if (home) $("games-nav").setAttribute("aria-current", "page");
  else $("games-nav").removeAttribute("aria-current");
  if (ready) {
    $("nav-game-name").textContent = state.session.name;
    for (const tab of ["overview", "replay", "coaching"]) {
      for (const suffix of ["nav", "tab"]) {
        const link = $(`${tab}-${suffix}`);
        link.href = gamePath(state.session.id, tab);
        link.classList.toggle("active", route.tab === tab);
        if (route.tab === tab) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      }
    }
    $("game-coach-link").href = gamePath(state.session.id, "coaching");
    $("replay-link").href = gamePath(state.session.id, "replay");
    $("temporary-note").hidden = !state.session.is_temporary;
  }
  document.querySelectorAll("[data-game-panel]").forEach((node) => {
    node.hidden = !ready || node.dataset.gamePanel !== route.tab ||
      (node.hasAttribute("data-needs-report") && !state.report);
  });
  $("coaching-error").hidden = !coaching || (!state.reportLoading && !state.reportError);
  $("coaching-error-title").textContent = state.reportLoading ? "Opening your coaching…" : "Coaching couldn't load.";
  $("coaching-error-copy").textContent = state.reportLoading
    ? "Building a review from this game's observations."
    : `${state.reportError} Your video and measured overview are still available.`;
  $("coaching-retry").hidden = state.reportLoading;
  $("workspace").dataset.tab = ready ? route.tab : "";
  // The replay brings its own synced copy of the recording; the main player waits.
  if (replaying) $("session-video").pause();
  globalThis.VantageReplay?.sync({
    active: replaying,
    session: ready ? state.session : null,
    startAt: $("session-video").currentTime || 0,
  });
}

function libraryEntries() {
  const saved = new Set(state.sessions.map((game) => game.id));
  const temporary = [...state.temporarySessions.values()].filter((game) => !saved.has(game.id)).map((game) => ({
    ...game, duration_s: game.stats.video.duration_s,
    quality: { status: game.stats.quality.status, coverage: game.stats.quality.ball_detection_coverage },
    has_video: false,
  }));
  return [...temporary, ...state.sessions];
}

function analyzedDate(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return "Saved analysis";
  return `Analyzed ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date)}`;
}

function renderLibrary() {
  const games = libraryEntries();
  $("games-count").textContent = `${games.length} ${games.length === 1 ? "game" : "games"}`;
  $("games-empty").hidden = games.length > 0 || state.libraryError;
  replace("games-list", games.map((game) => {
    const card = element("a", "game-card");
    card.href = gamePath(game.id);
    card.dataset.route = "";
    const cover = element("div", "game-cover");
    cover.append(element("div", "card-court"));
    if (typeof game.thumbnail_url === "string" && game.thumbnail_url.startsWith("/media/")) {
      const preview = element("img", "game-thumbnail");
      preview.src = game.thumbnail_url;
      preview.alt = "";
      preview.loading = "lazy";
      preview.addEventListener("error", () => preview.remove(), { once: true });
      cover.append(preview);
    }
    const labels = element("div", "game-cover-labels");
    labels.append(element("span", "game-sport", "PICKLEBALL"));
    if (game.is_demo) labels.append(element("span", "game-tag", "SYNTHETIC"));
    else if (game.is_temporary) labels.append(element("span", "game-tag", "TEMPORARY IMPORT"));
    cover.append(labels);
    cover.append(element("span", "game-duration", typeof game.duration_s === "number" ? time(game.duration_s) : "Game analysis"));
    const body = element("div", "game-card-body");
    body.append(element("p", "game-date", game.is_temporary ? "Available in this browser session" : analyzedDate(game.analyzed_at)));
    body.append(element("h3", "game-card-title", game.name || "Analyzed game"));
    const quality = game.quality;
    const support = element("p", "game-card-quality", quality?.status === "insufficient_evidence"
      ? "More ball observations needed" : quality?.status === "limited_evidence"
        ? "Limited tracking evidence" : "Analysis ready to review");
    support.prepend(element("span", "status-dot"));
    body.append(support);
    const footer = element("div", "game-card-footer");
    footer.append(element("span", "", game.has_video ? "Replay + coaching" : "Stats + coaching"));
    footer.append(element("span", "", "Open game →"));
    body.append(footer);
    card.append(cover, body);
    return card;
  }));
}

async function refreshLibrary() {
  try {
    const library = await api("/api/sessions");
    state.sessions = library.sessions || [];
    state.libraryError = false;
    $("session-errors").textContent = (library.errors || []).join("\n");
    $("session-errors").hidden = !library.errors?.length;
    renderLibrary();
    return true;
  } catch (error) {
    state.libraryError = true;
    $("session-errors").textContent = "Couldn't load your saved games. Check the connection, then refresh the library.";
    $("session-errors").hidden = false;
    renderLibrary();
    return false;
  }
}

function loading(active) {
  document.body.classList.toggle("is-loading", active);
  $("loading").hidden = !active || Boolean(state.session) || (state.route?.kind === "games" && !state.booting);
  $("loading-copy").textContent = state.booting ? "Opening your games…" : "Opening your game…";
  $("export-button").disabled = active || !state.report;
}

function rememberCurrentGame() {
  if (!state.session) return;
  state.gameSnapshots.set(state.session.id, {
    session: state.session, report: state.report, focus: state.focus,
    history: [...state.history],
    // Keep the completed transcript independently of the bounded provider history.
    // An in-flight question is retriable, so don't restore it without its answer.
    chatEntries: state.chatBusy ? state.chatEntries.slice(0, -1) : [...state.chatEntries],
    videoFile: state.videoFile, videoTime: $("session-video").currentTime || 0,
    // Shown immediately on return, then refreshed from the server.
    coachStatus: currentCoachStatus(), coachReceivedAt: coach.receivedAt,
  });
}

async function openSession(fetchSession) {
  rememberCurrentGame();
  const generation = ++state.generation;
  ++state.reportGeneration;
  ++state.chatGeneration;
  resetCoach();
  clearVideo();
  state.session = null;
  state.report = null;
  state.reportLoading = false;
  state.reportError = "";
  state.focus = "consistency";
  resetChat();
  applyAppLayout();
  loading(true);
  showError("");
  try {
    const session = await fetchSession();
    if (generation !== state.generation) return false;
    state.session = session;
    const previous = state.gameSnapshots.get(session.id);
    const saved = previous && JSON.stringify(previous.session.stats) === JSON.stringify(session.stats) ? previous : null;
    if (saved) {
      state.report = saved.report;
      state.focus = saved.focus;
      state.history = [...saved.history];
      for (const entry of saved.chatEntries) addMessage(entry.role, entry.text, entry.result);
      state.pendingResume = { id: session.id, time: saved.videoTime };
      if (saved.coachStatus) {
        coach.status = saved.coachStatus;
        coach.statusFor = session.id;
        coach.receivedAt = saved.coachReceivedAt;
      }
    }
    render();
    if (saved?.videoFile) {
      state.videoFile = saved.videoFile;
      setVideo(URL.createObjectURL(saved.videoFile), true);
    } else if (session.video_url) setVideo(session.video_url, false);
    loading(false);
    void loadCoachStatus();
    if (!state.report) await loadReport();
    return generation === state.generation;
  } catch (error) {
    if (generation === state.generation && state.route?.kind === "game") {
      state.routeError = error.status === 404
        ? "This game isn't available. Imported analyses are temporary; import it again or choose a saved game."
        : (error.message || "Could not open this game. Return to Games and try again.");
      applyAppLayout();
    }
    return false;
  } finally {
    if (generation === state.generation) loading(false);
  }
}

async function loadReport(focus = state.focus) {
  if (!state.session) return false;
  const generation = state.generation;
  const reportGeneration = ++state.reportGeneration;
  state.reportLoading = true;
  state.reportError = "";
  applyAppLayout();
  try {
    const report = await api("/api/report", { stats: state.session.stats, focus });
    if (generation !== state.generation || reportGeneration !== state.reportGeneration) return false;
    state.report = report;
    state.focus = focus;
    render();
    return true;
  } catch (error) {
    if (generation === state.generation && reportGeneration === state.reportGeneration) {
      state.reportError = error.message || "Please try again.";
    }
    return false;
  } finally {
    if (generation === state.generation && reportGeneration === state.reportGeneration) {
      state.reportLoading = false;
      applyAppLayout();
    }
  }
}

async function setFocus(focus) {
  if (!state.session || (focus === state.focus && !state.reportLoading)) return;
  // Local answers depend on the focus; the AI coach conversation does not.
  if (!coachChatActive()) {
    ++state.chatGeneration;
    resetChat();
  }
  await loadReport(focus);
}

function qualityForGame() {
  if (state.report) return state.report.quality;
  const quality = state.session.stats.quality;
  const coverage = quality.ball_detection_coverage;
  const status = coverage === 0 ? "insufficient_evidence" : quality.status;
  return { status, coverage, warnings: quality.warnings || [],
    label: status === "insufficient_evidence" ? "Insufficient evidence" : status === "limited_evidence" ? "Limited evidence" : "Estimated observations" };
}

function render() {
  const { session, report } = state;
  $("session-name").textContent = session.name || "Analyzed game";
  $("demo-badge").hidden = !session.is_demo;
  $("sample-note").hidden = !session.is_demo;
  $("session-meta").textContent = "PICKLEBALL · ANALYZED GAME";
  $("video-duration").textContent = `${time(session.stats.video?.duration_s)} analysis`;
  $("video-coverage").textContent = `${percent(qualityForGame().coverage)} of frames observed`;
  document.querySelectorAll("[data-focus]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.focus === state.focus));
  });
  renderMetrics();
  renderCourt();
  renderQuality();
  if (report) {
    $("report-headline").textContent = report.headline;
    $("report-summary").textContent = report.summary;
    renderInsights();
    renderMoments();
    renderDrills();
  }
  renderCoach();
  renderAIMode();
  applyAppLayout();
}

function overviewMetrics() {
  const stats = state.session.stats;
  const supported = qualityForGame().status !== "insufficient_evidence";
  return [
    { label: "Estimated rallies", value: supported ? stats.rally_count : null, detail: "Grouped by ball loss or inactivity" },
    { label: "Net crossings", value: supported ? stats.shot_count : null, detail: "Supported projected crossings" },
    { label: "Ball observed", value: percent(stats.quality.ball_detection_coverage), detail: "Share of frames with ball evidence" },
    { label: "Projected speed", value: supported && typeof stats.avg_ball_speed_kmh === "number" ? Math.round(stats.avg_ball_speed_kmh * 10) / 10 : null, unit: "km/h", detail: "Court-plane estimate" },
  ];
}

function renderMetrics() {
  replace(
    "metric-grid",
    (state.report?.metrics || overviewMetrics()).map((metric) => {
      const card = element("div", "metric");
      card.append(element("div", "metric-label", metric.label));
      const value = element("div", "metric-value", metric.value ?? "—");
      if (metric.unit) value.append(element("span", "", metric.unit));
      card.append(
        value,
        element("div", "metric-detail", metric.detail || "Session estimate"),
      );
      return card;
    }),
  );
}

function renderCourt() {
  const supported = qualityForGame().status !== "insufficient_evidence";
  const candidates = (
    supported ? state.session.stats.in_out_calls || [] : []
  ).filter(
    (bounce) =>
      Array.isArray(bounce.court) &&
      bounce.court.length === 2 &&
      bounce.court.every(
        (coordinate) =>
          typeof coordinate === "number" && Number.isFinite(coordinate),
      ) &&
      bounce.court[0] >= -0.8 &&
      bounce.court[0] <= 6.9 &&
      bounce.court[1] >= -0.8 &&
      bounce.court[1] <= 14.21,
  );
  const dots = candidates.map((bounce) => {
    const dot = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "circle",
    );
    dot.setAttribute("cx", bounce.court[0]);
    dot.setAttribute("cy", 13.41 - bounce.court[1]);
    dot.setAttribute("r", "0.13");
    dot.setAttribute("fill", bounce.call === "OUT" ? "#fff" : "#e8590c");
    dot.setAttribute("stroke", bounce.call === "OUT" ? "#e8590c" : "#fff");
    dot.setAttribute("stroke-width", "0.055");
    if (
      (bounce.quality_flags || []).some((flag) =>
        /boundary|uncertain/.test(flag),
      )
    )
      dot.setAttribute("opacity", "0.5");
    const title = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "title",
    );
    title.textContent = `Bounce candidate at ${time(bounce.time_s)} · estimated ${bounce.call || "location"}`;
    dot.append(title);
    return dot;
  });
  replace("court-dots", dots);
  $("court-caption").textContent = candidates.length
    ? `${candidates.length} estimated landings · both sides`
    : "No supported bounce locations";
}

function renderInsights() {
  const insights = state.report.insights || [];
  replace(
    "insights",
    insights.length
      ? insights.map((insight, index) => {
          const card = element("article", "insight");
          card.id = `insight-${insight.id}`;
          card.append(
            element(
              "span",
              "insight-number",
              String(index + 1).padStart(2, "0"),
            ),
          );
          const content = element("div", "insight-content");
          content.append(
            element("h3", "", insight.title),
            element("p", "", insight.body),
          );
          if (insight.evidence?.length) {
            const evidence = element("div", "evidence-pills");
            insight.evidence.forEach((item) =>
              evidence.append(
                element(
                  "span",
                  "evidence-pill",
                  `${item.label}: ${item.value}`,
                ),
              ),
            );
            content.append(evidence);
          }
          if (insight.moment_id) {
            const moment = state.report.moments.find(
              (item) => item.id === insight.moment_id,
            );
            if (moment) {
              const button = element(
                "button",
                "insight-link",
                `Review at ${time(moment.start_s)} ↗`,
              );
              button.type = "button";
              button.addEventListener("click", () => reviewMoment(moment));
              content.append(button);
            }
          }
          card.append(content);
          return card;
        })
      : [
          element(
            "p",
            "empty-message",
            "There isn’t enough evidence for a session pattern yet. Try the recording and review steps below.",
          ),
        ],
  );
}

function renderMoments() {
  const moments = state.report.moments || [];
  replace(
    "moments",
    moments.length
      ? moments.map((moment) => {
          const row = element("article", "moment");
          row.id = `moment-${moment.id}`;
          const description = element("div");
          description.append(
            element("h3", "", moment.title),
            element("p", "", moment.reason),
          );
          const button = element("button", "moment-action", "▷");
          button.type = "button";
          button.setAttribute(
            "aria-label",
            `Review ${moment.title} at ${time(moment.start_s)}`,
          );
          button.title = state.hasVideo
            ? "Play this moment"
            : "Attach video to review this moment";
          button.addEventListener("click", () => reviewMoment(moment));
          row.append(
            element("span", "moment-time", time(moment.start_s)),
            description,
            button,
          );
          return row;
        })
      : [
          element(
            "p",
            "empty-message",
            "No reliable moments to highlight from this analysis. You can still attach the video for your own review.",
          ),
        ],
  );
}

function planKey() {
  return `vantage.coaching.plan.v2.${state.session.id}.${state.focus}`;
}

function renderDrills() {
  try {
    const saved = JSON.parse(localStorage.getItem(planKey()) || "[]");
    state.completed = new Set(
      Array.isArray(saved) ? saved.filter((id) => typeof id === "string") : [],
    );
  } catch {
    state.completed = new Set();
  }
  const drills = state.report.drills || [];
  replace(
    "drills",
    drills.map((drill, index) => {
      const article = element("article", "drill");
      const heading = element("div", "drill-title");
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.id = `drill-${index}`;
      checkbox.checked = state.completed.has(drill.id);
      const label = element("label", "", drill.title);
      label.htmlFor = checkbox.id;
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.completed.add(drill.id);
        else state.completed.delete(drill.id);
        try {
          localStorage.setItem(planKey(), JSON.stringify([...state.completed]));
        } catch {
          notice(
            "Your browser could not save this checklist. You can still export it.",
          );
        }
        renderProgress();
      });
      heading.append(
        checkbox,
        label,
        element("span", "drill-minutes", `${drill.minutes} MIN`),
      );
      const body = element("div", "drill-body");
      body.append(element("p", "drill-why", drill.why));
      const details = element("details");
      if (index === 0) details.open = true;
      details.append(element("summary", "", "How to practice"));
      const steps = element("ol");
      (drill.steps || []).forEach((step) =>
        steps.append(element("li", "", step)),
      );
      details.append(
        steps,
        element("p", "drill-target", `Aim for: ${drill.target}`),
      );
      body.append(details);
      article.append(heading, body);
      return article;
    }),
  );
  const minutes = drills.reduce(
    (total, drill) => total + number(drill.minutes),
    0,
  );
  $("plan-duration").textContent = `${minutes} MIN PLAN`;
  renderProgress();
}

function renderProgress() {
  const drills = state.report.drills || [];
  const done = drills.filter((drill) => state.completed.has(drill.id)).length;
  $("plan-progress").textContent =
    `${done} of ${drills.length} drills completed${done === drills.length && done ? " · Nice work." : ""}`;
}

function renderQuality() {
  const quality = qualityForGame();
  $("quality-label").textContent = quality.label;
  $("quality-copy").textContent =
    `${percent(quality.coverage)} of video frames have an observed ball. Coverage describes visibility, not the accuracy of a shot or bounce call.`;
  replace(
    "quality-warnings",
    (quality.warnings || []).map((warning) => element("li", "", warning)),
  );
  $("quality-note").textContent =
    quality.status === "insufficient_evidence"
      ? "This session needs more ball observations. Start with the recording guidance; zero estimates don’t mean there was no play."
      : quality.status === "limited_evidence"
        ? "The ball is visible in a limited share of frames. Use these suggestions as a starting point for video review."
        : "These patterns come from observed ball movement. Check the video before treating an estimate as a finding.";
  $("coverage-value").textContent = percent(quality.coverage);
  $("coverage-bar").style.width = percent(quality.coverage);
}

function renderSuggestions() {
  const questions = coachChatActive()
    ? COACH_SUGGESTIONS
    : (state.report?.suggested_questions || []).slice(0, 3);
  replace(
    "suggested-questions",
    questions.map((question) => {
      const button = element("button", "suggestion");
      button.type = "button";
      button.append(element("span", "", question), element("span", "", "↗"));
      button.disabled = state.chatBusy;
      button.addEventListener("click", () => {
        $("chat-input").value = question;
        submitQuestion(question);
      });
      return button;
    }),
  );
  $("chat-log").querySelectorAll(".ai-follow-up").forEach((button) => {
    button.disabled = state.chatBusy;
  });
  renderMomentControls();
}

function chatModeKey() {
  return coachChatActive() ? `coach:${coachEngine().id}` : "local";
}

function renderAIMode() {
  const coachChat = coachChatActive();
  coach.chatMode = chatModeKey();
  $("ai-option").hidden = !state.aiAvailable || coachChat;
  if (!state.aiAvailable) $("use-ai").checked = false;
  const useAI = !coachChat && state.aiAvailable && $("use-ai").checked;
  const engine = coachChat ? coachEngine().label : "";
  const label = coachChat
    ? `AI coach · ${engine}`
    : useAI ? "AI responses · OpenAI" : "Session guide · local";
  $("coach-mode").replaceChildren(
    element("span", "status-dot"),
    document.createTextNode(label),
  );
  $("chat-footnote").textContent = coachChat
    ? `Sends your question, recent chat, and still frames to ${engine}. AI can make mistakes — check the video.`
    : useAI
      ? "AI can make mistakes. Check the session evidence."
      : "Fixed session guide · no generated AI responses.";
  // The AI coach answers from the video, so it doesn't wait for the local report.
  $("coach-card").toggleAttribute("data-needs-report", !coachChat);
  $("coach-moment-option").hidden = !coachChat;
  $("coach-intro-title").textContent = coachChat
    ? "Talk it through with your coach."
    : "A focus for your next game.";
  $("coach-intro-copy").textContent = coachChat
    ? "Your coach can look at frames from the video. Pause on a moment and ask what to improve."
    : "Ask about the session, review a moment, or find a drill to work on.";
  $("chat-input").placeholder = coachChat
    ? "Ask your coach about this game…"
    : "Ask about your session…";
  renderSuggestions();
}

function resetChat() {
  state.history = [];
  state.chatEntries = [];
  state.chatBusy = false;
  replace("chat-log", []);
  $("chat-input").value = "";
  $("chat-input").disabled = false;
  $("send-button").disabled = false;
  $("chat-error").hidden = true;
}

function addMessage(role, text, result) {
  state.chatEntries.push({ role, text, result });
  const coachAnswer = result?.source === "ai-coach";
  const message = element("div", `chat-message ${role}`);
  message.append(
    element(
      "div",
      "message-label",
      role === "user"
        ? "You"
        : coachAnswer
          ? `AI coach · ${result.engine_label || "AI"}`
          : result?.source === "openai"
            ? "AI coach · OpenAI"
            : "Session guide · local",
    ),
  );
  message.append(element("div", "message-body", text));
  if (coachAnswer) appendCoachExtras(message, role, result);
  if (result?.warning)
    message.append(element("p", "message-warning", result.warning));
  if (result?.evidence_ids?.length) {
    const evidence = element("div", "message-evidence");
    result.evidence_ids.forEach((id) => {
      const insight = state.report.insights.find((item) => item.id === id);
      const moment = state.report.moments.find((item) => item.id === id);
      if (!insight && !moment) return;
      const button = element("button", "", (insight || moment).title);
      button.type = "button";
      button.addEventListener("click", () => {
        const node = $(insight ? `insight-${id}` : `moment-${id}`);
        if (!node) return;
        node.scrollIntoView({ behavior: "smooth", block: "center" });
        node.classList.remove("highlight");
        requestAnimationFrame(() => node.classList.add("highlight"));
      });
      evidence.append(button);
    });
    message.append(evidence);
  }
  $("chat-log").append(message);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return message;
}

async function submitQuestion(raw, options) {
  if (coachChatActive()) return submitCoachQuestion(raw, options);
  const question = raw.trim();
  if (!question || !state.session || !state.report || state.chatBusy) return;
  if (question.length > 2000) {
    $("chat-error").textContent = "Keep your question under 2,000 characters.";
    $("chat-error").hidden = false;
    return;
  }
  const generation = state.generation;
  const chatGeneration = ++state.chatGeneration;
  state.chatBusy = true;
  $("chat-error").hidden = true;
  $("chat-input").value = "";
  $("chat-input").disabled = true;
  $("send-button").disabled = true;
  renderSuggestions();
  const userMessage = addMessage("user", question);
  const pending = element(
    "div",
    "pending-message",
    "Looking at the session evidence…",
  );
  $("chat-log").append(pending);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  try {
    const result = await api("/api/chat", {
      stats: state.session.stats,
      focus: state.focus,
      message: question,
      history: state.history.slice(-12).map((item) => ({
        role: item.role,
        content: item.content.slice(0, 2000),
      })),
      use_ai: state.aiAvailable && $("use-ai").checked,
    });
    if (
      generation !== state.generation ||
      chatGeneration !== state.chatGeneration
    )
      return;
    pending.remove();
    addMessage("assistant", result.answer, result);
    state.history.push(
      { role: "user", content: question },
      { role: "assistant", content: result.answer },
    );
    state.history = state.history.slice(-12);
  } catch (error) {
    if (
      generation !== state.generation ||
      chatGeneration !== state.chatGeneration
    )
      return;
    pending.remove();
    userMessage.remove();
    state.chatEntries.pop();
    $("chat-input").value = question;
    $("chat-error").textContent =
      error.message || "Could not get an answer. Please try again.";
    $("chat-error").hidden = false;
  } finally {
    if (
      generation === state.generation &&
      chatGeneration === state.chatGeneration
    ) {
      state.chatBusy = false;
      $("chat-input").disabled = false;
      $("send-button").disabled = false;
      renderSuggestions();
      $("chat-input").focus({ preventScroll: true });
    }
  }
}

function clearVideo() {
  const video = $("session-video");
  video.pause();
  video.removeAttribute("src");
  video.load();
  if (state.videoURL) URL.revokeObjectURL(state.videoURL);
  state.videoURL = null;
  state.videoFile = null;
  state.pendingResume = null;
  state.hasVideo = false;
  state.pendingSeek = null;
  $("video-status").textContent = "";
  $("video-container").hidden = true;
  $("video-empty").hidden = false;
  $("video-button").textContent = "+ Add video";
}

function setVideo(url, local) {
  if (
    !local &&
    !(typeof url === "string" && url.startsWith("/") && !url.startsWith("//"))
  )
    return;
  if (state.videoURL) URL.revokeObjectURL(state.videoURL);
  state.videoURL = local ? url : null;
  state.hasVideo = true;
  $("session-video").src = url;
  $("video-empty").hidden = true;
  $("video-container").hidden = false;
  $("video-button").textContent = "Change video";
  $("video-status").textContent = local
    ? "Local video · match it to this analysis for accurate timestamps."
    : "Session video · timestamps match the analyzed recording.";
  if (state.report) renderMoments();
}

function seekVideo(moment) {
  const video = $("session-video");
  const start = Math.max(0, number(moment.start_s));
  if (Number.isFinite(video.duration) && start >= video.duration) {
    $("video-status").textContent =
      "This moment falls outside the attached video. Choose the video used for this analysis.";
    state.pendingSeek = null;
    return;
  }
  video.currentTime = start;
  $("video-status").textContent =
    `${time(moment.start_s)}–${time(moment.end_s)} · ${moment.title}`;
  state.pendingSeek = null;
  video.play().catch(() => {
    /* Browser autoplay policy may require the play control. */
  });
}

function reviewMoment(moment) {
  $("playback").scrollIntoView({ behavior: "smooth", block: "start" });
  state.pendingSeek = moment;
  if (!state.hasVideo) {
    notice("Choose the video used for this analysis to review this moment.");
    $("video-file").click();
  } else if ($("session-video").readyState >= 1) seekVideo(moment);
}

function exportReport() {
  if (!state.report) return;
  const format = $("export-format").value;
  const report = state.report;
  const review = coachReview();
  const exported = {
    ...report,
    session_name: state.session.name,
    is_demo: Boolean(state.session.is_demo),
    completed_drill_ids: report.drills
      .filter((drill) => state.completed.has(drill.id))
      .map((drill) => drill.id),
  };
  if (review) exported.ai_review = review;
  let content;
  if (format === "json") content = JSON.stringify(exported, null, 2) + "\n";
  else {
    const lines = [
      "VANTAGE · COACHING REPORT",
      state.session.name,
      state.session.is_demo ? "SYNTHETIC SAMPLE — not a real session" : "",
      `Focus: ${state.focus}`,
      "",
      report.headline,
      report.summary,
      "",
      "SESSION MEASUREMENTS",
    ];
    report.metrics.forEach((metric) =>
      lines.push(
        `${metric.label}: ${metric.value ?? "—"} ${metric.unit || ""} — ${metric.detail || "Session estimate"}`,
      ),
    );
    lines.push("", "INSIGHTS");
    report.insights.forEach((insight) => {
      lines.push("", insight.title, insight.body);
      insight.evidence.forEach((item) =>
        lines.push(`  ${item.label}: ${item.value}`),
      );
    });
    lines.push("", "REVIEW MOMENTS");
    report.moments.forEach((moment) =>
      lines.push(
        `${time(moment.start_s)}–${time(moment.end_s)} · ${moment.title}`,
        moment.reason,
      ),
    );
    lines.push("", "PRACTICE PLAN");
    report.drills.forEach((drill) => {
      lines.push(
        "",
        `[${state.completed.has(drill.id) ? "x" : " "}] ${drill.title} · ${drill.minutes} minutes`,
        drill.why,
      );
      drill.steps.forEach((step, index) =>
        lines.push(`  ${index + 1}. ${step}`),
      );
      lines.push(`Aim for: ${drill.target}`);
    });
    if (review) lines.push(...coachReviewLines(review));
    lines.push(
      "",
      "EVIDENCE & LIMITATIONS",
      `${report.quality.label} · ${percent(report.quality.coverage)} ball observation coverage`,
      ...report.quality.warnings,
      "Session-level estimates across both sides; no identified player, verified technique, or official point/error attribution.",
    );
    content = lines.join("\n") + "\n";
  }
  const blob = new Blob([content], {
    type: format === "json" ? "application/json" : "text/plain;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const anchor = element("a");
  anchor.href = url;
  anchor.download = `vantage-coaching-${state.focus}.${format === "json" ? "json" : "txt"}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice(review
    ? "Coaching report exported with your practice checklist and AI coach review."
    : "Coaching report exported with your practice checklist.");
}

// AI video coach: a saved game's review from key-moment stills plus tracking
// estimates, and a chat that can attach the paused video moment. Every string
// from the server is untrusted and is rendered with textContent only.
function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
function records(value) {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}
function cleanText(value) {
  return typeof value === "string" ? value.trim() : "";
}
function validTime(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}
function mediaURL(value) {
  return typeof value === "string" && value.startsWith("/media/") && !value.includes("..") ? value : null;
}
function coachTime(value) {
  const tenths = Math.max(0, Math.round(number(value) * 10));
  const seconds = Math.floor(tenths / 10);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}.${tenths % 10}`;
}
function relativeTime(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return "";
  const seconds = (date.getTime() - Date.now()) / 1000;
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of [["year", 31536000], ["month", 2592000], ["week", 604800],
    ["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return "just now";
}
function readStorage(key) {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}
function writeStorage(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* Preferences are a convenience; coaching still works without storage. */
  }
}
function playerKey() {
  return `vantage.coach.player.${state.session.id}`;
}

function configureCoach(config) {
  coach.configured = isRecord(config);
  coach.engines = records(config?.engines).filter((engine) =>
    engine.available === true && typeof engine.id === "string" && cleanText(engine.label));
  coach.defaultEngine = typeof config?.default === "string" ? config.default : null;
  replace("ai-coach-engine-select", coach.engines.map((engine) => {
    const option = element("option", "", engine.detail ? `${engine.label} · ${engine.detail}` : engine.label);
    option.value = engine.id;
    return option;
  }));
}
function coachEngine() {
  if (!coach.defaultEngine) return null;
  const saved = readStorage(COACH_ENGINE_KEY);
  return coach.engines.find((engine) => engine.id === saved) ||
    coach.engines.find((engine) => engine.id === coach.defaultEngine) ||
    { id: coach.defaultEngine, label: "your AI coach" };
}
function coachSupported() {
  // Demo and imported games have no saved run (and so no video) on the server.
  return Boolean(state.session && /^[a-f0-9]{20}$/.test(state.session.id) && !state.session.is_temporary);
}
function currentCoachStatus() {
  return coach.status && state.session && coach.statusFor === state.session.id ? coach.status : null;
}
function coachRunning() {
  return COACH_RUNNING.has(currentCoachStatus()?.state);
}
function coachChatActive() {
  return coachSupported() && Boolean(coachEngine()) && currentCoachStatus()?.available === true;
}
function coachGameOpen() {
  return state.route?.kind === "game" && state.route.id === state.session?.id;
}
function coachReview() {
  const status = currentCoachStatus();
  if (!isRecord(status?.analysis)) return null;
  return {
    analysis: status.analysis,
    meta: isRecord(status.meta) ? status.meta : null,
    moments: coachMoments(status).map(({ id, time_s, start_s, end_s, kind, title }) =>
      ({ id, time_s, start_s, end_s, kind, title })),
  };
}
function coachMoments(status = currentCoachStatus()) {
  return records(status?.moments).filter((moment) =>
    typeof moment.id === "string" && validTime(moment.time_s));
}

function resetCoach() {
  coach.generation++;
  stopCoachPolling();
  coach.status = null;
  coach.statusFor = null;
  coach.error = "";
  coach.pollError = "";
  coach.actionBusy = false;
  coach.actionError = "";
  coach.cancelling = false;
  coach.editing = false;
  coach.formFor = null;
  coach.reviewKey = "";
}
function stopCoachPolling() {
  clearTimeout(coach.pollTimer);
  coach.pollTimer = null;
  clearInterval(coach.tickTimer);
  coach.tickTimer = null;
}
function scheduleCoachPoll(delay = COACH_POLL_MS) {
  clearTimeout(coach.pollTimer);
  coach.pollTimer = null;
  if (!coachRunning() || !coachGameOpen()) return;
  coach.pollTimer = setTimeout(() => {
    coach.pollTimer = null;
    if (coachRunning() && coachGameOpen()) void loadCoachStatus();
  }, delay);
}

// Re-render the coach card, and the chat only when its mode actually changes so
// polling never rebuilds buttons under the user's focus.
function updateCoach() {
  if (!state.session) return;
  renderCoach();
  if (chatModeKey() !== coach.chatMode) renderAIMode();
  applyAppLayout();
}

function acceptCoachStatus(status, seq) {
  if (!isRecord(status) || typeof status.state !== "string" ||
      (typeof status.session_id === "string" && status.session_id !== state.session?.id)) return false;
  // A response to an older request never overwrites a newer one.
  if (seq < coach.appliedSeq) return true;
  const wasRunning = coachRunning();
  coach.appliedSeq = seq;
  coach.status = status;
  coach.statusFor = state.session.id;
  coach.receivedAt = performance.now();
  coach.error = "";
  coach.pollError = "";
  if (!COACH_RUNNING.has(status.state)) coach.cancelling = false;
  if (wasRunning && status.state === "completed") notice("Your AI coach review is ready.");
  updateCoach();
  scheduleCoachPoll();
  return true;
}

async function loadCoachStatus() {
  if (!coachSupported()) return;
  const id = state.session.id;
  const generation = coach.generation;
  const seq = ++coach.seq;
  try {
    const status = await api(`/api/coach/${encodeURIComponent(id)}`);
    if (generation !== coach.generation) return;
    if (!acceptCoachStatus(status, seq))
      throw new Error("Vantage returned an unreadable coach status. Try again.");
  } catch (error) {
    if (generation !== coach.generation || seq < coach.appliedSeq) return;
    if (coachRunning() && error.status !== 404) {
      coach.pollError = "Lost touch with your coach. Reconnecting…";
      scheduleCoachPoll(4000);
    } else if (error.status === 404 || !currentCoachStatus()) {
      coach.status = null;
      coach.error = error.message || "Couldn't check your AI coach. Try again.";
    }
    updateCoach();
  }
}

async function startCoachAnalysis() {
  const engine = coachEngine();
  if (!currentCoachStatus() || !engine || coach.actionBusy || coachRunning()) return;
  const id = state.session.id;
  const generation = coach.generation;
  const seq = ++coach.seq;
  const force = coach.editing;
  const player = $("ai-coach-player").value.trim();
  writeStorage(playerKey(), player);
  coach.actionBusy = true;
  coach.actionError = "";
  updateCoach();
  const body = { engine: engine.id, force };
  if (player) body.player = player;
  try {
    const status = await api(`/api/coach/${encodeURIComponent(id)}/analyze`, body);
    if (generation !== coach.generation) return;
    coach.actionBusy = false;
    coach.editing = false;
    if (!acceptCoachStatus(status, seq))
      throw new Error("Vantage returned an unreadable coach status. Try again.");
    if (coachRunning()) $("ai-coach-running-title").focus({ preventScroll: true });
  } catch (error) {
    if (generation !== coach.generation) return;
    coach.actionBusy = false;
    coach.actionError = error.message || "Your coach couldn’t start. Try again.";
    updateCoach();
  }
}

async function cancelCoachAnalysis() {
  if (!coachRunning() || coach.cancelling) return;
  const id = state.session.id;
  const generation = coach.generation;
  const seq = ++coach.seq;
  coach.cancelling = true;
  coach.pollError = "";
  updateCoach();
  try {
    const status = await api(`/api/coach/${encodeURIComponent(id)}/cancel`, {});
    if (generation !== coach.generation) return;
    if (!acceptCoachStatus(status, seq))
      throw new Error("Vantage returned an unreadable coach status. Try again.");
    if (!$("ai-coach-start").hidden) $("ai-coach-analyze").focus({ preventScroll: true });
  } catch (error) {
    if (generation !== coach.generation) return;
    coach.cancelling = false;
    coach.pollError = error.message || "Couldn’t cancel the review. Try again.";
    updateCoach();
  }
}

function coachSetupCopy() {
  return ["Install and sign in to Claude Code (", ["code", "claude"], ") or Codex (", ["code", "codex"],
    "), or set ", ["code", "ANTHROPIC_API_KEY"], ", then restart Vantage to get video feedback on this game."]
    .map((part) => typeof part === "string" ? document.createTextNode(part) : element(part[0], "", part[1]));
}

function coachNote(status, engine, running, hasReview) {
  if (!coachSupported()) {
    return { compact: true, upload: true,
      copy: "AI video coaching works on saved games with video. Upload this game’s video to analyze it." };
  }
  // A running job or a saved review always shows, whatever else is unavailable.
  if (running || hasReview) return null;
  if (!coach.configured) {
    return { title: "AI coaching is unavailable",
      copy: "Couldn’t check which AI coach is available. Check that Vantage is running, then reload this page." };
  }
  if (!status && coach.error) return { title: "Your AI coach couldn’t load", copy: coach.error, retry: true };
  if (!status) return { loading: true, copy: "Checking for your AI coach…" };
  if (!engine) return { title: "Turn on AI video coaching", copy: coachSetupCopy() };
  if (status.available === false) {
    return { title: "The coach needs this game’s video", upload: true,
      copy: cleanText(status.reason) || "This game has no saved video for the coach to watch. Upload the video to analyze it." };
  }
  return null;
}

function renderCoach() {
  if (!state.session) return;
  const status = currentCoachStatus();
  const engine = coachEngine();
  const running = coachRunning();
  const hasReview = isRecord(status?.analysis);
  const note = coachNote(status, engine, running, hasReview);
  $("ai-coach").classList.toggle("is-compact", Boolean(note?.compact));
  $("ai-coach-note").hidden = !note;
  if (note) {
    $("ai-coach-note-title").textContent = note.title || "";
    $("ai-coach-note-title").hidden = !note.title;
    replace("ai-coach-note-copy", typeof note.copy === "string" ? [document.createTextNode(note.copy)] : note.copy);
    $("ai-coach-note").classList.toggle("is-loading", Boolean(note.loading));
    $("ai-coach-retry").hidden = !note.retry;
    $("ai-coach-upload").hidden = !note.upload;
  }

  const canAnalyze = Boolean(!note && status && engine && status.available !== false && !running);
  const failure = coach.actionError ||
    (status?.state === "failed" ? cleanText(status.error) || "Your coach couldn’t finish this review. Try again." : "");
  $("ai-coach-failure").textContent = failure;
  $("ai-coach-failure").hidden = !failure || Boolean(note) || running;

  const showStart = canAnalyze && (!hasReview || coach.editing);
  $("ai-coach-start").hidden = !showStart;
  if (showStart) {
    if (coach.formFor !== state.session.id) {
      $("ai-coach-player").value = readStorage(playerKey());
      coach.formFor = state.session.id;
    }
    $("ai-coach-engine-field").hidden = coach.engines.length < 2;
    $("ai-coach-engine-select").value = engine.id;
    $("ai-coach-start-title").textContent = coach.editing ? "Re-analyze this game" : "Get a coach’s eye on this game";
    $("ai-coach-start-copy").textContent = coach.editing
      ? "Tell your coach which player you are, or switch coaches, then run a fresh review."
      : "Your coach studies key moments from your video plus tracking data, then tells you what’s working and what to fix.";
    $("ai-coach-analyze").textContent = coach.actionBusy ? "Starting…"
      : coach.editing ? "Re-analyze" : status.state === "failed" ? "Try again" : "Analyze my game";
    $("ai-coach-analyze").disabled = coach.actionBusy;
    $("ai-coach-keep").hidden = !coach.editing;
    $("ai-coach-privacy").textContent = `Sends about 12 still frames and the measurements to ${engine.label}.`;
  }

  $("ai-coach-running").hidden = !running;
  if (running) {
    const stage = cleanText(status.stage) || COACH_STAGES[status.state];
    // Only touch the live region when the words change.
    if ($("ai-coach-stage").textContent !== stage) $("ai-coach-stage").textContent = stage;
    $("ai-coach-cancel").disabled = coach.cancelling;
    $("ai-coach-cancel").textContent = coach.cancelling ? "Cancelling…" : "Cancel";
    $("ai-coach-reconnect").textContent = coach.pollError;
    $("ai-coach-reconnect").hidden = !coach.pollError;
    renderCoachElapsed();
  }

  $("ai-coach-review").hidden = !hasReview || Boolean(note);
  if (hasReview) {
    const reanalyze = canAnalyze && !coach.editing;
    const key = JSON.stringify([state.session.id, status.analysis, status.meta, status.moments, reanalyze]);
    // Rebuild only on change: frames are served no-store and would refetch.
    if (key !== coach.reviewKey) {
      coach.reviewKey = key;
      renderCoachReview(status, reanalyze);
    }
  } else coach.reviewKey = "";

  renderGameCoachCard();
  const ticking = running && coachGameOpen();
  if (ticking && coach.tickTimer === null) coach.tickTimer = setInterval(renderCoachElapsed, 1000);
  else if (!ticking && coach.tickTimer !== null) {
    clearInterval(coach.tickTimer);
    coach.tickTimer = null;
  }
}

function renderCoachElapsed() {
  const status = currentCoachStatus();
  if (!COACH_RUNNING.has(status?.state)) return;
  const elapsed = number(status.elapsed_s) + (performance.now() - coach.receivedAt) / 1000;
  $("ai-coach-elapsed").textContent = `${time(elapsed)} elapsed`;
}

function renderGameCoachCard() {
  const status = currentCoachStatus();
  const ready = coachSupported() && isRecord(status?.analysis);
  const ai = coachSupported() && Boolean(coachEngine()) && status?.available !== false;
  $("game-coach-title").textContent = ready ? "Your AI coach review is ready."
    : ai ? "Get AI feedback on this game" : "Make this game count.";
  $("game-coach-copy").textContent = ready
    ? "See what’s working, what to fix next, and which moments to rewatch."
    : ai ? "Your AI coach reviews key moments from the video and answers your questions."
      : "Review the moments behind the numbers and take a focused plan into your next session.";
}

// Seek with a short lead-in so the player sees the moment build up.
function playCoachMoment(moment) {
  const at = number(moment.time_s);
  const start = validTime(moment.start_s) ? Math.min(moment.start_s, at) : at;
  const end = validTime(moment.end_s) ? Math.max(moment.end_s, at) : at;
  reviewMoment({
    start_s: Math.max(0, start - COACH_LEAD_IN_S),
    end_s: end,
    title: moment.title || `Coach moment at ${coachTime(at)}`,
  });
}

function coachChip(moment, label = coachTime(moment.time_s)) {
  const button = element("button", "ai-chip");
  button.type = "button";
  const icon = element("span", "ai-chip-icon", "▶");
  icon.setAttribute("aria-hidden", "true");
  button.append(icon, document.createTextNode(label));
  button.setAttribute("aria-label", `Play ${moment.title || "this moment"} at ${coachTime(moment.time_s)}`);
  button.addEventListener("click", () => playCoachMoment(moment));
  return button;
}

function coachFrame(moment) {
  const frame = element("span", "ai-thumb-frame");
  const url = mediaURL(moment.frame_url);
  if (url) {
    const image = element("img");
    image.src = url;
    image.alt = `Video stills at ${coachTime(moment.time_s)}`;
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => image.remove(), { once: true });
    frame.append(image);
  }
  const stamp = element("span", "ai-thumb-time", coachTime(moment.time_s));
  stamp.setAttribute("aria-hidden", "true");
  frame.append(stamp);
  return frame;
}

function coachThumb(moment) {
  const button = element("button", "ai-thumb");
  button.type = "button";
  button.append(coachFrame(moment));
  button.setAttribute("aria-label", `Play ${moment.title || "this moment"} at ${coachTime(moment.time_s)}`);
  button.addEventListener("click", () => playCoachMoment(moment));
  return button;
}

// Resolve an item's cited moments and loose timestamps, dropping near-duplicates.
function coachReferences(item, moments, title) {
  const cited = [];
  for (const id of Array.isArray(item.moment_ids) ? item.moment_ids : []) {
    const moment = moments.find((candidate) => candidate.id === id);
    if (moment && !cited.includes(moment)) cited.push(moment);
  }
  const times = [];
  for (const value of Array.isArray(item.time_s) ? item.time_s : []) {
    if (validTime(value) && ![...cited.map((moment) => moment.time_s), ...times.map((entry) => entry.time_s)]
      .some((other) => Math.abs(other - value) < 0.5)) times.push({ time_s: value, title });
  }
  return { cited, times };
}

function coachEvidence(item, moments, title, thumbnails) {
  const { cited, times } = coachReferences(item, moments, title);
  const pictured = thumbnails ? cited.filter((moment) => mediaURL(moment.frame_url)).slice(0, 3) : [];
  const chips = [...cited.filter((moment) => !pictured.includes(moment)), ...times];
  if (!pictured.length && !chips.length) return null;
  const evidence = element("div", "ai-evidence");
  pictured.forEach((moment) => evidence.append(coachThumb(moment)));
  if (chips.length) {
    const row = element("div", "ai-chips");
    chips.forEach((moment) => row.append(coachChip(moment)));
    evidence.append(row);
  }
  return evidence;
}

// High priority first; the coach's own order breaks ties.
function coachImprovements(analysis) {
  const rank = (item) => {
    const index = PRIORITIES.indexOf(item.priority);
    return index === -1 ? 1 : index;
  };
  return records(analysis.improvements)
    .filter((item) => cleanText(item.title))
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index)
    .map(({ item }) => item);
}

function reviewBlock(title) {
  const block = element("section", "ai-review-block");
  block.append(element("h3", "", title));
  return block;
}

function renderCoachReview(status, reanalyze) {
  const analysis = status.analysis;
  const moments = coachMoments(status);
  const nodes = [];
  const head = element("div", "ai-review-head");
  const headline = element("h2", "ai-review-headline", cleanText(analysis.headline) || "Your AI coach review");
  headline.id = "ai-review-headline";
  headline.tabIndex = -1;
  head.append(headline);
  if (cleanText(analysis.summary)) head.append(element("p", "ai-review-summary", analysis.summary));
  nodes.push(head);

  const players = records(analysis.players).filter((player) => cleanText(player.label) || cleanText(player.description));
  if (players.length) {
    const list = element("ul", "ai-players");
    list.setAttribute("aria-label", "Players your coach reviewed");
    players.forEach((player) => {
      const item = element("li", player.is_user === true ? "ai-player is-user" : "ai-player");
      const heading = element("div", "ai-player-head");
      if (player.side === "near" || player.side === "far") heading.append(element("span", "ai-tag", `${player.side} side`));
      heading.append(element("strong", "", cleanText(player.label) || "Player"));
      if (player.is_user === true) heading.append(element("span", "ai-tag ai-tag-you", "You"));
      item.append(heading);
      if (cleanText(player.description)) item.append(element("p", "", player.description));
      list.append(item);
    });
    nodes.push(list);
  }

  const strengths = records(analysis.strengths).filter((strength) => cleanText(strength.title));
  if (strengths.length) {
    const block = reviewBlock("What’s working");
    const list = element("ul", "ai-strengths");
    strengths.forEach((strength) => {
      const item = element("li", "ai-strength");
      const mark = element("span", "ai-check", "✓");
      mark.setAttribute("aria-hidden", "true");
      const body = element("div");
      body.append(element("strong", "", strength.title));
      if (cleanText(strength.detail)) body.append(element("p", "", strength.detail));
      const evidence = coachEvidence(strength, moments, strength.title, false);
      if (evidence) body.append(evidence);
      item.append(mark, body);
      list.append(item);
    });
    block.append(list);
    nodes.push(block);
  }

  const improvements = coachImprovements(analysis);
  if (improvements.length) {
    const block = reviewBlock("Work on next");
    const list = element("ol", "ai-improvements");
    improvements.forEach((item) => {
      const priority = PRIORITIES.includes(item.priority) ? item.priority : "medium";
      const card = element("li", "ai-improvement");
      card.dataset.priority = priority;
      card.append(element("span", `ai-priority ai-priority-${priority}`, `${priority} priority`));
      card.append(element("h4", "", item.title));
      if (cleanText(item.observation)) card.append(element("p", "ai-observation", item.observation));
      const points = element("dl", "ai-points");
      for (const [label, value] of [["Why it matters", item.why_it_matters], ["How to fix", item.how_to_fix]]) {
        if (!cleanText(value)) continue;
        const group = element("div");
        group.append(element("dt", "", label), element("dd", "", value));
        points.append(group);
      }
      if (points.childElementCount) card.append(points);
      const drill = isRecord(item.drill) ? item.drill : {};
      if (cleanText(drill.name) || cleanText(drill.instructions)) {
        const box = element("div", "ai-drill");
        box.append(element("span", "small-label", "Drill"));
        if (cleanText(drill.name)) box.append(element("strong", "", drill.name));
        if (cleanText(drill.instructions)) box.append(element("p", "", drill.instructions));
        if (cleanText(drill.target)) box.append(element("p", "ai-drill-target", `Target: ${drill.target}`));
        card.append(box);
      }
      const evidence = coachEvidence(item, moments, item.title, true);
      if (evidence) card.append(evidence);
      list.append(card);
    });
    block.append(list);
    nodes.push(block);
  }

  if (moments.length) {
    const notes = new Map(records(analysis.moment_notes)
      .filter((note) => typeof note.moment_id === "string" && cleanText(note.note))
      .map((note) => [note.moment_id, note.note]));
    const block = reviewBlock("Key moments");
    block.append(element("p", "ai-review-hint", "Stills your coach studied. Select one to play it in the video."));
    const list = element("ul", "ai-moments");
    moments.forEach((moment) => {
      const item = element("li");
      const button = element("button", "ai-moment");
      button.type = "button";
      const copy = element("span", "ai-moment-copy");
      const kind = MOMENT_KINDS[moment.kind];
      copy.append(element("span", "ai-moment-meta", kind ? `${coachTime(moment.time_s)} · ${kind}` : coachTime(moment.time_s)));
      copy.append(element("strong", "", cleanText(moment.title) || "Key moment"));
      if (notes.has(moment.id)) copy.append(element("span", "ai-moment-note", notes.get(moment.id)));
      button.append(coachFrame(moment), copy);
      button.addEventListener("click", () => playCoachMoment(moment));
      item.append(button);
      list.append(item);
    });
    block.append(list);
    nodes.push(block);
  }

  if (cleanText(analysis.next_focus)) {
    const focus = element("div", "ai-focus");
    focus.append(element("span", "small-label", "Next session focus"), element("p", "", analysis.next_focus));
    nodes.push(focus);
  }
  if (cleanText(analysis.limitations)) nodes.push(element("p", "ai-limitations", analysis.limitations));

  const meta = isRecord(status.meta) ? status.meta : {};
  const footer = element("div", "ai-review-footer");
  footer.append(element("span", "", [
    `Reviewed by ${cleanText(meta.engine_label) || "your AI coach"}`,
    cleanText(meta.model), relativeTime(meta.created_at),
  ].filter(Boolean).join(" · ")));
  if (reanalyze) {
    const button = element("button", "button button-secondary button-small", "Re-analyze");
    button.type = "button";
    button.addEventListener("click", () => {
      coach.editing = true;
      coach.actionError = "";
      updateCoach();
      $("ai-coach-player").focus();
    });
    footer.append(button);
  }
  nodes.push(footer);
  replace("ai-coach-review", nodes);
}

function coachReviewLines(review) {
  const { analysis, meta, moments } = review;
  const lines = ["", "AI COACH REVIEW"];
  const reviewer = [cleanText(meta?.engine_label), cleanText(meta?.model)].filter(Boolean).join(" · ");
  const created = new Date(meta?.created_at);
  const date = Number.isFinite(created.getTime())
    ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(created) : "";
  lines.push(`Reviewed by ${reviewer || "AI coach"}${date ? ` on ${date}` : ""} · from sampled video stills and tracking estimates`);
  for (const value of [analysis.headline, analysis.summary]) if (cleanText(value)) lines.push(cleanText(value));
  const times = (item) => {
    const { cited, times: loose } = coachReferences(item, moments, "");
    const all = [...cited, ...loose].map((entry) => entry.time_s).sort((a, b) => a - b).map(coachTime);
    return all.length ? all.join(", ") : "";
  };
  const players = records(analysis.players).filter((player) => cleanText(player.label));
  if (players.length) {
    lines.push("", "Players: " + players.map((player) =>
      `${player.side === "near" || player.side === "far" ? `${player.side} side · ` : ""}${cleanText(player.label)}${player.is_user === true ? " (you)" : ""}`,
    ).join("; "));
  }
  const strengths = records(analysis.strengths).filter((strength) => cleanText(strength.title));
  if (strengths.length) {
    lines.push("", "What's working");
    strengths.forEach((strength) => {
      const at = times(strength);
      lines.push(`- ${cleanText(strength.title)}${cleanText(strength.detail) ? `: ${cleanText(strength.detail)}` : ""}${at ? ` (${at})` : ""}`);
    });
  }
  const improvements = coachImprovements(analysis);
  if (improvements.length) {
    lines.push("", "Work on next");
    improvements.forEach((item, index) => {
      const priority = PRIORITIES.includes(item.priority) ? item.priority.toUpperCase() : "MEDIUM";
      lines.push(`${index + 1}. [${priority}] ${cleanText(item.title)}`);
      if (cleanText(item.observation)) lines.push(`   ${cleanText(item.observation)}`);
      if (cleanText(item.why_it_matters)) lines.push(`   Why it matters: ${cleanText(item.why_it_matters)}`);
      if (cleanText(item.how_to_fix)) lines.push(`   How to fix: ${cleanText(item.how_to_fix)}`);
      const drill = isRecord(item.drill) ? item.drill : {};
      if (cleanText(drill.name) || cleanText(drill.instructions)) {
        lines.push(`   Drill: ${[cleanText(drill.name), cleanText(drill.instructions)].filter(Boolean).join(" — ")}`);
      }
      if (cleanText(drill.target)) lines.push(`   Target: ${cleanText(drill.target)}`);
      const at = times(item);
      if (at) lines.push(`   Review at: ${at}`);
    });
  }
  if (cleanText(analysis.next_focus)) lines.push("", `Next session focus: ${cleanText(analysis.next_focus)}`);
  if (cleanText(analysis.limitations)) lines.push(`Limitations: ${cleanText(analysis.limitations)}`);
  return lines;
}

// Chat in AI mode: the answer may cite moments, loose times, and frames the
// server extracted for this question.
function currentVideoMoment() {
  const video = $("session-video");
  if (!state.hasVideo || video.readyState < 1) return null;
  const at = Math.round(video.currentTime * 10) / 10;
  const duration = state.session?.stats?.video?.duration_s;
  if (!Number.isFinite(at) || at <= 0 || (validTime(duration) && at > duration)) return null;
  return at;
}

function renderMomentControls() {
  if (!coachChatActive()) return;
  const at = currentVideoMoment();
  const label = at === null ? "" : `· ${coachTime(at)}`;
  if ($("coach-moment-time").textContent !== label) $("coach-moment-time").textContent = label;
  $("coach-ask-moment").disabled = state.chatBusy || at === null;
}

function coachChatResult(result, engine) {
  const moments = coachMoments();
  const frames = records(result.frames)
    .filter((frame) => validTime(frame.time_s) && mediaURL(frame.frame_url))
    .slice(0, 4)
    .map((frame) => ({
      id: cleanText(frame.id), time_s: frame.time_s, frame_url: frame.frame_url,
      title: `Frames around ${coachTime(frame.time_s)}`,
    }));
  const known = [...moments, ...frames.filter((frame) => frame.id)];
  const { cited, times } = coachReferences(result, known, "Moment your coach mentioned");
  const chips = [...cited, ...times]
    .filter((moment) => !frames.some((frame) => Math.abs(frame.time_s - moment.time_s) < 0.5))
    .map(({ time_s, start_s, end_s, title }) => ({ time_s, start_s, end_s, title }))
    .sort((a, b) => a.time_s - b.time_s);
  return {
    source: "ai-coach",
    engine_label: cleanText(result.engine_label) || engine?.label || "AI",
    chips,
    frames,
    follow_ups: (Array.isArray(result.follow_ups) ? result.follow_ups : [])
      .map(cleanText).filter(Boolean).slice(0, 3),
  };
}

function appendCoachExtras(message, role, result) {
  if (role === "user") {
    if (validTime(result.at_s)) {
      const row = element("div", "ai-chips");
      row.append(coachChip({ time_s: result.at_s, title: "The moment you asked about" }, `Asked at ${coachTime(result.at_s)}`));
      message.append(row);
    }
    return;
  }
  if (result.frames?.length) {
    const frames = element("div", "ai-frames");
    result.frames.forEach((frame) => frames.append(coachThumb(frame)));
    message.append(frames);
  }
  if (result.chips?.length) {
    const row = element("div", "ai-chips");
    result.chips.forEach((moment) => row.append(coachChip(moment)));
    message.append(row);
  }
  if (result.follow_ups?.length) {
    // Only the latest answer offers follow-ups.
    $("chat-log").querySelectorAll(".ai-follow-ups").forEach((node) => node.remove());
    const group = element("div", "ai-follow-ups");
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Suggested follow-up questions");
    result.follow_ups.forEach((question) => {
      const button = element("button", "ai-follow-up", question);
      button.type = "button";
      button.disabled = state.chatBusy;
      button.addEventListener("click", () => {
        $("chat-input").value = question;
        submitQuestion(question);
      });
      group.append(button);
    });
    message.append(group);
  }
}

function coachPendingMessage() {
  const node = element("div", "pending-message ai-pending");
  const ring = element("span", "loading-ring");
  ring.setAttribute("aria-hidden", "true");
  const clock = element("span", "ai-pending-time", "0s");
  // The ticking clock stays out of the chat's live region.
  clock.setAttribute("aria-hidden", "true");
  node.append(ring, element("span", "", "Coach is watching the video…"), clock);
  const started = Date.now();
  const timer = setInterval(() => {
    if (!node.isConnected) clearInterval(timer);
    else clock.textContent = `${Math.floor((Date.now() - started) / 1000)}s`;
  }, 1000);
  return { node, stop: () => clearInterval(timer) };
}

async function submitCoachQuestion(raw, { moment = false } = {}) {
  const question = raw.trim();
  if (!question || !state.session || state.chatBusy) return;
  if (question.length > 2000) {
    $("chat-error").textContent = "Keep your question under 2,000 characters.";
    $("chat-error").hidden = false;
    return;
  }
  const atS = moment || $("coach-include-moment").checked ? currentVideoMoment() : null;
  if (moment && atS === null) {
    notice("Play or pause the video at the moment you want feedback on.");
    return;
  }
  const sessionId = state.session.id;
  const engine = coachEngine();
  const generation = state.generation;
  const chatGeneration = ++state.chatGeneration;
  const stale = () => generation !== state.generation || chatGeneration !== state.chatGeneration;
  state.chatBusy = true;
  $("chat-error").hidden = true;
  $("chat-input").value = "";
  $("chat-input").disabled = true;
  $("send-button").disabled = true;
  renderSuggestions();
  const userMessage = addMessage("user", question, atS === null ? undefined : { source: "ai-coach", at_s: atS });
  const pending = coachPendingMessage();
  $("chat-log").append(pending.node);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  const body = {
    message: question,
    history: state.history.slice(-12).map((item) => ({
      role: item.role,
      content: item.content.slice(0, 2000),
    })),
  };
  if (engine) body.engine = engine.id;
  const player = readStorage(playerKey()).trim();
  if (player) body.player = player;
  if (atS !== null) body.at_s = atS;
  try {
    const result = await api(`/api/coach/${encodeURIComponent(sessionId)}/chat`, body, { timeoutMs: 210_000 });
    if (stale()) return;
    const answer = cleanText(result?.answer);
    if (!answer) throw new Error("The coach returned an empty response. Try again.");
    pending.node.remove();
    addMessage("assistant", answer, coachChatResult(result, engine));
    state.history.push(
      { role: "user", content: question },
      { role: "assistant", content: answer },
    );
    state.history = state.history.slice(-12);
  } catch (error) {
    if (stale()) return;
    pending.node.remove();
    userMessage.remove();
    state.chatEntries.pop();
    $("chat-input").value = question;
    $("chat-error").textContent =
      error.message || "Your coach couldn’t answer. Please try again.";
    $("chat-error").hidden = false;
  } finally {
    pending.stop();
    if (!stale()) {
      state.chatBusy = false;
      $("chat-input").disabled = false;
      $("send-button").disabled = false;
      renderSuggestions();
      $("chat-input").focus({ preventScroll: true });
    }
  }
}

$("sample-button").addEventListener("click", () => navigate("/games/sample"));
$("import-button").addEventListener("click", () => $("stats-file").click());
$("stats-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  showError("");
  try {
    if (file.size > 2_000_000) throw new Error("Import a stats.json file smaller than 2 MB.");
    let stats;
    try { stats = JSON.parse(await file.text()); }
    catch { throw new Error("This file isn't valid JSON. Choose stats.json from a completed Vantage analysis."); }
    const session = await api("/api/session", { stats,
      name: file.name.replace(/\.json$/i, "") || "Imported game" });
    session.is_temporary = true;
    state.temporarySessions.set(session.id, session);
    renderLibrary();
    await navigate(gamePath(session.id));
    notice("Analysis imported. This game is available until you reload the page.");
  } catch (error) { showError(error.message || "Could not import this analysis."); }
});
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-route]");
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin) return;
  event.preventDefault();
  void navigate(url.pathname);
});
window.addEventListener("popstate", () => { void applyRoute(); });
$("coaching-retry").addEventListener("click", () => { void loadReport(); });
document
  .querySelectorAll("[data-focus]")
  .forEach((button) =>
    button.addEventListener("click", () => setFocus(button.dataset.focus)),
  );
$("export-button").addEventListener("click", exportReport);
$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitQuestion($("chat-input").value);
});
$("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submitQuestion(event.target.value);
  }
});
$("use-ai").addEventListener("change", renderAIMode);
$("coach-ask-moment").addEventListener("click", () => {
  submitQuestion("What should I improve in this moment?", { moment: true });
});
$("ai-coach-start").addEventListener("submit", (event) => {
  event.preventDefault();
  void startCoachAnalysis();
});
$("ai-coach-player").addEventListener("input", (event) => {
  if (state.session) writeStorage(playerKey(), event.target.value.trim());
});
$("ai-coach-engine-select").addEventListener("change", (event) => {
  writeStorage(COACH_ENGINE_KEY, event.target.value);
  updateCoach();
});
$("ai-coach-keep").addEventListener("click", () => {
  coach.editing = false;
  coach.actionError = "";
  updateCoach();
  $("ai-review-headline")?.focus({ preventScroll: true });
});
$("ai-coach-cancel").addEventListener("click", () => { void cancelCoachAnalysis(); });
$("ai-coach-retry").addEventListener("click", () => {
  coach.error = "";
  updateCoach();
  void loadCoachStatus();
});
$("ai-coach-upload").addEventListener("click", () => openAnalysisPanel());
for (const type of ["loadedmetadata", "timeupdate", "seeked", "emptied"]) {
  $("session-video").addEventListener(type, renderMomentControls);
}
$("video-button").addEventListener("click", () => $("video-file").click());
$("video-attach-trigger").addEventListener("click", () =>
  $("video-file").click(),
);
$("video-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  if (
    !file.type.startsWith("video/") &&
    !/\.(mp4|mov|m4v|webm|ogg)$/i.test(file.name)
  ) {
    notice("Choose a video file, such as MP4, MOV, or WebM.");
    return;
  }
  state.videoFile = file;
  setVideo(URL.createObjectURL(file), true);
});
$("session-video").addEventListener("loadedmetadata", () => {
  if (state.pendingResume?.id === state.session?.id) {
    const video = $("session-video");
    if (state.pendingResume.time < video.duration) video.currentTime = state.pendingResume.time;
    state.pendingResume = null;
  }
  if (state.pendingSeek) seekVideo(state.pendingSeek);
  else
    $("video-status").textContent = state.videoURL
      ? "Local video · match it to this analysis for accurate timestamps."
      : "Session video · timestamps match the analyzed recording.";
});
$("session-video").addEventListener("loadstart", () => {
  if (state.hasVideo)
    $("video-status").textContent = "Preparing video for playback…";
});
$("session-video").addEventListener("error", () => {
  if (!state.hasVideo) return;
  $("video-status").textContent =
    "Could not prepare or play this video. Attach an H.264 MP4 version of the matching recording.";
});
window.addEventListener("beforeunload", () => {
  if (state.videoURL) URL.revokeObjectURL(state.videoURL);
});

document
  .querySelector('.quality-card a[href="#evidence-title"]')
  .addEventListener("click", () => {
    $("evidence-title").closest("details").open = true;
  });

// Video analysis is independent from the session being reviewed. The local server
// owns jobs; this client keeps only the current job ID so reloads can reconnect.
const ANALYSIS_STORAGE_KEY = "vantage.analysis.job.v1";
const CORNER_NAMES = ["near-left", "near-right", "far-right", "far-left"];
const TERMINAL_ANALYSIS_STATES = new Set(["completed", "failed", "cancelled"]);
const analysis = {
  available: false,
  configLoaded: false,
  configError: "Checking the local analyzer…",
  maxBytes: 536870912,
  maxDuration: 1200,
  job: null,
  uploading: false,
  uploadName: "",
  uploadProgress: null,
  xhr: null,
  generation: 0,
  pollTimer: null,
  pollingGeneration: null,
  actionBusy: false,
  cancelling: false,
  corners: [null, null, null, null],
  previewId: null,
  previewReady: false,
  error: "",
  connectionError: false,
  dismissed: false,
  openingResult: false,
};

function rememberAnalysisJob(id) {
  try {
    if (id) localStorage.setItem(ANALYSIS_STORAGE_KEY, id);
    else localStorage.removeItem(ANALYSIS_STORAGE_KEY);
  } catch {
    /* Jobs still run if browser storage is unavailable. */
  }
}
function analysisTerminal(job = analysis.job) {
  return Boolean(job && TERMINAL_ANALYSIS_STATES.has(job.status));
}
function invalidateAnalysisRequests() {
  analysis.generation++;
  analysis.pollingGeneration = null;
  clearTimeout(analysis.pollTimer);
}
function configureAnalysis(config) {
  analysis.configLoaded = true;
  analysis.available = Boolean(config.analysis_available);
  analysis.maxBytes = Number.isFinite(config.max_upload_bytes)
    ? config.max_upload_bytes
    : 536870912;
  analysis.maxDuration = Number.isFinite(config.max_duration_s)
    ? config.max_duration_s
    : 1200;
  analysis.configError = analysis.available
    ? ""
    : config.analysis_error ||
      "Video analysis is unavailable. Restart the local app with the trained detector installed.";
  $("analysis-file-limits").textContent =
    `MP4, MOV, M4V, WebM or AVI · up to ${Math.round(analysis.maxBytes / 1024 / 1024)} MB · ${Math.round(analysis.maxDuration / 60)} minutes`;
  renderAnalysis();
}
function analysisStageLabel(job = analysis.job) {
  if (analysis.uploading) return "Uploading video";
  if (analysis.cancelling) return "Cancelling analysis…";
  const labels = {
    preparing: "Preparing your video",
    awaiting_calibration: "Ready to mark the court",
    queued: "Waiting for the analyzer",
    analyzing: "Analyzing your game",
    rendering: "Creating your annotated replay",
    completed: "Your coaching review is ready",
    failed: "Analysis could not finish",
    cancelled: "Analysis cancelled",
  };
  return labels[job?.status] || "Video analysis";
}
function renderAnalysis() {
  const job = analysis.job;
  const terminal = analysisTerminal();
  const calibrating = job?.status === "awaiting_calibration";
  const processing =
    analysis.uploading || Boolean(job && !terminal && !calibrating);
  $("analysis-upload-panel").hidden = Boolean(job) || analysis.uploading;
  $("analysis-progress-panel").hidden = !processing;
  $("analysis-calibration-panel").hidden = !calibrating;
  $("analysis-result-panel").hidden = !terminal;
  $("analysis-choose-file").disabled =
    !analysis.available || analysis.uploading;
  $("analysis-file").disabled = !analysis.available || analysis.uploading;
  const error =
    analysis.error || (!job && !analysis.uploading ? analysis.configError : "");
  $("analysis-error").textContent = error;
  $("analysis-error").hidden = !error;
  $("analysis-retry").hidden = !analysis.connectionError;
  $("analysis-retry").disabled = analysis.actionBusy;
  const activeStep =
    analysis.uploading || !job || job.status === "preparing"
      ? "upload"
      : calibrating
        ? "court"
        : "results";
  document.querySelectorAll("[data-analysis-step]").forEach((node) => {
    node.toggleAttribute(
      "data-active",
      node.dataset.analysisStep === activeStep,
    );
    if (node.dataset.analysisStep === activeStep)
      node.setAttribute("aria-current", "step");
    else node.removeAttribute("aria-current");
  });
  $("analysis-job-stage").textContent = analysisStageLabel();
  $("analysis-job-name").textContent = analysis.uploading
    ? analysis.uploadName
    : job?.name || "";
  let progress = analysis.uploading ? analysis.uploadProgress : job?.progress;
  if (typeof progress === "number" && Number.isFinite(progress)) {
    progress = Math.max(0, Math.min(1, progress));
    $("analysis-progress").value = progress;
    $("analysis-job-percent").textContent = percent(progress);
  } else {
    $("analysis-progress").removeAttribute("value");
    $("analysis-job-percent").textContent = "";
  }
  const frames =
    job?.total_frames > 0
      ? `${Number(job.frames_done || 0).toLocaleString()} / ${Number(job.total_frames).toLocaleString()} frames`
      : "";
  $("analysis-job-detail").textContent = analysis.uploading
    ? "Keep this tab open until the upload finishes."
    : [job?.stage, frames].filter(Boolean).join(" · ");
  $("analysis-cancel").hidden = !analysis.uploading && (!job || terminal);
  $("analysis-cancel").textContent = analysis.uploading
    ? "Cancel upload"
    : "Cancel analysis";
  $("analysis-cancel").disabled = analysis.actionBusy || analysis.cancelling;
  $("analysis-background-note").textContent = analysis.uploading
    ? "Your video is being copied to the local analyzer. Keep this tab open."
    : job && !terminal
      ? "You can hide this panel. Processing continues while the local app is running."
      : "Processing stays on this computer. No AI account is needed to analyze a video.";
  if (terminal) {
    $("analysis-result-title").textContent = analysisStageLabel();
    $("analysis-result-copy").textContent =
      job.status === "completed"
        ? "Open the annotated replay, review the measured evidence, and choose your next practice focus."
        : job.status === "failed"
          ? job.error ||
            "Try a shorter, fixed-camera recording with a clearly visible court."
          : "This job has stopped. You can choose another video when you’re ready.";
  }
  $("analysis-view-results").hidden = job?.status !== "completed";
  $("analysis-view-results").disabled = analysis.openingResult;
  $("analysis-another").disabled = analysis.openingResult;
  $("analysis-banner").hidden =
    analysis.dismissed || (!job && !analysis.uploading);
  $("analysis-banner-title").textContent = analysisStageLabel();
  $("analysis-banner-copy").textContent = analysis.uploading
    ? analysis.uploadName
    : job?.name || "";
  $("analysis-banner-open").textContent =
    job?.status === "completed"
      ? "View results"
      : calibrating
        ? "Mark court"
        : terminal
          ? "Review status"
          : "View progress";
  renderCalibration();
}
function resetAnalysis() {
  invalidateAnalysisRequests();
  analysis.job = null;
  analysis.uploading = false;
  analysis.uploadProgress = null;
  analysis.error = "";
  analysis.connectionError = false;
  analysis.actionBusy = false;
  analysis.cancelling = false;
  analysis.dismissed = false;
  analysis.previewId = null;
  analysis.previewReady = false;
  analysis.corners = [null, null, null, null];
  $("analysis-synthetic").checked = false;
  rememberAnalysisJob(null);
  renderAnalysis();
}
function openAnalysisPanel() {
  if (analysis.dismissed && analysisTerminal()) resetAnalysis();
  if (!$("analysis-dialog").open) $("analysis-dialog").showModal();
  renderAnalysis();
}
function acceptAnalysisJob(job, autoOpen = true) {
  if (!job || typeof job.id !== "string" || typeof job.status !== "string")
    throw new Error(
      "The analyzer returned an unreadable job. Please reconnect.",
    );
  analysis.job = job;
  analysis.error = "";
  analysis.connectionError = false;
  if (analysisTerminal(job)) analysis.cancelling = false;
  rememberAnalysisJob(job.id);
  if (job.status === "awaiting_calibration" && analysis.previewId !== job.id) {
    analysis.previewId = job.id;
    analysis.previewReady = false;
    analysis.corners = [null, null, null, null];
    for (let index = 0; index < 4; index++) {
      $("corner-" + index + "-x").value = "";
      $("corner-" + index + "-y").value = "";
      $("corner-" + index + "-x").max = String(job.video.width - 1);
      $("corner-" + index + "-y").max = String(job.video.height - 1);
    }
    $("analysis-preview").src =
      `/api/analysis/${encodeURIComponent(job.id)}/preview`;
  }
  renderAnalysis();
  if (job.status === "completed" && autoOpen && $("analysis-dialog").open) {
    void openCompletedAnalysis();
  } else if (!analysisTerminal(job) && job.status !== "awaiting_calibration") {
    scheduleAnalysisPoll();
  }
}
function scheduleAnalysisPoll(delay = 1200) {
  clearTimeout(analysis.pollTimer);
  analysis.pollTimer = setTimeout(pollAnalysisJob, delay);
}
async function pollAnalysisJob() {
  const id = analysis.job?.id;
  const generation = analysis.generation;
  if (!id || analysis.pollingGeneration === generation) return;
  analysis.pollingGeneration = generation;
  try {
    const job = await api(`/api/analysis/${encodeURIComponent(id)}`);
    if (generation !== analysis.generation || analysis.job?.id !== id) return;
    acceptAnalysisJob(job);
  } catch (error) {
    if (generation !== analysis.generation || analysis.job?.id !== id) return;
    if (error.status === 404) {
      analysis.job = null;
      analysis.error =
        "This analysis job is no longer available. Completed sessions remain in Your sessions; upload the video again if it did not finish.";
      analysis.connectionError = false;
      rememberAnalysisJob(null);
    } else {
      analysis.error =
        "Connection to the local analyzer was interrupted. Reconnecting…";
      analysis.connectionError = true;
      scheduleAnalysisPoll(3000);
    }
    renderAnalysis();
  } finally {
    if (analysis.pollingGeneration === generation)
      analysis.pollingGeneration = null;
  }
}
async function restoreAnalysisJob() {
  let id;
  try {
    id = localStorage.getItem(ANALYSIS_STORAGE_KEY);
  } catch {
    return;
  }
  if (
    !id ||
    !/^[a-zA-Z0-9_-]{1,100}$/.test(id) ||
    analysis.job ||
    analysis.uploading
  )
    return;
  analysis.job = {
    id,
    name: "Previous video analysis",
    status: "preparing",
    stage: "Reconnecting",
    progress: null,
  };
  renderAnalysis();
  await pollAnalysisJob();
}
async function uploadAnalysisVideo(file) {
  if (!file || analysis.uploading || (analysis.job && !analysisTerminal()))
    return;
  if (!analysis.available) {
    openAnalysisPanel();
    return;
  }
  resetAnalysis();
  openAnalysisPanel();
  if (!/\.(mp4|mov|m4v|webm|avi)$/i.test(file.name)) {
    analysis.error = "Choose an MP4, MOV, M4V, WebM or AVI video.";
    renderAnalysis();
    return;
  }
  if (!file.size || file.size > analysis.maxBytes) {
    analysis.error = `Choose a non-empty video smaller than ${Math.round(analysis.maxBytes / 1024 / 1024)} MB.`;
    renderAnalysis();
    return;
  }
  const generation = analysis.generation;
  analysis.uploading = true;
  analysis.uploadName = file.name;
  renderAnalysis();
  try {
    const job = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      analysis.xhr = xhr;
      xhr.open("POST", `/api/analysis?name=${encodeURIComponent(file.name)}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.setRequestHeader("Accept", "application/json");
      xhr.timeout = 15 * 60 * 1000;
      xhr.upload.addEventListener("progress", (event) => {
        if (generation !== analysis.generation) return;
        analysis.uploadProgress = event.lengthComputable
          ? event.loaded / event.total
          : null;
        renderAnalysis();
      });
      xhr.addEventListener("load", () => {
        let response;
        try {
          response = JSON.parse(xhr.responseText);
        } catch {
          reject(
            new Error("The analyzer returned an unreadable upload response."),
          );
          return;
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(response);
        else
          reject(
            new Error(
              response.error ||
                "The video could not be uploaded. Please try again.",
            ),
          );
      });
      xhr.addEventListener("error", () =>
        reject(
          new Error(
            "Could not reach the local analyzer. Check that the app is running, then try again.",
          ),
        ),
      );
      xhr.addEventListener("timeout", () =>
        reject(new Error("The upload timed out. Try a smaller video.")),
      );
      xhr.addEventListener("abort", () =>
        reject(new Error("Upload cancelled.")),
      );
      xhr.send(file);
    });
    if (generation !== analysis.generation) return;
    analysis.uploading = false;
    analysis.xhr = null;
    acceptAnalysisJob(job);
  } catch (error) {
    if (generation !== analysis.generation) return;
    analysis.uploading = false;
    analysis.xhr = null;
    analysis.error = error.message || "The video could not be uploaded.";
    renderAnalysis();
  }
}
function validCorner(point, video) {
  return (
    Array.isArray(point) &&
    point.length === 2 &&
    point.every(Number.isFinite) &&
    point[0] >= 0 &&
    point[0] < video.width &&
    point[1] >= 0 &&
    point[1] < video.height
  );
}
function renderCalibration() {
  const job = analysis.job;
  if (job?.status !== "awaiting_calibration" || !job.video) return;
  const video = job.video;
  const next = analysis.corners.findIndex(
    (point) => !validCorner(point, video),
  );
  $("calibration-instruction").textContent =
    next === -1
      ? "All four corners selected. Check the outline, then run analysis."
      : `Select corner ${next + 1}: ${CORNER_NAMES[next]}.`;
  $("calibration-video-meta").textContent =
    `${video.width} × ${video.height} · ${time(video.duration_s)} · ${Number(video.fps).toFixed(1)} fps`;
  $("analysis-start").disabled =
    next !== -1 || !analysis.previewReady || analysis.actionBusy;
  $("analysis-start").textContent = analysis.actionBusy
    ? "Starting analysis…"
    : "Run analysis";
  $("calibration-undo").disabled =
    analysis.corners.every((point) => !point) || analysis.actionBusy;
  $("calibration-reset").disabled =
    analysis.corners.every((point) => !point) || analysis.actionBusy;
  const overlay = $("calibration-overlay");
  overlay.setAttribute("viewBox", `0 0 ${video.width} ${video.height}`);
  const ns = "http://www.w3.org/2000/svg";
  const nodes = [];
  const points = analysis.corners.filter((point) => validCorner(point, video));
  if (points.length > 1) {
    const outline = document.createElementNS(
      ns,
      points.length === 4 ? "polygon" : "polyline",
    );
    outline.setAttribute(
      "points",
      points.map((point) => point.join(",")).join(" "),
    );
    outline.setAttribute("class", "calibration-outline");
    nodes.push(outline);
  }
  const radius = Math.max(video.width, video.height) * 0.013;
  analysis.corners.forEach((point, index) => {
    if (!validCorner(point, video)) return;
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("cx", point[0]);
    circle.setAttribute("cy", point[1]);
    circle.setAttribute("r", radius);
    circle.setAttribute("class", "calibration-point");
    const label = document.createElementNS(ns, "text");
    label.setAttribute("x", point[0]);
    label.setAttribute("y", point[1]);
    label.setAttribute("font-size", radius * 1.3);
    label.setAttribute("class", "calibration-point-label");
    label.textContent = String(index + 1);
    nodes.push(circle, label);
  });
  overlay.replaceChildren(...nodes);
  overlay.setAttribute(
    "aria-label",
    `${points.length} of 4 court corners selected. ${$("calibration-instruction").textContent}`,
  );
}
function writeCornerInputs() {
  analysis.corners.forEach((point, index) => {
    $("corner-" + index + "-x").value = point ? String(point[0]) : "";
    $("corner-" + index + "-y").value = point ? String(point[1]) : "";
  });
  renderCalibration();
}
async function startVideoAnalysis() {
  const job = analysis.job;
  if (
    job?.status !== "awaiting_calibration" ||
    analysis.actionBusy ||
    !analysis.previewReady ||
    !analysis.corners.every((point) => validCorner(point, job.video))
  )
    return;
  invalidateAnalysisRequests();
  const generation = analysis.generation;
  analysis.actionBusy = true;
  analysis.error = "";
  renderAnalysis();
  try {
    const result = await api(
      `/api/analysis/${encodeURIComponent(job.id)}/start`,
      { corners: analysis.corners, synthetic: $("analysis-synthetic").checked },
    );
    if (generation !== analysis.generation) return;
    analysis.actionBusy = false;
    acceptAnalysisJob(result);
  } catch (error) {
    if (generation !== analysis.generation) return;
    analysis.actionBusy = false;
    analysis.error =
      error.message ||
      "Could not start analysis. Check the four court corners.";
    renderAnalysis();
  }
}
async function cancelVideoAnalysis() {
  if (analysis.actionBusy || analysis.cancelling) return;
  if (analysis.uploading) {
    const xhr = analysis.xhr;
    invalidateAnalysisRequests();
    analysis.xhr = null;
    analysis.uploading = false;
    analysis.error = "Upload cancelled. Choose a video to start again.";
    xhr?.abort();
    renderAnalysis();
    return;
  }
  const id = analysis.job?.id;
  if (!id || analysisTerminal()) return;
  invalidateAnalysisRequests();
  const generation = analysis.generation;
  analysis.actionBusy = true;
  analysis.cancelling = true;
  analysis.error = "";
  renderAnalysis();
  try {
    const job = await api(`/api/analysis/${encodeURIComponent(id)}/cancel`, {});
    if (generation !== analysis.generation) return;
    analysis.actionBusy = false;
    acceptAnalysisJob(job, false);
  } catch (error) {
    if (generation !== analysis.generation) return;
    analysis.actionBusy = false;
    analysis.cancelling = false;
    analysis.error =
      error.message ||
      "Could not cancel this job. Reconnect to check its status.";
    analysis.connectionError = true;
    renderAnalysis();
    scheduleAnalysisPoll(2000);
  }
}
async function openCompletedAnalysis() {
  const job = analysis.job;
  if (job?.status !== "completed" || !job.session_id || analysis.openingResult)
    return;
  if (!$("analysis-dialog").open) $("analysis-dialog").showModal();
  analysis.openingResult = true;
  analysis.error = "";
  renderAnalysis();
  try {
    await refreshLibrary();
    await navigate(gamePath(job.session_id));
    if (state.session?.id !== job.session_id)
      throw new Error(
        "Could not open the completed game. Please try View results again.",
      );
    $("analysis-dialog").close();
    analysis.dismissed = true;
    rememberAnalysisJob(null);
    notice(
      "Analysis complete. Your game is saved with its replay and coaching.",
    );
    $("main").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    analysis.error = error.message || "Could not open the coaching results.";
  } finally {
    analysis.openingResult = false;
    renderAnalysis();
  }
}

for (const id of ["upload-button", "header-upload", "games-upload", "empty-upload"]) {
  $(id).addEventListener("click", openAnalysisPanel);
}
$("games-refresh").addEventListener("click", () => { void refreshLibrary(); });
$("analysis-close").addEventListener("click", () =>
  $("analysis-dialog").close(),
);
$("analysis-choose-file").addEventListener("click", () =>
  $("analysis-file").click(),
);
$("analysis-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  void uploadAnalysisVideo(file);
});
$("analysis-drop-zone").addEventListener("dragover", (event) => {
  event.preventDefault();
  event.currentTarget.classList.add("drag-over");
});
$("analysis-drop-zone").addEventListener("dragleave", (event) =>
  event.currentTarget.classList.remove("drag-over"),
);
$("analysis-drop-zone").addEventListener("drop", (event) => {
  event.preventDefault();
  event.currentTarget.classList.remove("drag-over");
  if (event.dataTransfer.files.length !== 1) {
    analysis.error = "Choose one video at a time.";
    renderAnalysis();
    return;
  }
  void uploadAnalysisVideo(event.dataTransfer.files[0]);
});
$("analysis-preview").addEventListener("load", () => {
  if (analysis.job?.id !== analysis.previewId) return;
  analysis.previewReady = true;
  renderCalibration();
});
$("analysis-preview").addEventListener("error", () => {
  if (analysis.job?.status !== "awaiting_calibration") return;
  analysis.previewReady = false;
  analysis.error =
    "The court preview could not load. Retry the connection before selecting corners.";
  analysis.connectionError = true;
  renderAnalysis();
});
$("calibration-overlay").addEventListener("click", (event) => {
  if (
    !analysis.previewReady ||
    analysis.actionBusy ||
    analysis.job?.status !== "awaiting_calibration"
  )
    return;
  const video = analysis.job.video;
  const index = analysis.corners.findIndex(
    (point) => !validCorner(point, video),
  );
  if (index === -1) return;
  const rect = event.currentTarget.getBoundingClientRect();
  analysis.corners[index] = [
    Math.max(
      0,
      Math.min(
        video.width - 1,
        Math.round(((event.clientX - rect.left) / rect.width) * video.width),
      ),
    ),
    Math.max(
      0,
      Math.min(
        video.height - 1,
        Math.round(((event.clientY - rect.top) / rect.height) * video.height),
      ),
    ),
  ];
  writeCornerInputs();
});
for (let index = 0; index < 4; index++) {
  for (const axis of ["x", "y"])
    $("corner-" + index + "-" + axis).addEventListener("input", () => {
      const x = $("corner-" + index + "-x").value;
      const y = $("corner-" + index + "-y").value;
      analysis.corners[index] =
        x !== "" && y !== "" ? [Number(x), Number(y)] : null;
      renderCalibration();
    });
}
$("calibration-undo").addEventListener("click", () => {
  for (let index = 3; index >= 0; index--)
    if (analysis.corners[index]) {
      analysis.corners[index] = null;
      break;
    }
  writeCornerInputs();
});
$("calibration-reset").addEventListener("click", () => {
  analysis.corners = [null, null, null, null];
  writeCornerInputs();
});
$("analysis-start").addEventListener("click", startVideoAnalysis);
$("analysis-cancel").addEventListener("click", cancelVideoAnalysis);
$("analysis-view-results").addEventListener("click", openCompletedAnalysis);
$("analysis-another").addEventListener("click", resetAnalysis);
$("analysis-banner-open").addEventListener("click", () => {
  if (analysis.job?.status === "completed") void openCompletedAnalysis();
  else openAnalysisPanel();
});
$("analysis-retry").addEventListener("click", async () => {
  analysis.error = "";
  analysis.connectionError = false;
  if (analysis.job) {
    if (
      analysis.job.status === "awaiting_calibration" &&
      !analysis.previewReady
    ) {
      $("analysis-preview").src =
        `/api/analysis/${encodeURIComponent(analysis.job.id)}/preview?retry=${Date.now()}`;
    }
    await pollAnalysisJob();
  } else {
    try {
      configureAnalysis(await api("/api/config"));
    } catch {
      analysis.error =
        "Could not connect. Check that the local app is running.";
      analysis.connectionError = true;
    }
  }
  renderAnalysis();
});

async function initialize() {
  if (window.location.pathname === "/") window.history.replaceState({}, "", "/games");
  state.route = readRoute();
  applyAppLayout();
  loading(true);
  const [config] = await Promise.allSettled([
    api("/api/config"),
    refreshLibrary(),
  ]);
  if (config.status === "fulfilled") {
    state.aiAvailable = Boolean(config.value.ai_available);
    configureCoach(config.value.coach);
    configureAnalysis(config.value);
  } else {
    analysis.configLoaded = true;
    analysis.configError = "Could not connect to the analyzer. Check that Vantage is running.";
    analysis.connectionError = true;
    renderAnalysis();
  }
  state.booting = false;
  loading(false);
  renderAIMode();
  void restoreAnalysisJob();
  await applyRoute();
}

initialize();
