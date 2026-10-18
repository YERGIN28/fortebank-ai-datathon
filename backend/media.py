import cv2
import base64
import io
import math
import time


def extract_frame_base64(video_path: str, timestamp_sec: float):
    """Use the same source PTS origin as inference, including MOV edit offsets."""
    import av
    if not math.isfinite(timestamp_sec) or timestamp_sec < 0:
        raise ValueError('invalid_requested_timestamp')
    best_frame = None
    best_timestamp = None
    best_diff = float("inf")
    deadline = time.perf_counter() + 10.0
    with av.open(video_path) as container:
        stream = container.streams.video[0]
        origin = float((stream.start_time or 0) * stream.time_base)
        container.seek(int((timestamp_sec + origin) / stream.time_base),
                       stream=stream, backward=True, any_frame=False)
        for frame in container.decode(stream):
            if time.perf_counter() >= deadline:
                raise TimeoutError('evidence_decode_timeout')
            if frame.pts is None:
                continue
            current = float(frame.pts * stream.time_base) - origin
            if current < 0:
                continue
            difference = abs(current - timestamp_sec)
            if difference < best_diff:
                best_diff, best_timestamp, best_frame = difference, current, frame
            if current >= timestamp_sec and best_frame is not None:
                break
        if best_frame is not None:
            image = best_frame.to_image()
    if best_frame is None:
        raise RuntimeError('no_evidence_frame')
    if best_diff > 0.5:
        raise ValueError('evidence_timestamp_mismatch')
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=90)
    return {'timestamp_sec': best_timestamp,
            'image_base64': base64.b64encode(buffer.getvalue()).decode('ascii')}



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
