"""Preliminary contract: observations, not regulatory verdicts."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import math

OBSERVATION_TYPES = ('cash_left_unattended', 'unknown')
ACTOR_ROLES = ('cashier', 'customer', 'unknown')


@dataclass(frozen=True)
class InferenceConfig:
    model_path: Path
    window_seconds: float = 8.0
    overlap_seconds: float = 2.0
    frames_per_window: int = 4
    max_frame_side: int = 448
    max_new_tokens: int = 256
    time_budget_seconds: float = 300.0
    refine: bool = True
    refinement_frames: int = 6

    def __post_init__(self):
        for name in ('window_seconds', 'overlap_seconds', 'time_budget_seconds'):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f'{name} must be finite')
        if self.window_seconds <= 0 or not 0 <= self.overlap_seconds < self.window_seconds:
            raise ValueError('Require 0 <= overlap_seconds < window_seconds')
        if self.time_budget_seconds <= 0:
            raise ValueError('time_budget_seconds must be positive')
        for name in ('frames_per_window', 'refinement_frames', 'max_new_tokens'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if not isinstance(self.max_frame_side, int) or self.max_frame_side < 64:
            raise ValueError('max_frame_side must be an integer >= 64')


@dataclass
class Observation:
    start_sec: float
    end_sec: float
    description: str
    evidence_timestamps_sec: list[float]
    timing_resolution_sec: float
    refined: bool = False
    type: str = 'unknown'
    confidence: float | None = None
    actors: list[str] = field(default_factory=lambda: ['unknown'])


@dataclass
class InferenceResult:
    status: str = 'complete'
    observations: list[Observation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    processed_windows: int = 0
    planned_windows: int = 0
    duration_sec: float = 0.0
    elapsed_sec: float = 0.0
    model_load_sec: float = 0.0
    gpu_peak_allocated_mib: float = 0.0
    gpu_peak_reserved_mib: float = 0.0

    def to_dict(self):
        return asdict(self)
