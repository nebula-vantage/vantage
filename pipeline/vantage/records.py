"""Small shared records; every position uses native video pixel coordinates."""
from dataclasses import asdict, dataclass, field

Point = tuple[float, float]
Box = tuple[float, float, float, float]


@dataclass
class Detection:
    box: Box
    confidence: float
    track_id: int | None
    class_id: int

    @property
    def center(self) -> Point:
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, (y1 + y2) / 2)


@dataclass
class FrameRecord:
    index: int
    time_s: float
    players: list[Detection] = field(default_factory=list)
    ball: Detection | None = None
    paddles: list[Detection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrajectorySample:
    frame_index: int
    time_s: float
    pixel: Point
    court: Point | None
    source: str  # observed, interpolated, or coasted
    segment_id: int
    track_id: int | None


@dataclass
class BounceEvent:
    frame_index: int
    time_s: float
    pixel: Point
    court: Point
    call: str
    fit_improvement: float
    quality_flags: list[str] = field(default_factory=lambda: ["heuristic_bounce"])


@dataclass
class Rally:
    id: int
    start_s: float
    end_s: float
    crossing_times_s: list[float]

    @property
    def shots(self) -> int:
        return len(self.crossing_times_s)
