"use strict";

// The browser owns presentation, local video playback, and practice checkmarks.
// Reports and answers come from the same versioned API a future mobile client can use.
const $ = (id) => document.getElementById(id);
const state = {
  session: null,
  report: null,
  focus: "consistency",
  sessions: [],
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

async function api(path, body) {
  const options = { headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      "The coaching service returned an unreadable response. Try again.",
    );
  }
  if (!response.ok) {
    const error = new Error(
      payload.error || "That request could not be completed. Try again.",
    );
    error.status = response.status;
    throw error;
  }
  return payload;
}

function loading(active) {
  document.body.classList.toggle("is-loading", active);
  $("loading").hidden = !active || Boolean(state.session);
  $("export-button").disabled = active || !state.report;
}

async function openSession(fetchSession) {
  const generation = ++state.generation;
  state.chatGeneration++;
  clearVideo();
  state.session = null;
  state.report = null;
  resetChat();
  $("workspace").hidden = true;
  loading(true);
  showError("");
  try {
    const session = await fetchSession();
    if (generation !== state.generation) return;
    const report = await api("/api/report", {
      stats: session.stats,
      focus: state.focus,
    });
    if (generation !== state.generation) return;
    state.session = session;
    state.report = report;
    resetChat();
    render();
    if (session.video_url) setVideo(session.video_url, false);
  } catch (error) {
    if (generation === state.generation)
      showError(error.message || "Could not open this session.");
  } finally {
    if (generation === state.generation) loading(false);
  }
}

async function setFocus(focus) {
  if (!state.session || focus === state.focus) return;
  const generation = ++state.generation;
  state.chatGeneration++;
  resetChat();
  renderSuggestions();
  loading(true);
  showError("");
  try {
    const report = await api("/api/report", {
      stats: state.session.stats,
      focus,
    });
    if (generation !== state.generation) return;
    state.focus = focus;
    state.report = report;
    resetChat();
    render();
  } catch (error) {
    if (generation === state.generation)
      showError(error.message || "Could not update your focus.");
  } finally {
    if (generation === state.generation) loading(false);
  }
}

function render() {
  const { session, report } = state;
  $("workspace").hidden = false;
  $("session-name").textContent = session.name || "Analyzed session";
  $("demo-badge").hidden = !session.is_demo;
  $("sample-note").hidden = !session.is_demo;
  const duration = time(session.stats.video?.duration_s);
  $("session-meta").textContent = "PICKLEBALL · ANALYZED SESSION";
  $("video-duration").textContent = `${duration} analysis`;
  $("video-coverage").textContent =
    `${percent(report.quality.coverage)} of frames observed`;
  $("report-headline").textContent = report.headline;
  $("report-summary").textContent = report.summary;
  document.querySelectorAll("[data-focus]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.focus === state.focus),
    );
  });
  renderSessionSelect();
  renderMetrics();
  renderCourt();
  renderInsights();
  renderMoments();
  renderDrills();
  renderQuality();
  renderSuggestions();
  renderAIMode();
}

function renderSessionSelect() {
  const sessions = [...state.sessions];
  if (
    state.session &&
    !sessions.some((session) => session.id === state.session.id)
  ) {
    sessions.push({ id: state.session.id, name: state.session.name });
  }
  const options = sessions.map((session) => {
    const option = element("option", "", session.name);
    option.value = session.id;
    option.selected = session.id === state.session?.id;
    return option;
  });
  if (!options.length) {
    const option = element("option", "", "No sessions yet");
    option.value = "";
    options.push(option);
  }
  replace("session-select", options);
}

