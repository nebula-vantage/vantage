"""Simulate one- versus two-camera bounce localization for pickleball line calls.

Monte Carlo study, not a pipeline feature. Balls with drag, gravity and a lossy bounce
land within 15 cm of a line; pinhole 1080p cameras observe them at a fixed frame rate
with independent capture phases, missed detections, pixel noise and calibration from
four clicked court corners. Four estimators recover the contact point:

- single_today: nearest observed frame, ball centre projected through the ground
  homography (what `ball_physics.detect_bounces` does now).
- single_best: one camera, a 3-D flight fit through its projection with the contact
  at ball-radius height and a gravity-plus-drag prior on acceleration.
- dual_late: single_best in each camera, fused on the court by their covariances.
  Each camera keeps its own clock; only the bounce event must be matched.
- dual_early: one 3-D hinge trajectory fitted to both cameras' rays using their
  timestamps; needs sub-frame time sync.

single_best, dual_late (per camera) and dual_early make no call when their uncertainty
across the line exceeds 10 cm, as a product would answer "too close to call" or "not
visible from here"; single_today has no uncertainty and always calls.

`selfsync` estimates the residual time offset between two unsynchronized cameras from
the ball's own motion (epipolar consistency), without audio or extra hardware.

Run from the repository root:

    uv run python pipeline/diagnostics/two_camera_feasibility.py --self-check
    uv run python pipeline/diagnostics/two_camera_feasibility.py --experiments all
"""

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

COURT_W, COURT_L = 6.10, 13.41
BALL_R = 0.037  # Pickleball diameter is 73-75.5 mm.
GRAVITY = 9.81
# 0.5 * air density * cross-section / mass for a 24.5 g ball; times Cd gives quadratic
# drag, times the lift coefficient gives the Magnus (spin) force.
AERO_K = 0.5 * 1.2 * math.pi * BALL_R**2 / 0.0245
NOMINAL_CD = 0.40
DRAG_K = AERO_K * NOMINAL_CD  # What the estimators assume.
MAX_BALL_SPEED = 30.0  # m/s; faster than any pickleball shot, used to bound fits.
SKID_NOMINAL_S = 0.003  # Assumed ball-floor contact time.
WIDTH, HEIGHT = 1920, 1080
WINDOW_S = 0.15  # Observations used on each side of the bounce.


