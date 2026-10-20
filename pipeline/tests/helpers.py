from copy import deepcopy
import math

import numpy as np

from config import CONFIG
from records import Detection, FrameRecord, TrajectorySample


def settings():
    return deepcopy(CONFIG)


def record(index, x=100.0, y=100.0, fps=30.0, track_id=1):
    return FrameRecord(index, index / fps, ball=Detection((x-2, y-2, x+2, y+2), 0.9, track_id, 32))


def sample(index, x=3.0, y=5.0, fps=30.0, segment=0, source="observed"):
    return TrajectorySample(index, index/fps, (x*20, y*20), (x, y), source, segment, 1)
