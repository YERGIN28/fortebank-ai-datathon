import time
import math
from pathlib import Path

from backend.media import extract_frame_base64, validate_video
from backend import config


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
            refine=False, refinement_frames=6,
        )
        self.engine = InferenceEngine(settings)
        self.engine.load()

    def run_analysis(self, file_path: str):
        if self.mode == "fake":
            return run_analysis(file_path)
        if self.engine is None:
            raise RuntimeError("Inference engine is not ready")
        validate_video(file_path)
        result = self.engine.analyze_video(file_path).to_dict()
        if result.get("status") != "complete":
            raise RuntimeError(f"Inference did not complete: {result.get('status', 'missing status')}")
        from backend.services.rules_adapter import run_rule_engine
        return run_rule_engine(result, Path(file_path).stem)