@dataclass
class Camera:
    K: np.ndarray
    R: np.ndarray
    t: np.ndarray

    @property
    def P(self):
        return self.K @ np.hstack([self.R, self.t[:, None]])

    @property
    def centre(self):
        return -self.R.T @ self.t

    @property
    def hfov_deg(self):
        return math.degrees(2 * math.atan(WIDTH / 2 / self.K[0, 0]))

    def project(self, points):
        cam = (self.R @ np.atleast_2d(points).T).T + self.t
        depth = cam[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            pix = (self.K @ cam.T).T[:, :2] / depth[:, None]
        return pix, depth


def look_at(centre, target, margin_m=0.25, room_m=None):
    """A camera at `centre` aimed at `target`, zoomed so the court plus margin fits.

    `room_m` widens the framing behind the baseline nearest the camera, so a ball that
    bounces there stays in view longer.
    """
    centre, target = np.asarray(centre, float), np.asarray(target, float)
    forward = (target - centre) / np.linalg.norm(target - centre)
    right = np.cross(forward, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    R = np.stack([right, down, forward])
    t = -R @ centre
    m = margin_m
    near, far = (room_m or m, m) if centre[1] < COURT_L / 2 else (m, room_m or m)
    corners = np.array(
        [
            [-m, -near, 0],
            [COURT_W + m, -near, 0],
            [COURT_W + m, COURT_L + far, 0],
            [-m, COURT_L + far, 0],
        ]
    )
    cam = (R @ corners.T).T + t
    if np.any(cam[:, 2] <= 0):
        raise ValueError("Court corner behind camera")
    xn, yn = np.abs(cam[:, 0] / cam[:, 2]).max(), np.abs(cam[:, 1] / cam[:, 2]).max()
    f = min(0.95 * (WIDTH / 2) / xn, 0.95 * (HEIGHT / 2) / yn)
    K = np.array([[f, 0, WIDTH / 2], [0, f, HEIGHT / 2], [0, 0, 1.0]])
    return Camera(K, R, t)


CENTRE = (COURT_W / 2, COURT_L / 2, 0)
# Camera centres in court metres (x across, y along from the near baseline, z up). Each
# is zoomed to frame the whole court; 75-108 degrees of horizontal view needs the 0.5x
# ultra-wide lens. "today" is the pose recovered from the indoor real-match calibration
# (about 3.3 m behind the baseline, 1.6 m high).
NEAR_LEFT, NEAR_RIGHT = (-1.0, -3.5, 2.0), (COURT_W + 1.0, -3.5, 2.0)
CONFIGS = {
    "today": [look_at((3.05, -3.3, 1.6), CENTRE)],
    "single_fence": [look_at((3.05, -3.5, 3.0), CENTRE)],
    "same_baseline": [look_at(NEAR_LEFT, CENTRE), look_at(NEAR_RIGHT, CENTRE)],
    "same_baseline_fence": [
        look_at((-1.5, -3.5, 3.0), CENTRE),
        look_at((COURT_W + 1.5, -3.5, 3.0), CENTRE),
    ],
    "opposite_baselines": [
        look_at((3.05, -3.3, 1.6), CENTRE),
        look_at((3.05, COURT_L + 3.3, 1.6), CENTRE),
    ],
    "opposite_fence": [
        look_at((3.05, -3.5, 3.0), CENTRE),
        look_at((3.05, COURT_L + 3.5, 3.0), CENTRE),
    ],
    "opposite_fence_room_half": [
        look_at((3.05, -3.5, 3.0), CENTRE, room_m=0.5),
        look_at((3.05, COURT_L + 3.5, 3.0), CENTRE, room_m=0.5),
    ],
    "opposite_fence_room": [
        look_at((3.05, -3.5, 3.0), CENTRE, room_m=1.0),
        look_at((3.05, COURT_L + 3.5, 3.0), CENTRE, room_m=1.0),
    ],
    "diagonal_corners": [
        look_at(NEAR_LEFT, CENTRE),
        look_at((COURT_W + 1.0, COURT_L + 3.5, 2.0), CENTRE),
    ],
}

# Axis of the line normal, candidate lines as (coordinate, sign of "in"), landing range
# along the line, and the direction the ball travels (-1 toward the near baseline).
# Sidelines pick the left or right line per shot so no layout is favoured.
REGIONS = {
    "near baseline": dict(axis=1, lines=[(0.0, 1)], along=(0.3, COURT_W - 0.3), travel=-1),
    "near sideline": dict(axis=0, lines=[(0.0, 1), (COURT_W, -1)], along=(0.5, 6.2), travel=-1),
    "far sideline": dict(axis=0, lines=[(0.0, 1), (COURT_W, -1)], along=(7.2, 12.9), travel=1),
    "far baseline": dict(axis=1, lines=[(COURT_L, -1)], along=(0.3, COURT_W - 0.3), travel=1),
}


@dataclass
class BallPhysics:
    """True per-shot ball behaviour; the estimators only know the nominal values."""

    cd: float = NOMINAL_CD
    lift: float = 0.0  # Magnus lift coefficient: + backspin floats, - topspin dives.
    restitution: float = 0.62  # Vertical; about 32 in rebound from a 78 in drop.
    retain: float = 0.80  # Horizontal speed kept through the bounce.
    skid_s: float = 0.0  # Time the ball slides on the floor.

    @classmethod
    def sample(cls, rng):
        return cls(
            cd=rng.uniform(0.33, 0.50),
            lift=rng.uniform(-0.15, 0.15),
            restitution=rng.uniform(0.55, 0.68),
            retain=rng.uniform(0.70, 0.90),
            skid_s=rng.uniform(0.002, 0.004),
        )


def _accel(v, physics):
    """Drag, Magnus lift and gravity. Plain floats: this runs ~10^5 times per shot."""
    vx, vy, vz = v
    speed2 = vx * vx + vy * vy + vz * vz
    drag = AERO_K * physics.cd * math.sqrt(speed2)
    ax, ay, az = -drag * vx, -drag * vy, -drag * vz - GRAVITY
    if speed2 > 1e-12:
        # Magnus force perpendicular to the velocity in its vertical plane.
        nx, ny, nz = -vz * vx / speed2, -vz * vy / speed2, 1 - vz * vz / speed2
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm > 1e-12:
            lift = AERO_K * physics.lift * speed2 / norm
            ax, ay, az = ax + lift * nx, ay + lift * ny, az + lift * nz
    return ax, ay, az


def _integrate(position, velocity, duration, dt, physics):
    steps = int(round(abs(duration) / abs(dt)))
    out = np.empty((steps + 1, 3))
    out[0] = position
    p, v = tuple(float(x) for x in position), tuple(float(x) for x in velocity)

    def shift(a, b, h):
        return (a[0] + h * b[0], a[1] + h * b[1], a[2] + h * b[2])

    for i in range(steps):
        # RK4 on (p, v); a negative dt integrates backward in time.
        k1v, k1p = _accel(v, physics), v
        k2p = shift(v, k1v, 0.5 * dt)
        k2v = _accel(k2p, physics)
        k3p = shift(v, k2v, 0.5 * dt)
        k3v = _accel(k3p, physics)
        k4p = shift(v, k3v, dt)
        k4v = _accel(k4p, physics)
        p = tuple(p[j] + dt / 6 * (k1p[j] + 2 * k2p[j] + 2 * k3p[j] + k4p[j]) for j in range(3))
        v = tuple(v[j] + dt / 6 * (k1v[j] + 2 * k2v[j] + 2 * k3v[j] + k4v[j]) for j in range(3))
        out[i + 1] = p
    return out


class Flight:
    """Ball centre over time: first floor touch at t=0, sliding with the centre at
    BALL_R for the skid time, then the rebound."""

    def __init__(self, contact_xy, v_in, physics, pre_s=WINDOW_S + 0.05, post_s=WINDOW_S + 0.05):
        dt = 5e-4
        first = np.array([*contact_xy, BALL_R])
        before = _integrate(first, v_in, -pre_s, -dt, physics)[::-1]
        p = physics
        v_out = np.array([p.retain * v_in[0], p.retain * v_in[1], -p.restitution * v_in[2]])
        slide = np.array([(v_in[0] + v_out[0]) / 2, (v_in[1] + v_out[1]) / 2, 0.0])
        n_skid = int(round(p.skid_s / dt))
        skid = first + slide * (np.arange(1, n_skid + 1) * dt)[:, None]
        last = first + slide * n_skid * dt
        after = _integrate(last, v_out, post_s, dt, physics)
        self.first_touch, self.last_touch = first[:2], last[:2]
        self.times = np.concatenate(
            [
                np.arange(-len(before) + 1, 1) * dt,
                np.arange(1, n_skid + 1) * dt,
                (n_skid + np.arange(1, len(after))) * dt,
            ]
        )
        self.points = np.vstack([before, skid, after[1:]])

    def at(self, t):
        t = np.atleast_1d(t)
        return np.column_stack([np.interp(t, self.times, self.points[:, i]) for i in range(3)])


@dataclass
class Shot:
    flight: Flight
    axis: int
    line: float
    inward: int
    d: float  # True call distance inside the line: the most-inward floor contact.

    def inside(self, point):
        return self.inward * (point[self.axis] - self.line)


def sample_shot(region, rng):
    spec = REGIONS[region]
    line, inward = spec["lines"][rng.integers(len(spec["lines"]))]
    d = rng.uniform(-0.15, 0.15)  # Signed distance of the first touch inside the line.
    contact = np.zeros(2)
    contact[spec["axis"]] = line + inward * d
    contact[1 - spec["axis"]] = rng.uniform(*spec["along"])
    speed_h = rng.uniform(5, 16)
    descent = math.radians(rng.uniform(8, 35))
    if spec["axis"] == 1:
        azimuth = math.radians(rng.uniform(-20, 20))
    else:  # Cross-court balls drift toward the sideline they land near.
        azimuth = math.radians(rng.uniform(5, 25)) * -inward
    vx = speed_h * math.sin(azimuth)
    vy = speed_h * math.cos(azimuth) * spec["travel"]
    v_in = np.array([vx, vy, -speed_h * math.tan(descent)])
    return contact, v_in, spec["axis"], line, inward


def sample_flight(region, rng, realistic=True, window_s=WINDOW_S):
    """A shot whose ball stays off the floor for the observed window except its bounce."""
    while True:
        contact, v_in, axis, line, inward = sample_shot(region, rng)
        physics = BallPhysics.sample(rng) if realistic else BallPhysics()
        flight = Flight(contact, v_in, physics, pre_s=window_s + 0.05, post_s=window_s + 0.05)
        airborne = (np.abs(flight.times) <= window_s) & (
            (flight.times < 0) | (flight.times > physics.skid_s + 1e-9)
        )
        if flight.points[airborne, 2].min() >= BALL_R - 1e-6:
            shot = Shot(flight, axis, line, inward, 0.0)
            # A ball touching the line is in: any point of the skid counts.
            shot.d = max(shot.inside(flight.first_touch), shot.inside(flight.last_touch))
            return shot


@dataclass
class Settings:
    fps: float = 60.0
    pixel_sigma: float = 1.0
    miss_rate: float = 0.4  # pickleball-v1 tracks about 62% of visible balls.
    click_sigma: float = 2.0  # Court-corner click error in source pixels.
    sync_error_s: float = 0.0  # Residual offset of camera 2's clock (early fusion only).
    readout_s: float = 0.0  # Uncorrected rolling-shutter readout time.
    known_intrinsics: bool = True
    realistic_ball: bool = True  # Per-shot drag, spin, bounce and skid (see BallPhysics).
    size_dependent_misses: bool = True  # Small, distant balls are missed more often.
    assumed_skid_s: float = SKID_NOMINAL_S  # The fitted methods' skid-length guess.
    # Chance that a camera loses every frame within OCCLUSION_WINDOW_S of the bounce,
    # as when a player stands between it and the ball. Independent per camera.
    occlusion_prob: float = 0.0


OCCLUSION_WINDOW_S = 0.05


def observe(flight, camera, settings, rng, t_lo=-WINDOW_S, t_hi=WINDOW_S):
    """Frame timestamps and noisy ball-centre pixels as one camera records them."""
    period = 1 / settings.fps
    phase = rng.uniform(0, period)
    frames = np.arange(math.floor((t_lo - phase) / period), math.ceil((t_hi - phase) / period) + 1)
    stamps = phase + frames * period
    stamps = stamps[(stamps >= t_lo) & (stamps <= t_hi)]
    pix, depth = camera.project(flight.at(stamps))
    if settings.readout_s:
        capture = stamps + np.clip(pix[:, 1], 0, HEIGHT) / HEIGHT * settings.readout_s
        pix, depth = camera.project(flight.at(capture))
    visible = (depth > 0.3) & (pix[:, 0] >= 0) & (pix[:, 0] < WIDTH)
    visible &= (pix[:, 1] >= 0) & (pix[:, 1] < HEIGHT)
    miss = np.full(len(stamps), settings.miss_rate)
    if settings.size_dependent_misses:
        # The COCO detector's missed balls had a median size of 8 px (ml/README.md); no
        # figure exists for pickleball-v1. Assumed: below 8 px recall falls in
        # proportion to size, to 40% of normal at 3.2 px and under.
        diameter_px = camera.K[0, 0] * 2 * BALL_R / np.maximum(depth, 0.3)
        miss = 1 - (1 - miss) * np.clip(diameter_px / 8, 0.4, 1.0)
    visible &= rng.random(len(stamps)) >= miss
    noisy = pix[visible] + rng.normal(0, settings.pixel_sigma, (visible.sum(), 2))
    stamps = stamps[visible]
    if settings.occlusion_prob and rng.random() < settings.occlusion_prob:
        keep = np.abs(stamps) > OCCLUSION_WINDOW_S
        stamps, noisy = stamps[keep], noisy[keep]
    return stamps, noisy


COURT_CORNERS = np.array([[0, 0, 0], [COURT_W, 0, 0], [COURT_W, COURT_L, 0], [0, COURT_L, 0.0]])


@dataclass
class Calibration:
    camera: Camera  # Estimated pose with the assumed intrinsics.
    homography: np.ndarray  # Image to court, from the clicks, as court.py computes it.
    clicked: np.ndarray
    click_sigma: float  # The click error the system assumes when propagating it.


def solve_pose(clicked, K):
    # Not IPPE: on an exactly symmetric view (camera on the centre line) both of its
    # planar solutions are hundreds of pixels off. SQPnP finds the global optimum.
    _, rvec, tvec = cv2.solvePnP(COURT_CORNERS, clicked, K, None, flags=cv2.SOLVEPNP_SQPNP)
    camera = Camera(K, cv2.Rodrigues(rvec)[0], tvec.ravel())
    if camera.centre[2] <= 0:
        raise RuntimeError("Calibration placed the camera below the court")
    return camera


def calibrate(camera, settings, rng):
    """Pose and ground homography from four noisy corner clicks, like court.py."""
    pix, _ = camera.project(COURT_CORNERS)
    clicked = pix + rng.normal(0, settings.click_sigma, pix.shape)
    homography = cv2.getPerspectiveTransform(
        np.float32(clicked), np.float32(COURT_CORNERS[:, :2])
    ).astype(float)
    K = camera.K.copy()
    if not settings.known_intrinsics:
        K[0, 0] = K[1, 1] = K[0, 0] * (1 + rng.normal(0, 0.03))
    return Calibration(solve_pose(clicked, K), homography, clicked, max(settings.click_sigma, 0.5))


def apply_homography(h, point):
    p = h @ np.array([point[0], point[1], 1.0])
    return p[:2] / p[2]


def plane_homography(camera, z):
    """Maps court (x, y) on the plane at height z to pixels."""
    P = camera.P
    return np.column_stack([P[:, 0], P[:, 1], P[:, 2] * z + P[:, 3]])


def calibration_covariance(calibration, point, step=0.5):
    """Court-position covariance of a contact seen at `point` from corner-click error.

    Small near the camera, tens of centimetres at lines far from it.
    """
    pixel = apply_homography(plane_homography(calibration.camera, BALL_R), point)
    J = np.zeros((2, 8))
    for j in range(8):
        clicked = calibration.clicked.ravel().copy()
        clicked[j] += step
        moved = solve_pose(clicked.reshape(4, 2), calibration.camera.K)
        to_court = np.linalg.inv(plane_homography(moved, BALL_R))
        J[:, j] = (apply_homography(to_court, pixel) - point) / step
    return calibration.click_sigma**2 * J @ J.T


def _t_grid(span):
    return np.arange(-span, span + 1e-12, 1e-3)


def _search(solve, span, fine=True):
    """Minimize solve(t_c)[0] on a 1 ms grid, then (if fine) a 0.05 ms grid around the
    best."""
    best = None
    for grid in (_t_grid(span), None) if fine else (_t_grid(span),):
        if grid is None:
            grid = best[1] + np.arange(-1e-3, 1e-3 + 1e-12, 5e-5)
        for t_c in grid:
            result = solve(t_c)
            if result is not None and (best is None or result[0] < best[0]):
                best = (result[0], t_c, result)
        if best is None:
            return None
    return best


# Acceleration prior on each side of the bounce: gravity plus nominal drag at the fitted
# velocity, +/- 3 m/s^2 per axis for the unknown drag coefficient and spin. It is what
# makes one camera's depth observable; two cameras barely need it.
ACCEL_PRIOR_SIGMA = 3.0
PIXEL_SIGMA = 1.0  # Assumed detector noise when weighting the prior against pixels.
PIXEL_FLOOR = 0.5  # Lower bound on the residual noise estimate for covariances.
REFINE_ITERATIONS = 40
# One camera's pixels barely constrain velocity along its line of sight, so a fit can
# run away to unphysical speeds there. The refinement penalizes speed above
# SPEED_LIMIT (one-sided, so real shots are unaffected); the linear initialization uses
# a weak zero-mean ridge instead.
SPEED_LIMIT = 22.0  # m/s at contact; the simulated shots reach about 19.5.
SPEED_PENALTY_SIGMA = 2.0
INIT_VELOCITY_SIGMA = 15.0


def fit_hinge_3d(observations, estimates, span, skid_s=SKID_NOMINAL_S, min_side=3):
    """First floor touch (x, y), its covariance and the sliding velocity, from one 3-D
    flight fitted to every camera's pixels through its projection.

    Model: X(t) = C + b1 tau + c1 tau^2 before the touch (tau = t - t_c < 0); the centre
    slides at ball-radius height for the assumed skid time at the mean of the incoming
    and outgoing horizontal velocities; then X = C + slide + b2 tau' + c2 tau'^2. One
    camera is enough because the contact height is known and the acceleration is bounded
    by gravity and drag; a second camera measures depth directly. Timestamps must share
    one clock.

    A linear (algebraic) fit of the skid-free hinge initializes a damped Gauss-Newton
    refinement of the pixel error. The algebraic error alone is biased along a single
    camera's line of sight (the noisy pixel sits in its design matrix).
    """
    initial = _algebraic_hinge(observations, estimates, span, min_side)
    if initial is None:
        return None
    # The linear fit sometimes sends one side of the flight off along a camera's line
    # of sight (the noisy pixel sits in its design matrix), even behind the camera.
    # Also start from each side mirrored through a nominal bounce; keep the best fit.
    starts = [initial, _bounce_start(initial, from_pre=True), _bounce_start(initial, False)]
    refined = [r for r in (_refine(t, observations, estimates, skid_s) for t in starts) if r]
    if not refined:
        return None
    theta, cov, _ = min(refined, key=lambda r: r[2])
    # Like detect_bounces' max_outside_court_m: a contact this far off court, or a ball
    # faster than any shot, is a failed fit.
    if not (-2 <= theta[0] <= COURT_W + 2 and -2 <= theta[1] <= COURT_L + 2):
        return None
    if max(np.linalg.norm(theta[2:5]), np.linalg.norm(theta[8:11])) > MAX_BALL_SPEED:
        return None
    return theta[:2], cov, _slide(theta)[:2]


def _bounce_start(theta, from_pre):
    """theta with one side of the flight rebuilt from the other through a nominal bounce."""
    nominal = BallPhysics()
    keep = np.array([nominal.retain, nominal.retain, -nominal.restitution])
    start = theta.copy()
    if from_pre:
        start[8:11] = theta[2:5] * keep
        start[11:14] = _accel_prior(start[8:11])
    else:
        start[2:5] = theta[8:11] / keep
        start[5:8] = _accel_prior(start[2:5])
    return start


def _algebraic_hinge(observations, estimates, span, min_side):
    """Parameters [C(2), b1, c1, b2, c2, t_c] of the skid-free hinge from linear fits."""
    rows, stamps, cams = [], [], []
    for k, ((times, pixels), camera) in enumerate(zip(observations, estimates, strict=True)):
        P = camera.P
        for t, (u, v) in zip(times, pixels, strict=True):
            rows.extend([u * P[2] - P[0], v * P[2] - P[1]])
            stamps.extend([t, t])
            cams.extend([k, k])
    if len(rows) < 4 * min_side:
        return None
    a, stamps, cams = np.array(rows), np.array(stamps), np.array(cams)
    g = a[:, :3]
    rhs = -a[:, 3] - a[:, 2] * BALL_R
    weights = np.full(len(a), 0.1)  # About 1/depth until the first fit gives depths.
    prior = np.zeros((12, 14))
    prior[0:3, 5:8] = prior[3:6, 11:14] = np.eye(3)  # c = a/2 before and after.
    # A weak pull of each velocity toward zero keeps the biased algebraic solution from
    # sliding along a camera's line of sight.
    prior[6:9, 2:5] = prior[9:12, 8:11] = np.eye(3)
    prior_rhs = np.concatenate([np.tile([0.0, 0.0, -GRAVITY / 2], 2), np.zeros(6)])
    velocity_w = np.full(6, PIXEL_SIGMA / INIT_VELOCITY_SIGMA)
    # Horizontal drag is unknown until a first fit gives the velocity.
    accel_w = PIXEL_SIGMA / (ACCEL_PRIOR_SIGMA / 2)
    prior_w = np.concatenate([np.tile([0.0, 0.0, 1.0], 2) * accel_w, velocity_w])

    def solve(t_c):
        tau = stamps - t_c
        pre = tau < 0
        if min(pre.sum(), (~pre).sum()) < 2 * min_side:
            return None
        A = np.column_stack(
            [
                g[:, 0],
                g[:, 1],
                g * (tau * pre)[:, None],
                g * (tau**2 * pre)[:, None],
                g * (tau * ~pre)[:, None],
                g * (tau**2 * ~pre)[:, None],
            ]
        )
        M = np.vstack([A * weights[:, None], prior * prior_w[:, None]])
        y = np.concatenate([rhs * weights, prior_rhs * prior_w])
        try:  # Normal equations: much faster than lstsq for these small systems.
            coef = np.linalg.solve(M.T @ M + 1e-12 * np.eye(14), M.T @ y)
        except np.linalg.LinAlgError:
            return None
        resid = M @ coef - y
        return float(resid @ resid), coef

    # Two passes on a 1 ms grid are enough to start the refinement, which then moves
    # the contact time continuously.
    for _ in range(2):  # Reweight algebraic rows by 1/depth so residuals approach pixels.
        best = _search(solve, span, fine=False)
        if best is None:
            return None
        _, t_c, (_, coef) = best
        theta = np.append(coef, t_c)
        X = _flight_points(theta, stamps, 0.0)
        depth = np.array(
            [estimates[k].R[2] @ x + estimates[k].t[2] for k, x in zip(cams, X, strict=True)]
        )
        weights = 1 / np.maximum(depth, 0.3)
        prior_rhs[:6] = np.concatenate([_accel_prior(theta[2:5]), _accel_prior(theta[8:11])])
        prior_w[:6] = accel_w
    return theta


def _accel_prior(b):
    """Expected c = a/2 at velocity b. The speed is capped: along one camera's line of
    sight velocity is barely observed, and drag at an unbounded fitted speed would feed
    the error back."""
    speed = min(np.linalg.norm(b), MAX_BALL_SPEED)
    return (-DRAG_K * speed * b - np.array([0, 0, GRAVITY])) / 2


def _slide(theta):
    return np.array([(theta[2] + theta[8]) / 2, (theta[3] + theta[9]) / 2, 0.0])


def _flight_points(theta, times, skid_s, jacobian=False):
    """Modelled ball centres at `times` for theta = [C(2), b1, c1, b2, c2, t_c], and
    optionally their derivatives d X / d theta (n x 3 x 15)."""
    C = np.array([theta[0], theta[1], BALL_R])
    b1, c1, b2, c2, t_c = theta[2:5], theta[5:8], theta[8:11], theta[11:14], theta[14]
    slide = _slide(theta)
    tau = times - t_c
    pre, post = tau < 0, tau >= skid_s
    mid = ~pre & ~post
    tp, tm, ta = tau[pre][:, None], tau[mid][:, None], (tau[post] - skid_s)[:, None]
    X = np.empty((len(times), 3))
    X[pre] = C + b1 * tp + c1 * tp**2
    X[mid] = C + slide * tm
    X[post] = C + slide * skid_s + b2 * ta + c2 * ta**2
    if not jacobian:
        return X
    dX = np.zeros((len(times), 3, 15))
    dX[:, 0, 0] = dX[:, 1, 1] = 1.0
    eye = np.eye(3)
    dX[pre, :, 2:5] = eye * tp[:, :, None]
    dX[pre, :, 5:8] = eye * tp[:, :, None] ** 2
    dX[pre, :, 14] = -(b1 + 2 * c1 * tp)
    half = np.diag([0.5, 0.5, 0.0])  # d slide / d b (horizontal mean of b1 and b2)
    dX[mid, :, 2:5] = dX[mid, :, 8:11] = half * tm[:, :, None]
    dX[mid, :, 14] = -slide
    dX[post, :, 2:5] = half * skid_s
    dX[post, :, 8:11] = eye * ta[:, :, None] + half * skid_s
    dX[post, :, 11:14] = eye * ta[:, :, None] ** 2
    dX[post, :, 14] = -(b2 + 2 * c2 * ta)
    return X, dX


def _residuals(theta, observations, estimates, skid_s, jacobian=False):
    """Pixel residuals (in units of PIXEL_SIGMA), acceleration-prior residuals and,
    optionally, the Jacobian of both stacked."""
    parts, J_parts = [], []
    for (times, pixels), camera in zip(observations, estimates, strict=True):
        if len(times) == 0:
            continue
        flight = _flight_points(theta, times, skid_s, jacobian)
        X, dX = flight if jacobian else (flight, None)
        P = camera.P
        Xh = np.column_stack([X, np.ones(len(X))])
        w = Xh @ P[2]
        if np.any(w < 0.1):
            return None
        uv = np.column_stack([Xh @ P[0], Xh @ P[1]]) / w[:, None]
        parts.append(((uv - pixels) / PIXEL_SIGMA).ravel())
        if jacobian:
            dpi = (P[None, :2, :3] - uv[:, :, None] * P[None, 2:3, :3]) / w[:, None, None]
            J_parts.append(np.einsum("nij,njk->nik", dpi, dX).reshape(-1, 15) / PIXEL_SIGMA)
    sigma_c = ACCEL_PRIOR_SIGMA / 2
    prior = [(theta[5:8] - _accel_prior(theta[2:5])) / sigma_c]
    prior.append((theta[11:14] - _accel_prior(theta[8:11])) / sigma_c)
    speeds = [np.linalg.norm(theta[2:5]), np.linalg.norm(theta[8:11])]
    prior.append(np.array([max(v - SPEED_LIMIT, 0.0) / SPEED_PENALTY_SIGMA for v in speeds]))
    r = (np.concatenate(parts), np.concatenate(prior))
    if not jacobian:
        return r
    J_prior = np.zeros((8, 15))
    for row, (b, c) in ((0, (2, 5)), (3, (8, 11))):
        J_prior[row : row + 3, c : c + 3] = np.eye(3) / sigma_c
        J_prior[row : row + 3, b : b + 3] = -_accel_prior_jacobian(theta[b : b + 3]) / sigma_c
    for row, (b, speed) in ((6, (2, speeds[0])), (7, (8, speeds[1]))):
        if speed > SPEED_LIMIT:
            J_prior[row, b : b + 3] = theta[b : b + 3] / speed / SPEED_PENALTY_SIGMA
    return r, np.vstack([*J_parts, J_prior])


def _accel_prior_jacobian(b):
    speed = np.linalg.norm(b)
    if speed >= MAX_BALL_SPEED:
        return -DRAG_K * MAX_BALL_SPEED / 2 * np.eye(3)
    if speed < 1e-9:
        return np.zeros((3, 3))
    return -DRAG_K / 2 * (speed * np.eye(3) + np.outer(b, b) / speed)


def _refine(theta, observations, estimates, skid_s):
    """Levenberg-Marquardt on the pixel error; returns (theta, covariance of C, cost) or
    None if it does not converge."""

    def evaluate(th):
        out = _residuals(th, observations, estimates, skid_s, jacobian=True)
        if out is None:
            return None
        r, J = out
        return r, float(r[0] @ r[0] + r[1] @ r[1]), J

    current = evaluate(theta)
    if current is None:
        return None
    r, cost, J = current
    lam = 1e-3
    for _ in range(REFINE_ITERATIONS):
        A, grad = J.T @ J, J.T @ np.concatenate(r)
        while True:
            try:
                delta = -np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), grad)
            except np.linalg.LinAlgError:
                return None
            trial = evaluate(theta + delta)
            if trial is not None and trial[1] <= cost:
                theta, (r, cost, J), lam = theta + delta, trial, max(lam / 3, 1e-9)
                break
            lam *= 5
            if lam > 1e9:  # No downhill step left: at the minimum.
                delta = np.zeros_like(theta)
                break
        if np.all(np.abs(delta[:2]) < 2e-5) and abs(delta[14]) < 2e-6:
            break
    else:
        return None  # Not converged: no call rather than an unfinished answer.
    n = len(r[0])
    J_pix, J_prior = J[:n], J[n:]
    s2 = max(float(r[0] @ r[0]) * PIXEL_SIGMA**2 / max(n - len(theta), 1), PIXEL_FLOOR**2)
    info = J_pix.T @ J_pix * PIXEL_SIGMA**2 / s2 + J_prior.T @ J_prior
    try:
        return theta, np.linalg.inv(info)[:2, :2], cost
    except np.linalg.LinAlgError:
        return None


