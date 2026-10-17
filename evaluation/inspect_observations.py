
# evaluation/inspect_observations.py

import json
from pathlib import Path

input_path = Path("results/predictions.json")

with input_path.open("r", encoding="utf-8") as file:
    data = json.load(file)

for video in data.get("videos", []):
    print(f"\nВидео: {video['video_id']}")
    print(f"Статус: {video.get('status')}")

    observations = video.get("observations", [])
    print(f"Наблюдений: {len(observations)}")

    for number, obs in enumerate(observations, start=1):
        start = obs.get("start_sec")
        end = obs.get("end_sec")
        action_type = obs.get("type", "unknown")
        description = obs.get("description", "")

        print(
            f"{number}. [{start}–{end} сек] "
            f"type={action_type}"
        )
        print(f"   {description}")
