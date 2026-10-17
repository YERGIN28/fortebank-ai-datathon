"""Offline GPU comparison on generated geometric video; no real input accepted."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import tempfile

from . import InferenceConfig, InferenceEngine
from .model import QwenModel
from .synthetic import create_video
from .video import VideoReader, iter_windows
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-path', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    base = InferenceConfig(args.model_path, refine=False)
    model = QwenModel(base)
    model.load()
    report = {
        'input_source': 'Generated shapes only; no real video accepted',
        'source_dimensions': [1280, 720],
        'source_fps': 10,
        'model_load_seconds': model.load_seconds,
        'repetitions_per_setting': 2,
        'notes': ['Loaded model reused across trials; one GPU generation warmup excluded.',
                  'Geometric shapes do not measure cash-action detection accuracy.',
                  'Refinement disabled to compare coarse-pass cost only.'],
        'trials': [],
    }
    with tempfile.TemporaryDirectory(prefix='forte-benchmark-') as directory:
        path = Path(directory) / 'generated-16s.mov'
        create_video(path, duration_seconds=16, width=1280, height=720)
        reader = VideoReader(path, base.max_frame_side)
        try:
            frames = reader.sample(0, 8, 4, time.perf_counter() + 30)
        finally:
            reader.close()
        warmup_started = time.perf_counter()
        model.observe(frames, warmup_started + 120)
        report['warmup_seconds'] = time.perf_counter() - warmup_started
        for trial_index, count in enumerate((4, 6, 4, 6)):
            config = replace(base, frames_per_window=count)
            model.config = config
            # Separate local decoder verification records actual source PTS.
            reader = VideoReader(path, config.max_frame_side)
            try:
                windows = [
                    {'start_sec': start, 'end_sec': end,
                     'sampled_timestamps_sec': [frame.timestamp_sec for frame in reader.sample(
                         start, end, count, time.perf_counter() + 30)]}
                    for start, end in iter_windows(reader.duration,
                        config.window_seconds, config.overlap_seconds)
                ]
            finally:
                reader.close()
            result = InferenceEngine(config, model=model).analyze_video(path)
            trial = {'repeat': trial_index // 2 + 1,
                     'frames_per_window': count, 'max_frame_side': config.max_frame_side,
                     'windows': windows, 'result': result.to_dict()}
            report['trials'].append(trial)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'frames_per_window': count, 'status': result.status,
                'elapsed_sec': result.elapsed_sec, 'processed_windows': result.processed_windows,
                'planned_windows': result.planned_windows,
                'gpu_peak_allocated_mib': result.gpu_peak_allocated_mib,
                'gpu_peak_reserved_mib': result.gpu_peak_reserved_mib}), flush=True)
        # Warm model with a negligible budget should return an explicit timeout.
        timeout_result = InferenceEngine(replace(base, time_budget_seconds=0.000001),
                                         model=model).analyze_video(path)
        report['deadline_check'] = {'status': timeout_result.status,
                                   'processed_windows': timeout_result.processed_windows}
        report['negative_control_passed'] = all(
            not trial['result']['observations'] for trial in report['trials'])
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if any(t['result']['status'] != 'complete' for t in report['trials']):
        raise SystemExit('At least one synthetic trial did not complete; inspect report')
    if report['deadline_check']['status'] != 'timeout':
        raise SystemExit('Deadline check failed')
    if not report['negative_control_passed']:
        raise SystemExit('Geometry-only negative control produced observations; inspect report')


if __name__ == '__main__':
    main()
