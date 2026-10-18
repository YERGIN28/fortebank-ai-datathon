"""Sequential GPU inference, bounded sampling and optional local refinement."""
import math
import json
from dataclasses import replace
from collections import Counter
from pathlib import Path
import time

from .model import ModelOutputError, QwenModel, parse_service_context
from .schemas import ACTOR_ROLES, OBSERVATION_TYPES, MAX_EVENTS_PER_WINDOW, InferenceConfig, InferenceResult, Observation
from .video import SampledFrame, VideoReader, iter_windows
from .postprocess import HANDHELD_ACTIONS, deduplicate, normalize_action
from .conditions import CONDITION_SPECS, UNSUPPORTED_ABSENCE_ACTIONS, parse_condition_checks

ERROR_CODES = {'Model response is not valid JSON': 'invalid_json',
               'Model response needs an observations list': 'invalid_model_schema',
               'Expected at most three observations': 'too_many_events',
               'Event count exceeds defensive limit': 'too_many_events',
               'Frame indexes must be integers': 'invalid_frame_index',
               'Frame index outside the sampled window': 'invalid_frame_index',
               'actors must be a list of role strings': 'invalid_actor_schema',
               'No decodable frames in window': 'no_frames'}


def context_order(observations):
    """Give distinct candidate categories a first check before repeated ones.

    No dataset identifiers or labels participate. Results are sorted back by time.
    """
    priority = {name: rank for rank, name in enumerate((
        'cash_left_unattended', 'workstation_left_with_screen_on', 'safe_left_open',
        'key_left_in_safe_lock', 'cash_on_desk_with_next_customer',
        'cashier_leaves_during_service', 'customer_leaves_during_cash_check',
        'cash_on_desk_during_break', 'cash_left_after_counting'))}
    occurrences = Counter()
    queued = []
    for observation in observations:
        occurrence = occurrences[observation.type]
        occurrences[observation.type] += 1
        queued.append(((occurrence, priority.get(observation.type, len(priority)),
                        observation.start_sec, observation.end_sec), observation))
    return [observation for _, observation in sorted(queued, key=lambda item: item[0])]


def context_targets(observation, duration, count=6):
    """Retain up to four seed evidence points and add before/after context."""
    limit = max(0.0, duration - 1e-6)
    evidence = sorted(set(min(limit, max(0.0, t)) for t in observation.evidence_timestamps_sec))
    if len(evidence) > count - 2:
        evidence = [evidence[round(i * (len(evidence)-1)/(count-3))] for i in range(count-2)]
    targets = set(evidence)
    targets.update((max(0.0, observation.start_sec-3.0), min(limit, observation.end_sec+3.0)))
    while len(targets) < count:
        ordered = sorted(targets)
        gaps = [(b-a,a,b) for a,b in zip(ordered,ordered[1:]) if b-a>0.2]
        if not gaps:
            break
        _,a,b=max(gaps)
        targets.add((a+b)/2)
    return sorted(targets)


def safe_window_error(error):
    if isinstance(error, ModelOutputError):
        return error.code
    return ERROR_CODES.get(str(error), 'invalid_model_schema')


