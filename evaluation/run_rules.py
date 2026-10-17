
# evaluation/run_rules.py

import argparse
import json
from pathlib import Path

from app.rules.engine import check_events
from app.rules.classifier import classify_observations


def process_video(video):
    video_id = video["video_id"]
    status = video.get("status", "failed")

    # Неполный анализ не может означать no_violation.
    if status != "complete":
        return {
            "video_id": video_id,
            "status": status,
            "verdict": "needs_review",
            "violations": [],
            "candidates": [],
        }

    observations = video.get("observations", [])

    classified_observations = classify_observations(observations)
    candidates = check_events(classified_observations)

    # Условия и исключения правил пока не проверены.
    # Поэтому подтверждённых нарушений нет.
    return {
        "video_id": video_id,
        "status": status,
        "verdict": "needs_review",
        "violations": [],
        "candidates": candidates,
    }


def main():
    parser = argparse.ArgumentParser()

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
        "videos": [
            process_video(video)
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
