"""Basic verdict/point evaluation, separate from strict observation evaluation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from statistics import mean

from .evaluate import number


def video_key(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Expected video identifier')
    key = value.strip().casefold()
    if key.endswith('.mov'):
        key = key[:-4]
    # Dataset filenames may use Cyrillic Х while manually entered IDs use Latin X.
    # Normalize only the X-number identifier pattern, not arbitrary text.
    match = re.fullmatch(r'[xх]\s*[-_\u2010-\u2015\u2212]?\s*(\d+)', key)
    return f'x{int(match.group(1))}' if match else key


def rows(document):
    if not isinstance(document, dict):
        raise ValueError('Expected object')
    values = document.get('videos', [document])
    if not isinstance(values, list):
        raise ValueError('Expected videos list')
    return values


def reference_records(document) -> dict:
    result = {}
    for row in rows(document):
        if not isinstance(row, dict):
            raise ValueError('Expected reference object')
        key = video_key(row.get('video_id'))
        if key in result or row.get('verdict') not in ('violation', 'no_violation'):
            raise ValueError('Duplicate ID or invalid reference verdict')
        timestamp = number(row.get('timecode_sec')) if row['verdict'] == 'violation' else None
        result[key] = {'verdict': row['verdict'], 'timecode_sec': timestamp}
    if not result:
        raise ValueError('Reference must not be empty')
    return result


def prediction_records(document) -> dict:
    result = {}
    for row in rows(document):
        if not isinstance(row, dict):
            raise ValueError('Expected prediction object')
        key, status = video_key(row.get('video_id')), row.get('status')
        if key in result or status not in ('complete', 'partial', 'timeout', 'failed'):
            raise ValueError('Duplicate ID or invalid analysis status')
        if status != 'complete':
            result[key] = {'status': status}
            continue
        verdict, violations = row.get('verdict'), row.get('violations')
        if verdict not in ('violation', 'no_violation', 'needs_review') or not isinstance(violations, list):
            raise ValueError('Complete prediction needs final Rule Engine verdict and violations list')
        if verdict == 'no_violation' and violations:
            raise ValueError('Verdict inconsistent with violations list')
        times = []
        for violation in violations:
            if not isinstance(violation, dict):
                raise ValueError('Expected violation object')
            timestamp = number(violation.get('timecode_sec'))
            item_status = violation.get('status', 'needs_review' if verdict == 'needs_review' else 'violation')
            if item_status not in ('violation', 'needs_review'):
                raise ValueError('Invalid violation item status')
            if verdict == 'needs_review' and item_status == 'violation':
                raise ValueError('Review verdict cannot contain a confirmed violation')
            if item_status == 'violation':
                times.append(timestamp)
        if verdict == 'violation' and not times:
            raise ValueError('Violation verdict needs at least one confirmed point')
        result[key] = {'status': status, 'verdict': verdict, 'times': times}
    return result


def select_reference_by_manifest(truth_document, manifest_document) -> dict:
    """Fix evaluation scope BEFORE seeing predictions; failed/missing jobs stay in scope."""
    reference_records(truth_document)
    if not isinstance(manifest_document, dict) or not isinstance(manifest_document.get('videos'), list):
        raise ValueError('Manifest needs a videos list')
    entries = manifest_document['videos']
    if not entries:
        raise ValueError('Manifest must not be empty')
    indexed = {video_key(row['video_id']): row for row in rows(truth_document)}
    selected, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Manifest entry must be an object')
        key = video_key(entry.get('video_id'))
        if key in seen or key not in indexed:
            raise ValueError('Duplicate manifest ID or reference not found')
        seen.add(key)
        row = indexed[key]
        selected.append({'video_id': row['video_id'], 'verdict': row['verdict'],
                         'timecode_sec': row.get('timecode_sec')})
    return {'videos': selected}


def evaluate_baseline(truth_document, prediction_document, *, tolerance_sec=2.0,
                      ambiguous_groups=(('X-4', 'X-47'),)) -> dict:
    tolerance_sec = number(tolerance_sec)
    truth, predictions = reference_records(truth_document), prediction_records(prediction_document)
    if predictions.keys() - truth.keys():
        raise ValueError('Predictions contain unlabelled video IDs')
    excluded, present_groups = set(), []
    for group in ambiguous_groups:
        keys = {video_key(key) for key in group}
        if len(keys) < 2 or excluded & keys:
            raise ValueError('Groups must be disjoint and contain at least two unique IDs')
        excluded.update(keys)
        present = keys & truth.keys()
        if present:
            present_groups.append(present)
    primary = truth.keys() - excluded
    counts, statuses, ambiguity_statuses = Counter(), Counter(), Counter()
    errors, hits, positives, predicted_points = [], 0, 0, 0
    for key in primary:
        prediction = predictions.get(key)
        status = prediction['status'] if prediction else 'missing'
        statuses[status] += 1
        if status != 'complete':
            continue
        if prediction['verdict'] == 'needs_review':
            statuses['needs_review'] += 1
            continue
        expected = truth[key]['verdict'] == 'violation'
        found = prediction['verdict'] == 'violation'
        counts['tp' if expected and found else 'fn' if expected else 'fp' if found else 'tn'] += 1
        predicted_points += len(prediction['times'])
        if expected:
            positives += 1
            if found:
                error = min(abs(timestamp - truth[key]['timecode_sec']) for timestamp in prediction['times'])
                errors.append(error)
                hits += error <= tolerance_sec
    for key in truth.keys() & excluded:
        ambiguity_statuses[predictions[key]['status'] if key in predictions else 'missing'] += 1
    tp, fp, fn, tn = (counts[name] for name in ('tp', 'fp', 'fn', 'tn'))
    total = tp + fp + fn + tn
    statuses_order = ('complete', 'partial', 'timeout', 'failed', 'missing')
    return {
        'evaluation_scope': 'primary records only; ambiguous groups excluded',
        'evaluation_complete': bool(primary) and total == len(primary),
        'reference_records_total': len(truth),
        'primary_coverage': {'reference_records': len(primary),
            **{status: statuses[status] for status in statuses_order},
            'complete_fraction': statuses['complete'] / len(primary) if primary else None,
            'needs_review': statuses['needs_review'],
            'decision_fraction': total / len(primary) if primary else None},
        'ambiguity': {'groups_present': len(present_groups),
            'reference_records_excluded': sum(len(group) for group in present_groups),
            'known_duplicate_groups_excluded_from_primary': True,
            'record_status_counts': {status: ambiguity_statuses[status] for status in statuses_order},
            'metrics_computed': False},
        'verdict_metrics_on_complete_primary_only': {
            'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            'accuracy': (tp + tn) / total if total else None},
        'point_localization_on_complete_primary_only': {
            'tolerance_sec': tolerance_sec, 'reference_positive_videos': positives,
            'hits': hits, 'misses': positives - hits,
            'hit_rate': hits / positives if positives else None,
            'mean_nearest_error_on_detected_positives_sec': mean(errors) if errors else None,
            'detected_positive_samples_for_error': len(errors),
            'predicted_points_total': predicted_points},
        'notes': [
            'Verdict comes from Rule Engine, never from nonempty AI observations.',
            'Incomplete predictions excluded; report primary coverage alongside metrics.',
            'needs_review is abstention: excluded from binary and timing metrics; report decision_fraction.',
            'Ambiguous duplicate records are excluded; no independent scores for that pair.',
            'Localization hit uses nearest predicted point, without type or interval matching.',
            'One reference point is not exhaustive event annotation; extra points are not scored as event FP.',
            'Inspect predicted_points_total: many guesses can inflate nearest-point hit rate.',
            'No identifiers, event descriptions, reference times or frames are included.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--truth', required=True, type=Path)
    parser.add_argument('--predictions', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--tolerance-sec', type=float, default=2.0)
    parser.add_argument('--manifest', type=Path, help='Evaluate only IDs planned in this manifest')
    args = parser.parse_args()
    try:
        sources = [args.truth.resolve(), args.predictions.resolve()]
        if args.manifest is not None:
            sources.append(args.manifest.resolve())
        if args.report.resolve() in sources:
            raise ValueError('Report cannot overwrite input')
        truth = json.loads(args.truth.read_text(encoding='utf-8-sig'))
        reference_count = len(reference_records(truth))
        if args.manifest is not None:
            manifest = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            truth = select_reference_by_manifest(truth, manifest)
        predictions = json.loads(args.predictions.read_text(encoding='utf-8-sig'))
        report = evaluate_baseline(truth, predictions, tolerance_sec=args.tolerance_sec)
        report['selection'] = {'mode': 'manifest' if args.manifest is not None else 'all_references',
                               'available_reference_records': reference_count,
                               'selected_reference_records': len(reference_records(truth))}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    except (OSError, ValueError, TypeError):
        raise SystemExit('Baseline evaluation failed: check local normalized JSON, verdicts and times') from None
    print(json.dumps(report, ensure_ascii=False))
    if not report['evaluation_complete']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
