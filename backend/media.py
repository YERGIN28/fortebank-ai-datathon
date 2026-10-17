import cv2
import base64


def extract_frame_base64(video_path: str, timestamp_sec: float):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError("Could not open video file")

    best_frame = None
    best_timestamp = None
    best_diff = float("inf")

    while True:
        success, frame = cap.read()

        if not success:
            break

        current_timestamp_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        diff = abs(current_timestamp_sec - timestamp_sec)

        if diff < best_diff:
            best_diff = diff
            best_frame = frame.copy()
            best_timestamp = current_timestamp_sec

        if current_timestamp_sec > timestamp_sec and best_frame is not None:
            break

    cap.release()

    if best_frame is None:
        raise RuntimeError(
            f"Could not extract frame near {timestamp_sec} seconds"
        )

    success, buffer = cv2.imencode(".jpg", best_frame)

    if not success:
        raise RuntimeError("Could not encode frame as JPEG")

    image_base64 = base64.b64encode(buffer).decode("utf-8")

    return {
        "timestamp_sec": round(best_timestamp, 3),
        "image_base64": image_base64
    }



def validate_video(video_path: str):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        cap.release()
        raise RuntimeError("Could not open video file")

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration_sec = 0

    if fps and fps > 0:
        duration_sec = frame_count / fps

    success, _ = cap.read()
    cap.release()

    if not success:
        raise RuntimeError("Video contains no readable frames")

    return {
        "frame_count": frame_count,
        "fps": fps,
        "duration_sec": duration_sec
    }