def single_today(times, pixels, homography):
    if len(times) == 0:
        return None
    i = int(np.argmin(np.abs(times)))  # Ideal frame choice: the one nearest contact.
    return apply_homography(homography, pixels[i]), None, None


# A camera whose uncertainty across the line exceeds the gate (the far camera at the
# near baseline is 20-75 cm) says nothing useful, so it makes no call rather than a
# coin-flip one. The floor covers unmodelled effects such as the skid-length guess.
GATE_SIGMA_M = 0.10
MODEL_FLOOR_M = 0.005


def _usable(cov):
    # An ill-conditioned fit can produce a non-positive-definite covariance: no call.
    return np.isfinite(cov).all() and np.linalg.eigvalsh(cov).min() > 0


def gate(estimate, normal, calibrations):
    """Add calibration uncertainty; drop the estimate if it is too uncertain to call."""
    if estimate is None or estimate[1] is None:
        return None
    point, cov, velocity = estimate
    cal = [calibration_covariance(c, point) for c in calibrations]
    # Cameras fitted together: their independent calibration errors combine.
    cal = cal[0] if len(cal) == 1 else np.linalg.inv(sum(np.linalg.inv(c) for c in cal))
    cov = cov + cal + np.eye(2) * MODEL_FLOOR_M**2
    if not _usable(cov) or math.sqrt(normal @ cov @ normal) > GATE_SIGMA_M:
        return None
    return point, cov, velocity


