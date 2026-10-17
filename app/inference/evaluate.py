"""Local event evaluation. Reports contain aggregates, never event text or IDs."""
import argparse
from collections import Counter, deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class Event:
    type: str
    start: float
    end: float


def number(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError('Expected a finite nonnegative number')
    return float(value)


def records(document, *, prediction: bool) -> dict:
    if not isinstance(document, dict):
        raise ValueError('Input must be an object')
    rows = document.get('videos', [document])
    if not isinstance(rows, list) or (not rows and not prediction):
        raise ValueError('Reference needs a nonempty videos list')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Video record must be an object')
        key = row.get('video_id')
        if not isinstance(key, str) or not key or key in result:
            raise ValueError('video_id must be a unique nonempty string')
        status = row.get('status') if prediction else 'reference'
        if prediction and status not in ('complete', 'partial', 'timeout', 'failed'):
            raise ValueError('Prediction needs explicit complete/partial/timeout/failed status')
        observations = row.get('observations')
        if not isinstance(observations, list):
            raise ValueError('observations must be a list')
        events = []
        for observation in observations:
            if not isinstance(observation, dict):
                raise ValueError('Observation must be an object')
            category = observation.get('type')
            if not isinstance(category, str) or not category.strip():
                raise ValueError('Observation needs a nonempty type')
            start, end = number(observation.get('start_sec')), number(observation.get('end_sec'))
            if start > end:
                raise ValueError('start_sec must not exceed end_sec')
            events.append(Event(category, start, end))
        runtime = {name: number(row[name]) for name in (
            'elapsed_sec', 'gpu_peak_allocated_mib', 'gpu_peak_reserved_mib') if name in row}
        # Discard all descriptions, evidence, identifiers and actor fields here.
        result[key] = {'status': status, 'events': sorted(events, key=lambda e: (e.type, e.start, e.end)),
                       'runtime': runtime}
    return result


def temporal_iou(left: Event, right: Event) -> float:
    union = max(left.end, right.end) - min(left.start, right.start)
    if union == 0:
        return 1.0
    return max(0.0, min(left.end, right.end) - max(left.start, right.start)) / union


def match_events(truth: list[Event], predictions: list[Event], *, mode: str,
                 tolerance: float, iou_threshold: float) -> list[tuple[int, int]]:
    """Maximum-cardinality bipartite matching; never reuse an event."""
    adjacency = []
    for pred in predictions:
        compatible = []
        for index, reference in enumerate(truth):
            if pred.type != reference.type:
                continue
            error = max(abs(pred.start - reference.start), abs(pred.end - reference.end))
            if mode == 'boundaries':
                eligible = error <= tolerance
            elif pred.start == pred.end and reference.start == reference.end:
                eligible = error <= tolerance
            else:
                eligible = temporal_iou(pred, reference) >= iou_threshold
            if eligible:
                compatible.append((error, index))
        adjacency.append([index for _, index in sorted(compatible)])
    match_pred, match_truth = {}, {}
    for root in range(len(predictions)):
        queue, seen_pred, parent_truth = deque([root]), {root}, {}
        free_truth = None
        while queue and free_truth is None:
            pred_index = queue.popleft()
            for truth_index in adjacency[pred_index]:
                if truth_index in parent_truth:
                    continue
                parent_truth[truth_index] = pred_index
                if truth_index not in match_truth:
                    free_truth = truth_index
                    break
                other_pred = match_truth[truth_index]
                if other_pred not in seen_pred:
                    seen_pred.add(other_pred)
                    queue.append(other_pred)
        while free_truth is not None:
            pred_index = parent_truth[free_truth]
            previous = match_pred.get(pred_index)
            match_pred[pred_index] = free_truth
            match_truth[free_truth] = pred_index
            free_truth = previous
    return sorted((truth_index, pred_index) for pred_index, truth_index in match_pred.items())


def evaluate(truth_document, prediction_document, *, mode='boundaries',
             tolerance_sec=2.0, iou_threshold=0.3) -> dict:
    tolerance_sec = number(tolerance_sec)
    iou_threshold = number(iou_threshold)
    if mode not in ('boundaries', 'iou') or not 0 < iou_threshold <= 1:
        raise ValueError('Invalid matching configuration')
    truth = records(truth_document, prediction=False)
    predictions = records(prediction_document, prediction=True)
    if predictions.keys() - truth.keys():
        raise ValueError('Prediction contains videos absent from reference')
    statuses = Counter()
    tp = fp = fn = unknown_truth = unknown_pred = 0
    start_errors, end_errors, ious = [], [], []
    runtime = {'elapsed_sec': [], 'gpu_peak_allocated_mib': [], 'gpu_peak_reserved_mib': []}
    negative_videos = negative_with_fp = 0
    for video_id, reference in truth.items():
        prediction = predictions.get(video_id)
        if prediction is None:
            statuses['missing'] += 1
            continue
        statuses[prediction['status']] += 1
        for name, value in prediction['runtime'].items():
            runtime[name].append(value)
        if prediction['status'] != 'complete':
            continue
        expected, found = reference['events'], prediction['events']
        pairs = match_events(expected, found, mode=mode,
                             tolerance=tolerance_sec, iou_threshold=iou_threshold)
        tp += len(pairs)
        fp += len(found) - len(pairs)
        fn += len(expected) - len(pairs)
        unknown_truth += sum(event.type == 'unknown' for event in expected)
        unknown_pred += sum(event.type == 'unknown' for event in found)
        if not expected:
            negative_videos += 1
            negative_with_fp += bool(found)
        for truth_index, pred_index in pairs:
            left, right = expected[truth_index], found[pred_index]
            start_errors.append(abs(left.start - right.start))
            end_errors.append(abs(left.end - right.end))
            ious.append(temporal_iou(left, right))
    def average(values):
        return mean(values) if values else None
    return {
        'evaluation_complete': statuses['complete'] == len(truth),
        'matching': {'mode': mode, 'boundary_tolerance_sec': tolerance_sec,
                     'iou_threshold': iou_threshold,
                     'policy': 'same type; maximum one-to-one cardinality; timing tie preference only'},
        'coverage': {'reference_videos': len(truth),
                     **{status: statuses[status] for status in ('complete', 'partial', 'timeout', 'failed', 'missing')},
                     'complete_fraction': statuses['complete'] / len(truth)},
        'metrics_on_complete_videos_only': {
            'tp': tp, 'fp': fp, 'fn': fn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            'mean_start_error_sec': average(start_errors),
            'mean_end_error_sec': average(end_errors), 'mean_temporal_iou': average(ious),
            'unknown_reference_events': unknown_truth, 'unknown_predicted_events': unknown_pred,
            'negative_videos': negative_videos, 'negative_videos_with_false_alarms': negative_with_fp,
        },
        'runtime_on_available_predictions': {
            'elapsed_samples': len(runtime['elapsed_sec']),
            'mean_elapsed_sec': average(runtime['elapsed_sec']),
            'max_elapsed_sec': max(runtime['elapsed_sec'], default=None),
            'max_gpu_allocated_mib': max(runtime['gpu_peak_allocated_mib'], default=None),
            'max_gpu_reserved_mib': max(runtime['gpu_peak_reserved_mib'], default=None),
        },
        'notes': ['No video IDs, event descriptions, actors or frame data in this report.',
                  'Incomplete/missing videos excluded from event metrics; check coverage first.',
                  'unknown matches only unknown; this does not validate a rule category.',
                  'Undefined ratios are null. Timing metrics use matched pairs only.',
                  'Maximum-cardinality pairing does not minimize total timing error.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--truth', required=True, type=Path)
    parser.add_argument('--predictions', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--match-mode', choices=('boundaries', 'iou'), default='boundaries')
    parser.add_argument('--tolerance-sec', type=float, default=2.0)
    parser.add_argument('--iou-threshold', type=float, default=0.3)
    args = parser.parse_args()
    try:
        # Never overwrite an input file, including through a symlink.
        if args.report.resolve() in (args.truth.resolve(), args.predictions.resolve()):
            raise ValueError('Report must differ from input paths')
        truth = json.loads(args.truth.read_text(encoding='utf-8-sig'))
        predictions = json.loads(args.predictions.read_text(encoding='utf-8-sig'))
        report = evaluate(truth, predictions, mode=args.match_mode,
                          tolerance_sec=args.tolerance_sec, iou_threshold=args.iou_threshold)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    except (OSError, ValueError, TypeError):
        # Do not echo private paths, malformed records or JSON excerpts.
        raise SystemExit('Evaluation failed: check local files, schema and numeric parameters') from None
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    if not report['evaluation_complete']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
