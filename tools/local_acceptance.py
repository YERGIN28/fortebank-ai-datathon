"""Local HTTP checks. Only aggregate counters go to stdout; raw results stay private."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service_manager import initialize, PRIVATE, RUNTIME, URL
from app.inference.smoke_http import run_probe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, help='Explicit local manifest; never prints source content')
    parser.add_argument('--expect-version', help='Require this loaded version; defaults to the local source version')
    args = parser.parse_args()
    values = initialize()
    if args.manifest is None:
        result = run_probe(URL, values['API_KEY'])
        (PRIVATE / 'results').mkdir(parents=True, exist_ok=True)
        (PRIVATE / 'results' / 'service_synthetic_check.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
        return
    import httpx
    from app.inference.evaluate_baseline import evaluate_baseline, select_reference_by_manifest
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    entries = manifest.get('videos', [])
    if not entries:
        raise ValueError('Empty manifest')
    run = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    result_dir = PRIVATE / 'results'
    result_dir.mkdir(parents=True, exist_ok=True)
    target = result_dir / ('service_predictions_' + run + '.json')
    rows, elapsed, reasons = [], [], Counter()
    with httpx.Client(base_url=URL, trust_env=False, follow_redirects=False, timeout=15,
                      headers={'X-API-Key': values['API_KEY']}) as client:
        from app.inference import INFERENCE_VERSION
        response = client.get('/health')
        response.raise_for_status()
        health = response.json()
        expected = args.expect_version or INFERENCE_VERSION
        if health.get('inference_version') != expected:
            raise SystemExit('Loaded worker version differs from expected source. Restart the managed service before a new approved run.')
        if health.get('assessment_mode') != 'possible_signs':
            raise SystemExit('This acceptance command requires the reviewed possible_signs service configuration.')
        for entry in entries:
            started = time.perf_counter()
            path = Path(entry['path'])
            with path.open('rb') as source:
                submitted = client.post('/api/v1/analyze', files={'file': (path.name, source, 'video/quicktime')})
            submitted.raise_for_status()
            job = submitted.json()['job_id']
            deadline = time.monotonic() + 330
            while True:
                response = client.get('/api/v1/jobs/' + job)
                response.raise_for_status()
                data = response.json()
                if data['status'] != 'processing':
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Local acceptance polling timed out; do not start another worker')
                time.sleep(1)
            duration = time.perf_counter() - started
            elapsed.append(duration)
            data['video_id'] = entry['video_id']
            data['status'] = 'complete' if data['status'] == 'done' else data['status']
            rows.append(data)
            target.write_text(json.dumps({'videos': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
            if data['status'] == 'failed':
                error = data.get('error', '')
                reason = ('unresolved_observations' if error.startswith('unresolved_observations:') else
                          'timeout' if 'timeout' in error.lower() or '300 seconds' in error else
                          'incomplete_inference' if error.startswith('Inference did not complete') else 'technical_error')
                reasons[reason] += 1
            print(json.dumps({'finished': len(rows), 'total': len(entries),
                              'status_counts': dict(Counter(row['status'] for row in rows))}), flush=True)
    summary = {'inference_version': health['inference_version'],
               'model_name': health.get('model_name'), 'quantization': health.get('quantization'),
               'positive_verification': health.get('positive_verification'),
               'rules_version': health.get('rules_version'), 'assessment_mode': health['assessment_mode'],
               'videos': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows)),
               'verdict_counts': dict(Counter(r.get('verdict', 'unresolved') for r in rows)),
               'failure_categories': dict(reasons), 'max_elapsed_sec': round(max(elapsed), 3),
               'mean_elapsed_sec': round(sum(elapsed)/len(elapsed), 3),
               'over_300_seconds': sum(t > 300 for t in elapsed)}
    labels = PRIVATE / 'labels' / 'baseline_labels.json'
    if labels.exists():
        truth = select_reference_by_manifest(json.loads(labels.read_text(encoding='utf-8')), manifest)
        evaluation = evaluate_baseline(truth, {'videos': rows}, tolerance_sec=2)
        summary['evaluation'] = {key: evaluation[key] for key in (
            'primary_coverage', 'verdict_metrics_on_complete_primary_only',
            'point_localization_on_complete_primary_only', 'system_metrics_all_primary_records')}
    (result_dir / ('service_summary_' + run + '.json')).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (PRIVATE / 'last_service_run.json').write_text(json.dumps({'predictions': target.name,
               'summary': 'service_summary_' + run + '.json'}, indent=2), encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
