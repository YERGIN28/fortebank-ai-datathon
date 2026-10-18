"""Contract-only synthetic cases. No videos, labels or real observations."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app.rules.actions import ACTION_CATALOG
from app.rules.ai4_catalog import AI4_REVIEW_RULES
from app.rules.catalog import RULE_CATALOG
from app.rules.classifier import classify_observation, classify_observations
from app.rules.decision import build_job_result, decide_video
from app.rules.engine import check_events
from evaluation.run_rules import process_video

CONTRACT = json.loads((Path(__file__).parent/'fixtures'/'ai4_condition_contract.json').read_text(encoding='utf-8'))
CONNECTED = ('cashier_leaves_during_service','cash_counting_without_customer','previous_cash_outside_storage')


def event_for(name):
    rule = RULE_CATALOG[name]
    conditions = rule['conditions'] + rule.get('scope_conditions', [])
    checks = {key: {'state':'observed','evidence_timestamps_sec':[10,12]} for key in conditions}
    checks.update({key:{'state':'refuted','evidence_timestamps_sec':[10,12]} for key in rule.get('exceptions',[])})
    return {'type':name,'start_sec':8,'end_sec':16,
            'description':'Synthetic contract case, not real observations',
            'condition_checks':checks,'confidence':None}


def video(*events):
    return {'video_id':'synthetic','status':'complete','duration_sec':20,
            'processed_windows':1,'planned_windows':1,'observations':list(events)}


class AI4ContractTests(unittest.TestCase):
    def test_every_candidate_preserved_and_non_neutral(self):
        for name in CONTRACT['candidates']:
            with self.subTest(candidate=name):
                event=event_for(name)
                event['description']='Customer hands a banknote to cashier.'
                original=copy.deepcopy(event)
                self.assertEqual(classify_observation(event),name)
                self.assertEqual(classify_observations([event])[0]['type'],name)
                self.assertNotIn(name,ACTION_CATALOG)
                candidate=check_events([event])[0]
                self.assertEqual(candidate['condition_checks'],event['condition_checks'])
                self.assertEqual(event,original)
                self.assertEqual(RULE_CATALOG[name]['conditions'],list(CONTRACT['candidates'][name]))

    def test_every_candidate_condition_matrix(self):
        for name in (*CONNECTED,*AI4_REVIEW_RULES):
            rule=RULE_CATALOG[name]
            event=event_for(name)
            with self.subTest(candidate=name,case='all_observed'):
                result=decide_video(video(event))
                self.assertEqual(result.get('verdict'),'violation' if name in CONNECTED else None)
                self.assertEqual(result['status'],'done' if name in CONNECTED else 'failed')
            for key in rule['conditions']+rule.get('scope_conditions',[]):
                for case in ('unclear','missing','no_evidence','refuted'):
                    modified=copy.deepcopy(event)
                    if case=='missing':
                        modified['condition_checks'].pop(key)
                    elif case=='no_evidence':
                        modified['condition_checks'][key]['evidence_timestamps_sec']=[]
                    else:
                        modified['condition_checks'][key]['state']=case
                    with self.subTest(candidate=name,condition=key,case=case):
                        result=decide_video(video(modified))
                        if case=='refuted' and key not in rule.get('visibility_conditions',[]):
                            self.assertEqual(result['verdict'],'no_violation')
                        else:
                            self.assertEqual(result['status'],'failed')
                            self.assertNotIn('verdict',result)

    def test_exceptions_each_connected_rule_and_review_candidate(self):
        for name in (*CONNECTED,*AI4_REVIEW_RULES):
            rule=copy.deepcopy(RULE_CATALOG[name])
            # The three narrow cash rules express exclusions in applicability
            # conditions. Exercise the general exception gate without inventing law.
            if not rule.get('exceptions'):
                rule['exceptions']=['synthetic_exception_only']
            with patch.dict(RULE_CATALOG,{name:rule}):
                event=event_for(name)
                for exception in rule['exceptions']:
                    modified=copy.deepcopy(event)
                    modified['condition_checks'][exception]['state']='observed'
                    with self.subTest(candidate=name,exception=exception):
                        self.assertEqual(decide_video(video(modified))['verdict'],'no_violation')

    def test_right_time_condition_and_three_frames_max(self):
        for name in CONNECTED:
            event=event_for(name)
            key=RULE_CATALOG[name]['time_condition']
            event['condition_checks'][key]['evidence_timestamps_sec']=[14]
            # The chosen action point must also have simultaneous supporting facts.
            for condition in RULE_CATALOG[name]['temporal_policy']['simultaneous']:
                event['condition_checks'][condition]['evidence_timestamps_sec']=[14]
            with self.subTest(candidate=name):
                result=decide_video(video(event))
                self.assertEqual(result['violations'][0]['timecode_sec'],14)
                self.assertLessEqual(len(result['violations'][0]['evidence_timestamps_sec']),3)

    def test_preserve_unsupported_tracking_uncertainty(self):
        event=event_for('previous_cash_outside_storage')
        event['condition_checks']['previous_cash_continuously_tracked']['state']='unclear'
        before=copy.deepcopy(event)
        self.assertEqual(decide_video(video(event))['status'],'failed')
        self.assertEqual(event,before)
        self.assertFalse(RULE_CATALOG[event['type']]['inference_supported'])

    def test_unresolved_does_not_erase_other_confirmed_event(self):
        positive=event_for('cash_counting_without_customer')
        for name in AI4_REVIEW_RULES:
            with self.subTest(candidate=name):
                result=decide_video(video(event_for(name),positive))
                self.assertEqual(result['verdict'],'violation')
                self.assertEqual(len(result['violations']),1)

    def test_description_cannot_convert_unknown_to_final_negative(self):
        event=event_for('cash_counting_without_customer')
        event.update(type='unknown',description='Customer hands a banknote to cashier.')
        self.assertEqual(decide_video(video(event))['status'],'failed')
        event['type']='document_transfer'
        self.assertEqual(decide_video(video(event))['verdict'],'no_violation')

    def test_evaluation_complete_and_public_done_are_distinct(self):
        data=video()
        self.assertEqual(process_video(data,assessment_mode='strict')['status'],'complete')
        self.assertEqual(build_job_result('synthetic',data,lambda t:None)['status'],'done')
        failed=process_video(video(event_for('safe_left_open')),assessment_mode='strict')
        self.assertEqual(failed['status'],'failed')
        self.assertNotIn('verdict',failed)


if __name__=='__main__':
    unittest.main()
