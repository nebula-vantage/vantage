"""Paddle-hit onsets from the video's audio track.

A pickleball hit is a sharp, broadband pop. It shows up as a sudden rise in
high-frequency energy over a few milliseconds, which footsteps, voices, and
wind rarely produce. Onsets are candidates: neighbouring courts and bounces on
a hard floor can also pop, so rallies corroborate them with ball tracking.
"""
import subprocess

import numpy as np


def read_audio(path, rate):
    """Mono float samples in [-1, 1], or None when the video has no audio track."""
    from imageio_ffmpeg import get_ffmpeg_exe

    command = [get_ffmpeg_exe(), "-nostdin", "-v", "error", "-i", str(path),
               "-map", "0:a:0?", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    result = subprocess.run(command, capture_output=True)
    if result.returncode and b"does not contain any stream" in result.stderr:
        return None
    if result.returncode:
        raise RuntimeError(f"Could not decode audio from {path}: {result.stderr.decode()[-500:].strip()}")
    if not result.stdout:
        return None
    return np.frombuffer(result.stdout, np.int16).astype(np.float32) / 32768


def hit_onsets(samples, rate, config):
    """Times (s) where band energy jumps by more than rise_db within one short hop."""
    cfg = config["audio"]
    hop = max(1, round(rate * cfg["hop_s"]))
    count = len(samples) // hop
    if count < 2:
        return []
    frames = np.asarray(samples[:count * hop], np.float32).reshape(count, hop)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(hop, 1 / rate)
    band = (freqs >= cfg["band_low_hz"]) & (freqs <= cfg["band_high_hz"])
    level = 10 * np.log10(power[:, band].sum(axis=1) + 1e-10)
    rise = np.diff(level, prepend=level[0])
    # Peak of each rise, so one pop spread over two hops counts once.
    peaks = np.flatnonzero((rise > cfg["rise_db"]) & (rise >= np.append(rise[1:], -np.inf)))
    onsets = []
    for index in peaks:
        time_s = index * hop / rate
        if not onsets or time_s - onsets[-1] >= cfg["min_interval_s"]:
            onsets.append(time_s)
    return onsets
