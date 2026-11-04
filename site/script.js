(() => {
  "use strict";

  const signupUrl = window.VANTAGE_CONFIG?.signupUrl?.trim();
  if (signupUrl) {
    try {
      const destination = new URL(signupUrl);
      if (!["https:", "http:"].includes(destination.protocol)) {
        throw new Error("The signup form must use an HTTP or HTTPS URL.");
      }
      document.querySelectorAll("[data-signup-link]").forEach((link) => {
        link.href = destination.href;
        link.hidden = false;
      });
      document.querySelector("[data-signup-pending]").hidden = true;
    } catch {
      // Preserve the honest unavailable state if the form URL is missing or invalid.
      console.warn("Vantage: set a valid signupUrl in config.js before publishing.");
    }
  }

  document.getElementById("copyright-year").textContent = new Date().getFullYear();

  const controls = document.querySelector(".replay-controls");
  const playButton = document.querySelector(".play-button");
  const slider = document.getElementById("replay-progress");
  const timeDisplay = document.getElementById("current-time");
  const path = document.getElementById("rally-path");
  const ball = document.getElementById("tracked-ball");
  const duration = 12_000;
  const pathLength = path.getTotalLength();
  let progress = Number(slider.value) / Number(slider.max);
  let playing = false;
  let animationFrame = null;
  let lastTimestamp = null;

  function renderProgress() {
    const point = path.getPointAtLength(progress * pathLength);
    ball.setAttribute("transform", `translate(${point.x} ${point.y})`);
    slider.value = Math.round(progress * Number(slider.max));
    slider.style.setProperty("--progress", `${progress * 100}%`);
    const seconds = Math.floor((progress * duration) / 1_000);
    slider.setAttribute("aria-valuetext", `${seconds} of 12 seconds`);
    timeDisplay.textContent = `00:${String(seconds).padStart(2, "0")}`;
  }

  function setPlaying(value) {
    playing = value;
    playButton.setAttribute("aria-pressed", String(value));
    playButton.setAttribute("aria-label", value ? "Pause illustrated rally" : "Play illustrated rally");
    lastTimestamp = null;
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
    if (value) {
      if (progress >= 1) progress = 0;
      animationFrame = requestAnimationFrame(animate);
    }
  }

  function animate(timestamp) {
    if (!playing) return;
    if (lastTimestamp !== null) progress = Math.min(1, progress + (timestamp - lastTimestamp) / duration);
    lastTimestamp = timestamp;
    renderProgress();
    if (progress >= 1) setPlaying(false);
    else animationFrame = requestAnimationFrame(animate);
  }

  playButton.addEventListener("click", () => setPlaying(!playing));
  slider.addEventListener("input", () => {
    setPlaying(false);
    progress = Number(slider.value) / Number(slider.max);
    renderProgress();
  });

  document.querySelectorAll(".overlay-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const active = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(active));
      document.querySelector(`.${button.dataset.overlay}`).style.visibility = active ? "visible" : "hidden";
    });
  });

  // Replay is user initiated; it never auto-plays, including with reduced motion.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) setPlaying(false);
  });
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) setPlaying(false);
    }).observe(controls);
  }

  renderProgress();
  controls.hidden = false;
})();
