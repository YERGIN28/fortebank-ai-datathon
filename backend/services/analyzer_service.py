import time
import math
import logging
import json
from pathlib import Path

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
    validate_video(file_path)
    result = analyze_video(file_path, delay_seconds=20)
    for violation in result["violations"]:
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
            window_seconds=8.0, overlap_seconds=2.0, frames_per_window=4,
            max_frame_side=448, max_new_tokens=256, time_budget_seconds=300.0,
            refine=False, refinement_frames=6, check_relevance=False,
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
        deadline = time.perf_counter() + 300.0
        result = self.engine.analyze_video(file_path).to_dict()
        metrics = inference_metrics(result)
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
        from backend.services.service_context import enrich_service_context
        if any(event.get("type") == "cash_left_unattended" for event in result.get("observations", [])):
            result = enrich_service_context(result, file_path, self.engine.model, deadline)
        response = run_rule_engine(result, file_path)
        if time.perf_counter() >= deadline:
            raise TimeoutError("Job analysis exceeded 300 seconds")
        return response
