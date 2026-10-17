
# evaluation/test_run_rules.py

from evaluation.run_rules import process_video


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
    assert result["status"] == "complete"
    assert result["verdict"] == "needs_review"
    assert result["violations"] == []

    print("Тест 1 пройден: complete обработан")


def test_timeout_video():
    video = {
        "video_id": "synthetic_002",
        "status": "timeout",
        "observations": [],
    }

    result = process_video(video)

    assert result["status"] == "timeout"
    assert result["verdict"] == "needs_review"

    print("Тест 2 пройден: timeout обработан")


def test_partial_video():
    video = {
        "video_id": "synthetic_003",
        "status": "partial",
        "observations": [],
    }

    result = process_video(video)

    assert result["status"] == "partial"
    assert result["verdict"] == "needs_review"

    print("Тест 3 пройден: partial обработан")


if __name__ == "__main__":
    test_complete_video()
    test_timeout_video()
    test_partial_video()

    print("Все 3 теста успешно пройдены!")