def fuse(estimates, normal):
    estimates = [e for e in estimates if e is not None]
    if not estimates:
        return None
    info = sum(np.linalg.inv(cov) for _, cov, _ in estimates)
    weighted = sum(np.linalg.inv(cov) @ point for point, cov, _ in estimates)
    cov = np.linalg.inv(info)
    # Velocity (for the skid correction) from the camera that sees this line best.
    velocity = min(estimates, key=lambda e: normal @ e[1] @ normal)[2]
    return cov @ weighted, cov, velocity


def called_distance(shot, result, assumed_skid_s):
    """Estimated call distance inside the line from a contact estimate.

    The fitted methods return the first touch and the sliding velocity; any touch of the
    line counts, so the call uses the more inward end of the modelled skid. Today's
    method has a single point.
    """
    point, _, velocity = result
    if velocity is None:
        return shot.inside(point)
    return max(shot.inside(point), shot.inside(point + velocity * assumed_skid_s))


METHODS = ("single_today", "single_best", "dual_late", "dual_early")


def run_trial(args):
    config, region, settings, seed, methods = args
    # Separate streams for the shot and each camera's calibration and frames, so a
    # camera in the same pose sees identical data in every layout.
    streams = [np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(5)]
    shot = sample_flight(region, streams[0], settings.realistic_ball)
    cameras = CONFIGS[config]
    calibrations = [calibrate(c, settings, streams[1 + 2 * k]) for k, c in enumerate(cameras)]
    observations = [
        observe(shot.flight, c, settings, streams[2 + 2 * k]) for k, c in enumerate(cameras)
    ]
    if len(observations) > 1 and settings.sync_error_s:
        times, pixels = observations[1]
        observations[1] = (times + settings.sync_error_s, pixels)
    span = 1 / settings.fps + 0.01 + 0.002  # Contact time may sit mid-skid.
    estimates = [cal.camera for cal in calibrations]
    singles = {}

    def single(k):
        if k not in singles:
            singles[k] = fit_hinge_3d(
                [observations[k]], [estimates[k]], span, settings.assumed_skid_s
            )
        return singles[k]

    normal = np.zeros(2)
    normal[shot.axis] = 1.0
    out = {}
    for method in methods:
        if method == "single_today":
            result = single_today(*observations[0], calibrations[0].homography)
        elif method == "single_best":
            result = gate(single(0), normal, calibrations[:1])
        elif len(cameras) < 2:
            continue
        elif method == "dual_late":
            gated = [gate(single(k), normal, [calibrations[k]]) for k in range(len(cameras))]
            result = fuse(gated, normal)
        else:
            joint = fit_hinge_3d(observations, estimates, span, settings.assumed_skid_s)
            result = gate(joint, normal, calibrations)
        if result is None:
            out[method] = None
            continue
        error = float(called_distance(shot, result, settings.assumed_skid_s) - shot.d)
        sigma = None if result[1] is None else float(math.sqrt(normal @ result[1] @ normal))
        out[method] = (error, sigma)
    return config, region, shot.d, out


