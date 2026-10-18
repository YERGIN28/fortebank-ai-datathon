"""Aggregate local diagnostics; never print event types, text, timestamps or frames."""
import json
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.service_manager import PRIVATE
from app.rules.actions import ACTION_CATALOG
from app.rules.catalog import RULE_CATALOG


def summarize_inference(payload, assessment_mode='strict'):
    if assessment_mode == 'possible_signs':
        from app.rules.indicator_catalog import INDICATOR_CATALOG
        catalog = INDICATOR_CATALOG
    else:
        catalog = RULE_CATALOG
    counts = Counter()
    observations = payload.get('observations', [])
    for event in observations:
        counts['observations'] += 1
        kind = event.get('type')
        if kind == 'unknown':
            counts['unknown_action'] += 1
            continue
        if kind in ACTION_CATALOG and kind not in catalog:
            counts['ordinary_action'] += 1
            continue
        rule = catalog.get(kind)
        if rule is None:
            counts['unsupported_category'] += 1
            continue
        counts['rule_candidate'] += 1
        available = rule.get('enabled') if assessment_mode == 'possible_signs' else (
            rule.get('verified') and rule.get('regulation') and rule.get('decision_mode') != 'review_only')
        if not available:
            counts['candidate_without_automatic_rule'] += 1
        checks = event.get('condition_checks', {})
        required = rule['conditions'] + rule.get('scope_conditions', []) + rule.get('exceptions', [])
        counts['required_checks'] += len(required)
        for name in required:
            check = checks.get(name, {})
            state = check.get('state') if check.get('evidence_timestamps_sec') else None
            counts['checks_' + (state if state in ('observed', 'refuted', 'unclear') else 'missing')] += 1
    return dict(counts)


def main():
    last = json.loads((PRIVATE / 'last_service_run.json').read_text(encoding='utf-8'))
    source = PRIVATE / 'results' / Path(last['predictions']).name
    batch = json.loads(source.read_text(encoding='utf-8'))
    totals = Counter()
    totals['planned_results'] = len(batch['videos'])
    for row in batch['videos']:
        identity = row.get('job_id', '')
        if not isinstance(identity, str) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            totals['audit_missing'] += 1
            continue
        artifact = PRIVATE / 'inference_audit' / (identity + '.json')
        if not artifact.exists():
            totals['audit_missing'] += 1
            continue
        saved = json.loads(artifact.read_text(encoding='utf-8'))
        payload = saved['inference']
        totals['audited_results'] += 1
        totals.update(summarize_inference(payload, saved.get('assessment_mode','strict')))
    report = {'counts':dict(totals), 'note':'Aggregate only. Missing old audit artifacts are not reconstructed by rerunning videos.'}
    (PRIVATE / 'results' / 'quality_diagnostics_summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
