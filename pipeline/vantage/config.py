"""All tunable choices live here; distances are metres and times are seconds."""

CONFIG = {
    # Replace this whole entry on one line to use custom weights and class IDs.
    "model": {"path": "yolo26n.pt", "classes": {"player": 0, "ball": 32, "paddle": 38}},
    "detection": {
        "confidence": 0.10,  # Preserve weak raw ball observations.
        "player_confidence": 0.25,  # Display threshold for people.
        "ball_confidence": 0.10,  # Raw ball candidate threshold.
        "paddle_confidence": 0.20,  # Paddle proxy threshold.
        "iou": 0.70,  # Detector suppression overlap threshold.
        "image_size": 1280,  # Larger input helps with a small, distant ball.
        "device": "cpu",  # Portable default; set to 'mps' or '0' for acceleration.
        "max_detections": 100,  # Cap predictions per frame.
        "max_motion_diagonals_s": 2.0,  # Reject impossible image-plane ball jumps.
        "motion_slack_diagonals": 0.015,  # Permit detector jitter.
        "candidate_reset_s": 0.20,  # Start a new ball identity after this loss.
    },
    "ball_tracker": {
        "confirmation_window_s": 0.20,  # Acquire from two recent observations.
        "min_confirmation_motion_diagonals": 0.003,  # Reject stationary acquisition.
        "prediction_slack_diagonals": 0.015,  # Position uncertainty near prediction.
        "max_acceleration_diagonals_s2": 12.0,  # Expand prediction gate with elapsed time.
        "velocity_smoothing_s": 0.04,  # Time-based smoothing, independent of frame rate.
        "confidence_weight": 0.15,  # Prefer motion consistency over confidence.
        "turn_window_s": 0.10,  # Permit abrupt direction changes over short gaps.
        "stationary_timeout_s": 0.40,  # Release a track stuck on background clutter.
        "stationary_radius_diagonals": 0.004,  # Tolerate stationary detection jitter.
        # Static-clutter suppression: ignore candidates at a spot that keeps producing
        # detections (leaves, debris, signs). Time-based, so independent of frame rate.
        "static_memory_s": 3.0,  # Candidate history window.
        "static_min_age_s": 1.0,  # Spot must have been seen at least this long ago...
        "static_min_observed_s": 0.25,  # ...for at least this much frame time in the window.
        "static_radius_diagonals": 0.006,  # Same-spot distance.
        "static_max_frame_gap_s": 0.10,  # Cap one frame's observation weight across gaps.
    },
    "tracker": {
        "tracker_type": "bytetrack",  # Player tracking only; balls use motion association.
        "track_high_thresh": 0.15,  # First-stage matching confidence.
        "track_low_thresh": 0.05,  # Recovery confidence floor.
        "new_track_thresh": 0.15,  # Minimum confidence to start a track.
        "track_buffer_s": 1.0,  # Lifetime of an unmatched track, converted using FPS.
        "match_thresh": 0.80,  # ByteTrack association distance threshold.
        "fuse_score": True,  # Fuse confidence into association cost.
    },
    "court": {
        "width_m": 6.10,  # Official doubles/singles court width.
        "length_m": 13.41,  # Full baseline-to-baseline length.
        "preview_width": 1280,  # Maximum calibration window width.
        "preview_height": 800,  # Maximum calibration window height.
        "min_area_fraction": 0.005,  # Reject near-degenerate calibration polygons.
        "line_tolerance_m": 0.10,  # Flag line calls within this boundary distance.
        "projection_epsilon": 1e-9,  # Reject points at the homography horizon.
        "boundary_epsilon_m": 1e-5,  # Floating-point tolerance on inclusive lines.
        "gui_poll_ms": 30,  # UI event polling interval.
    },
    "trajectory": {
        "interpolate_gap_s": 0.20,  # Maximum endpoint separation for interpolation.
        "coast_s": 0.10,  # Extrapolation for display only.
        "smooth_window_s": 0.12,  # Total local polynomial fit window.
        "smooth_degree": 2,  # Quadratic trajectory fit.
        "max_projected_speed_kmh": 180.0,  # Reject projection spikes, not a speed claim.
    },
    "bounce": {
        "max_outside_court_m": 2.0,  # Reject contact projections far outside this court.
        "fit_half_window_s": 0.12,  # Fit raw image-y motion on each side of a kink.
        "min_side_observations": 3,  # Independent observed support on each side.
        "min_vertical_velocity_heights_s": 0.03,  # Require descent and ascent.
        "min_fit_improvement": 0.45,  # Relative error reduction versus one line.
        "min_single_rmse_height": 0.0008,  # Do not classify tiny jitter as a bounce.
        "cooldown_s": 0.25,  # Merge nearby candidate peaks.
        "paddle_radius_diagonals": 0.045,  # Suppress possible paddle contacts.
        "marker_duration_s": 1.25,  # How long bounce labels remain visible.
    },
    "stats": {
        "net_deadband_m": 0.25,  # Crossing must clear both sides of the net.
        "crossing_support_s": 0.04,  # Stable observed support on each side.
        "crossing_cooldown_s": 0.20,  # Debounce repeated net crossings.
        "speed_smooth_window_s": 0.25,  # Local median speed filter.
        "low_coverage_fraction": 0.30,  # Warn when ball evidence is sparse.
    },
    "audio": {
        "sample_rate": 16000,  # Decoded mono rate; covers the pop's 1-6 kHz band.
        "hop_s": 0.005,  # A paddle pop rises within a few milliseconds.
        "band_low_hz": 1000,  # Below this is wind, footsteps, and voices.
        "band_high_hz": 6000,
        "rise_db": 11.0,  # Band-energy jump within one hop that counts as a hit.
        "min_interval_s": 0.2,  # Echoes and double peaks of one hit count once.
    },
    "rallies": {
        "max_gap_s": 4.0,  # Longer without a hit (or, without audio, other evidence) ends a rally.
        "min_hits": 3,  # Serve, return, and a third shot; fewer is feeding balls back.
        "min_ball_fraction": 0.15,  # Tracked-ball share of frames; rejects pops from other courts.
        "min_duration_s": 1.0,  # Shorter evidence is a toss or retrieval, not a point.
        # Fallback when the video has no audio; unreliable for behind-baseline cameras,
        # where an airborne ball's court projection is meaningless.
        "min_ball_speed_kmh": 8.0,  # Slower projected motion (held, carried, rolling) is not evidence.
        "min_crossings": 1,  # A point crosses the net at least once.
        "lead_in_s": 1.0,  # Kept before a rally so cuts include the serve motion.
        "lead_out_s": 1.0,  # Kept after the last evidence so cuts don't end abruptly.
    },
    "motion": {
        "projection_margin_m": 2.0,  # Limit unstable court projections beyond the playing area.
        "max_pair_gap_s": 0.10,  # Motion needs consecutive frames within this time gap.
        "player_max_speed_m_s": 12.0,  # Reject identity switches and detector jumps.
        "player_smoothing_s": 0.10,  # Causal foot-position smoothing.
        "player_min_step_m": 0.05,  # Accumulated displacement needed to reduce jitter.
        "hit_min_turn_degrees": 60.0,  # Direction change around a paddle observation.
        "hit_min_speed_diagonals_s": 0.05,  # Ignore tiny stationary-ball jitter.
        "hit_paddle_margin_diagonals": 0.015,  # Distance from ball centre to paddle box.
        "hit_cooldown_s": 0.25,  # Avoid repeated contact candidates for one turn.
    },
    "heatmap": {
        "margin_m": 2.0,  # Keep nearby out-of-bounds landings visible.
        "sigma_m": 0.40,  # Gaussian smoothing radius (standard deviation in metres).
        "pixels_per_m": 60,  # Same scale on both axes; preserves court proportions.
        "kitchen_depth_m": 2.1336,  # Seven feet on each side of the net.
    },
    "visual": {
        "trail_length": 15,  # Last positions in a continuous trajectory.
        "codec": "mp4v",  # Widely supported OpenCV MP4 encoder.
        "player_color": (70, 210, 80),  # OpenCV BGR colours.
        "ball_color": (0, 240, 255),
        "estimated_color": (0, 165, 255),
        "in_color": (80, 220, 80),
        "out_color": (70, 70, 255),
        "text_color": (255, 255, 255),
        "panel_color": (25, 25, 25),
        "reference_height": 720,  # Scale overlay sizes with resolution.
        "min_scale": 0.30,  # Keep overlays visible on small videos.
        "font_scale": 0.60,  # Text size at reference height.
        "line_width": 2,  # Base stroke width.
        "point_radius": 4,  # Trail and calibration dot radius.
        "bounce_radius": 9,  # Bounce event ring radius.
        "margin": 12,  # Panel inset and padding in reference pixels.
        "line_height": 25,  # Text row spacing in reference pixels.
        "panel_alpha": 0.75,  # Background opacity.
        "trail_min_alpha": 0.15,  # Oldest trail point brightness.
    },
    "runtime": {
        "progress_every_s": 5.0,  # Wall-clock progress reporting interval.
        "fps_relative_tolerance": 1e-3,  # Encoder metadata rounding tolerance.
        "frame_count_tolerance": 1,  # Container metadata rounding allowance.
        "schema_version": 2,  # Adds tracking provenance, evidence, and event exports.
    },
}
