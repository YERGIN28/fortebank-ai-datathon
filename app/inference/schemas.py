"""Preliminary contract: observations, not regulatory verdicts."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import math

OBSERVATION_TYPES = (
    'cash_handling', 'cash_transfer', 'cash_left_unattended',
    'cash_drawer_opened', 'cash_drawer_closed',
    'document_handling', 'document_transfer', 'object_transfer', 'unknown',
)
OBJECT_KINDS = ('banknote', 'id_document', 'paper_document', 'unknown', 'none')
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
    refine: bool = False
    refinement_frames: int = 6
    verify_objects: bool = True
    verification_frame_side: int = 640
    max_object_checks: int = 3
    object_check_seconds: float = 6.0

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
        if type(self.verify_objects) is not bool:
            raise ValueError('verify_objects must be a boolean')
        if type(self.verification_frame_side) is not int or self.verification_frame_side < 64:
            raise ValueError('verification_frame_side must be an integer >= 64')
        if type(self.max_object_checks) is not int or self.max_object_checks < 0:
            raise ValueError('max_object_checks must be a nonnegative integer')
        if not math.isfinite(self.object_check_seconds) or self.object_check_seconds <= 0:
            raise ValueError('object_check_seconds must be finite and positive')


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
