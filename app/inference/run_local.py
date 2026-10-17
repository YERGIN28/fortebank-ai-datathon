"""Local batch runner. Never logs private filenames, frames or observations."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import tempfile
import time

from . import InferenceConfig, InferenceEngine


def read_manifest(path: Path) -> list[tuple[str, Path]]:
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(document, dict) or not isinstance(document.get('videos'), list) or not document['videos']:
        raise ValueError('Expected a nonempty videos list')
    seen, videos = set(), []
    for row in document['videos']:
        if not isinstance(row, dict):
            raise ValueError('Manifest record must be an object')
        key, filename = row.get('video_id'), row.get('path')
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('Unique video_id required')
        if not isinstance(filename, str) or not filename or '://' in filename or filename.startswith(('\\\\', '//')):
            raise ValueError('Only local paths are accepted')
        video = Path(filename)
        if not video.is_absolute():
            video = path.parent / video
        video = video.resolve()
        if video.suffix.lower() != '.mov' or not video.is_file():
            raise ValueError('Manifest needs existing local MOV files')
        seen.add(key)
        videos.append((key, video))
    return videos


def save_private_results(path: Path, rows: list[dict]):
    """Checkpoint without truncating the previous completed checkpoint."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.inference-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'videos': rows}, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_batch(videos: list[tuple[str, Path]], engine, output: Path) -> dict:
    if output.exists() or output.resolve() in {path.resolve() for _, path in videos}:
        raise ValueError('Choose a new output file')
    output.parent.mkdir(parents=True, exist_ok=True)
    engine.load()  # Model startup precedes jobs and happens once in this process.
    rows, statuses = [], Counter()
    for index, (video_id, path) in enumerate(videos):
        started = time.perf_counter()
        try:
            payload = engine.analyze_video(path).to_dict()
        except Exception:
            # No raw exception text: it can contain private paths or model content.
            payload = {'status': 'failed', 'observations': [],
                       'warnings': ['Local inference failed; no final verdict available'],
                       'elapsed_sec': time.perf_counter() - started}
        rows.append({'video_id': video_id, **payload})
        statuses[payload['status']] += 1
        save_private_results(output, rows)
        print(json.dumps({'finished': index + 1, 'total': len(videos),
                          'status_counts': dict(statuses)}), flush=True)
        if payload['status'] == 'failed':
            # A CUDA/device failure may make further work unsafe in this worker.
            # Missing subsequent video IDs are reported as missing by the evaluator.
            break
    return dict(statuses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--model-path', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--time-budget-sec', type=float, default=300)
    parser.add_argument('--refine', action='store_true')
    args = parser.parse_args()
    try:
        if args.output.resolve() == args.manifest.resolve():
            raise ValueError('Output must differ from manifest')
        videos = read_manifest(args.manifest)
        engine = InferenceEngine(InferenceConfig(args.model_path,
            time_budget_seconds=args.time_budget_sec, refine=args.refine))
        statuses = run_batch(videos, engine, args.output)
    except Exception:
        raise SystemExit('Local run failed: check environment, local paths and config; private details suppressed') from None
    if any(status != 'complete' for status in statuses):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
