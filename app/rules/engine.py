
# app/rules/engine.py

import math
import copy

try:
    from .catalog import RULE_CATALOG
except ImportError:
    from catalog import RULE_CATALOG


def is_valid_time(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def check_events(events, *, assessment_mode='strict'):
    """
    Принимает наблюдения AI.
    Возвращает кандидатов для ручной проверки.

    Не подтверждает нарушения автоматически.
    """

    if assessment_mode == 'possible_signs':
        from .indicator_catalog import INDICATOR_CATALOG
        catalog = INDICATOR_CATALOG
    elif assessment_mode == 'strict':
        catalog = RULE_CATALOG
    else:
        raise ValueError('Unknown assessment mode')
    candidates = []

    for event in events:
        event_type = event.get("type", "unknown")

        if event_type not in catalog:
            continue

        rule = catalog[event_type]

        start_sec = event.get("start_sec")
        end_sec = event.get("end_sec")

        # Исключаем bool, NaN, infinity и отрицательные значения.
        if not is_valid_time(start_sec):
            continue

        if not is_valid_time(end_sec):
            continue

        if end_sec < start_sec:
            continue

        # Временная точка кандидата:
        # начало наблюдаемого интервала.
        timecode_sec = start_sec

        # Сохраняем только корректные отметки доказательств.
        raw_evidence = event.get("evidence_timestamps_sec") or []

        evidence = []

        if isinstance(raw_evidence, list):
            evidence = [
                timestamp
                for timestamp in raw_evidence
                if is_valid_time(timestamp)
                and start_sec <= timestamp <= end_sec
            ]

        candidates.append({
            "type": event_type,
            "title": rule["title"],
            "description": rule["description"],
            "severity": rule["severity"],
            "start_sec": start_sec,
            "end_sec": end_sec,
            "timecode_sec": timecode_sec,
            "evidence_timestamps_sec": evidence,
            "timing_resolution_sec": event.get(
                "timing_resolution_sec"
            ),
            "refined": event.get("refined", False),
            "confidence": event.get("confidence"),
            "actors": event.get("actors", []),
            "regulation": rule.get("regulation"),
            "verified": rule.get("verified", False),
            "status": "needs_review",
            "condition_checks": copy.deepcopy(event.get("condition_checks", {})),
            "decision_mode": rule.get("decision_mode", "conditional"),
            "review_reason": rule.get("review_reason"),
        })

    return candidates


if __name__ == "__main__":
    # Искусственное наблюдение для проверки.
    test_events = [
        {
            "type": "cash_left_unattended",
            "start_sec": 10,
            "end_sec": 15,
            "evidence_timestamps_sec": [11, 13],
            "timing_resolution_sec": 1,
            "refined": True,
            "confidence": None,
            "actors": ["cashier"],
        }
    ]

    result = check_events(test_events)

    print("Найдено кандидатов:", len(result))

    for candidate in result:
        print(candidate)
