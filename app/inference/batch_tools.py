"""User-run manifest preparation and aggregate technical summaries. No video decoding."""
import argparse
from collections import Counter
import json
import re
from pathlib import Path
from statistics import mean

from .evaluate import number
from .evaluate_baseline import reference_records, rows, select_reference_by_manifest, video_key
from .schemas import INFERENCE_VERSION


def safe_batch_error(error: Exception) -> str:
    codes = {
        'Video ID is absent from converted labels': 'id_not_in_labels',
        'Batch must contain one normal and one positive reference video': 'need_one_normal_one_positive',
        'Select an existing local MOV': 'mov_file_not_found',
        'Ambiguous X-4/X-47 group is excluded from this batch': 'ambiguous_pair_excluded',
        'Two different videos and IDs are required': 'duplicate_file_or_id',
        'Choose a new output filename': 'output_already_exists',
        'Duplicate ID or invalid reference verdict': 'duplicate_label_id_after_normalization',
    }
    if isinstance(error, FileNotFoundError):
        return 'local_file_not_found'
    return codes.get(str(error), 'invalid_local_input')


def build_manifest(labels_document, selections, output_path: Path) -> dict:
    """Validate one normal and one positive selection without reading video bytes."""
    labels = reference_records(labels_document)
    original_ids = {video_key(row['video_id']): row['video_id'].strip() for row in rows(labels_document)}
    if len(selections) != 2:
        raise ValueError('Select exactly two videos')
    videos, seen_ids, seen_paths, verdicts = [], set(), set(), Counter()
    forbidden = {video_key('X-4'), video_key('X-47')}
    for filename, identifier in selections:
        filename = str(filename)
        if '://' in filename or filename.startswith(('\\\\', '//')):
            raise ValueError('Only local video files are accepted')
        path = Path(filename).expanduser().resolve()
        key = video_key(identifier)
        if key in forbidden:
            raise ValueError('Ambiguous X-4/X-47 group is excluded from this batch')
        if key not in labels:
            raise ValueError('Video ID is absent from converted labels')
        if key in seen_ids or path in seen_paths:
            raise ValueError('Two different videos and IDs are required')
        if path.suffix.casefold() != '.mov' or not path.is_file():
            raise ValueError('Select an existing local MOV')
        if path == output_path.resolve():
            raise ValueError('Manifest cannot overwrite a video')
        seen_ids.add(key)
        seen_paths.add(path)
        verdicts[labels[key]['verdict']] += 1
        videos.append({'video_id': original_ids[key], 'path': str(path)})
    if verdicts != Counter({'violation': 1, 'no_violation': 1}):
        raise ValueError('Batch must contain one normal and one positive reference video')
    return {'videos': videos}


