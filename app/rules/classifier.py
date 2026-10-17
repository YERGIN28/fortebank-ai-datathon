
# app/rules/classifier.py

from .actions import ACTION_CATALOG


def classify_observation(observation):
    """
    Простой классификатор для прототипа.
    Не определяет нарушения.
    """

    existing_type = observation.get("type", "unknown")

    # Сохраняем тип, если AI уже указал
    # известную категорию.
    if existing_type in ACTION_CATALOG and existing_type != "unknown":
        return existing_type

    description = observation.get("description", "").lower()

    if "hands a banknote to" in description:
        return "banknote_handover"

    if "receives banknote" in description:
        return "banknote_handover"

    if "places banknote on table" in description:
        return "banknote_placed_on_table"

    if "handles a banknote" in description:
        return "banknote_handling"

    if "holds a banknote" in description:
        return "banknote_handling"

    if "enters the office" in description:
        return "person_enters"

    return "unknown"


def classify_observations(observations):
    """
    Возвращает копии наблюдений с добавленным type.
    Исходные данные не изменяет.
    """

    result = []

    for observation in observations:
        updated = observation.copy()
        updated["type"] = classify_observation(observation)
        result.append(updated)

    return result