function renderMetrics() {
  replace(
    "metric-grid",
    (state.report.metrics || []).map((metric) => {
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
  const supported = state.report.quality.status !== "insufficient_evidence";
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
  return `vantage.coaching.plan.v1.${state.report.session_id}.${state.focus}`;
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
  const quality = state.report.quality;
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
  replace(
    "suggested-questions",
    (state.report.suggested_questions || []).slice(0, 3).map((question) => {
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
}

function renderAIMode() {
  $("ai-option").hidden = !state.aiAvailable;
  if (!state.aiAvailable) $("use-ai").checked = false;
  const useAI = state.aiAvailable && $("use-ai").checked;
  const label = useAI ? "AI responses · OpenAI" : "Session guide · local";
  $("coach-mode").replaceChildren(
    element("span", "status-dot"),
    document.createTextNode(label),
  );
  $("chat-footnote").textContent = useAI
    ? "AI can make mistakes. Check the session evidence."
    : "Fixed session guide · no generated AI responses.";
}

function resetChat() {
  state.history = [];
  state.chatBusy = false;
  replace("chat-log", []);
  $("chat-input").value = "";
  $("chat-input").disabled = false;
  $("send-button").disabled = false;
  $("chat-error").hidden = true;
}

function addMessage(role, text, result) {
  const message = element("div", `chat-message ${role}`);
  message.append(
    element(
      "div",
      "message-label",
      role === "user"
        ? "You"
        : result?.source === "openai"
          ? "AI coach · OpenAI"
          : "Session guide · local",
    ),
  );
  message.append(element("div", "message-body", text));
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

async function submitQuestion(raw) {
  const question = raw.trim();
  if (!question || !state.session || state.chatBusy) return;
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
  renderMoments();
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
  const exported = {
    ...report,
    session_name: state.session.name,
    is_demo: Boolean(state.session.is_demo),
    completed_drill_ids: report.drills
      .filter((drill) => state.completed.has(drill.id))
      .map((drill) => drill.id),
  };
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
  notice("Coaching report exported with your practice checklist.");
}

$("sample-button").addEventListener("click", () =>
  openSession(() => api("/api/demo")),
);
$("import-button").addEventListener("click", () => $("stats-file").click());
$("stats-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  openSession(async () => {
    if (file.size > 2_000_000) {
      throw new Error(
        "This file is too large. Import a stats.json file smaller than 2 MB.",
      );
    }
    let stats;
    try {
      stats = JSON.parse(await file.text());
    } catch {
      throw new Error(
        "This file isn’t valid JSON. Choose stats.json from a completed Vantage analysis.",
      );
    }
    return api("/api/session", {
      stats,
      name: file.name.replace(/\.json$/i, "") || "Imported session",
    });
  });
});
$("session-select").addEventListener("change", (event) => {
  const id = event.target.value;
  if (!id || id === state.session?.id) return;
  openSession(() => api(`/api/sessions/${encodeURIComponent(id)}`));
});
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
  setVideo(URL.createObjectURL(file), true);
});
$("session-video").addEventListener("loadedmetadata", () => {
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

// These are links to sections in the review, not tabs that hide page content.
// Reflect the section in view while preserving native anchor/keyboard behavior.
const sectionLinks = [...document.querySelectorAll(".section-tabs a")];
let sectionFrame = null;
function syncSectionNavigation() {
  sectionFrame = null;
  if (!state.report) return;
  let current = "#overview";
  for (const link of sectionLinks) {
    const target = document.querySelector(link.getAttribute("href"));
    if (target.getBoundingClientRect().top <= window.innerHeight * 0.35) {
      current = link.getAttribute("href");
    }
  }
  for (const link of sectionLinks) {
    if (link.getAttribute("href") === current)
      link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener(
  "scroll",
  () => {
    if (sectionFrame === null)
      sectionFrame = requestAnimationFrame(syncSectionNavigation);
  },
  { passive: true },
);
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
    const library = await api("/api/sessions");
    state.sessions = library.sessions || [];
    renderSessionSelect();
    await openSession(() =>
      api(`/api/sessions/${encodeURIComponent(job.session_id)}`),
    );
    if (state.session?.id !== job.session_id || !state.report)
      throw new Error(
        "Could not open the completed review. Please try View coaching results again.",
      );
    $("analysis-dialog").close();
    analysis.dismissed = true;
    rememberAnalysisJob(null);
    notice(
      "Analysis complete. Your annotated replay and coaching review are ready.",
    );
    $("main").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    analysis.error = error.message || "Could not open the coaching results.";
  } finally {
    analysis.openingResult = false;
    renderAnalysis();
  }
}

$("upload-button").addEventListener("click", openAnalysisPanel);
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
  const [config, sessions] = await Promise.allSettled([
    api("/api/config"),
    api("/api/sessions"),
  ]);
  if (config.status === "fulfilled") {
    state.aiAvailable = Boolean(config.value.ai_available);
    configureAnalysis(config.value);
  } else {
    analysis.configLoaded = true;
    analysis.configError =
      "Could not connect to the local analyzer. Check that the app is running.";
    analysis.connectionError = true;
    renderAnalysis();
  }
  void restoreAnalysisJob();
  if (sessions.status === "fulfilled") {
    state.sessions = sessions.value.sessions || [];
    if (sessions.value.errors?.length) {
      $("session-errors").textContent = sessions.value.errors.join("\n");
      $("session-errors").hidden = false;
    }
  }
  renderSessionSelect();
  renderAIMode();
  if (state.generation > 0) return;
  const first = state.sessions[0];
  await openSession(() =>
    api(first ? `/api/sessions/${encodeURIComponent(first.id)}` : "/api/demo"),
  );
}

initialize();
