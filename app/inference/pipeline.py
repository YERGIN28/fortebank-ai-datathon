"""Sequential GPU inference, bounded sampling and optional local refinement."""
import math
from collections import Counter
from pathlib import Path
import time

from .model import ModelOutputError, QwenModel
from .schemas import ACTOR_ROLES, OBSERVATION_TYPES, InferenceConfig, InferenceResult, Observation
from .video import SampledFrame, VideoReader, iter_windows
from .postprocess import HANDHELD_ACTIONS, deduplicate, normalize_action

ERROR_CODES = {'Model response is not valid JSON': 'invalid_json',
               'Model response needs an observations list': 'invalid_model_schema',
               'Expected at most three observations': 'too_many_events',
               'Frame indexes must be integers': 'invalid_frame_index',
               'Frame index outside the sampled window': 'invalid_frame_index',
               'actors must be a list of role strings': 'invalid_actor_schema',
               'No decodable frames in window': 'no_frames'}


def safe_window_error(error):
    if isinstance(error, ModelOutputError):
        return error.code
    return ERROR_CODES.get(str(error), 'invalid_model_schema')


def parse_observations(rows: list[dict], frames: list[SampledFrame],
                       resolution: float) -> list[Observation]:
    """Validate the entire response; invalid output never becomes a negative result."""
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError('Expected at most three observations')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Observation must be an object')
        start, end = row.get('start_frame'), row.get('end_frame')
        if type(start) is not int or type(end) is not int:
            raise ValueError('Frame indexes must be integers')
        if not 0 <= start <= end < len(frames):
            raise ValueError('Frame index outside the sampled window')
        description = row.get('description')
        if not isinstance(description, str) or not description.strip() or len(description) > 2000:
            raise ValueError('Observation needs a bounded nonempty description')
        # Validate roles even when irrelevant narration will subsequently be filtered.
        raw_actors = row.get('actors', ['unknown'])
        if not isinstance(raw_actors, list) or any(not isinstance(actor, str) for actor in raw_actors):
            raise ValueError('actors must be a list of role strings')
        normalized = normalize_action(row)
        if normalized is None:
            continue
        row = normalized
        description = row['description']
        action_type = row.get('type', 'unknown')
        if not isinstance(action_type, str) or action_type not in OBSERVATION_TYPES:
            action_type = 'unknown'
        actors = row.get('actors', ['unknown'])
        if not isinstance(actors, list) or any(not isinstance(actor, str) for actor in actors):
            raise ValueError('actors must be a list of role strings')
        actors = list(dict.fromkeys(actor if actor in ACTOR_ROLES else 'unknown'
                                   for actor in actors)) or ['unknown']
        result.append(Observation(
            start_sec=frames[start].timestamp_sec,
            end_sec=frames[end].timestamp_sec,
            description=description.strip(),
            evidence_timestamps_sec=[f.timestamp_sec for f in frames[start:end + 1]],
            timing_resolution_sec=resolution,
            type=action_type, actors=actors,
            # Qwen's self-reported scores are not calibrated probabilities.
            confidence=None))
    return result


