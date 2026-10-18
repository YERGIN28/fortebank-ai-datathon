"""Generate a known artificial MOV. Never reads user data."""
from fractions import Fraction
from pathlib import Path


def create_video(path: Path, duration_seconds: float = 4.0,
                 width: int = 320, height: int = 240, codec: str = 'mpeg4'):
    import math
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError('duration_seconds must be finite and positive')
    if width < 64 or height < 64 or width % 2 or height % 2:
        raise ValueError('Video dimensions must be even and >= 64')
    import av
    from PIL import Image, ImageDraw
    with av.open(str(path), 'w', format='mov') as container:
        if codec not in ('mpeg4', 'libx264'):
            raise ValueError('Unsupported synthetic codec')
        stream = container.add_stream(codec, rate=10)
        stream.width, stream.height = width, height
        stream.pix_fmt = 'yuv420p'
        for index in range(math.ceil(duration_seconds * 10)):
            image = Image.new('RGB', (320, 240), 'white')
            draw = ImageDraw.Draw(image)
            left = 20 + (index * 3) % 150
            draw.rectangle((left, 80, left + 40, 120), fill='red')
            draw.ellipse((230, 80, 270, 120), fill='blue')
            frame = av.VideoFrame.from_image(image.resize((width, height)))
            frame.pts = index
            frame.time_base = Fraction(1, 10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def main():
    import argparse
    import json
    import tempfile
    from . import InferenceConfig, analyze_video
    parser = argparse.ArgumentParser(description='Synthetic-only offline GPU smoke check')
    parser.add_argument('--model-path', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='forte-synthetic-') as directory:
        path = Path(directory) / 'shapes.mov'
        create_video(path)
        result = analyze_video(path, InferenceConfig(
            model_path=args.model_path, frames_per_window=3, refine=False))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
    # Only aggregate metrics; descriptions are kept in the explicitly synthetic report.
    print(json.dumps({key: value for key, value in result.to_dict().items()
                      if key not in ('observations', 'warnings')}))
    if result.status != 'complete':
        raise SystemExit('Synthetic inference did not complete successfully')


if __name__ == '__main__':
    main()
