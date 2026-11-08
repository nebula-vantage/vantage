from copy import deepcopy

from vantage.config import CONFIG
from vantage.records import Detection, FrameRecord, TrajectorySample


def settings():
    return deepcopy(CONFIG)


def record(index, x=100.0, y=100.0, fps=30.0, track_id=1):
    return FrameRecord(
        index, index / fps, ball=Detection((x - 2, y - 2, x + 2, y + 2), 0.9, track_id, 32)
    )


def sample(index, x=3.0, y=5.0, fps=30.0, segment=0, source="observed"):
    return TrajectorySample(index, index / fps, (x * 20, y * 20), (x, y), source, segment, 1)


def sign_in(server, name="Test Player", email="player@example.com", password="correct horse"):
    """Create the server's account and return the Cookie header a signed-in browser sends."""
    _, token = server.accounts.create(name, email, password)
    return f"vantage_session_{server.server_port}={token}"
