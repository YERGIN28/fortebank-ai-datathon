import time

from backend.media import extract_frame_base64, validate_video


def analyze_video(video_path: str, *, delay_seconds: float = 3):
    """Legacy demo result; this is deliberately not an AI verdict."""
    time.sleep(delay_seconds)

    return {
        "verdict": "violation",
        "violations": [
            {
                "type": "Test violation",
                "timecode_sec": 10.0,
                "description": "Test violation detected",
                "evidence_frames": []
            }
        ]
    }


def run_analysis(file_path: str):
    """Current demo pipeline, isolated from job lifecycle and the HTTP API."""
    validate_video(file_path)
    result = analyze_video(file_path, delay_seconds=20)
    for violation in result["violations"]:
        violation["evidence_frames"] = [
            extract_frame_base64(file_path, violation["timecode_sec"])
        ]
    return result
