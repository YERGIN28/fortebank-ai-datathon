"""Enrich unattended-cash candidates through the public AI context method.

Departure candidates already carry condition_checks from inference 2026.10.18.3
and are left unchanged here. The Rule Engine owns the final verdict.
"""
import copy
import time

CONDITIONS = ("cashier_left_workplace", "customer_service_ongoing")


def enrich_service_context(result, video_path, model, deadline, reader_factory=None):
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
            if time.perf_counter() >= deadline:
                raise TimeoutError("Context check exhausted the job budget")
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
