
# evaluation/run_rules.py

import argparse
import json
from pathlib import Path

from app.rules.engine import check_events
from app.rules.classifier import classify_observations
from app.rules.decision import decide_video


def process_video(video, *, assessment_mode='possible_signs'):
    video_id = video["video_id"]
    status = video.get("status", "failed")

    decision = decide_video(video, assessment_mode=assessment_mode)
    # Evaluator uses complete, while the public job adapter uses done.
    # Only an actual final verdict is normalized; failed stays failed.
    if decision["status"] == "done":
        decision = {**decision, "status": "complete"}
    observations = video.get("observations", [])
    candidates = []
    if status == "complete" and isinstance(observations, list):
        # Diagnostics only; malformed observations are already failed by decide_video.
        valid = [item for item in observations if isinstance(item, dict)
                 and isinstance(item.get("type"), str)
                 and isinstance(item.get("description", ""), str)]
        candidates = check_events(classify_observations(valid), assessment_mode=assessment_mode)
    return {
        "video_id": video_id,
        **decision,
        "candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assessment-mode', choices=('possible_signs', 'strict'), default='possible_signs')

    parser.add_argument(
        "input_json",
        type=Path,
        help="Путь к predictions.json",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/rule_predictions.json"),
        help="Куда сохранить результат",
    )

    args = parser.parse_args()

    with args.input_json.open("r", encoding="utf-8") as file:
        predictions = json.load(file)

    if not isinstance(predictions, dict):
        raise ValueError("Корень JSON должен быть объектом")

    if not isinstance(predictions.get("videos"), list):
        raise ValueError("В JSON отсутствует список videos")

    result = {
        'assessment_mode': args.assessment_mode,
        "videos": [
            process_video(video, assessment_mode=args.assessment_mode)
            for video in predictions["videos"]
        ]
    }

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print("Обработано видео:", len(result["videos"]))
    print("Результат:", output.resolve())


if __name__ == "__main__":
    main()
