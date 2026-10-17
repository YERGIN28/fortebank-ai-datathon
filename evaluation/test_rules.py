
from app.rules.engine import check_events, is_valid_time


def test_violation_candidate():
    events = [
        {
            "type": "cash_left_unattended",
            "start_sec": 57,
            "end_sec": 60,
            "evidence_timestamps_sec": [58],
            "confidence": 0.91,
        }
    ]

    result = check_events(events)

    assert len(result) == 1
    assert result[0]["status"] == "needs_review"
    assert result[0]["timecode_sec"] == 57
    assert result[0]["start_sec"] == 57
    assert result[0]["end_sec"] == 60

    print("Тест 1 пройден: кандидат найден")


def test_normal_action():
    events = [
        {
            "type": "normal_customer_service",
            "start_sec": 80,
            "end_sec": 85,
            "confidence": 0.95,
        }
    ]

    result = check_events(events)

    assert len(result) == 0

    print("Тест 2 пройден: обычное действие не стало кандидатом")


def test_empty_events():
    assert check_events([]) == []

    print("Тест 3 пройден: пустой список обработан")


def test_invalid_times():
    invalid_values = [
        True,
        False,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
        "57",
        None,
    ]

    for value in invalid_values:
        assert not is_valid_time(value)

        events = [
            {
                "type": "cash_left_unattended",
                "start_sec": value,
                "end_sec": 60,
            }
        ]

        assert check_events(events) == []

    print("Тест 4 пройден: некорректное время отклонено")


if __name__ == "__main__":
    test_violation_candidate()
    test_normal_action()
    test_empty_events()
    test_invalid_times()

    print("\nВсе 4 теста успешно пройдены!")