CONFIDENT_SIGMAS = 2.0  # Call IN/OUT only this many standard deviations from the line.
BANDS_CM = (0, 2, 4, 6, 8, 10, 15)  # True distance from the line, for the band breakdown.
# Today's pipeline flags calls within CONFIG["court"]["line_tolerance_m"] as near_boundary
# ("IN (est.) ?"); its unflagged calls are the comparable "confident" ones.
TODAY_FLAG_M = 0.10


def summarize(rows, methods):
    """Per (config, method, region): |error| percentiles, median signed error, calls.

    Balls land uniformly within 15 cm of the line, in or out. Error percentiles and
    "correct" are over calls made (estimates that passed the gate). "Confident" calls
    apply the product rule: IN/OUT only when the estimate is more than 2 sigma from the
    line, otherwise "too close to call"; their share is of all shots. Today's method has
    no sigma; its confident calls are those it does not flag as near the boundary.
    "within_2sigma" is the share of errors inside 2 sigma (95.4% if sigma is honest).
    """
    table = {}
    for config, region, d, out in rows:
        for method in methods:
            if method not in out:
                continue
            key = (config, method, region)
            entry = table.setdefault(
                key,
                {
                    "errors": [],
                    "correct": 0,
                    "none": 0,
                    "n": 0,
                    "confident": 0,
                    "right": 0,
                    "z": [],
                    "band_n": np.zeros(len(BANDS_CM) - 1, int),
                    "band_confident": np.zeros(len(BANDS_CM) - 1, int),
                },
            )
            entry["n"] += 1
            band = min(int(np.searchsorted(BANDS_CM, abs(d) * 100, side="right")) - 1, 5)
            entry["band_n"][band] += 1
            if out[method] is None:
                entry["none"] += 1
                continue
            error, sigma = out[method]
            entry["errors"].append(error)
            right = (d + error > 0) == (d > 0)
            entry["correct"] += int(right)
            threshold = TODAY_FLAG_M if sigma is None else CONFIDENT_SIGMAS * sigma
            if abs(d + error) > threshold:
                entry["confident"] += 1
                entry["right"] += int(right)
                entry["band_confident"][band] += 1
            if sigma:
                entry["z"].append(abs(error) / sigma)
    summary = {}
    for key, entry in table.items():
        errors = np.abs(entry["errors"]) * 100
        made, confident = len(entry["errors"]), entry["confident"]
        summary["|".join(key)] = {
            "trials": entry["n"],
            "no_call_pct": 100 * entry["none"] / entry["n"],
            "median_abs_cm": float(np.median(errors)) if made else None,
            "p95_abs_cm": float(np.percentile(errors, 95)) if made else None,
            "bias_cm": float(np.median(entry["errors"]) * 100) if made else None,  # Robust.
            "correct_within_15cm_pct": 100 * entry["correct"] / made if made else None,
            "confident_call_pct": 100 * confident / entry["n"],
            "confident_accuracy_pct": 100 * entry["right"] / confident if confident else None,
            "confident_wrong": int(confident - entry["right"]),
            "confident_by_band_pct": {
                f"{lo}-{hi}": 100 * float(c / n) if n else None
                for lo, hi, c, n in zip(
                    BANDS_CM[:-1],
                    BANDS_CM[1:],
                    entry["band_confident"],
                    entry["band_n"],
                    strict=True,
                )
            },
            "within_2sigma_pct": (
                100 * float(np.mean(np.array(entry["z"]) <= 2)) if entry["z"] else None
            ),
        }
    return summary


