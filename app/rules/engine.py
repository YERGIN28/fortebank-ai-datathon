
# app/rules/engine.py

# Демонстрационные правила.
# Позже заменим на подтверждённые правила кейса.
RULES = {
    "cash_left_unattended": {
        "title": "Наличные оставлены без присмотра",
        "description": "Обнаружена ситуация, требующая проверки",
        "severity": "high",
    },
    "unauthorized_phone_use": {
        "title": "Использование телефона",
        "description": "Возможно использование телефона во время операции",
        "severity": "medium",
    },
}


def check_events(events):
    """
    Получает события от AI и проверяет правила.

    events = [
        {
            "type": "cash_left_unattended",
            "timestamp_sec": 57,
            "confidence": 0.9
        }
    ]
    """

    violations = []

    for event in events:
        event_type = event.get("type")

        # Если событие не входит в наши правила,
        # пока пропускаем его.
        if event_type not in RULES:
            continue

        rule = RULES[event_type]

        violations.append({
            "type": event_type,
            "title": rule["title"],
            "description": rule["description"],
            "severity": rule["severity"],
            "timestamp_sec": event.get("timestamp_sec"),
            "confidence": event.get("confidence"),
            "status": "needs_review",
        })

    return violations


if __name__ == "__main__":
    # Тестовые события, не из настоящего видео.
    test_events = [
        {
            "type": "cash_left_unattended",
            "timestamp_sec": 57,
            "confidence": 0.91,
        },
        {
            "type": "normal_customer_service",
            "timestamp_sec": 80,
            "confidence": 0.95,
        },
    ]

    result = check_events(test_events)

    print("Найдено потенциальных нарушений:", len(result))

    for violation in result:
        print(violation)
