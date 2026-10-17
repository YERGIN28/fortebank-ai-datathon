"""Local video-only PyAV decoding with source presentation timestamps."""
from dataclasses import dataclass
from pathlib import Path
import math
import time


@dataclass
class SampledFrame:
    timestamp_sec: float
    image: object


class VideoReader:
    def __init__(self, path: str | Path, max_side: int = 448):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        import av
        self.container = av.open(str(path), mode='r')
        self.max_side = max_side
        try:
            self.stream = self.container.streams.video[0]
            if self.stream.duration is None or self.stream.time_base is None:
                raise ValueError('Video stream needs a reliable duration/time base')
            self.duration = float(self.stream.duration * self.stream.time_base)
            self.origin = float((self.stream.start_time or 0) * self.stream.time_base)
            if not math.isfinite(self.duration) or self.duration <= 0:
                raise ValueError('Video duration must be positive')
        except Exception:
            self.container.close()
            raise

    def sample(self, start: float, end: float, count: int,
               deadline: float) -> list[SampledFrame]:
        targets = [start + (end - start) * i / count for i in range(count)]
        self.container.seek(int((start + self.origin) / self.stream.time_base),
                            stream=self.stream, backward=True, any_frame=False)
        frames = []
        target_index = 0
        for frame in self.container.decode(self.stream):
            if time.perf_counter() >= deadline:
                raise TimeoutError('Video decoding exhausted the time budget')
            if frame.pts is None:
                continue
            timestamp = float(frame.pts * self.stream.time_base) - self.origin
            if timestamp >= end:
                break
            if timestamp < targets[target_index] - 1e-6:
                continue
            scale = min(1.0, self.max_side / max(frame.width, frame.height))
            image = frame.reformat(width=max(1, int(frame.width * scale)),
                                   height=max(1, int(frame.height * scale)),
                                   format='rgb24').to_image()
            frames.append(SampledFrame(timestamp, image))
            while target_index < count and targets[target_index] <= timestamp + 1e-6:
                target_index += 1
            if target_index == count:
                break
        return frames

    def close(self):
        self.container.close()


def iter_windows(duration: float, size: float, overlap: float):
    start = 0.0
    while start < duration:
        end = min(duration, start + size)
        yield start, end
        if end >= duration:
            break
        start += size - overlap