def run_grid(configs, settings, trials, methods, seed, pool):
    jobs = []
    for config in configs:  # Same seeds per layout: every layout sees the same shots.
        for r_index, region in enumerate(REGIONS):
            for i in range(trials):
                jobs.append(
                    (
                        config,
                        region,
                        settings,
                        seed + 1_000_003 * r_index + 7919 * i,
                        methods,
                    )
                )
    rows = pool.map(run_trial, jobs, chunksize=16)
    return summarize(rows, methods)


# Self-synchronization from ball motion -------------------------------------------------


def fundamental(cam_a, cam_b):
    """F with x_b^T F x_a = 0."""
    R = cam_b.R @ cam_a.R.T
    t = cam_b.t - R @ cam_a.t
    tx = np.array([[0, -t[2], t[1]], [t[2], 0, -t[0]], [-t[1], t[0], 0]])
    return np.linalg.inv(cam_b.K).T @ tx @ R @ np.linalg.inv(cam_a.K)


def selfsync_trial(args):
    config, settings, seed, shots = args
    rng = np.random.default_rng(seed)
    cameras = CONFIGS[config]
    estimates = [calibrate(c, settings, rng).camera for c in cameras]
    F = fundamental(*estimates)
    true_offset = rng.uniform(-0.02, 0.02)
    tracks = []
    for _ in range(shots):
        region = list(REGIONS)[rng.integers(len(REGIONS))]
        flight = sample_flight(region, rng, settings.realistic_ball, window_s=0.25).flight
        a = observe(flight, cameras[0], settings, rng, -0.25, 0.25)
        b = observe(flight, cameras[1], settings, rng, -0.25, 0.25)
        tracks.append((a, (b[0] + true_offset, b[1])))
    period = 1 / settings.fps

    def cost(offset):
        distances = []
        for (ta, pa), (tb, pb) in tracks:
            if len(ta) < 2:
                continue
            tq = tb - offset
            j = np.searchsorted(ta, tq)
            ok = (j > 0) & (j < len(ta))
            j = np.clip(j, 1, len(ta) - 1)
            gap = ta[j] - ta[j - 1]
            ok &= gap <= 2.5 * period
            alpha = ((tq - ta[j - 1]) / gap)[:, None]
            xa = pa[j - 1] + alpha * (pa[j] - pa[j - 1])
            xa_h = np.column_stack([xa, np.ones(len(xa))])
            xb_h = np.column_stack([pb, np.ones(len(pb))])
            lines = xa_h @ F.T
            dist = np.abs((xb_h * lines).sum(1)) / np.hypot(lines[:, 0], lines[:, 1])
            distances.append(dist[ok])
        dist = np.sort(np.concatenate(distances)) if distances else np.array([])
        if len(dist) < 10:
            return math.inf
        keep = dist[: int(0.8 * len(dist))]  # Trim kinks at bounces and gaps.
        return float(np.mean(keep**2))

    grid = np.arange(-0.04, 0.04 + 1e-12, 5e-4)
    values = np.array([cost(o) for o in grid])
    best = grid[int(np.argmin(values))]
    fine = best + np.arange(-5e-4, 5e-4 + 1e-12, 2e-5)
    estimate = fine[int(np.argmin([cost(o) for o in fine]))]
    return float(estimate - true_offset)


