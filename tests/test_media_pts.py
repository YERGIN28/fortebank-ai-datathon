"""Generated video only: backend evidence shares inference's source timeline."""
import time
from app.inference.video import VideoReader
from backend.media import extract_frame_base64


def test_evidence_uses_source_pts(video):
    reader = VideoReader(video)
    try:
        frames = reader.sample(0,reader.duration,4,time.perf_counter()+10)
        for frame in frames:
            evidence = extract_frame_base64(str(video),frame.timestamp_sec)
            assert evidence['timestamp_sec'] >= 0
            assert abs(evidence['timestamp_sec']-frame.timestamp_sec) < 1e-6
    finally:
        reader.close()


from tests.test_backend import video
