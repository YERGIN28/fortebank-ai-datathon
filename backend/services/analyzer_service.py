import time


def analyze_video(video_path: str):
    time.sleep(3)

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