# Experiments ---------------------------------------------------------------------------


DUAL_CONFIGS = ["same_baseline", "opposite_baselines"]
DUAL_METHODS = ("dual_late", "dual_early")


def experiment_placement(pool, trials, seed):
    configs = list(CONFIGS)
    return run_grid(configs, Settings(fps=60), trials, METHODS, seed, pool)


def experiment_fps(pool, trials, seed):
    results = {}
    for fps in (30, 60, 120, 240):
        s = Settings(fps=fps)
        configs = ["today", "same_baseline", "opposite_baselines"]
        results[str(fps)] = run_grid(configs, s, trials, METHODS, seed, pool)
    return results


def experiment_sync(pool, trials, seed):
    results = {}
    for ms in (0, 1, 2, 4, 8, 16):
        s = Settings(fps=60, sync_error_s=ms / 1000)
        results[str(ms)] = run_grid(DUAL_CONFIGS, s, trials, DUAL_METHODS, seed, pool)
    s = Settings(fps=60, readout_s=0.012)
    results["rolling_shutter_12ms"] = run_grid(DUAL_CONFIGS, s, trials, DUAL_METHODS, seed, pool)
    return results


def experiment_calibration(pool, trials, seed):
    results = {}
    for sigma in (0.0, 1.0, 2.0, 4.0):
        s = Settings(fps=60, click_sigma=sigma)
        results[str(sigma)] = run_grid(["today", *DUAL_CONFIGS], s, trials, METHODS, seed, pool)
    s = Settings(fps=60, known_intrinsics=False)
    results["unknown_focal_3pct"] = run_grid(DUAL_CONFIGS, s, trials, METHODS, seed, pool)
    # Better calibration and a better detector together.
    s = Settings(fps=60, click_sigma=1.0, miss_rate=0.2)
    results["1px_20pct_misses"] = run_grid(["today", *DUAL_CONFIGS], s, trials, METHODS, seed, pool)
    return results


def experiment_selfsync(pool, trials, seed):
    # (fps, shots, click sigma): frame rate, how many shots are pooled, calibration.
    variants = [(30, 8, 2.0), (60, 8, 2.0), (120, 8, 2.0), (60, 32, 2.0), (60, 8, 0.0)]
    results = {}
    for config in ("same_baseline", "opposite_baselines", "diagonal_corners"):
        for fps, shots, click in variants:
            s = Settings(fps=fps, click_sigma=click)
            jobs = [(config, s, seed + i, shots) for i in range(trials)]
            errors = np.abs(pool.map(selfsync_trial, jobs, chunksize=4)) * 1000
            results[f"{config}|{fps}|{shots}|{click}"] = {
                "trials": trials,
                "median_abs_ms": float(np.median(errors)),
                "p95_abs_ms": float(np.percentile(errors, 95)),
            }
    return results


def experiment_occlusion(pool, trials, seed):
    results = {}
    for p in (0.0, 0.25, 0.5):
        s = Settings(fps=60, occlusion_prob=p)
        results[str(p)] = run_grid(DUAL_CONFIGS, s, trials, METHODS, seed, pool)
    return results


def experiment_misses(pool, trials, seed):
    results = {}
    for rate in (0.2, 0.4, 0.6):
        s = Settings(fps=60, miss_rate=rate)
        results[str(rate)] = run_grid(["today", *DUAL_CONFIGS], s, trials, METHODS, seed, pool)
    return results


EXPERIMENTS = {
    "placement": experiment_placement,
    "fps": experiment_fps,
    "sync": experiment_sync,
    "calibration": experiment_calibration,
    "selfsync": experiment_selfsync,
    "misses": experiment_misses,
    "occlusion": experiment_occlusion,
}


def _raw_fit_errors(config, region, settings, seed):
    """Ungated contact errors (m) of each camera's fit and the joint fit, for checks."""
    rng = np.random.default_rng(seed)
    shot = sample_flight(region, rng, settings.realistic_ball)
    calibrations = [calibrate(c, settings, rng) for c in CONFIGS[config]]
    observations = [observe(shot.flight, c, settings, rng) for c in CONFIGS[config]]
    cameras = [c.camera for c in calibrations]
    span = 1 / settings.fps + 0.012
    skid = settings.assumed_skid_s
    fits = [fit_hinge_3d([o], [c], span, skid) for o, c in zip(observations, cameras, strict=True)]
    fits.append(fit_hinge_3d(observations, cameras, span, skid))
    return [
        None if f is None else called_distance(shot, f, settings.assumed_skid_s) - shot.d
        for f in fits
    ]


