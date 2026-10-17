"""Final decisions from visible conditions; no confidence/keyword legal verdicts."""
import base64

from .actions import ACTION_CATALOG
from .catalog import RULE_CATALOG
from .classifier import classify_observations
from .engine import is_valid_time


def _failed(reason):
    return {"status": "failed", "error": reason}


def decide_video(inference_result):
    """Return internal events or failure. Internal events still need real JPEGs.

    condition_checks values: observed/refuted/unclear. Each check has its own
    evidence_timestamps_sec, from a local context pass or manual visual review.
    Caller must not invent checks from type, confidence, refined or description.
    """
    if not isinstance(inference_result, dict):
        return _failed("invalid_inference_result")
    if inference_result.get("status") != "complete":
        return _failed("incomplete_inference")
    processed = inference_result.get("processed_windows")
    planned = inference_result.get("planned_windows")
    if processed is not None or planned is not None:
        if (type(processed) is not int or type(planned) is not int
                or planned < 1 or processed != planned):
            return _failed("incomplete_window_coverage")
    observations = inference_result.get("observations")
    if not isinstance(observations, list):
        return _failed("invalid_observations")
    duration = inference_result.get("duration_sec")
    if duration is not None and (not is_valid_time(duration) or duration <= 0):
        return _failed("invalid_video_duration")

    confirmed, unresolved = [], []
    for original in observations:
        if not isinstance(original, dict) or not isinstance(original.get("type"), str):
            return _failed("invalid_observation")
        start, end = original.get("start_sec"), original.get("end_sec")
        if (not is_valid_time(start) or not is_valid_time(end) or end < start
                or (duration is not None and end > duration)):
            return _failed("invalid_observation_time")
        if not isinstance(original.get("description", ""), str):
            return _failed("invalid_observation_description")
        event = classify_observations([original])[0]
        event_type = event["type"]
        if (event_type in ACTION_CATALOG and event_type != "unknown") or event_type.startswith("document_"):
            continue
        rule = RULE_CATALOG.get(event_type)
        if not rule or not rule.get("verified") or not rule.get("regulation"):
            unresolved.append(event_type)
            continue
        checks = event.get("condition_checks", {})
        if not isinstance(checks, dict):
            return _failed("invalid_condition_checks")
        states, timestamps = [], []
        for name in rule["conditions"]:
            check = checks.get(name, {})
            if not isinstance(check, dict):
                return _failed("invalid_condition_check")
            state = check.get("state", "unclear")
            if state not in ("observed", "refuted", "unclear"):
                return _failed("invalid_condition_state")
            evidence = check.get("evidence_timestamps_sec", [])
            if (not isinstance(evidence, list)
                    or any(not is_valid_time(t) or not start <= t <= end for t in evidence)):
                return _failed("invalid_condition_evidence")
            # Both confirmation and refutation require visible evidence.
            states.append(state if evidence else "unclear")
            timestamps.extend(evidence)
        if "refuted" in states:
            continue
        if not states or any(state != "observed" for state in states):
            unresolved.append(event_type)
            continue
        times = sorted(set(timestamps))
        # Keep up to three points including the first and last context frames.
        selected = times if len(times) <= 3 else [times[0], times[len(times) // 2], times[-1]]
        regulation = rule["regulation"]
        confirmed.append({
            "type": rule["title"],
            "timecode_sec": selected[0],
            "description": (rule["description"] + " Основание: "
                            + regulation["document"] + ", п. " + regulation["paragraph"]
                            + ". " + regulation["url"]),
            "evidence_timestamps_sec": selected,
        })
    # A confirmed event proves the positive video verdict despite other unclear events.
    if confirmed:
        unique = []
        for event in confirmed:
            if event not in unique:
                unique.append(event)
        return {"status": "done", "verdict": "violation", "violations": unique}
    if unresolved:
        return _failed("unresolved_observations: " + ", ".join(sorted(set(unresolved))))
    return {"status": "done", "verdict": "no_violation", "violations": []}


def build_job_result(job_id, inference_result, extract_frame):
    """API adapter. extract_frame(seconds) returns a real frame from this video.

    The backend owns video decoding and calls this before deleting its upload.
    No candidates, internal states or needs_review enter the public response.
    Exceptions from inference itself belong to the backend's failed-job handler.
    """
    result = decide_video(inference_result)
    if result["status"] != "done" or result["verdict"] == "no_violation":
        return {"job_id": job_id, **result}
    violations = []
    try:
        for event in result["violations"]:
            frames = []
            for timestamp in event["evidence_timestamps_sec"]:
                frame = extract_frame(timestamp)
                if not isinstance(frame, dict) or not is_valid_time(frame.get("timestamp_sec")):
                    raise ValueError("invalid_frame")
                actual = frame["timestamp_sec"]
                duration = inference_result.get("duration_sec")
                if abs(actual - timestamp) > 0.5 or (duration is not None and actual > duration):
                    raise ValueError("frame_time_mismatch")
                jpeg = base64.b64decode(frame["image_base64"], validate=True)
                if not jpeg.startswith(b"\xff\xd8\xff") or not jpeg.endswith(b"\xff\xd9"):
                    raise ValueError("not_jpeg")
                frames.append({"timestamp_sec": actual, "image_base64": frame["image_base64"]})
            violations.append({
                "type": event["type"], "timecode_sec": frames[0]["timestamp_sec"],
                "description": event["description"], "evidence_frames": frames,
            })
    except Exception as error:
        # Return no partial done response when any evidence extraction fails.
        return {"job_id": job_id, **_failed("evidence_extraction_failed: " + type(error).__name__)}
    return {"job_id": job_id, "status": "done", "verdict": "violation", "violations": violations}