class InferenceEngine:
    """Reuse one loaded model. Call sequentially; this object is not thread safe."""
    def __init__(self, config: InferenceConfig, *, model=None):
        self.config = config
        self.model = model if model is not None else QwenModel(config)
        self._loaded = False
        self._object_checks = 0
        self._object_diagnostics = Counter()

    def load(self) -> None:
        """Explicit worker startup hook; safe to call repeatedly, sequentially."""
        if not self._loaded:
            self.model.load()
            self._loaded = True

    def _observe(self, reader, start, end, count, deadline):
        frames = reader.sample(start, end, count, deadline)
        if not frames:
            raise ValueError('No decodable frames in window')
        if time.perf_counter() >= deadline:
            raise TimeoutError('Time budget exhausted')
        # Includes the unsampled tail: timestamps do not imply frame-exact boundaries.
        boundaries = [start] + [f.timestamp_sec for f in frames] + [end]
        resolution = max(b - a for a, b in zip(boundaries, boundaries[1:]))
        rows = self.model.observe(frames, deadline)
        parse_observations(rows, frames, resolution)  # Validate indexes/schema before any extra work.
        verified_rows = []
        for row in rows:
            row = dict(row)
            normalized = normalize_action(row)
            cash_types = ('cash_handling', 'cash_transfer', 'cash_left_unattended')
            possible_cash = (normalized is not None and normalized.get('type') in cash_types)
            possible_cash |= (row.get('type') in cash_types and row.get('object_kind', 'unknown') == 'unknown')
            if possible_cash:
                # Cash needs verification; documents/unknown transfers do not trigger extra passes.
                row['object_kind'] = 'unknown'
                can_check = (self.config.verify_objects
                             and self._object_checks < self.config.max_object_checks
                             and deadline - time.perf_counter() > self.config.object_check_seconds)
                if can_check:
                    self._object_checks += 1
                    check_deadline = min(deadline, time.perf_counter() + self.config.object_check_seconds)
                    moment = (frames[row['start_frame']].timestamp_sec + frames[row['end_frame']].timestamp_sec) / 2
                    try:
                        detailed = reader.sample(moment, min(end, moment + 0.25), 1, check_deadline,
                                                 max_side=self.config.verification_frame_side)
                        if not detailed:
                            raise ValueError('No object verification frames')
                        kind = self.model.verify_object(detailed, check_deadline)
                        if time.perf_counter() >= check_deadline:
                            raise TimeoutError('Object check time budget exhausted')
                        row['object_kind'] = kind
                    except TimeoutError:
                        self._object_diagnostics['object_check_timeout'] += 1
                    except ValueError:
                        self._object_diagnostics['object_check_invalid_output'] += 1
                else:
                    self._object_diagnostics['object_check_skipped'] += 1
            verified_rows.append(row)
        return parse_observations(verified_rows, frames, resolution)

    def analyze_video(self, path: str | Path) -> InferenceResult:
        started = time.perf_counter()
        deadline = started + self.config.time_budget_seconds
        result = InferenceResult()
        self._object_checks = 0
        self._object_diagnostics.clear()
        reader = VideoReader(path, self.config.max_frame_side)
        loaded = False
        try:
            result.duration_sec = reader.duration
            step = self.config.window_seconds - self.config.overlap_seconds
            result.planned_windows = max(1, math.ceil(max(
                0, reader.duration - self.config.window_seconds) / step) + 1)
            was_loaded = self._loaded
            load_started = time.perf_counter()
            self.load()
            loaded = True
            result.model_load_sec = 0.0 if was_loaded else time.perf_counter() - load_started
            self.model.reset_metrics()
            for index, (start, end) in enumerate(iter_windows(
                    reader.duration, self.config.window_seconds, self.config.overlap_seconds)):
                if time.perf_counter() >= deadline:
                    result.status = 'timeout'
                    break
                try:
                    observations = self._observe(reader, start, end,
                        self.config.frames_per_window, deadline)
                except TimeoutError:
                    result.status = 'timeout'
                    break
                except ValueError as error:
                    result.status = 'partial'
                    result.warnings.append(f'Window {index}: {safe_window_error(error)}')
                    continue
                result.observations.extend(observations)
                result.processed_windows += 1
            result.observations = deduplicate(result.observations)
            # Coarse coverage comes first; refinement uses only remaining time.
            if self.config.refine and result.status != 'timeout':
                refined = []
                for index, observation in enumerate(result.observations):
                    if time.perf_counter() >= deadline:
                        result.status = 'timeout'
                        refined.extend(result.observations[index:])
                        break
                    margin = max(0.5, observation.timing_resolution_sec)
                    start = max(0.0, observation.start_sec - margin)
                    end = min(reader.duration, observation.end_sec + margin)
                    try:
                        candidates = self._observe(reader, start, end,
                            self.config.refinement_frames, deadline)
                        # Preserve coarse evidence when a second pass finds nothing.
                        # No semantic matching or automatic claim of confirmation.
                        if candidates:
                            for candidate in candidates:
                                candidate.refined = True
                            refined.extend(candidates)
                        else:
                            refined.append(observation)
                            result.warnings.append(f'Observation {index}: not reproduced in refinement')
                    except TimeoutError:
                        result.status = 'timeout'
                        refined.extend(result.observations[index:])
                        break
                    except ValueError:
                        refined.append(observation)
                        result.warnings.append(f'Observation {index}: refinement unavailable')
                result.observations = refined
            result.observations = deduplicate(result.observations)
            if time.perf_counter() >= deadline:
                result.status = 'timeout'
            if result.status == 'timeout':
                result.warnings.append('Time budget exhausted; do not treat as a completed analysis')
            result.warnings.extend(f'{code}: {count}' for code, count in self._object_diagnostics.items())
        finally:
            reader.close()
            result.elapsed_sec = time.perf_counter() - started
            if loaded:
                for key, value in self.model.metrics().items():
                    setattr(result, key, round(value, 2))
        return result


def analyze_video(path: str | Path, config: InferenceConfig) -> InferenceResult:
    """Convenient cold-start entry point. Reuse InferenceEngine for multiple videos."""
    return InferenceEngine(config).analyze_video(path)
