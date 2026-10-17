"""Evidence from original source PTS, decoded locally with PyAV."""
import base64
import io
import time


def extract_frame_base64(video_path, timestamp_sec, deadline=None):
    import av
    with av.open(str(video_path)) as container:
        stream = container.streams.video[0]
        origin = float((stream.start_time or 0) * stream.time_base)
        container.seek(int((timestamp_sec + origin) / stream.time_base),
                       stream=stream, backward=True, any_frame=False)
        best, actual, best_diff = None, None, float("inf")
        for frame in container.decode(stream):
            if deadline is not None and time.perf_counter() >= deadline:
                raise TimeoutError("Evidence decoding exceeded the job deadline")
            if frame.pts is None:
                continue
            seconds = float(frame.pts * stream.time_base) - origin
            diff = abs(seconds - timestamp_sec)
            if seconds >= 0 and diff < best_diff:
                best, actual, best_diff = frame, seconds, diff
            if seconds >= timestamp_sec:
                break
        if best is None:
            raise ValueError("No evidence frame")
        output = io.BytesIO()
        best.to_image().save(output, format="JPEG", quality=90)
        return {"timestamp_sec": round(actual, 6),
                "image_base64": base64.b64encode(output.getvalue()).decode("ascii")}


def validate_video(video_path):
    from app.inference.video import VideoReader
    reader = VideoReader(video_path)
    try:
        return {"duration_sec": reader.duration}
    finally:
        reader.close()
