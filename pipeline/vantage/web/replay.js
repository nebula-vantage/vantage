"use strict";

// 3-D match replay. The server reconstructs the game (court-plane players, gravity-fitted
// ball flight, and the original camera pose); this file redraws it on a canvas from any
// angle, with a match timeline and positioning measured from the player you pick.
// Plain Canvas 2D keeps the app free of libraries and build steps.
(() => {
  const $ = (id) => document.getElementById(id);
  const DEG = Math.PI / 180;
  const NEAR = 0.15;
  const SPEEDS = [0.25, 0.5, 1, 2];
  const TRAIL_S = 3.5;
  const YOU_TRAIL_S = 5;
  const CAPTION_S = 1.2;
  const COLORS = {
    background: "#233b30",
    surround: "#536049",
    court: "#304b3f",
    kitchen: "#829074",
    line: "#e4e4cd",
    net: "#c6c9ab",
    netTop: "#f1efda",
    shadow: "#182d25",
    near: "#eee9d5",
    far: "#dce4cb",
    bracket: "#c5dfb4",
    ball: "#ff8a43",
    ballRing: "#ff9c5b",
    ballGlow: "#fb7434",
    ballLight: "#ffd6ad",
    you: "#f6b184",
    out: "#ff7a59",
  };
  // Orbit views: azimuth 0 looks from behind the near baseline; elevation is above the court.
  const VIEWS = {
    angle: { name: "Angled", az: -38, el: 30, dist: 17, fov: 40, target: [3.05, 6.2, 0] },
    // Overhead lays the court across the wide stage, near baseline on the left. Sideline sits
    // a little off square so partners standing in line don't hide each other.
    top: { name: "Overhead", az: 90, el: 89, dist: 16, fov: 40, target: [3.05, 6.7, 0] },
    side: { name: "Sideline", az: 72, el: 14, dist: 15.5, fov: 40, target: [3.05, 6.7, 1.1] },
  };
  const ZONES = {
    kitchen: "Kitchen line",
    transition: "Transition zone",
    baseline: "Baseline",
  };

  const replay = {
    sessionId: null,
    session: null,
    data: null,
    loading: false,
    scrubbing: false,
    startAt: 0,
    error: "",
    active: false,
    generation: 0,
    time: 0,
    playing: false,
    speed: 1,
    view: "angle",
    camera: null,
    transition: null,
    follow: { az: 0, el: 0, zoom: 1 },
    you: null,
    show: { ball: true, players: true, video: true, footage: false },
    frame: null,
    lastTick: 0,
    frameDt: 1 / 60,
    clock: null, // Virtual milliseconds while a recording steps frames; null in normal use.
    hits: [],
    facing: new Map(),
    pointers: new Map(),
    drag: null,
    captionKey: "",
    coordinateKey: "",
    liveAt: 0,
    size: { width: 0, height: 0 },
    dots: null,
  };

  // ---- Vectors and camera ---------------------------------------------------------------

  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
  const unit = (a) => {
    const length = Math.hypot(a[0], a[1], a[2]) || 1;
    return [a[0] / length, a[1] / length, a[2] / length];
  };
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
  const angleDelta = (from, to) => Math.atan2(Math.sin(to - from), Math.cos(to - from));
  const now = () => replay.clock ?? performance.now();

  function orbit(preset) {
    return {
      target: [...preset.target],
      az: preset.az * DEG,
      el: preset.el * DEG,
      dist: preset.dist,
      fov: preset.fov,
    };
  }

  // The recorded viewpoint as an orbit around the point where the camera looks at the court.
  function recordedOrbit(camera) {
    const eye = camera.position_m;
    const forward = unit(camera.forward);
    const reach = forward[2] < -0.05 ? -eye[2] / forward[2] : 20;
    const target = eye.map((value, i) => value + forward[i] * reach);
    const offset = sub(eye, target);
    const dist = Math.hypot(...offset);
    return {
      target,
      az: Math.atan2(offset[0], -offset[1]),
      el: Math.asin(clamp(offset[2] / dist, -1, 1)),
      dist,
      fov: camera.vertical_fov_deg,
    };
  }

  // `frameAspect` fits a whole recorded frame of that aspect inside the canvas (Original view),
  // so the projection and the footage drawn under it share one frame.
  function makeView(state, width, height, frameAspect = null) {
    const { target, az, el, dist } = state;
    const eye = [
      target[0] + dist * Math.sin(az) * Math.cos(el),
      target[1] - dist * Math.cos(az) * Math.cos(el),
      target[2] + dist * Math.sin(el),
    ];
    const forward = unit(sub(target, eye));
    const right = unit(cross(forward, [0, 0, 1]));
    const up = cross(right, forward);
    const frameHeight = frameAspect ? Math.min(height, width / frameAspect) : height;
    const focal = frameHeight / 2 / Math.tan((state.fov * DEG) / 2);
    return { eye, forward, right, up, focal, cx: width / 2, cy: height / 2, width, height };
  }

  function toCamera(view, p) {
    const d = sub(p, view.eye);
    return [dot(d, view.right), dot(d, view.up), dot(d, view.forward)];
  }
  function toScreen(view, c) {
    return [view.cx + (c[0] * view.focal) / c[2], view.cy - (c[1] * view.focal) / c[2], c[2]];
  }
  function project(view, p) {
    const c = toCamera(view, p);
    return c[2] > NEAR ? toScreen(view, c) : null;
  }
  function nearCut(a, b) {
    const t = (NEAR - a[2]) / (b[2] - a[2]);
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, NEAR];
  }
  function clipPolygon(points) {
    const out = [];
    points.forEach((a, i) => {
      const b = points[(i + 1) % points.length];
      if (a[2] > NEAR) out.push(a);
      if (a[2] > NEAR !== b[2] > NEAR) out.push(nearCut(a, b));
    });
    return out;
  }

  // ---- Replay data ----------------------------------------------------------------------

  function prepare(data) {
    const ball = [...data.ball].sort((a, b) => a.t0 - b.t0);
    const players = data.players.map((player) => ({ ...player }));
    for (const player of players) {
      player.partner = players.find((p) => p !== player && p.side === player.side) || null;
    }
    return {
      ...data,
      ball,
      players,
      duration: Math.max(0.1, data.video.duration_s),
      gravity: data.gravity_m_s2 || 9.81,
      rate: data.player_rate_hz,
    };
  }

  function ballAt(match, t) {
    const pieces = match.ball;
    let low = 0;
    let high = pieces.length - 1;
    let found = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (pieces[mid].t0 <= t) {
        found = mid;
        low = mid + 1;
      } else high = mid - 1;
    }
    // Neighbouring pieces share their boundary, so check the one before as well.
    for (const index of [found, found - 1]) {
      const piece = pieces[index];
      if (piece && t >= piece.t0 && t <= piece.t1) {
        const tau = t - piece.t0;
        return {
          position: [
            piece.p0[0] + piece.v0[0] * tau,
            piece.p0[1] + piece.v0[1] * tau,
            Math.max(0, piece.p0[2] + piece.v0[2] * tau - 0.5 * match.gravity * tau * tau),
          ],
          quality: piece.quality,
        };
      }
    }
    return null;
  }

  function playerAt(match, player, t) {
    const index = t * match.rate;
    const i = Math.floor(index);
    const a = player.samples[i];
    const b = player.samples[i + 1];
    if (a && b) {
      const f = index - i;
      return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
    }
    return a || b || null;
  }

  function zoneOf(court, side, position) {
    const net = court.net_y_m;
    const fromNet = side === "near" ? net - position[1] : position[1] - net;
    const behindKitchen = fromNet - court.kitchen_depth_m;
    const fromBaseline = side === "near" ? position[1] : court.length_m - position[1];
    if (behindKitchen < -0.15) return { key: "kitchen", label: "In the kitchen", behindKitchen };
    if (behindKitchen <= 0.9) return { key: "kitchen", label: "Kitchen line", behindKitchen };
    if (fromBaseline <= 1.5) return { key: "baseline", label: "Baseline", behindKitchen };
    return { key: "transition", label: "Transition zone", behindKitchen };
  }

  function summarize(match, player) {
    const dt = 1 / match.rate;
    const zones = { kitchen: 0, transition: 0, baseline: 0 };
    let seen = 0;
    let distance = 0;
    let spacing = 0;
    let spaced = 0;
    player.samples.forEach((sample, i) => {
      if (!sample) return;
      seen += 1;
      const previous = player.samples[i - 1];
      if (previous) {
        const step = Math.hypot(sample[0] - previous[0], sample[1] - previous[1]);
        if (step <= 9 * dt) distance += step;
      }
      zones[zoneOf(match.court, player.side, sample).key] += 1;
      const other = player.partner?.samples[i];
      if (other) {
        spacing += Math.hypot(sample[0] - other[0], sample[1] - other[1]);
        spaced += 1;
      }
    });
    return {
      seen: seen * dt,
      coverage: seen / Math.max(1, player.samples.length),
      distance,
      zones: Object.fromEntries(Object.entries(zones).map(([k, v]) => [k, seen ? v / seen : 0])),
      spacing: spaced ? spacing / spaced : null,
    };
  }

  // ---- Drawing ----------------------------------------------------------------------------

  function polygonPath(ctx, view, points) {
    const clipped = clipPolygon(points.map((p) => toCamera(view, p)));
    if (clipped.length < 3) return false;
    ctx.beginPath();
    clipped.forEach((c, i) => {
      const [x, y] = toScreen(view, c);
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.closePath();
    return true;
  }

  function fillPolygon(ctx, view, points, style) {
    if (polygonPath(ctx, view, points)) {
      ctx.fillStyle = style;
      ctx.fill();
    }
  }

  function line(ctx, view, a, b) {
    let ca = toCamera(view, a);
    let cb = toCamera(view, b);
    if (ca[2] <= NEAR && cb[2] <= NEAR) return;
    if (ca[2] <= NEAR) ca = nearCut(ca, cb);
    if (cb[2] <= NEAR) cb = nearCut(cb, ca);
    const [x1, y1] = toScreen(view, ca);
    const [x2, y2] = toScreen(view, cb);
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
  }

  function polyline(ctx, view, points) {
    let open = false;
    for (const p of points) {
      const s = p && project(view, p);
      if (!s) {
        open = false;
        continue;
      }
      if (open) ctx.lineTo(s[0], s[1]);
      else ctx.moveTo(s[0], s[1]);
      open = true;
    }
  }

  function groundCircle(center, radius, z = 0.005, steps = 22) {
    return Array.from({ length: steps }, (_, i) => {
      const a = (i / steps) * Math.PI * 2;
      return [center[0] + Math.cos(a) * radius, center[1] + Math.sin(a) * radius, z];
    });
  }

  function scaleAt(view, point) {
    const c = toCamera(view, point);
    return c[2] > NEAR ? view.focal / c[2] : 0;
  }

  // Text laid flat on the court: an affine map from the local projection of its baseline.
  function groundText(ctx, view, text, origin, size, alpha) {
    const o = project(view, origin);
    const x = project(view, [origin[0] + 1, origin[1], origin[2]]);
    const y = project(view, [origin[0], origin[1] - 1, origin[2]]);
    if (!o || !x || !y) return;
    // Draw the lettering whole or not at all: fragments under the chips or edges look broken.
    const half = text.length * size * 0.32;
    const ends = [-1, 1].map((side) => project(view, [origin[0] + side * half, origin[1], origin[2]]));
    const inside = (p) => p && p[0] > 40 && p[0] < view.width - 40 && p[1] > 110 && p[1] < view.height - 70;
    if (!ends.every(inside)) return;
    ctx.save();
    // Fonts misrender below a pixel, so draw at 100x and shrink the transform to match.
    const k = 0.01;
    ctx.setTransform(
      ...dprTransform((x[0] - o[0]) * k, (x[1] - o[1]) * k, (y[0] - o[0]) * k, (y[1] - o[1]) * k, o[0], o[1]),
    );
    ctx.globalAlpha = alpha;
    ctx.fillStyle = COLORS.line;
    ctx.font = `${size * 100}px "IBM Plex Mono", monospace`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 0, 0);
    ctx.restore();
  }

  function dprTransform(a, b, c, d, e, f) {
    const r = window.devicePixelRatio || 1;
    return [a * r, b * r, c * r, d * r, e * r, f * r];
  }

  function courtDots(court) {
    const dots = [];
    for (let x = -3; x <= court.width_m + 3; x += 0.45) {
      for (let y = -4; y <= court.length_m + 4; y += 0.45) dots.push([x, y, 0]);
    }
    return dots;
  }

  function drawCourt(ctx, view, court, footage) {
    const w = court.width_m;
    const l = court.length_m;
    const net = court.net_y_m;
    const k = court.kitchen_depth_m;
    if (!footage) {
      fillPolygon(ctx, view, [[-3, -4, 0], [w + 3, -4, 0], [w + 3, l + 4, 0], [-3, l + 4, 0]], COLORS.surround);
      ctx.fillStyle = "rgba(255,255,255,.06)";
      for (const dot of replay.dots) {
        const s = project(view, dot);
        if (s && s[0] > -2 && s[1] > -2 && s[0] < view.width + 2 && s[1] < view.height + 2) {
          ctx.fillRect(s[0], s[1], 1.1, 1.1);
        }
      }
      fillPolygon(ctx, view, [[0, 0, 0], [w, 0, 0], [w, l, 0], [0, l, 0]], COLORS.court);
      fillPolygon(ctx, view, [[0, net - k, 0], [w, net - k, 0], [w, net + k, 0], [0, net + k, 0]], COLORS.kitchen);
    }
    ctx.beginPath();
    for (const [a, b] of [
      [[0, 0, 0], [w, 0, 0]],
      [[w, 0, 0], [w, l, 0]],
      [[w, l, 0], [0, l, 0]],
      [[0, l, 0], [0, 0, 0]],
      [[0, net - k, 0], [w, net - k, 0]],
      [[0, net + k, 0], [w, net + k, 0]],
      [[w / 2, 0, 0], [w / 2, net - k, 0]],
      [[w / 2, net + k, 0], [w / 2, l, 0]],
    ]) line(ctx, view, a, b);
    ctx.strokeStyle = footage ? "rgba(228,228,205,.75)" : COLORS.line;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();
    // Floor lettering reads well from above; from low or follow cameras it only gets in the way.
    if (!footage && replay.view !== "you" && view.forward[2] < -0.34) {
      groundText(ctx, view, "A  N E W  P E R S P E C T I V E", [w / 2, -1.7, 0], 0.32, 0.55);
    }
  }

  function netTop(court, x) {
    const half = court.width_m / 2 + 0.3048;
    const f = (x - court.width_m / 2) / half;
    return court.net_center_height_m + (court.net_post_height_m - court.net_center_height_m) * f * f;
  }

  function drawNet(ctx, view, court) {
    const y = court.net_y_m;
    const left = -0.3048;
    const right = court.width_m + 0.3048;
    const xs = Array.from({ length: 13 }, (_, i) => left + ((right - left) * i) / 12);
    const top = xs.map((x) => [x, y, netTop(court, x)]);
    if (polygonPath(ctx, view, [...top, [right, y, 0.03], [left, y, 0.03]])) {
      ctx.fillStyle = "rgba(198,201,171,.13)";
      ctx.fill();
    }
    ctx.beginPath();
    for (let x = left; x <= right; x += 0.22) line(ctx, view, [x, y, 0.03], [x, y, netTop(court, x)]);
    for (const h of [0.2, 0.38, 0.56, 0.72]) polyline(ctx, view, xs.map((x) => [x, y, Math.min(h, netTop(court, x))]));
    ctx.strokeStyle = "rgba(198,201,171,.32)";
    ctx.lineWidth = 0.6;
    ctx.stroke();
    ctx.beginPath();
    line(ctx, view, [left, y, 0.03], [right, y, 0.03]);
    ctx.strokeStyle = COLORS.shadow;
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.beginPath();
    polyline(ctx, view, top);
    ctx.strokeStyle = COLORS.netTop;
    ctx.lineWidth = 2.5;
    ctx.stroke();
    ctx.beginPath();
    line(ctx, view, [left, y, 0], [left, y, court.net_post_height_m + 0.04]);
    line(ctx, view, [right, y, 0], [right, y, court.net_post_height_m + 0.04]);
    ctx.strokeStyle = COLORS.net;
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  function facingFor(match, player, position, ball) {
    const toward = ball && Math.hypot(ball[0] - position[0], ball[1] - position[1]) < 7
      ? Math.atan2(ball[1] - position[1], ball[0] - position[0])
      : player.side === "near" ? Math.PI / 2 : -Math.PI / 2;
    const previous = replay.facing.get(player.id);
    if (previous === undefined) {
      replay.facing.set(player.id, toward);
      return toward;
    }
    const next = previous + angleDelta(previous, toward) * 0.18;
    replay.facing.set(player.id, next);
    return next;
  }

  function drawPlayer(ctx, view, match, player, position, facing, you) {
    const [x, y] = position;
    const h = player.height_m;
    const body = player.side === "near" ? COLORS.near : COLORS.far;
    const scale = scaleAt(view, [x, y, h * 0.5]);
    if (!scale) return null;
    const fx = Math.cos(facing);
    const fy = Math.sin(facing);
    const rx = fy;
    const ry = -fx;
    const hip = project(view, [x, y, 0.42]);
    const chest = project(view, [x, y, h - 0.42]);
    const head = project(view, [x, y, h - 0.13]);
    const shoulder = [x + rx * 0.2, y + ry * 0.2, h - 0.45];
    const hand = [shoulder[0] + fx * 0.32 + rx * 0.2, shoulder[1] + fy * 0.32 + ry * 0.2, h - 0.62];
    const paddle = [hand[0] + fx * 0.2 + rx * 0.06, hand[1] + fy * 0.2 + ry * 0.06, h - 0.5];
    const ps = [project(view, shoulder), project(view, hand), project(view, paddle)];
    if (!hip || !chest || !head) return null;
    ctx.lineCap = "round";
    ctx.strokeStyle = body;
    ctx.lineWidth = Math.max(5, 0.42 * scale);
    ctx.beginPath();
    ctx.moveTo(hip[0], hip[1]);
    ctx.lineTo(chest[0], chest[1]);
    ctx.stroke();
    if (ps.every(Boolean)) {
      ctx.lineWidth = Math.max(2, 0.075 * scale);
      ctx.beginPath();
      ctx.moveTo(ps[0][0], ps[0][1]);
      ctx.lineTo(ps[1][0], ps[1][1]);
      ctx.stroke();
      ctx.lineWidth = Math.max(3.5, 0.17 * scale);
      ctx.beginPath();
      ctx.moveTo(ps[1][0], ps[1][1]);
      ctx.lineTo(ps[2][0], ps[2][1]);
      ctx.stroke();
    }
    const radius = Math.max(3.2, 0.135 * scale);
    ctx.beginPath();
    ctx.arc(head[0], head[1], radius, 0, Math.PI * 2);
    ctx.fillStyle = body;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = you ? COLORS.you : COLORS.background;
    ctx.stroke();
    const foot = project(view, [x, y, 0]);
    const xsAll = [hip[0], chest[0], head[0], foot?.[0] ?? hip[0], ...ps.filter(Boolean).map((p) => p[0])];
    const ysAll = [hip[1], chest[1], head[1], foot?.[1] ?? hip[1], ...ps.filter(Boolean).map((p) => p[1])];
    const pad = Math.max(6, 0.12 * scale);
    return {
      x1: Math.min(...xsAll) - pad,
      y1: Math.min(...ysAll) - radius - pad * 0.6,
      x2: Math.max(...xsAll) + pad,
      y2: Math.max(...ysAll) + pad * 0.6,
    };
  }

  function drawBrackets(ctx, box, color) {
    const size = Math.min(10, (box.x2 - box.x1) / 3, (box.y2 - box.y1) / 3);
    ctx.beginPath();
    for (const [x, y, dx, dy] of [
      [box.x1, box.y1, 1, 1],
      [box.x2, box.y1, -1, 1],
      [box.x2, box.y2, -1, -1],
      [box.x1, box.y2, 1, -1],
    ]) {
      ctx.moveTo(x, y + dy * size);
      ctx.lineTo(x, y);
      ctx.lineTo(x + dx * size, y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.lineCap = "butt";
    ctx.stroke();
  }

  // Labels are queued while drawing and placed last, nudged apart so none hide another.
  const labels = [];
  function chip(text, x, y, background, color, priority = 2) {
    labels.push({ text, x, y, background, color, priority });
  }

  // Every label also keeps clear of the player figures in `obstacles`; measurement chips
  // (priority 2) are dropped rather than drawn over something.
  function drawLabels(ctx, obstacles = []) {
    ctx.font = '500 11px "IBM Plex Mono", monospace';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const placed = [...obstacles];
    const overlaps = (r) => placed.some((q) => r.x1 < q.x2 && r.x2 > q.x1 && r.y1 < q.y2 && r.y2 > q.y1);
    labels.sort((a, b) => a.priority - b.priority);
    for (const label of labels) {
      const width = ctx.measureText(label.text).width + 12;
      const offset = [0, -21, 21, -42, 42].find((dy) => !overlaps({
        x1: label.x - width / 2, x2: label.x + width / 2, y1: label.y + dy - 10, y2: label.y + dy + 10,
      }));
      if (offset === undefined && label.priority > 1) continue;
      const y = label.y + (offset ?? 0);
      placed.push({ x1: label.x - width / 2, x2: label.x + width / 2, y1: y - 10, y2: y + 10 });
      ctx.fillStyle = label.background;
      ctx.beginPath();
      ctx.roundRect(label.x - width / 2, y - 10, width, 20, 3);
      ctx.fill();
      ctx.fillStyle = label.color;
      ctx.fillText(label.text, label.x, y + 0.5);
    }
    labels.length = 0;
  }

  function drawBall(ctx, view, ball) {
    const p = project(view, ball.position);
    if (!p) return;
    const estimated = ball.quality === "approximate" || ball.quality === "bridged";
    const r = clamp(0.055 * (view.focal / p[2]), 3.5, 8);
    ctx.beginPath();
    ctx.arc(p[0], p[1], r * 2.8, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(251,116,52,.14)";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(p[0], p[1], r * 1.8, 0, Math.PI * 2);
    ctx.setLineDash(estimated ? [2, 3] : []);
    ctx.strokeStyle = "rgba(255,156,91,.7)";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p[0], p[1], r, 0, Math.PI * 2);
    const alpha = ctx.globalAlpha;
    ctx.globalAlpha = alpha * (estimated ? 0.7 : 1);
    ctx.fillStyle = COLORS.ball;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(p[0] - r * 0.25, p[1] - r * 0.3, r * 0.32, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.ballLight;
    ctx.fill();
    ctx.globalAlpha = alpha;
  }

  // Continuous runs keep the dash pattern intact; runs split where the ball is missing,
  // where its estimate changes kind, and at age steps so older flight fades out.
  function drawTrail(ctx, view, match, t) {
    const step = 1 / 60;
    const start = Math.max(0, t - TRAIL_S);
    let run = [];
    let style = "";
    const flush = () => {
      if (run.length > 1) {
        const [estimated, age] = style.split("|");
        ctx.globalAlpha = (estimated === "1" ? 0.45 : 0.85) * (1 - Number(age) * 0.28);
        ctx.setLineDash(estimated === "1" ? [2, 6] : [4, 6]);
        ctx.beginPath();
        run.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
      }
      run = [];
    };
    for (let s = start; s <= t + 1e-6; s += step) {
      const ball = ballAt(match, s);
      const point = ball && project(view, ball.position);
      if (!point) {
        flush();
        style = "";
        continue;
      }
      const estimated = ball.quality === "approximate" || ball.quality === "bridged";
      const next = `${estimated ? 1 : 0}|${Math.min(2, Math.floor((t - s) / (TRAIL_S / 3)))}`;
      if (next !== style && run.length) {
        const last = run[run.length - 1];
        flush();
        run.push(last);
      }
      style = next;
      run.push(point);
    }
    flush();
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  }

  function drawBounces(ctx, view, match, t) {
    for (const event of match.events) {
      if (event.type !== "bounce" || event.time_s > t || event.time_s < t - 6) continue;
      const age = t - event.time_s;
      const out = event.call === "OUT";
      const color = out ? COLORS.out : COLORS.line;
      ctx.globalAlpha = clamp(1 - age / 6, 0, 1) * 0.85;
      if (polygonPath(ctx, view, groundCircle(event.court_m, 0.13))) {
        ctx.fillStyle = color;
        ctx.fill();
      }
      if (age < 0.9 && polygonPath(ctx, view, groundCircle(event.court_m, 0.2 + age * 0.9))) {
        ctx.globalAlpha = 1 - age / 0.9;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }

  function drawYouGuides(ctx, view, match, you, position, t) {
    const court = match.court;
    const trail = [];
    for (let s = Math.max(0, t - YOU_TRAIL_S); s <= t; s += 1 / 15) {
      const p = playerAt(match, you, s);
      trail.push(p ? [p[0], p[1], 0.01] : null);
    }
    ctx.beginPath();
    polyline(ctx, view, trail);
    ctx.strokeStyle = "rgba(246,177,132,.75)";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();
    if (polygonPath(ctx, view, groundCircle(position, 0.5))) {
      ctx.fillStyle = "rgba(246,177,132,.14)";
      ctx.fill();
      ctx.strokeStyle = COLORS.you;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
    // Distance to your kitchen line, measured straight toward the net.
    const lineY = you.side === "near" ? court.net_y_m - court.kitchen_depth_m : court.net_y_m + court.kitchen_depth_m;
    const from = [position[0], position[1], 0.01];
    const to = [position[0], lineY, 0.01];
    const gap = Math.abs(lineY - position[1]);
    if (gap > 0.25) {
      ctx.beginPath();
      line(ctx, view, from, to);
      ctx.setLineDash([3, 4]);
      ctx.strokeStyle = "rgba(246,177,132,.8)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.setLineDash([]);
      const end = project(view, to);
      if (end) chip(`${gap.toFixed(1)} m to kitchen`, end[0], end[1] - 12, "rgba(24,45,35,.88)", COLORS.you);
    }
    const partner = you.partner && playerAt(match, you.partner, t);
    if (partner) {
      ctx.beginPath();
      line(ctx, view, from, [partner[0], partner[1], 0.01]);
      ctx.setLineDash([2, 5]);
      ctx.strokeStyle = "rgba(228,228,205,.55)";
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.setLineDash([]);
      const mid = project(view, [(position[0] + partner[0]) / 2, (position[1] + partner[1]) / 2, 0.01]);
      const spacing = Math.hypot(partner[0] - position[0], partner[1] - position[1]);
      if (mid) chip(`${spacing.toFixed(1)} m apart`, mid[0], mid[1] - 12, "rgba(24,45,35,.88)", COLORS.line);
    }
  }

  function drawFootage(ctx, view, video, camera) {
    if (video.readyState < 2) return;
    // The whole recorded frame, centred: the same frame makeView fitted the projection to.
    const height = Math.min(view.height, view.width / camera.aspect);
    const width = height * camera.aspect;
    ctx.drawImage(video, view.cx - width / 2, view.cy - height / 2, width, height);
    ctx.fillStyle = "rgba(24,45,35,.18)";
    ctx.fillRect(0, 0, view.width, view.height);
  }

  function render() {
    replay.frame = null;
    const canvas = $("replay-canvas");
    const match = replay.data;
    if (!canvas || !match || !replay.active) return;
    const { width, height } = replay.size;
    if (!width || !height) return;
    // Match the backing store to the current pixel ratio, which changes when the window
    // moves between displays.
    const dpr = window.devicePixelRatio || 1;
    const pixels = [Math.round(width * dpr), Math.round(height * dpr)];
    if (canvas.width !== pixels[0] || canvas.height !== pixels[1]) [canvas.width, canvas.height] = pixels;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = COLORS.background;
    ctx.fillRect(0, 0, width, height);
    const state = currentCamera();
    const view = makeView(state, width, height, replay.view === "camera" ? match.camera.aspect : null);
    const t = replay.time;
    const video = $("replay-video");
    const footage = replay.show.footage && replay.view === "camera" && videoReady();
    if (footage) drawFootage(ctx, view, video, match.camera);
    drawCourt(ctx, view, match.court, footage);
    drawBounces(ctx, view, match, t);

    const ball = ballAt(match, t);
    const players = replay.show.players
      ? match.players
        .map((player) => ({ player, position: playerAt(match, player, t) }))
        .filter((entry) => entry.position)
      : [];
    const you = players.find((entry) => entry.player.id === replay.you);
    if (you) drawYouGuides(ctx, view, match, you.player, you.position, t);

    for (const { position } of players) {
      if (polygonPath(ctx, view, groundCircle(position, 0.34, 0.004, 16))) {
        ctx.fillStyle = "rgba(24,45,35,.55)";
        ctx.fill();
      }
    }
    if (ball) {
      const [bx, by, bz] = ball.position;
      if (polygonPath(ctx, view, groundCircle([bx, by], 0.07 + bz * 0.03, 0.006, 12))) {
        ctx.fillStyle = `rgba(24,45,35,${clamp(0.6 - bz * 0.12, 0.2, 0.6)})`;
        ctx.fill();
      }
      ctx.beginPath();
      line(ctx, view, [bx, by, 0.01], [bx, by, bz]);
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = "rgba(228,228,205,.35)";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (replay.show.ball) {
      ctx.strokeStyle = COLORS.ballRing;
      ctx.lineWidth = 1.7;
      ctx.lineCap = "round";
      drawTrail(ctx, view, match, t);
    }

    // Painter's order: everything beyond the net from this viewpoint, the net, then the rest.
    const netY = match.court.net_y_m;
    const cameraSide = Math.sign(view.eye[1] - netY) || -1;
    const items = players.map((entry) => ({
      kind: "player",
      ...entry,
      depth: toCamera(view, [entry.position[0], entry.position[1], 1])[2],
      y: entry.position[1],
    }));
    if (ball) items.push({ kind: "ball", ball, depth: toCamera(view, ball.position)[2], y: ball.position[1] });
    const beyond = (item) => Math.sign(item.y - netY) === -cameraSide;
    const sorted = (list) => list.sort((a, b) => b.depth - a.depth);
    const boxes = [];
    const drawItem = (item) => {
      if (item.kind === "ball") {
        drawBall(ctx, view, item.ball);
        return;
      }
      const ballGround = ball?.position;
      const facing = facingFor(match, item.player, item.position, ballGround);
      const isYou = item.player.id === replay.you;
      const box = drawPlayer(ctx, view, match, item.player, item.position, facing, isYou);
      if (box) boxes.push({ box, player: item.player, isYou });
    };
    // Over the footage, keep the real players visible through their reconstructions.
    ctx.globalAlpha = footage ? 0.55 : 1;
    sorted(items.filter(beyond)).forEach(drawItem);
    if (!footage) drawNet(ctx, view, match.court);
    sorted(items.filter((item) => !beyond(item))).forEach(drawItem);
    ctx.globalAlpha = 1;

    for (const { box, player, isYou } of boxes) {
      drawBrackets(ctx, box, isYou ? COLORS.you : COLORS.bracket);
      // Over the footage the detector's own boxes name the players; only YOU is tagged.
      if (footage && !isYou) continue;
      const label = isYou ? "YOU" : player.label.toUpperCase();
      // From behind you or the recording's low camera, a tag above your head would land
      // on the far court.
      const below = isYou && (replay.view === "you" || footage);
      chip(
        label,
        (box.x1 + box.x2) / 2,
        below ? box.y2 + 14 : box.y1 - 12,
        isYou ? COLORS.you : "rgba(24,45,35,.78)",
        isYou ? COLORS.shadow : "rgba(228,228,205,.9)",
        isYou ? 0 : 1,
      );
    }
    drawLabels(ctx, boxes.map(({ box }) => box));
    replay.hits = boxes;
    drawCrosshairs(ctx, width, height);
    updateOverlays(view, state, t, ball);
  }

  function drawCrosshairs(ctx, width, height) {
    ctx.beginPath();
    for (const [x, y] of [[width * 0.085, height * 0.24], [width - 34, height - 64]]) {
      ctx.moveTo(x - 7, y);
      ctx.lineTo(x + 7, y);
      ctx.moveTo(x, y - 7);
      ctx.lineTo(x, y + 7);
    }
    ctx.strokeStyle = "rgba(168,179,155,.45)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // ---- Camera control -------------------------------------------------------------------

  function baseCamera(name, hold = false) {
    const match = replay.data;
    if (name === "camera" && match) return recordedOrbit(match.camera);
    if (name === "you" && match) {
      const player = match.players.find((p) => p.id === replay.you);
      const position = player && playerAt(match, player, replay.time);
      if (position) {
        const toward = player.side === "near" ? 1 : -1;
        return {
          target: [position[0] * 0.7 + match.court.width_m * 0.15, position[1] + toward * 3.4, 0.6],
          az: (player.side === "near" ? 0 : Math.PI) + replay.follow.az,
          el: clamp(17 * DEG + replay.follow.el, 4 * DEG, 85 * DEG),
          dist: 8.6 * replay.follow.zoom,
          fov: 52,
        };
      }
      if (hold) return null;
    }
    return orbit(VIEWS[name] || VIEWS.angle);
  }

  function currentCamera() {
    if (replay.view === "you") {
      // Hold the last framing while you're hidden instead of jumping to another view.
      const goal = baseCamera("you", true) || replay.camera || baseCamera("angle");
      if (!replay.camera) replay.camera = goal;
      const c = replay.camera;
      const k = 1 - Math.exp(-replay.frameDt * 9);
      replay.camera = {
        target: c.target.map((v, i) => v + (goal.target[i] - v) * k),
        az: c.az + angleDelta(c.az, goal.az) * k,
        el: c.el + (goal.el - c.el) * k,
        dist: c.dist + (goal.dist - c.dist) * k,
        fov: c.fov + (goal.fov - c.fov) * k,
      };
    } else if (replay.transition) {
      const { from, to, start, duration } = replay.transition;
      const f = ease(clamp((now() - start) / duration, 0, 1));
      replay.camera = {
        target: from.target.map((v, i) => v + (to.target[i] - v) * f),
        az: from.az + angleDelta(from.az, to.az) * f,
        el: from.el + (to.el - from.el) * f,
        dist: from.dist + (to.dist - from.dist) * f,
        fov: from.fov + (to.fov - from.fov) * f,
      };
      if (f >= 1) replay.transition = null;
    }
    if (!replay.camera) replay.camera = baseCamera(replay.view);
    return replay.camera;
  }

  function setView(name, animate = true) {
    if (name === "you" && !replay.you) return;
    replay.view = name;
    replay.follow = { az: 0, el: 0, zoom: 1 };
    const goal = baseCamera(name);
    if (animate && replay.camera && name !== "you") {
      replay.transition = { from: replay.camera, to: goal, start: now(), duration: 650 };
    } else if (name !== "you" || !replay.camera || !animate) {
      replay.camera = goal;
      replay.transition = null;
    }
    renderViewButtons();
    syncFootageControl();
    schedule();
  }

  function renderViewButtons() {
    document.querySelectorAll("[data-replay-view]").forEach((button) => {
      const name = button.dataset.replayView;
      button.setAttribute("aria-pressed", String(name === replay.view));
      if (name === "you") button.disabled = !replay.you;
      if (name === "camera") button.disabled = !replay.data;
    });
  }

  function orbitBy(dx, dy) {
    if (replay.view === "you") {
      replay.follow.az -= dx * 0.008;
      replay.follow.el += dy * 0.006;
    } else {
      const c = currentCamera();
      replay.transition = null;
      replay.camera = { ...c, az: c.az - dx * 0.008, el: clamp(c.el + dy * 0.006, 2 * DEG, 89.5 * DEG) };
      markFree();
    }
    schedule();
  }

  function panBy(dx, dy) {
    if (replay.view === "you") return;
    const c = currentCamera();
    const scale = c.dist * 0.0016;
    const right = [Math.cos(c.az), Math.sin(c.az)];
    const ahead = [-Math.sin(c.az), Math.cos(c.az)];
    replay.transition = null;
    replay.camera = {
      ...c,
      target: [
        clamp(c.target[0] - (right[0] * dx - ahead[0] * dy) * scale, -6, 12),
        clamp(c.target[1] - (right[1] * dx - ahead[1] * dy) * scale, -8, 21),
        c.target[2],
      ],
    };
    markFree();
    schedule();
  }

  function zoomBy(factor) {
    if (replay.view === "you") {
      replay.follow.zoom = clamp(replay.follow.zoom * factor, 0.45, 3);
    } else {
      const c = currentCamera();
      replay.transition = null;
      replay.camera = { ...c, dist: clamp(c.dist * factor, 3, 70) };
      markFree();
    }
    schedule();
  }

  function markFree() {
    if (replay.view === "free") return;
    replay.view = "free";
    renderViewButtons();
    syncFootageControl();
  }

  // ---- Playback ---------------------------------------------------------------------------

  function videoReady() {
    const video = $("replay-video");
    return Boolean(replay.session?.video_url) && video.readyState >= 2;
  }

  function videoInUse() {
    return Boolean(replay.session?.video_url) && (replay.show.video || (replay.show.footage && replay.view === "camera"));
  }

  function setTime(t, { fromVideo = false } = {}) {
    const match = replay.data;
    if (!match) return;
    replay.time = clamp(t, 0, match.duration);
    const video = $("replay-video");
    if (!fromVideo && videoInUse() && video.readyState >= 1 && Math.abs(video.currentTime - replay.time) > 0.05) {
      video.currentTime = Math.min(replay.time, (video.duration || replay.time) - 0.001);
    }
    schedule();
  }

  function setPlaying(playing) {
    const match = replay.data;
    if (!match) return;
    if (playing && replay.time >= match.duration - 0.05) setTime(0);
    replay.playing = playing;
    const video = $("replay-video");
    // A stepped recording seeks the video frame by frame instead of letting it play.
    if (videoInUse() && video.readyState >= 1 && replay.clock === null) {
      video.playbackRate = replay.speed;
      if (playing) {
        video.currentTime = Math.min(replay.time, (video.duration || replay.time) - 0.001);
        video.play().catch(() => {
          /* Autoplay can be refused; the replay clock keeps time instead. */
        });
      } else video.pause();
    }
    const button = $("replay-play");
    button.setAttribute("aria-pressed", String(playing));
    button.setAttribute("aria-label", playing ? "Pause replay" : "Play replay");
    replay.lastTick = performance.now();
    schedule();
  }

  function tick(now) {
    const dt = Math.min(0.1, (now - replay.lastTick) / 1000);
    replay.lastTick = now;
    replay.frameDt = dt;
    if (replay.playing && replay.data) {
      const video = $("replay-video");
      // While the recording plays, it is the clock, so the two views never drift apart.
      if (videoInUse() && !video.paused && !video.seeking && video.readyState >= 2) {
        replay.time = clamp(video.currentTime, 0, replay.data.duration);
      } else {
        replay.time = Math.min(replay.data.duration, replay.time + dt * replay.speed);
      }
      if (replay.time >= replay.data.duration - 1e-3 || (video.ended && videoInUse())) {
        replay.time = replay.data.duration;
        setPlaying(false);
      }
    }
    render();
  }

  function schedule() {
    if (replay.frame === null && replay.active && replay.clock === null) {
      replay.frame = requestAnimationFrame((now) => {
        replay.frame = null;
        tick(now);
        if (replay.playing || replay.transition || replay.view === "you" || replay.drag) schedule();
      });
    }
  }

  // Rallies when the analysis found them; otherwise bursts of tracked ball flight.
  function exchanges(match) {
    if (match.rallies.length) return match.rallies.map((r) => r.start_s);
    const starts = [];
    let end = -Infinity;
    for (const piece of match.ball) {
      if (piece.t0 - end > 1.5) starts.push(piece.t0);
      end = Math.max(end, piece.t1);
    }
    return starts;
  }

  function jumpRally(direction) {
    const match = replay.data;
    if (!match) return;
    const t = replay.time;
    const starts = exchanges(match);
    const target = direction > 0
      ? starts.find((start) => start > t + 0.6)
      : [...starts].reverse().find((start) => start < t - 1.2);
    if (target !== undefined) setTime(Math.max(0, target - 0.4));
    else if (direction < 0) setTime(0);
  }

  // ---- DOM ------------------------------------------------------------------------------

  function clock(value) {
    const seconds = Math.max(0, Math.floor(value));
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function updateOverlays(view, state, t, ball) {
    const match = replay.data;
    const progress = $("replay-progress");
    if (document.activeElement !== progress || !replay.scrubbing) {
      progress.value = String(Math.round((t / match.duration) * 1000));
    }
    progress.style.setProperty("--progress", `${(t / match.duration) * 100}%`);
    $("replay-current").textContent = clock(t);
    const name = replay.view === "free" ? "FREE ORBIT" : (replay.view === "camera" ? "ORIGINAL CAMERA" : replay.view === "you" ? "BEHIND YOU" : VIEWS[replay.view].name.toUpperCase());
    const az = ((Math.round(state.az / DEG) % 360) + 360) % 360;
    const coordinate = `${name}|AZ ${az}° / EL ${Math.round(state.el / DEG)}°`;
    if (coordinate !== replay.coordinateKey) {
      replay.coordinateKey = coordinate;
      const [first, second] = coordinate.split("|");
      $("replay-coordinate").replaceChildren(document.createTextNode(first), document.createElement("br"), document.createTextNode(second));
    }
    const caption = captionAt(match, t, ball);
    const key = caption || "";
    if (key !== replay.captionKey) {
      replay.captionKey = key;
      $("replay-caption").hidden = !caption;
      $("replay-caption-text").textContent = caption || "";
    }
    const now = performance.now();
    if (now - replay.liveAt > 120 || !replay.playing) {
      replay.liveAt = now;
      renderLive(t, ball);
    }
  }

  function captionAt(match, t, ball) {
    const recent = [...match.events].reverse().find((e) => e.time_s <= t && t - e.time_s <= CAPTION_S);
    if (recent) {
      if (recent.type === "bounce") {
        return `Bounce · ${recent.call === "OUT" ? "Out" : "In"}${recent.near_line ? " · close to the line" : ""}`;
      }
      if (recent.type === "net_crossing") return "Over the net";
      if (recent.type === "hit") {
        const who = match.players.find((p) => p.id === recent.player);
        if (who && who.id === replay.you) return "Possible hit · You";
        return who ? `Possible hit · ${who.label}` : "Possible hit";
      }
    }
    const rally = match.rallies.find((r) => t >= r.start_s && t <= r.end_s);
    if (rally && t - rally.start_s < CAPTION_S) return `Rally ${rally.id} · ${rally.shots} shot${rally.shots === 1 ? "" : "s"}`;
    if (!ball && replay.playing && !match.ball.some((p) => p.t0 > t - 2 && p.t0 < t + 2)) {
      return match.ball.length ? "Ball not tracked here" : "";
    }
    return "";
  }

  function stat(label, value, note) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    if (note) {
      const small = document.createElement("span");
      small.textContent = note;
      detail.append(small);
    }
    row.append(term, detail);
    return row;
  }

  function renderLive(t, ball) {
    const match = replay.data;
    const live = $("replay-live");
    const player = match?.players.find((p) => p.id === replay.you);
    if (!player) {
      live.hidden = true;
      return;
    }
    live.hidden = false;
    const position = playerAt(match, player, t);
    if (!position) {
      live.replaceChildren(stat("Right now", "Not visible", "Out of frame or hidden"));
      return;
    }
    const zone = zoneOf(match.court, player.side, position);
    const toLine = zone.behindKitchen > 0.15
      ? `${zone.behindKitchen.toFixed(1)} m behind`
      : zone.behindKitchen < -0.15 ? `${(-zone.behindKitchen).toFixed(1)} m inside` : "On the line";
    const partner = player.partner && playerAt(match, player.partner, t);
    const previous = playerAt(match, player, Math.max(0, t - 0.2));
    const speed = previous ? Math.hypot(position[0] - previous[0], position[1] - previous[1]) / Math.min(0.2, t || 0.2) : 0;
    let ballText = "Not tracked";
    let ballNote = "";
    if (ball) {
      const [bx, by, bz] = ball.position;
      const yours = player.side === "near" ? by < match.court.net_y_m : by > match.court.net_y_m;
      ballText = `${Math.hypot(bx - position[0], by - position[1]).toFixed(1)} m away`;
      ballNote = `${yours ? "Your side" : "Their side"} · ${bz.toFixed(1)} m high`;
    }
    live.replaceChildren(
      stat("Court position", zone.label),
      stat("To kitchen line", toLine),
      stat("Partner spacing", partner ? `${Math.hypot(partner[0] - position[0], partner[1] - position[1]).toFixed(1)} m` : "—"),
      stat("Ball", ballText, ballNote),
      stat("Moving", `${speed.toFixed(1)} m/s`),
    );
  }

  function renderPlayers() {
    const match = replay.data;
    const list = $("replay-players");
    if (!match) {
      list.replaceChildren();
      return;
    }
    const order = { near: 0, far: 1 };
    const players = [...match.players].sort((a, b) => order[a.side] - order[b.side] || a.label.localeCompare(b.label));
    const focused = list.contains(document.activeElement) ? document.activeElement.dataset.player : null;
    list.replaceChildren(
      ...players.map((player) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "replay-player";
        button.setAttribute("aria-pressed", String(player.id === replay.you));
        button.dataset.player = player.id;
        const name = document.createElement("strong");
        name.textContent = player.label;
        const meta = document.createElement("span");
        meta.textContent = match.synthetic ? "Synthetic player" : `${Math.round(player.coverage * 100)}% visible`;
        button.append(name, meta);
        button.addEventListener("click", () => chooseYou(player.id === replay.you ? null : player.id));
        return button;
      }),
    );
    $("replay-players-empty").hidden = players.length > 0;
    if (focused) list.querySelector(`[data-player="${focused}"]`)?.focus({ preventScroll: true });
  }

  function renderSummary() {
    const match = replay.data;
    const player = match?.players.find((p) => p.id === replay.you);
    const box = $("replay-summary");
    $("replay-you-copy").textContent = player
      ? `Following ${player.label.toLowerCase()}. Numbers are estimated from this court position, not a recognized person.`
      : "Pick your court position, or click yourself in the replay, to see your movement against the play.";
    if (!player) {
      box.hidden = true;
      return;
    }
    const summary = summarize(match, player);
    const shares = wholePercents(summary.zones);
    box.hidden = false;
    const bar = $("replay-zone-bar");
    bar.replaceChildren(
      ...Object.entries(ZONES).map(([key, label]) => {
        const part = document.createElement("span");
        part.className = `zone-${key}`;
        part.style.setProperty("--share", `${(summary.zones[key] * 100).toFixed(1)}%`);
        part.title = `${label}: ${shares[key]}%`;
        return part;
      }),
    );
    $("replay-zone-legend").replaceChildren(
      ...Object.entries(ZONES).map(([key, label]) => {
        const item = document.createElement("li");
        item.dataset.zone = key;
        item.textContent = `${label} ${shares[key]}%`;
        return item;
      }),
    );
    $("replay-totals").replaceChildren(
      stat("Distance covered", `${Math.round(summary.distance)} m`, "Estimated"),
      stat("Partner spacing", summary.spacing === null ? "—" : `${summary.spacing.toFixed(1)} m`, "Average"),
      match.synthetic
        ? stat("Tracked", "Synthetic", "Generated play")
        : stat("Tracked", `${Math.round(summary.coverage * 100)}%`, "Of the video"),
    );
  }

  // Whole percentages that still add up to 100 (largest remainders get the spare points).
  function wholePercents(fractions) {
    const entries = Object.entries(fractions).map(([key, f]) => [key, f * 100]);
    const total = entries.reduce((sum, [, v]) => sum + v, 0);
    if (!total) return Object.fromEntries(entries.map(([key]) => [key, 0]));
    const floors = entries.map(([key, v]) => [key, Math.floor(v), v - Math.floor(v)]);
    let spare = Math.round(total) - floors.reduce((sum, [, v]) => sum + v, 0);
    for (const entry of [...floors].sort((a, b) => b[2] - a[2])) {
      if (spare-- <= 0) break;
      entry[1] += 1;
    }
    return Object.fromEntries(floors.map(([key, v]) => [key, v]));
  }

  function chooseYou(id) {
    replay.you = id;
    if (replay.sessionId) {
      try {
        if (id) localStorage.setItem(`vantage.replay.you.${replay.sessionId}`, id);
        else localStorage.removeItem(`vantage.replay.you.${replay.sessionId}`);
      } catch {
        /* Storage can be unavailable; the choice still applies to this visit. */
      }
    }
    if (!id && replay.view === "you") setView("angle");
    renderPlayers();
    renderSummary();
    renderViewButtons();
    schedule();
  }

  function renderTrack() {
    const match = replay.data;
    const track = $("replay-track");
    const nodes = [];
    for (const rally of match.rallies) {
      const band = document.createElement("span");
      band.className = "replay-rally";
      band.style.left = `${(rally.start_s / match.duration) * 100}%`;
      band.style.width = `${Math.max(0.4, ((rally.end_s - rally.start_s) / match.duration) * 100)}%`;
      nodes.push(band);
    }
    for (const piece of match.ball) {
      const band = document.createElement("span");
      band.className = "replay-flight";
      band.style.left = `${(piece.t0 / match.duration) * 100}%`;
      band.style.width = `${Math.max(0.15, ((piece.t1 - piece.t0) / match.duration) * 100)}%`;
      nodes.push(band);
    }
    for (const event of match.events) {
      if (event.type !== "bounce") continue;
      const tick = document.createElement("span");
      tick.className = event.call === "OUT" ? "replay-tick is-out" : "replay-tick";
      tick.style.left = `${(event.time_s / match.duration) * 100}%`;
      nodes.push(tick);
    }
    track.replaceChildren(...nodes);
  }

  function renderAbout() {
    const match = replay.data;
    const quality = match.quality;
    const camera = match.camera;
    const list = $("replay-about-list");
    const items = [];
    if (match.synthetic) {
      items.push("Synthetic sample: generated play that follows this sample game's rallies. Nothing here was recorded.");
    } else {
      const share = Math.round(quality.ball_time_fraction * 100);
      items.push(
        `Ball flight is drawn for ${share}% of the video: ${quality.ball_fitted_s.toFixed(1)} s fitted to gravity, ${quality.ball_approximate_s.toFixed(1)} s approximate, ${quality.ball_bridged_s.toFixed(1)} s bridged across gaps.`,
      );
      const [x, y, z] = camera.position_m;
      const back = y < 0 ? `${(-y).toFixed(1)} m behind the near baseline` : `${y.toFixed(1)} m along the court`;
      items.push(
        `Your camera was about ${z.toFixed(1)} m high and ${back}${camera.focal_estimated ? ", recovered from the four court corners" : "; its lens was assumed"}.`,
      );
      for (const warning of quality.warnings) items.push(warning);
    }
    list.replaceChildren(
      ...items.map((text) => {
        const item = document.createElement("li");
        item.textContent = text;
        return item;
      }),
    );
    $("replay-label").textContent = match.synthetic ? "Synthetic sample" : "Estimated reconstruction";
  }

  function syncFootageControl() {
    const footage = document.querySelector('[data-replay-toggle="footage"]');
    const video = document.querySelector('[data-replay-toggle="video"]');
    const hasVideo = Boolean(replay.session?.video_url);
    footage.hidden = !hasVideo || replay.view !== "camera";
    video.hidden = !hasVideo;
    const overlay = replay.show.footage && replay.view === "camera" && hasVideo;
    $("replay-inset").hidden = !hasVideo || !replay.show.video || overlay;
    // Over the footage, the corner label and hint would print over the video's own text.
    $("replay-stage").classList.toggle("is-footage", overlay);
    for (const button of document.querySelectorAll("[data-replay-toggle]")) {
      button.setAttribute("aria-pressed", String(Boolean(replay.show[button.dataset.replayToggle])));
    }
  }

  function message(title, copy, busy) {
    const box = $("replay-message");
    box.hidden = !title;
    $("replay-message-title").textContent = title || "";
    $("replay-message-copy").textContent = copy || "";
    $("replay-message-ring").hidden = !busy;
    $("replay").classList.toggle("is-empty", Boolean(title));
  }

  function resize() {
    const rect = $("replay-canvas").getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    replay.size = { width: rect.width, height: rect.height };
    schedule();
  }

  async function load(session) {
    const generation = ++replay.generation;
    replay.loading = true;
    replay.error = "";
    message("Building your 3D replay…", "Placing the players and ball flight on the court.", true);
    try {
      const path = session.id === "demo" ? "/api/demo/replay" : `/api/sessions/${encodeURIComponent(session.id)}/replay`;
      const data = await globalThis.VantageAPI.request(path, undefined, { timeoutMs: 120_000 });
      if (generation !== replay.generation) return;
      replay.data = prepare(data);
      replay.dots = courtDots(replay.data.court);
      replay.facing.clear();
      let saved = null;
      try {
        saved = localStorage.getItem(`vantage.replay.you.${session.id}`);
      } catch {
        saved = null;
      }
      replay.you = replay.data.players.some((p) => p.id === saved) ? saved : null;
      $("replay-duration").textContent = clock(replay.data.duration);
      const unit = replay.data.rallies.length ? "rally" : "exchange";
      const name = unit === "rally" ? "Rally" : "Exchange";
      $("replay-prev").textContent = `‹ ${name}`;
      $("replay-next").textContent = `${name} ›`;
      $("replay-prev").setAttribute("aria-label", `Previous ${unit}`);
      $("replay-next").setAttribute("aria-label", `Next ${unit}`);
      $("replay-prev").disabled = $("replay-next").disabled = !exchanges(replay.data).length;
      message("");
      renderTrack();
      renderAbout();
      renderPlayers();
      renderSummary();
      setView("angle", false);
      const start = replay.startAt;
      setTime(start > 0.5 && start < replay.data.duration ? start : firstAction(replay.data));
    } catch (error) {
      if (generation !== replay.generation) return;
      replay.error = error.message || "Could not build the replay.";
      message("A 3D replay isn't available for this game.", replay.error, false);
    } finally {
      if (generation === replay.generation) replay.loading = false;
    }
  }

  function firstAction(match) {
    const first = match.rallies[0]?.start_s ?? match.ball[0]?.t0 ?? 0;
    return Math.max(0, first - 0.5);
  }

  function attachVideo(session) {
    const video = $("replay-video");
    if (session?.video_url) {
      if (video.getAttribute("src") !== session.video_url) video.src = session.video_url;
    } else {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
  }

  // Called by the app whenever the route or open game changes.
  function sync({ active, session, startAt = 0 }) {
    const changed = (session?.id || null) !== replay.sessionId;
    if (changed) {
      replay.generation += 1;
      replay.loading = false;
      replay.sessionId = session?.id || null;
      replay.session = session || null;
      replay.data = null;
      replay.camera = null;
      replay.transition = null;
      replay.view = "angle";
      replay.time = 0;
      replay.captionKey = "";
      setPlaying(false);
      replay.playing = false;
      $("replay-play").setAttribute("aria-pressed", "false");
      attachVideo(null);
    }
    replay.active = Boolean(active && session);
    if (!replay.active) {
      if (replay.playing) setPlaying(false);
      $("replay-video").pause();
      return;
    }
    if (session.is_temporary) {
      message("A 3D replay needs the saved game.", "Imported analyses don't include tracking data. Upload the video to analyze it on this computer.", false);
      return;
    }
    attachVideo(session);
    syncFootageControl();
    renderViewButtons();
    if (!replay.data && !replay.loading) {
      replay.startAt = startAt;
      void load(session);
    }
    requestAnimationFrame(resize);
  }

  function hitPlayer(event) {
    const rect = $("replay-canvas").getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    return replay.hits.find(({ box }) => x >= box.x1 && x <= box.x2 && y >= box.y1 - 18 && y <= box.y2);
  }

  function setupInput() {
    const stage = $("replay-stage");
    const canvas = $("replay-canvas");
    canvas.addEventListener("pointerdown", (event) => {
      if (!replay.data) return;
      canvas.setPointerCapture(event.pointerId);
      replay.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      replay.drag = {
        x: event.clientX,
        y: event.clientY,
        moved: 0,
        pan: event.shiftKey || event.button === 2,
        pinch: replay.pointers.size === 2 ? pinchDistance() : 0,
      };
      stage.focus({ preventScroll: true });
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!replay.drag) {
        canvas.style.cursor = hitPlayer(event) ? "pointer" : "grab";
        return;
      }
      replay.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      const drag = replay.drag;
      if (replay.pointers.size === 2) {
        const distance = pinchDistance();
        if (drag.pinch) zoomBy(drag.pinch / distance);
        drag.pinch = distance;
        drag.moved += 10;
        return;
      }
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      drag.x = event.clientX;
      drag.y = event.clientY;
      drag.moved += Math.abs(dx) + Math.abs(dy);
      canvas.style.cursor = "grabbing";
      if (drag.pan) panBy(dx, dy);
      else orbitBy(dx, dy);
    });
    const end = (event) => {
      replay.pointers.delete(event.pointerId);
      const drag = replay.drag;
      if (drag && drag.moved < 5 && event.type === "pointerup") {
        const hit = hitPlayer(event);
        if (hit) chooseYou(hit.player.id === replay.you ? null : hit.player.id);
      }
      if (!replay.pointers.size) replay.drag = null;
      canvas.style.cursor = "grab";
    };
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());
    canvas.addEventListener("wheel", (event) => {
      // Trackpad pinches arrive as Ctrl+wheel. Plain scrolling keeps scrolling the page
      // until the replay has focus, so reading past it never zooms by accident.
      if (!replay.data || (!event.ctrlKey && !event.metaKey && document.activeElement !== stage)) return;
      event.preventDefault();
      zoomBy(Math.exp(event.deltaY * (event.ctrlKey ? 0.01 : 0.0012)));
    }, { passive: false });
    canvas.addEventListener("dblclick", () => setView(replay.view === "free" ? "angle" : replay.view));
    const onKey = (event) => {
      if (!replay.data || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      // Inputs keep their keys; buttons keep Space and Enter; the slider keeps its arrows.
      if (target.matches("input:not([type=range]), textarea, select")) return;
      if (target.matches("button") && (event.key === " " || event.key === "Enter")) return;
      if (target.id === "replay-progress" && event.key.startsWith("Arrow")) return;
      const frame = 1 / Math.min(30, replay.data.video.fps || 30);
      const keys = {
        " ": () => setPlaying(!replay.playing),
        k: () => setPlaying(!replay.playing),
        ArrowLeft: () => setTime(replay.time - (event.shiftKey ? frame : 2)),
        ArrowRight: () => setTime(replay.time + (event.shiftKey ? frame : 2)),
        ",": () => setTime(replay.time - frame),
        ".": () => setTime(replay.time + frame),
        "[": () => jumpRally(-1),
        "]": () => jumpRally(1),
        1: () => setView("camera"),
        2: () => setView("angle"),
        3: () => setView("top"),
        4: () => setView("side"),
        5: () => setView("you"),
        "+": () => zoomBy(0.85),
        "=": () => zoomBy(0.85),
        "-": () => zoomBy(1.18),
      };
      const action = keys[event.key];
      if (action) {
        event.preventDefault();
        action();
      }
    };
    $("replay").addEventListener("keydown", onKey);
    $("replay-you").addEventListener("keydown", onKey);
    new ResizeObserver(resize).observe(canvas);
  }

  function pinchDistance() {
    const [a, b] = [...replay.pointers.values()];
    return Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
  }

  function setupControls() {
    $("replay-play").addEventListener("click", () => setPlaying(!replay.playing));
    const progress = $("replay-progress");
    progress.addEventListener("input", () => {
      if (!replay.data) return;
      replay.scrubbing = true;
      setTime((Number(progress.value) / 1000) * replay.data.duration);
    });
    progress.addEventListener("change", () => {
      replay.scrubbing = false;
    });
    $("replay-speed").addEventListener("click", () => {
      replay.speed = SPEEDS[(SPEEDS.indexOf(replay.speed) + 1) % SPEEDS.length];
      $("replay-speed").textContent = `${replay.speed}×`;
      $("replay-speed").setAttribute("aria-label", `Playback speed ${replay.speed} times`);
      $("replay-video").playbackRate = replay.speed;
    });
    $("replay-prev").addEventListener("click", () => jumpRally(-1));
    $("replay-next").addEventListener("click", () => jumpRally(1));
    document.querySelectorAll("[data-replay-view]").forEach((button) => {
      button.addEventListener("click", () => setView(button.dataset.replayView));
    });
    document.querySelectorAll("[data-replay-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const name = button.dataset.replayToggle;
        replay.show[name] = !replay.show[name];
        syncFootageControl();
        if (replay.playing && videoInUse()) setPlaying(true);
        if (!videoInUse()) $("replay-video").pause();
        schedule();
      });
    });
    const video = $("replay-video");
    video.addEventListener("loadeddata", () => {
      if (videoInUse()) video.currentTime = Math.min(replay.time, (video.duration || replay.time) - 0.001);
      schedule();
    });
    video.addEventListener("seeked", schedule);
    $("replay-inset").addEventListener("click", () => {
      replay.show.video = false;
      syncFootageControl();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("replay")) return;
    setupInput();
    setupControls();
  });

  // ---- Scripted control -------------------------------------------------------------------
  // For automation, tests, and recorded demos. Cameras use degrees for az/el and metres
  // for dist and target. `capture(true)` stops the animation loop so that time, camera
  // transitions, and the synced video advance only through `step(dt)`, frame by frame.

  function orbitDegrees(state) {
    return { target: [...state.target], az: state.az / DEG, el: state.el / DEG, dist: state.dist, fov: state.fov };
  }

  function setCamera(state) {
    const c = currentCamera();
    replay.transition = null;
    replay.camera = {
      target: state.target ? [...state.target] : c.target,
      az: state.az === undefined ? c.az : state.az * DEG,
      el: state.el === undefined ? c.el : clamp(state.el * DEG, 2 * DEG, 89.5 * DEG),
      dist: state.dist ?? c.dist,
      fov: state.fov ?? c.fov,
    };
    markFree();
    schedule();
  }

  function once(target, events, timeoutMs) {
    return new Promise((resolve) => {
      const done = () => {
        clearTimeout(timer);
        for (const name of events) target.removeEventListener(name, done);
        resolve();
      };
      const timer = setTimeout(done, timeoutMs);
      for (const name of events) target.addEventListener(name, done);
    });
  }

  async function showVideoFrame() {
    const video = $("replay-video");
    if (!videoInUse() || !video.getAttribute("src")) return;
    if (video.readyState < 1) await once(video, ["loadedmetadata", "error"], 8000);
    const target = Math.min(replay.time, (video.duration || replay.time) - 0.001);
    if (Math.abs(video.currentTime - target) > 0.005) video.currentTime = target;
    if (video.seeking || video.readyState < 2) await once(video, ["seeked", "canplay", "error"], 8000);
  }

  async function step(dt = 1 / 30) {
    if (replay.clock === null || !replay.data) return replay.time;
    replay.clock += dt * 1000;
    replay.frameDt = dt;
    if (replay.playing) {
      replay.time = Math.min(replay.data.duration, replay.time + dt * replay.speed);
      if (replay.time >= replay.data.duration) setPlaying(false);
    }
    await showVideoFrame();
    render();
    return replay.time;
  }

  globalThis.VantageReplay = Object.freeze({
    sync,
    time: () => replay.time,
    ready: () => Boolean(replay.data) && !replay.loading,
    players: () => (replay.data?.players || []).map(({ id, label, side }) => ({ id, label, side })),
    seek: (t) => setTime(t),
    play: (on = true) => setPlaying(Boolean(on)),
    speed: (value) => {
      replay.speed = value;
      $("replay-speed").textContent = `${value}×`;
    },
    view: (name, animate = false) => setView(name, animate),
    choose: (id) => chooseYou(id || null),
    toggle: (name, on) => {
      if (!(name in replay.show)) return;
      replay.show[name] = Boolean(on);
      syncFootageControl();
      schedule();
    },
    camera: (state) => (state ? setCamera(state) : orbitDegrees(currentCamera())),
    preset: (name) => orbitDegrees(baseCamera(name)),
    capture: (on) => {
      if (on) {
        if (replay.frame !== null) cancelAnimationFrame(replay.frame);
        replay.frame = null;
        replay.clock = performance.now();
        $("replay-video").pause();
      } else {
        replay.clock = null;
        replay.lastTick = performance.now();
        schedule();
      }
    },
    step,
  });
})();
