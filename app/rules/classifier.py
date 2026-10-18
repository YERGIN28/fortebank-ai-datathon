
# app/rules/classifier.py

from .actions import ACTION_CATALOG
from .catalog import RULE_CATALOG
from .indicator_catalog import INDICATOR_CATALOG


def classify_observation(observation):
    """
    Простой классификатор для прототипа.
    Не определяет нарушения.
    """

    existing_type = observation.get("type", "unknown")

    # Candidate rules take priority over neutral categories and fallback text.
    if isinstance(existing_type, str) and existing_type in (RULE_CATALOG.keys() | INDICATOR_CATALOG.keys()):
        return existing_type

    # Нейтральные действия не превращаем в кандидатов по описанию.
    if isinstance(existing_type, str) and (
        existing_type.startswith("document_") or existing_type == "object_transfer"
    ):
        return existing_type

    # Тип из inference/каталога правил имеет приоритет над fallback.
    # Сохранение типа ещё не подтверждает нарушение: это решает rule engine.
    if isinstance(existing_type, str) and existing_type != "unknown" and (
        existing_type in ACTION_CATALOG or existing_type in RULE_CATALOG
    ):
        return existing_type

    description = observation.get("description", "")
    description = description.lower() if isinstance(description, str) else ""

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
