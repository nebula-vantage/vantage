"""All tunable choices live here; distances are metres and times are seconds."""

CONFIG = {
    # Replace this whole entry on one line to use custom weights and class IDs.
    "model": {"path": "yolo26n.pt", "classes": {"player": 0, "ball": 32, "paddle": 38}},
    "detection": {
        "confidence": 0.10,  # Let ByteTrack recover weak ball observations.
        "player_confidence": 0.25,  # Display threshold for people.
        "ball_confidence": 0.10,  # Ball candidate threshold after tracking.
        "paddle_confidence": 0.20,  # Paddle proxy threshold.
        "iou": 0.70,  # Detector suppression overlap threshold.
        "image_size": 1280,  # Larger input helps with a small, distant ball.
        "device": "cpu",  # Portable default; set to 'mps' or '0' for acceleration.
        "max_detections": 100,  # Cap predictions per frame.
        "max_motion_diagonals_s": 2.0,  # Reject impossible image-plane ball jumps.
        "motion_slack_diagonals": 0.015,  # Permit detector jitter.
        "candidate_reset_s": 0.20,  # Reacquire without a motion gate after a gap.
    },
    "tracker": {
        "tracker_type": "bytetrack",  # Explicitly select Ultralytics ByteTrack.
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
        "rally_gap_s": 2.0,  # Missing ball or sustained inactivity ends a rally.
        "inactive_speed_kmh": 1.0,  # Court-projected inactivity threshold.
        "speed_smooth_window_s": 0.25,  # Local median speed filter.
        "low_coverage_fraction": 0.30,  # Warn when ball evidence is sparse.
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
        "schema_version": 1,  # JSON format version.
    },
}
