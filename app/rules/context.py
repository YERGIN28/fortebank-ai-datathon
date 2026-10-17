"""Bounded local checks for three cash rules; unknown observations stay unknown."""
import copy
import time
from .catalog import RULE_CATALOG

RULE_TYPES = ("cashier_leaves_during_service", "cash_counting_without_customer",
              "previous_cash_outside_storage")
REVIEW_TYPES = {"cash_handling", "cash_transfer", "cash_left_unattended", "unknown",
                "cash_drawer_opened", "cash_drawer_closed"}
STATE_CODES = {"o": "observed", "r": "refuted", "u": "unclear"}

CONDITIONS = ("cashier_left_workplace", "customer_service_ongoing")


def _legacy_service_context(result, video_path, model, deadline, reader_factory=None):
    result = copy.deepcopy(result)
    if result.get("status") != "complete":
        return result
    events = [event for event in result.get("observations", [])
              if event.get("type") == "cash_left_unattended"]
    if not events:
        return result
    if reader_factory is None:
        from app.inference.video import VideoReader
        reader_factory = VideoReader
    reader = reader_factory(video_path, 448)
    try:
        for event in events:
            if time.perf_counter() >= deadline:
                raise TimeoutError("Context check exhausted the job budget")
            start = max(0.0, event["start_sec"] - 6)
            end = min(reader.duration, event["end_sec"] + 6)
            frames = reader.sample(start, end, 6, deadline)
            if len(frames) < 2:
                continue
            checks = model.check_service_context(frames, deadline)
            if not isinstance(checks, dict) or set(checks) != set(CONDITIONS):
                raise ValueError("Invalid context response")
            converted = {}
            for condition in CONDITIONS:
                check = checks[condition]
                if not isinstance(check, dict) or check.get("state") not in ("observed", "refuted", "unclear"):
                    raise ValueError("Invalid context state")
                indexes = check.get("frames")
                if (not isinstance(indexes, list)
                        or any(type(index) is not int or not 0 <= index < len(frames) for index in indexes)):
                    raise ValueError("Invalid context evidence indexes")
                converted[condition] = {
                    "state": check["state"],
                    "evidence_timestamps_sec": sorted({frames[index].timestamp_sec for index in indexes}),
                }
            event.update(type="cashier_leaves_during_service", start_sec=start,
                         end_sec=end, condition_checks=converted)
    finally:
        reader.close()
    return result


def _convert_bundle(payload, frames):
    if not isinstance(payload, dict) or set(payload) != set(RULE_TYPES):
        raise ValueError("Invalid cash rule context response")
    converted = {}
    for rule_type in RULE_TYPES:
        conditions = RULE_CATALOG[rule_type]["conditions"]
        rows = payload[rule_type]
        if not isinstance(rows, list) or len(rows) != len(conditions):
            raise ValueError("Invalid cash rule condition count")
        checks = {}
        for name, row in zip(conditions, rows):
            if (not isinstance(row, list) or len(row) != 2
                    or not isinstance(row[0], str) or row[0] not in STATE_CODES
                    or not isinstance(row[1], list)
                    or any(type(i) is not int or not 0 <= i < len(frames) for i in row[1])):
                raise ValueError("Invalid cash rule evidence")
            if row[0] != "u" and not row[1]:
                raise ValueError("Cash rule fact needs supporting frames")
            checks[name] = {"state": STATE_CODES[row[0]],
                            "evidence_timestamps_sec": sorted({frames[i].timestamp_sec for i in row[1]})}
        converted[rule_type] = checks
    return converted


def enrich_service_context(result, video_path, model, deadline, reader_factory=None,
                           *, max_windows=4, context_seconds=50.0):
    """Compatibility entry point used by backend; the public model method checks 3 rules.

    The bounded review is candidate-driven. It cannot establish full coverage of
    every possible violation; unreviewed candidates and original unknowns abstain.
    """
    if not hasattr(model, "check_cash_rules_context"):
        return _legacy_service_context(result, video_path, model, deadline, reader_factory)
    result = copy.deepcopy(result)
    if result.get("status") != "complete":
        return result
    events = [event for event in result.get("observations", []) if event.get("type") in REVIEW_TYPES]
    if not events:
        return result
    if reader_factory is None:
        from app.inference.video import VideoReader
        reader_factory = VideoReader
    reader = reader_factory(video_path, 448)
    context_deadline = min(deadline - 3.0, time.perf_counter() + context_seconds)
    windows = []
    for event in sorted(events, key=lambda item: item["start_sec"]):
        start = max(0.0, event["start_sec"] - 8.0)
        end = min(reader.duration, start + 24.0, event["end_sec"] + 8.0)
        if windows and event["start_sec"] >= windows[-1][0] and event["end_sec"] <= windows[-1][1]:
            windows[-1][2].append(event)
        else:
            windows.append([start, end, [event]])
    additions, replaced, checked, attempted = [], set(), 0, 0
    incomplete = any(event["end_sec"] > end for start, end, originals in windows for event in originals)
    try:
        for start, end, originals in windows:
            if attempted >= max_windows or time.perf_counter() >= context_deadline:
                incomplete = True
                break
            attempted += 1
            call_deadline = min(context_deadline, time.perf_counter() + 20.0)
            frames = reader.sample(start, end, 6, call_deadline)
            if len(frames) < 2:
                incomplete = True
                continue
            try:
                bundle = _convert_bundle(model.check_cash_rules_context(frames, call_deadline), frames)
            except TimeoutError:
                incomplete = True
                break
            checked += 1
            for rule_type, checks in bundle.items():
                additions.append({"type": rule_type, "start_sec": start, "end_sec": end,
                                  "description": "Local cash-rule context check",
                                  "condition_checks": checks,
                                  "evidence_timestamps_sec": sorted({t for c in checks.values()
                                                                     for t in c["evidence_timestamps_sec"]})})
            # Replace only the old unattended-cash proxy with the explicit checks.
            # Unknown events may concern other rules and must not become negatives.
            replaced.update(id(event) for event in originals if event["type"] == "cash_left_unattended"
                            and start <= event["start_sec"] <= event["end_sec"] <= end)
    finally:
        reader.close()
    result["observations"] = [event for event in result["observations"] if id(event) not in replaced] + additions
    if incomplete:
        result["observations"].append({"type": "unknown", "start_sec": 0.0,
                                       "end_sec": reader.duration,
                                       "description": "Cash-rule context coverage incomplete"})
    result["rule_context_summary"] = {"planned_windows": len(windows), "checked_windows": checked,
                                       "attempted_windows": attempted,
                                       "incomplete": incomplete, "rule_types": list(RULE_TYPES)}
    return result