def summarize(document, *, planned_videos=None, wall_elapsed_sec=None) -> dict:
    """Ignore all event content. Output only validated numeric aggregates."""
    if not isinstance(document, dict) or not isinstance(document.get('videos'), list):
        raise ValueError('Expected a predictions videos list')
    records = document['videos']
    if planned_videos is None:
        planned_videos = len(records)
    if type(planned_videos) is not int or planned_videos < len(records):
        raise ValueError('Invalid expected video count')
    statuses, samples, complete_times = Counter(), {}, []
    diagnostic_counts = Counter()
    versions = Counter()
    safe_diagnostics = {'invalid_json', 'json_token_limit', 'invalid_model_schema', 'too_many_events',
                        'invalid_frame_index', 'invalid_actor_schema', 'no_frames', 'invalid_object_json',
                        'object_check_timeout', 'object_check_invalid_output', 'object_check_skipped',
                        'event_count_above_target'}
    safe_diagnostics.update(('service_context_skipped', 'service_context_timeout', 'service_context_invalid_output'))
    safe_diagnostics.update(('relevance_rejected', 'relevance_fallback'))
    for row in records:
        if not isinstance(row, dict) or row.get('status') not in ('complete', 'partial', 'timeout', 'failed'):
            raise ValueError('Invalid processing status')
        statuses[row['status']] += 1
        version = row.get('inference_version')
        versions[INFERENCE_VERSION if version == INFERENCE_VERSION else 'other_or_missing'] += 1
        stages = row.get('stage_timings_sec', {})
        if not isinstance(stages, dict):
            raise ValueError('Invalid timing metrics')
        for stage in ('decode', 'relevance', 'observe', 'verify_object', 'service_context'):
            if stage in stages:
                samples.setdefault('stage_' + stage, []).append(number(stages[stage]))
        for warning in row.get('warnings', []):
            if not isinstance(warning, str):
                continue
            window = re.fullmatch(r'Window \d+: ([a-z_]+)', warning)
            count = re.fullmatch(r'(object_check_[a-z_]+|service_context_[a-z_]+|relevance_[a-z_]+|event_count_above_target): (\d+)', warning)
            if window and window.group(1) in safe_diagnostics:
                diagnostic_counts[window.group(1)] += 1
            elif count and count.group(1) in safe_diagnostics:
                diagnostic_counts[count.group(1)] += int(count.group(2))
        for field in ('elapsed_sec', 'duration_sec', 'gpu_peak_allocated_mib', 'gpu_peak_reserved_mib'):
            if field in row:
                value = number(row[field])
                samples.setdefault(field, []).append(value)
                if field == 'elapsed_sec' and row['status'] == 'complete':
                    complete_times.append(value)
    elapsed = samples.get('elapsed_sec', [])
    return {
        'planned_videos': planned_videos,
        'saved_results': len(records),
        'missing_results': planned_videos - len(records),
        'status_counts': {status: statuses[status] for status in ('complete', 'partial', 'timeout', 'failed')},
        'all_complete': bool(planned_videos) and statuses['complete'] == planned_videos,
        'diagnostic_counts': dict(diagnostic_counts),
        'inference_version_counts': dict(versions),
        'stage_timings': {stage: {'samples': len(samples.get('stage_' + stage, [])),
                                 'total_sec': sum(samples['stage_' + stage]) if 'stage_' + stage in samples else None}
                          for stage in ('decode', 'relevance', 'observe', 'verify_object', 'service_context')},
        'timing': {
            'elapsed_samples': len(elapsed),
            'mean_elapsed_sec': mean(elapsed) if elapsed else None,
            'max_elapsed_sec': max(elapsed, default=None),
            'complete_only_mean_elapsed_sec': mean(complete_times) if complete_times else None,
            'results_over_300_sec': sum(value > 300 for value in elapsed),
            'source_duration_samples': len(samples.get('duration_sec', [])),
            'source_duration_total_sec': sum(samples['duration_sec']) if 'duration_sec' in samples else None,
            'batch_wall_elapsed_sec': number(wall_elapsed_sec) if wall_elapsed_sec is not None else None},
        'gpu': {
            'allocated_samples': len(samples.get('gpu_peak_allocated_mib', [])),
            'peak_allocated_mib': max(samples.get('gpu_peak_allocated_mib', []), default=None),
            'reserved_samples': len(samples.get('gpu_peak_reserved_mib', [])),
            'peak_reserved_mib': max(samples.get('gpu_peak_reserved_mib', []), default=None)},
        'notes': ['Technical stability only; no rule verdict or event accuracy is evaluated.',
                  'Per-video elapsed excludes worker startup; batch wall time includes it when available.',
                  'GPU values are PyTorch counters, not total device usage.',
                  'No video IDs, paths, labels, observations or descriptions are included.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='action', required=True)
    prepare = subparsers.add_parser('prepare')
    prepare.add_argument('--labels', required=True, type=Path)
    prepare.add_argument('--output', required=True, type=Path)
    summary = subparsers.add_parser('summary')
    summary.add_argument('--predictions', required=True, type=Path)
    summary.add_argument('--manifest', type=Path)
    summary.add_argument('--wall-elapsed-sec', type=float)
    summary.add_argument('--output', required=True, type=Path)
    subset = subparsers.add_parser('select-labels')
    subset.add_argument('--labels', required=True, type=Path)
    subset.add_argument('--manifest', required=True, type=Path)
    subset.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError('Choose a new output filename')
        if args.action == 'prepare':
            labels = json.loads(args.labels.read_text(encoding='utf-8-sig'))
            selections = []
            for instruction in ('NORMAL video', 'video labelled VIOLATION'):
                print(f'Select {instruction}; ambiguous X-4/X-47 are excluded.', flush=True)
                filename = input('Paste full local MOV path (Copy as path): ').strip().strip('"\'')
                identifier = input('Original video ID from Excel (Enter if original filename kept): ').strip()
                if not identifier:
                    identifier = Path(filename).stem
                selections.append((filename, identifier))
            payload = build_manifest(labels, selections, args.output)
        elif args.action == 'select-labels':
            labels = json.loads(args.labels.read_text(encoding='utf-8-sig'))
            manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            payload = select_reference_by_manifest(labels, manifest)
        else:
            document = json.loads(args.predictions.read_text(encoding='utf-8-sig'))
            expected = None
            if args.manifest is not None:
                manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
                if not isinstance(manifest, dict) or not isinstance(manifest.get('videos'), list):
                    raise ValueError('Invalid manifest')
                expected = len(manifest['videos'])
            payload = summarize(document, planned_videos=expected, wall_elapsed_sec=args.wall_elapsed_sec)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, TypeError, KeyError, EOFError) as error:
        raise SystemExit(f'Batch tool failed [code={safe_batch_error(error)}]; private details suppressed') from None
    if args.action == 'prepare':
        print('Manifest saved for two labelled videos. Video bytes were not opened.', flush=True)
    elif args.action == 'select-labels':
        print(json.dumps({'selected_reference_records': len(payload['videos']),
                          'saved_locally': True}), flush=True)
    else:
        print(json.dumps(payload, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
