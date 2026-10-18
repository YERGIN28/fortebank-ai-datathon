"""Artificial rule facts only; no real videos, labels or expected model answers."""
import copy
import json
import pytest
from app.rules.indicator_catalog import INDICATOR_CATALOG, SCENARIO_COVERAGE
from app.rules.decision import decide_video, build_job_result
from app.rules.classifier import classify_observation
from app.inference.conditions import CONDITION_SPECS, parse_condition_checks
from app.inference.schemas import OBSERVATION_TYPES
from evaluation.run_rules import process_video


def event_for(name):
    rule = INDICATOR_CATALOG[name]
    checks = {condition: {'state':'observed','evidence_timestamps_sec':[10.0,13.0]}
              for condition in rule['conditions']}
    return {'type':name,'start_sec':8.0,'end_sec':16.0,'description':'Artificial example.',
            'condition_checks':checks,'evidence_timestamps_sec':[10.0,13.0]}


def video_for(event):
    return {'video_id':'synthetic_case','status':'complete','processed_windows':1,
            'planned_windows':1,'duration_sec':20,'observations':[event]}


ENABLED = [name for name, rule in INDICATOR_CATALOG.items() if rule['enabled']]


@pytest.mark.parametrize('name', ENABLED)
def test_visible_supported_sign_reaches_possible_verdict(name):
    result = decide_video(video_for(event_for(name)), assessment_mode='possible_signs')
    assert result['status'] == 'done'
    assert result['verdict'] == 'violation'
    assert 'проверки человеком' in result['violations'][0]['description']


@pytest.mark.parametrize('name', list(INDICATOR_CATALOG))
def test_category_without_facts_is_not_a_positive_or_negative(name):
    event = event_for(name)
    event['condition_checks'] = {}
    result = decide_video(video_for(event), assessment_mode='possible_signs')
    assert result['status'] == 'failed'
    assert 'verdict' not in result


def test_every_scenario_is_mapped_and_every_enabled_check_is_producible():
    assert set(SCENARIO_COVERAGE) == set(range(1,21))
    for names in SCENARIO_COVERAGE.values():
        assert set(names) <= set(OBSERVATION_TYPES)
    for name, rule in INDICATOR_CATALOG.items():
        assert classify_observation({'type':name}) == name
        from app.rules.engine import check_events
        event = event_for(name)
        assert process_video(video_for(event))['candidates'] == check_events([event], assessment_mode='possible_signs')
        if name == 'cashier_leaves_during_service':
            continue
        assert set(rule['conditions']) <= set(CONDITION_SPECS[name])
        assert not rule.get('scope_conditions')


def test_screen_alert_does_not_require_or_claim_unlock_or_confidential_content():
    event = event_for('workstation_left_with_screen_on')
    possible = decide_video(video_for(event), assessment_mode='possible_signs')
    strict = decide_video(video_for(event), assessment_mode='strict')
    assert possible['verdict'] == 'violation'
    assert strict['status'] == 'failed'
    description = possible['violations'][0]['description']
    assert 'не установлены' in description
    assert 'норма не подтверждена' in description
    assert 'компьютер разблокирован' not in description


def test_cash_with_next_customer_does_not_claim_provenance():
    result = decide_video(video_for(event_for('cash_on_desk_with_next_customer')), assessment_mode='possible_signs')
    assert result['verdict'] == 'violation'
    assert 'принадлежность предыдущему клиенту' in result['violations'][0]['description']
    assert 'не доказаны' in result['violations'][0]['description']


def test_before_departure_only_cannot_be_reported_as_after_departure():
    event = event_for('workstation_left_with_screen_on')
    event['condition_checks']['screen_on_after_departure']['evidence_timestamps_sec'] = [10]
    assert decide_video(video_for(event),assessment_mode='possible_signs')['status']=='failed'


def test_a_cup_and_cash_at_different_moments_do_not_match():
    event = event_for('cash_on_desk_during_break')
    event['condition_checks']['operator_drinking']['evidence_timestamps_sec']=[15]
    assert decide_video(video_for(event),assessment_mode='possible_signs')['status']=='failed'


@pytest.mark.parametrize('name', ['entrance_door_left_open','cash_left_after_counting','safe_open_during_other_activity'])
def test_single_moment_cannot_establish_persistence(name):
    event = event_for(name)
    for condition in INDICATOR_CATALOG[name]['temporal_policy']['minimum_span']:
        event['condition_checks'][condition]['evidence_timestamps_sec']=[13]
    assert decide_video(video_for(event),assessment_mode='possible_signs')['status']=='failed'


def test_returning_banknotes_alone_is_not_a_violation():
    event={'type':'cash_returned_after_check','start_sec':1,'end_sec':2,'description':'Artificial return.'}
    result=decide_video(video_for(event),assessment_mode='possible_signs')
    assert result['verdict']=='no_violation'


@pytest.mark.parametrize('name', ['cash_received_without_visible_id_check','cash_stored_without_visible_check'])
def test_sparse_negative_procedure_claim_cannot_be_enabled_by_model(name):
    answer={key:{'state':'observed','frames':[0,3]} for key in CONDITION_SPECS[name]}
    checks=parse_condition_checks(json.dumps(answer),name,4)
    assert any(check['state']=='unclear' for check in checks.values())
    assert decide_video(video_for(event_for(name)),assessment_mode='possible_signs')['status']=='failed'


def test_refutation_unknown_and_positive_have_distinct_outcomes():
    event=event_for('safe_left_open')
    event['condition_checks']['safe_open_after_departure']['state']='refuted'
    assert decide_video(video_for(event),assessment_mode='possible_signs')['verdict']=='no_violation'
    event['condition_checks']['safe_open_after_departure']['state']='unclear'
    assert decide_video(video_for(event),assessment_mode='possible_signs')['status']=='failed'


def test_incomplete_video_cannot_produce_a_possible_verdict():
    video=video_for(event_for('safe_left_open'))
    video['status']='partial'
    assert decide_video(video,assessment_mode='possible_signs')['status']=='failed'


def test_export_and_decision_use_the_same_explicit_mode():
    video=video_for(event_for('workstation_left_with_screen_on'))
    assert process_video(video)['verdict']=='violation'
    assert process_video(video,assessment_mode='possible_signs')['verdict']=='violation'
    assert process_video(video,assessment_mode='strict')['status']=='failed'


def test_old_strict_catalog_not_mutated():
    from app.rules.catalog import RULE_CATALOG
    assert RULE_CATALOG['workstation_left_with_screen_on']['verified'] is False
    assert 'session_is_unlocked' in RULE_CATALOG['workstation_left_with_screen_on']['scope_conditions']
