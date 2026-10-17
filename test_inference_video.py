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
print("Model loaded")

video_path = "X-1-short.mov"

print("Analyzing:", video_path)

result = engine.analyze_video(video_path)

data = result.to_dict()

print("\nStatus:", data["status"])
print("Processed windows:", data["processed_windows"])
print("Planned windows:", data["planned_windows"])
print("Duration:", data["duration_sec"])
print("Elapsed:", data["elapsed_sec"])
print("Warnings:", data["warnings"])

print("\nObservations:")

for i, obs in enumerate(data["observations"], start=1):
    print(f"\nObservation {i}")
    print("Type:", obs["type"])
    print("Start:", obs["start_sec"])
    print("End:", obs["end_sec"])
    print("Description:", obs["description"])
    print("Evidence timestamps:", obs["evidence_timestamps_sec"])
    print("Actors:", obs["actors"])