def geometry(pool, trials, seed):
    """Across-line centimetres per pixel at each line, and today's noise-free bias."""
    lines = {  # Midpoints of the line segments each region samples, and the normal axis.
        "near baseline": ([(COURT_W / 2, 0.0)], 1),
        "near sideline (left / right)": ([(0.0, 3.35), (COURT_W, 3.35)], 0),
        "far sideline (left / right)": ([(0.0, 10.05), (COURT_W, 10.05)], 0),
        "far baseline": ([(COURT_W / 2, COURT_L)], 1),
    }
    print("| camera | " + " | ".join(lines) + " |\n| --- |" + " ---: |" * len(lines))
    cameras = (("today", 0), ("single_fence", 0), ("same_baseline", 0), ("opposite_baselines", 1))
    for name, k in cameras:
        camera = CONFIGS[name][k]
        H = plane_homography(camera, BALL_R)
        cells = []
        for points, axis in lines.values():
            values = []
            for x, y in points:
                pixel = apply_homography(H, (x, y))
                J = np.zeros((2, 2))
                for i in range(2):
                    step = np.zeros(2)
                    step[i] = 0.5
                    J[:, i] = (apply_homography(np.linalg.inv(H), pixel + step) - (x, y)) / 0.5
                # Worst-direction court movement across the line per pixel.
                values.append(f"{np.linalg.norm(J[axis]) * 100:.1f}")
            cells.append(" / ".join(values))
        print(f"| {name}[{k}] at {np.round(camera.centre, 1)} | " + " | ".join(cells) + " |")
    clean = Settings(fps=120, pixel_sigma=0.0, miss_rate=0.0, click_sigma=0.0)
    clean.size_dependent_misses = False
    jobs = [
        ("today", region, clean, seed + 1_000_003 * r + 7919 * i, ("single_today",))
        for r, region in enumerate(REGIONS)
        for i in range(trials)
    ]
    rows = pool.map(run_trial, jobs, chunksize=16)
    print("\nToday's method, noise-free 120 fps, realistic ball (cm, + = toward IN):")
    for region in REGIONS:
        errors = np.array([o["single_today"][0] for _, r, _, o in rows if r == region]) * 100
        p5, p50, p95 = np.percentile(errors, [5, 50, 95])
        print(f"- {region}: median {p50:+.0f}, 5th-95th percentile {p5:+.0f} to {p95:+.0f}")


def self_check():
    """Noise-free observations of nominal physics must give the contact to millimetres."""
    clean = Settings(
        fps=120,
        pixel_sigma=0.0,
        miss_rate=0.0,
        click_sigma=0.0,
        realistic_ball=False,
        size_dependent_misses=False,
        assumed_skid_s=0.0,
    )
    for name, settings, limit in (
        ("nominal ball", clean, 0.005),
        # Unknown drag, spin, bounce and skid: the floor of what the model can do.
        (
            "realistic ball",
            Settings(
                **{**clean.__dict__, "realistic_ball": True, "assumed_skid_s": SKID_NOMINAL_S}
            ),
            None,
        ),
    ):
        worst = np.zeros(3)
        for i in range(60):
            region = list(REGIONS)[i % len(REGIONS)]
            errors = _raw_fit_errors("same_baseline", region, settings, 100 + i)
            for k, error in enumerate(errors):
                assert error is not None, (name, region, k)
                worst[k] = max(worst[k], abs(error))
        labels = ("camera 1 alone", "camera 2 alone", "both cameras")
        print(
            name, {lab: f"{w * 1000:.1f} mm" for lab, w in zip(labels, worst, strict=True)}, "worst"
        )
        if limit is not None:
            # Quadratic segments approximate drag flight: a few millimetres of model error.
            assert worst.max() < limit, worst
    for name, cams in CONFIGS.items():
        print(name, [f"{c.hfov_deg:.0f} deg hfov at {np.round(c.centre, 1)}" for c in cams])


def _cell(entry):
    if entry is None or entry["p95_abs_cm"] is None:
        return "no call"
    cell = f"{entry['p95_abs_cm']:.0f} cm / {entry['correct_within_15cm_pct']:.0f}%"
    if abs(entry["bias_cm"]) >= 3:
        cell += f" (bias {entry['bias_cm']:+.0f})"
    if entry["no_call_pct"] >= 5:
        cell += f", {entry['no_call_pct']:.0f}% none"
    return cell


def _decision_cell(entry):
    if entry is None or not entry["confident_call_pct"]:
        return "no call"
    return f"{entry['confident_call_pct']:.0f}% / {entry['confident_accuracy_pct']:.1f}%"


def markdown_table(summary, label="", cell=_cell):
    """Rows per config and method; cells are p95 |error| / correct calls within 15 cm,
    or with cell=_decision_cell, confident calls made / their accuracy."""
    keys = {}
    for key in summary:
        config, method, region = key.split("|")
        keys.setdefault((config, method), {})[region] = summary[key]
    head = f"| {label or 'setup'} | method | " + " | ".join(REGIONS) + " |"
    lines = [head, "| --- | --- |" + " ---: |" * len(REGIONS)]
    for (config, method), regions in keys.items():
        cells = " | ".join(cell(regions.get(r)) for r in REGIONS)
        lines.append(f"| {config} | {method} | {cells} |")
    return "\n".join(lines)


def print_tables(results):
    """Both tables for every setting. Coverage (within_2sigma_pct), wrong confident calls
    and the per-distance confident shares are in the JSON only."""
    decision = "\nConfident calls (|estimate| > 2 sigma): share of shots called / accuracy\n"
    for name, result in results.items():
        print(f"\n### {name}\n")
        if name == "selfsync":
            print("| setup | fps | shots pooled | corner click error | median | p95 |")
            print("| --- | ---: | ---: | ---: | ---: | ---: |")
            for key, entry in result.items():
                config, fps, shots, click = key.split("|")
                print(
                    f"| {config} | {fps} | {shots} | {float(click):.0f} px "
                    f"| {entry['median_abs_ms']:.1f} ms | {entry['p95_abs_ms']:.1f} ms |"
                )
            continue
        settings = {"default": result} if name == "placement" else result
        for setting, summary in settings.items():
            if name != "placement":
                print(f"\n{name} = {setting}\n")
            print(markdown_table(summary))
            print(decision)
            print(markdown_table(summary, cell=_decision_cell))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--experiments", default="placement", help="comma list or 'all'")
    parser.add_argument("--trials", type=int, default=300, help="per region and setting")
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--workers", type=int, default=os.cpu_count())
    parser.add_argument(
        "--output", type=Path, default=Path("output/two-camera-feasibility/summary.json")
    )
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument(
        "--geometry", action="store_true", help="cm/px per line and today's noise-free bias"
    )
    parser.add_argument("--tables", action="store_true", help="print saved results only")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    if args.geometry:
        with Pool(args.workers) as pool:
            geometry(pool, args.trials, args.seed)
        return
    if args.tables:
        print_tables(json.loads(args.output.read_text()))
        return
    names = list(EXPERIMENTS) if args.experiments == "all" else args.experiments.split(",")
    results = json.loads(args.output.read_text()) if args.output.exists() else {}
    with Pool(args.workers) as pool:
        for name in names:
            start = time.time()
            trials = max(args.trials // 3, 20) if name == "selfsync" else args.trials
            results[name] = EXPERIMENTS[name](pool, trials, args.seed)
            print(f"{name}: {time.time() - start:.0f} s", file=sys.stderr)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2))
    print_tables({n: results[n] for n in names})


if __name__ == "__main__":
    main()