def parse_observations(rows: list[dict], frames: list[SampledFrame],
                       resolution: float) -> list[Observation]:
    """Validate the entire response; invalid output never becomes a negative result."""
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS_PER_WINDOW:
        raise ValueError('Event count exceeds defensive limit')
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
        self._stage_timings = Counter()
        self._service_checks = 0
        self._positive_checks = 0

    def _timed(self, stage, operation, *args, **kwargs):
        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            # Include failed/timed-out calls. Never record inputs or model output.
            self._stage_timings[stage] += time.perf_counter() - started

    def load(self) -> None:
        """Explicit worker startup hook; safe to call repeatedly, sequentially."""
        if not self._loaded:
            self.model.load()
            self._loaded = True

    def _observe(self, reader, start, end, count, deadline):
        frames = self._timed('decode', reader.sample, start, end, count, deadline)
        if not frames:
            raise ValueError('No decodable frames in window')
        if time.perf_counter() >= deadline:
            raise TimeoutError('Time budget exhausted')
        # Includes the unsampled tail: timestamps do not imply frame-exact boundaries.
        boundaries = [start] + [f.timestamp_sec for f in frames] + [end]
        resolution = max(b - a for a, b in zip(boundaries, boundaries[1:]))
        if self.config.check_relevance and hasattr(self.model, 'check_relevance'):
            gate_deadline = min(deadline, time.perf_counter() + self.config.relevance_check_seconds)
            try:
                relevant = self._timed('relevance', self.model.check_relevance, frames, gate_deadline)
                if time.perf_counter() >= deadline:
                    raise TimeoutError('Time budget exhausted')
                if time.perf_counter() < gate_deadline and relevant is False:
                    self._object_diagnostics['relevance_rejected'] += 1
                    return []
            except (ValueError, TimeoutError):
                if time.perf_counter() >= deadline:
                    raise TimeoutError('Time budget exhausted') from None
                self._object_diagnostics['relevance_fallback'] += 1
        rows = self._timed('observe', self.model.observe, frames, deadline)
        parse_observations(rows, frames, resolution)  # Validate indexes/schema before any extra work.
        if len(rows) > 2:
            self._object_diagnostics['event_count_above_target'] += 1
        verified_rows = []
        for row in rows:
            row = dict(row)
            normalized = normalize_action(row)
            cash_types = ('cash_handling', 'cash_transfer', 'cash_left_unattended', 'cash_returned_after_check')
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
                        detailed = self._timed('decode', reader.sample, moment, min(end, moment + 0.25), 1, check_deadline,
                                                 max_side=self.config.verification_frame_side)
                        if not detailed:
                            raise ValueError('No object verification frames')
                        kind = self._timed('verify_object', self.model.verify_object, detailed, check_deadline)
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
        self._stage_timings.clear()
        self._service_checks = 0
        self._positive_checks = 0
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
            # Departure does not require visible banknotes. Keep evidence separate
            # from the category; the Rule Engine alone decides the final verdict.
            contextual = []
            for observation in context_order(result.observations):
                if observation.type in UNSUPPORTED_ABSENCE_ACTIONS:
                    self._object_diagnostics['procedure_gap_unresolved'] += 1
                    contextual.append(observation)
                    continue
                if result.status != 'complete' or observation.type not in (
                        'cashier_leaves_during_service', *CONDITION_SPECS):
                    contextual.append(observation)
                    continue
                if (self._service_checks >= self.config.max_service_checks
                        or deadline - time.perf_counter() <= self.config.service_check_seconds):
                    self._object_diagnostics['service_context_skipped'] += 1
                    contextual.append(observation)
                    continue
                self._service_checks += 1
                check_deadline = min(deadline, time.perf_counter() + self.config.service_check_seconds)
                start = max(0, observation.start_sec - 6)
                end = min(reader.duration, observation.end_sec + 6)
                try:
                    frames = self._timed('decode', reader.sample_evidence,
                                         context_targets(observation, reader.duration), check_deadline,
                                         max_side=self.config.verification_frame_side)
                    if len(frames) < 2:
                        raise ValueError('Insufficient context frames')
                    if observation.type == 'cashier_leaves_during_service':
                        checks = self._timed('service_context', self.model.check_service_context, frames, check_deadline)
                        checks = parse_service_context(json.dumps(checks), len(frames))
                    else:
                        checks = self._timed('service_context', self.model.check_conditions,
                                             frames, observation.type, check_deadline)
                        checks = parse_condition_checks(json.dumps(checks), observation.type, len(frames))
                    if time.perf_counter() >= check_deadline:
                        raise TimeoutError('Context check exhausted budget')
                    # Explicit visual counterevidence rejects a candidate. Unclear,
                    # missing or timed-out evidence never silently becomes negative.
                    if any(check['state'] == 'refuted' for check in checks.values()):
                        self._object_diagnostics['service_context_refuted'] += 1
                        continue
                    if self.config.verify_positive_conditions and all(
                            check['state'] == 'observed' for check in checks.values()):
                        # A second answer is not an independent model. It is a consistency
                        # check on a denser sample, blind to the first answer.
                        supported = False
                        can_verify = (self._positive_checks < self.config.max_positive_checks
                                      and deadline - time.perf_counter() > self.config.positive_check_seconds)
                        if can_verify:
                            self._positive_checks += 1
                            verify_deadline = min(deadline, time.perf_counter() + self.config.positive_check_seconds)
                            try:
                                # Retain the exact before/after evidence. A narrower new
                                # interval can omit the transition that created the candidate.
                                detail = frames
                                if len(detail) < 2:
                                    raise ValueError('Insufficient verification frames')
                                secondary = self._timed('service_context', self.model.verify_positive_conditions,
                                    detail, observation.type, verify_deadline)
                                if observation.type == 'cashier_leaves_during_service':
                                    secondary = parse_service_context(json.dumps(secondary), len(detail))
                                else:
                                    secondary = parse_condition_checks(json.dumps(secondary), observation.type, len(detail))
                                if time.perf_counter() >= verify_deadline:
                                    raise TimeoutError('Positive verification exhausted budget')
                                if all(check['state'] == 'observed' for check in secondary.values()):
                                    checks, frames = secondary, detail
                                    supported = True
                                    self._object_diagnostics['positive_verification_supported'] += 1
                                else:
                                    self._object_diagnostics['positive_verification_disagreed'] += 1
                            except (ValueError, AttributeError, TimeoutError):
                                self._object_diagnostics['positive_verification_unavailable'] += 1
                        else:
                            self._object_diagnostics['positive_verification_skipped'] += 1
                        if not supported:
                            # Disagreement, unsupported methods and missing budget are
                            # abstentions. They never certify a negative video verdict.
                            checks = {name: {**check, 'state': 'unclear'}
                                      for name, check in checks.items()}
                    converted = {name: {'state': check['state'], 'evidence_timestamps_sec':
                                 [frames[index].timestamp_sec for index in check['frames']]}
                                 for name, check in checks.items()}
                    observation = replace(observation, start_sec=start, end_sec=end,
                                          condition_checks=converted,
                                          timing_resolution_sec=max(
                                              observation.timing_resolution_sec,
                                              max((b.timestamp_sec - a.timestamp_sec
                                                   for a, b in zip(frames, frames[1:])), default=0)))
                except TimeoutError:
                    self._object_diagnostics['service_context_timeout'] += 1
                except (ValueError, AttributeError):
                    self._object_diagnostics['service_context_invalid_output'] += 1
                contextual.append(observation)
            result.observations = sorted(contextual, key=lambda item: (item.start_sec, item.end_sec))
            if time.perf_counter() >= deadline:
                result.status = 'timeout'
            if result.status == 'timeout':
                result.warnings.append('Time budget exhausted; do not treat as a completed analysis')
            result.warnings.extend(f'{code}: {count}' for code, count in self._object_diagnostics.items())
            result.warnings.extend(f'{code}: {count}' for code, count in
                                   getattr(self.model, 'condition_diagnostics', {}).items())
        finally:
            reader.close()
            result.elapsed_sec = time.perf_counter() - started
            result.stage_timings_sec = {stage: round(self._stage_timings[stage], 4)
                                       for stage in ('decode', 'relevance', 'observe', 'verify_object', 'service_context')}
            if loaded:
                for key, value in self.model.metrics().items():
                    setattr(result, key, round(value, 2))
        return result


def analyze_video(path: str | Path, config: InferenceConfig) -> InferenceResult:
    """Convenient cold-start entry point. Reuse InferenceEngine for multiple videos."""
    return InferenceEngine(config).analyze_video(path)
