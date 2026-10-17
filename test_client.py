import time
import requests
import base64

API_URL = "http://127.0.0.1:8000"
API_KEY = "forte-datathon-secret"
VIDEO_PATH = "X-1.mov"


def submit_video():
    with open(VIDEO_PATH, "rb") as video_file:
        response = requests.post(
            f"{API_URL}/api/v1/analyze",
            headers={
                "X-API-Key": API_KEY
            },
            files={
                "file": (
                    VIDEO_PATH,
                    video_file,
                    "video/quicktime"
                )
            },
            timeout=30
        )

    response.raise_for_status()

    data = response.json()

    return data["job_id"]


def wait_for_result(job_id):
    start_time = time.time()

    while True:
        response = requests.get(
            f"{API_URL}/api/v1/jobs/{job_id}",
            headers={
                "X-API-Key": API_KEY
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        status = data["status"]

        print(
            f"Job {job_id}: {status}"
        )

        if status == "done":
            return data

        if status == "failed":
            raise RuntimeError(
                data.get(
                    "error",
                    "Unknown processing error"
                )
            )

        if time.time() - start_time > 300:
            raise TimeoutError(
                "Processing exceeded 5 minutes"
            )

        time.sleep(1)

def validate_result(result):
    assert "job_id" in result
    assert result["status"] == "done"

    assert result["verdict"] in [
        "violation",
        "no_violation"
    ]

    assert "violations" in result
    assert isinstance(result["violations"], list)

    if result["verdict"] == "no_violation":
        assert len(result["violations"]) == 0

    for violation in result["violations"]:
        assert "type" in violation
        assert "timecode_sec" in violation
        assert "description" in violation
        assert "evidence_frames" in violation

        assert 1 <= len(
            violation["evidence_frames"]
        ) <= 3

        for frame in violation["evidence_frames"]:
            assert "timestamp_sec" in frame
            assert "image_base64" in frame

            image_bytes = base64.b64decode(
                frame["image_base64"],
                validate=True
            )

            if not image_bytes.startswith(b"\xff\xd8"):
                raise AssertionError(
                    "Evidence is not a valid JPEG"
                )

    print("\nAPI validation: PASSED")


def main():
    print("Submitting video...")

    job_id = submit_video()

    print(f"Created job: {job_id}")

    result = wait_for_result(job_id)
    validate_result(result)

    print("\nFinal result:")
    print("Status:", result["status"])
    print("Verdict:", result["verdict"])

    violations = result.get("violations", [])


    if not violations:
        print("No violations detected")
        return

    for i, violation in enumerate(violations, start=1):
        print(f"\nViolation {i}")
        print("Type:", violation["type"])
        print("Time:", violation["timecode_sec"])
        print("Description:", violation["description"])

        for frame in violation.get("evidence_frames", []):
            print(
                "Evidence frame:",
                frame["timestamp_sec"],
                "sec"
            )

            print(
                "Base64 received:",
                len(frame["image_base64"]),
                "characters"
            )
if __name__ == "__main__":
    main()            