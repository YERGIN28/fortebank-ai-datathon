
# evaluation/test_run_rules.py

from evaluation.run_rules import process_video
from app.rules.classifier import classify_observation, classify_observations
from app.rules.catalog import RULE_CATALOG
from app.rules.engine import check_events


def test_known_rule_types_survive_pipeline():
    for event_type in RULE_CATALOG:
        observation = {
            "type": event_type,
            "start_sec": 10,
            "end_sec": 15,
            "description": "Customer hands a banknote to cashier.",
            "evidence_timestamps_sec": [11],
        }
        original = observation.copy()
        direct = check_events([observation])
        result = process_video({
            "video_id": "synthetic_known_type",
            "status": "complete",
            "observations": [observation],
        })
        assert len(direct) == 1
        assert result["candidates"] == direct
        assert result["status"] == "failed"
        assert "verdict" not in result
        assert observation == original


def test_neutral_inference_actions_are_not_candidates():
    for event_type in ("document_handling", "document_transfer", "object_transfer"):
        observation = {
            "type": event_type,
            "start_sec": 10,
            "end_sec": 15,
            "description": "Customer hands a banknote to cashier.",
        }
        assert classify_observation(observation) == event_type
        result = process_video({
            "video_id": "synthetic_neutral_action",
            "status": "complete",
            "observations": [observation],
        })
        assert result["candidates"] == []
        assert result["violations"] == []
        assert result["verdict"] == "no_violation"


def test_unknown_fallback_remains_neutral():
    observations = [
        {"type": "unknown", "description": "Customer hands a banknote to cashier."},
        {"type": "unknown", "description": "Unclear synthetic observation"},
    ]
    result = classify_observations(observations)
    assert [item["type"] for item in result] == ["banknote_handover", "unknown"]
    assert check_events(result) == []


def test_complete_video():
    video = {
        "video_id": "synthetic_001",
        "status": "complete",
        "observations": [
            {
                "type": "unknown",
                "start_sec": 10,
                "end_sec": 15,
                "description": "Искусственное наблюдение",
            }
        ],
    }

    result = process_video(video)

    assert result["video_id"] == "synthetic_001"
    assert result["status"] == "failed"
    assert "verdict" not in result

    print("Тест 1 пройден: complete обработан")


def test_timeout_video():
    video = {
        "video_id": "synthetic_002",
        "status": "timeout",
        "observations": [],
    }

    result = process_video(video)

    assert result["status"] == "failed"
    assert "verdict" not in result

    print("Тест 2 пройден: timeout обработан")


def test_partial_video():
    video = {
        "video_id": "synthetic_003",
        "status": "partial",
        "observations": [],
    }

    result = process_video(video)

    assert result["status"] == "failed"
    assert "verdict" not in result

    print("Тест 3 пройден: partial обработан")


if __name__ == "__main__":
    test_complete_video()
    test_timeout_video()
    test_partial_video()

    print("Все 3 теста успешно пройдены!")

