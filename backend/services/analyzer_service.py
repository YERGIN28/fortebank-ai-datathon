import time
import math
import logging
import json
import re
from collections import Counter
from pathlib import Path
from dataclasses import replace
import uuid

from backend.media import extract_frame_base64, validate_video
from backend import config


def inference_metrics(result):
    """Technical counters only: never log frames, paths, observations or warnings."""
    def number(value):
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            return round(value, 4)
        return None

    status = result.get("status")
    metrics = {"status": status if status in ("complete", "partial", "timeout") else "unknown"}
    for field in ("elapsed_sec", "duration_sec", "model_load_sec",
                  "gpu_peak_allocated_mib", "gpu_peak_reserved_mib"):
        metrics[field] = number(result.get(field))
    for field in ("processed_windows", "planned_windows"):
        value = result.get(field)
        metrics[field] = value if type(value) is int and value >= 0 else None
    stages = result.get("stage_timings_sec", {})
    if not isinstance(stages, dict):
        stages = {}
    metrics["stage_timings_sec"] = {
        stage: number(stages.get(stage))
        for stage in ("decode", "relevance", "observe", "verify_object", "service_context")
    }
    codes = Counter()
    allowed = {'invalid_json', 'json_token_limit', 'invalid_model_schema',
               'too_many_events', 'invalid_frame_index', 'invalid_actor_schema', 'no_frames',
               'invalid_presence_schema', 'inconsistent_presence', 'invalid_action_code',
               'invalid_object_code', 'missing_event_fields', 'invalid_event_container'}
    for warning in result.get('warnings', []):
        match = re.fullmatch(r'Window \d+: ([a-z_]+)', warning) if isinstance(warning, str) else None
        if match and match.group(1) in allowed:
            codes[match.group(1)] += 1
    metrics['diagnostic_counts'] = dict(codes)
    return metrics


def analyze_video(video_path: str, *, delay_seconds: float = 3):
    """Legacy demo result; this is deliberately not an AI verdict."""
    time.sleep(delay_seconds)

    return {
        "verdict": "violation",
        "violations": [
            {
                "type": "Test violation",
                "timecode_sec": 10.0,
                "description": "Test violation detected",
                "evidence_frames": []
            }
        ]
    }


def extract_evidence(file_path: str, timestamps):
    """Extract at most three distinct JPEG frames at supplied event times."""
    selected = []
    for timestamp in timestamps:
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Invalid evidence timestamp")
        if timestamp not in selected and len(selected) < 3:
            selected.append(timestamp)
    if not selected:
        raise ValueError("A violation requires at least one evidence timestamp")
    return [extract_frame_base64(file_path, timestamp) for timestamp in selected]


def run_analysis(file_path: str):
    """Current demo pipeline, isolated from job lifecycle and the HTTP API."""
    info = validate_video(file_path)
    result = analyze_video(file_path, delay_seconds=20)
    for violation in result["violations"]:
        violation['timecode_sec'] = min(violation['timecode_sec'],
                                        max(0.0, info['duration_sec'] - 0.2))
        violation["evidence_frames"] = extract_evidence(file_path, [violation["timecode_sec"]])
    return result


class VideoAnalyzer:
    """Owned by one worker. Heavy AI imports and loading happen only in real mode."""
    def __init__(self, mode=None):
        self.mode = config.ANALYSIS_MODE if mode is None else mode
        self.engine = None

    def load(self):
        if self.mode == "fake":
            return
        if self.mode != "real":
            raise ValueError("ANALYSIS_MODE must be fake or real")
        if not config.MODEL_PATH or not Path(config.MODEL_PATH).is_dir():
            raise RuntimeError("MODEL_PATH must point to an existing local model directory")
        from app.inference import InferenceConfig, InferenceEngine
        settings = InferenceConfig(
            model_path=Path(config.MODEL_PATH),
            quantization=config.MODEL_QUANTIZATION,
            window_seconds=8.0, overlap_seconds=2.0, frames_per_window=4,
            max_frame_side=640, max_new_tokens=256, time_budget_seconds=300.0,
            verification_frame_side=640,
            refine=False, refinement_frames=6, check_relevance=False,
            max_service_checks=6, service_check_seconds=45.0,
            verify_positive_conditions=config.VERIFY_POSITIVE_CONDITIONS,
            positive_check_seconds=45.0, max_positive_checks=6,
        )
        self.engine = InferenceEngine(settings)
        self.engine.load()
        from app.inference import INFERENCE_VERSION
        logging.getLogger("uvicorn.error").info("Inference loaded: %s", INFERENCE_VERSION)

    def run_analysis(self, file_path: str):
        if self.mode == "fake":
            return run_analysis(file_path)
        if self.engine is None:
            raise RuntimeError("Inference engine is not ready")
        validate_video(file_path)
        deadline = min(time.perf_counter() + 300.0, getattr(self, 'job_deadline', float('inf')))
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError('Job exceeded 300 seconds before inference')
        previous_config = getattr(self.engine, 'config', None)
        try:
            if previous_config is not None:
                self.engine.config = replace(previous_config, time_budget_seconds=min(
                    previous_config.time_budget_seconds, remaining))
            result = self.engine.analyze_video(file_path).to_dict()
        finally:
            if previous_config is not None:
                self.engine.config = previous_config
        metrics = inference_metrics(result)
        if config.INFERENCE_AUDIT_DIR is not None:
            # Optional private local artifact. Never includes pixels or enters logs/API.
            folder = Path(config.INFERENCE_AUDIT_DIR)
            folder.mkdir(parents=True, exist_ok=True)
            prefix = Path(file_path).name.split('_', 1)[0]
            identity = prefix if re.fullmatch(r'[0-9a-f]{32}', prefix) else uuid.uuid4().hex
            artifact = {'inference': result, 'inference_version': __import__(
                'app.inference', fromlist=['INFERENCE_VERSION']).INFERENCE_VERSION}
            artifact['assessment_mode'] = config.ASSESSMENT_MODE
            with (folder / (identity + '.json')).open('x', encoding='utf-8') as output:
                json.dump(artifact, output, ensure_ascii=False, allow_nan=False)
        logging.getLogger("uvicorn.error").log(
            logging.INFO if result.get("status") == "complete" else logging.WARNING,
            "Inference metrics: %s", json.dumps(metrics, allow_nan=False),
        )
        if result.get("status") != "complete":
            details = []
            if metrics["elapsed_sec"] is not None:
                details.append(f"elapsed {metrics['elapsed_sec']:.1f}s")
            if metrics["processed_windows"] is not None and metrics["planned_windows"] is not None:
                details.append(f"completed windows {metrics['processed_windows']}/{metrics['planned_windows']}")
            suffix = f" ({', '.join(details)})" if details else ""
            raise RuntimeError(f"Inference did not complete: {result.get('status', 'missing status')}{suffix}")
        from backend.services.rules_adapter import run_rule_engine
        # AI4 owns bounded context checks. Preserve original types and evidence;
        # unattended cash is not automatically a departure during service.
        response = run_rule_engine(result, file_path)
        if time.perf_counter() >= deadline:
            raise TimeoutError("Job analysis exceeded 300 seconds")
        return response
