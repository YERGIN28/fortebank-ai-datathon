import os
from pathlib import Path

from dotenv import load_dotenv
from app.inference import InferenceConfig, InferenceEngine

load_dotenv()

model_path = os.getenv("MODEL_PATH")

if not model_path:
    raise RuntimeError("MODEL_PATH is not set")

config = InferenceConfig(
    model_path=Path(model_path),
    window_seconds=8.0,
    overlap_seconds=2.0,
    frames_per_window=4,
    max_frame_side=448,
    max_new_tokens=256,
    time_budget_seconds=300.0,
    refine=False,
    refinement_frames=6,
)

engine = InferenceEngine(config)

print("Loading model...")
engine.load()
print("Model loaded successfully")