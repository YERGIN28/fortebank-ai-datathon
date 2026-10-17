
from app.rules.classifier import classify_observations


def test_classifier():
    observations = [
        {
            "type": "unknown",
            "description": "Customer hands a banknote to cashier.",
        },
        {
            "type": "unknown",
            "description": "A man stands at the door.",
        },
        {
            "type": "unknown",
            "description": "Woman places banknote on table.",
        },
    ]

    result = classify_observations(observations)

    assert result[0]["type"] == "banknote_handover"
    assert result[1]["type"] == "unknown"
    assert result[2]["type"] == "banknote_placed_on_table"

    # Проверяем, что исходные наблюдения не изменились.
    assert observations[0]["type"] == "unknown"

    print("Все тесты классификатора прошли!")


if __name__ == "__main__":
    test_classifier()
