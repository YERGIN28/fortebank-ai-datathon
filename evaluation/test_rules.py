
from app.rules.engine import check_events


def test_violation_detected():
    events = [
        {
            "type": "cash_left_unattended",
            "timestamp_sec": 57,
            "confidence": 0.91,
        }
    ]

    result = check_events(events)

    assert len(result) == 1
    assert result[0]["status"] == "needs_review"
    assert result[0]["timestamp_sec"] == 57

    print("Тест 1 пройден: потенциальное нарушение найдено")


def test_normal_action():
    events = [
        {
            "type": "normal_customer_service",
            "timestamp_sec": 80,
            "confidence": 0.95,
        }
    ]

    result = check_events(events)

    assert len(result) == 0

    print("Тест 2 пройден: обычное действие не считается нарушением")


def test_empty_events():
    result = check_events([])

    assert result == []

    print("Тест 3 пройден: пустой список обработан")


if __name__ == "__main__":
    test_violation_detected()
    test_normal_action()
    test_empty_events()

    print("\nВсе 3 теста успешно пройдены!")

