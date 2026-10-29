from copy import deepcopy
import math

import numpy as np

from vantage.config import CONFIG
from vantage.records import Detection, FrameRecord, TrajectorySample


def settings():
    return deepcopy(CONFIG)


def record(index, x=100.0, y=100.0, fps=30.0, track_id=1):
    return FrameRecord(index, index / fps, ball=Detection((x-2, y-2, x+2, y+2), 0.9, track_id, 32))


def sample(index, x=3.0, y=5.0, fps=30.0, segment=0, source="observed"):
    return TrajectorySample(index, index/fps, (x*20, y*20), (x, y), source, segment, 1)


AUDIO_RATE = 16000


def noise(seconds, level=0.01, seed=0):
    return np.random.default_rng(seed).normal(0, level, int(seconds * AUDIO_RATE)).astype(np.float32)


def add_pop(signal, time_s, amplitude=0.6):
    """A few milliseconds of broadband energy with a fast decay, like a paddle hit."""
    start = int(time_s * AUDIO_RATE)
    length = int(0.01 * AUDIO_RATE)
    burst = np.random.default_rng(int(time_s * 1000)).normal(0, amplitude, length) * np.exp(-np.arange(length) / 40)
    signal[start:start + length] += burst.astype(np.float32)
