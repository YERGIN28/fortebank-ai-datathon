import time
import requests


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


def main():
    print("Submitting video...")

    job_id = submit_video()

    print(f"Created job: {job_id}")

    result = wait_for_result(job_id)

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