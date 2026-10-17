"""Optional CPU integration against the supplied AI4 source package."""
import base64
import copy
import json
from pathlib import Path
import unittest

from app.rules.decision import build_job_result, decide_video
from evaluation.run_rules import process_video
from evaluation.test_ai4_rules import CONTRACT, event_for, video

try:
    from app.inference.conditions import CONDITION_SPECS, parse_condition_checks
    from app.inference.schemas import INFERENCE_VERSION, InferenceResult, Observation
    from app.inference.evaluate_baseline import evaluate_baseline
    HAS_AI4 = INFERENCE_VERSION == '2026.10.18.4'
except ImportError:
    HAS_AI4 = False


@unittest.skipUnless(HAS_AI4, 'Needs the unchanged supplied AI 2026.10.18.4 source package')
class AI4SourceIntegrationTests(unittest.TestCase):
    def test_contract_matches_source_and_every_new_type_reaches_rules(self):
        self.assertEqual(CONDITION_SPECS,CONTRACT['candidates'])
        for name,spec in CONDITION_SPECS.items():
            answer={key:{'state':'observed','frames':[0,2]} for key in spec}
            parsed=parse_condition_checks(json.dumps(answer),name,3)
            checks={key:{'state':entry['state'],
                         'evidence_timestamps_sec':[[10,12,14][i] for i in entry['frames']]}
                    for key,entry in parsed.items()}
            event=Observation(type=name,start_sec=8,end_sec=16,
                              description='Synthetic AI4 contract case',
                              evidence_timestamps_sec=[10,14],timing_resolution_sec=2,
                              condition_checks=checks)
            source=InferenceResult(observations=[event],duration_sec=20,
                                   processed_windows=1,planned_windows=1).to_dict()
            original=copy.deepcopy(source)
            result=decide_video(source)
            with self.subTest(candidate=name):
                if name=='cash_counting_without_customer':
                    self.assertEqual(result['verdict'],'violation')
                else:
                    self.assertEqual(result['status'],'failed')
                self.assertEqual(source,original)
                if name=='previous_cash_outside_storage':
                    self.assertEqual(checks['previous_cash_continuously_tracked']['state'],'unclear')

    def test_supplied_ai4_dataclass_to_public_jpeg(self):
        event=event_for('cash_counting_without_customer')
        source=InferenceResult(observations=[Observation(
            type=event['type'],start_sec=event['start_sec'],end_sec=event['end_sec'],
            description=event['description'],evidence_timestamps_sec=[10,12],
            timing_resolution_sec=2,condition_checks=event['condition_checks'])],
            duration_sec=20,processed_windows=1,planned_windows=1).to_dict()
        jpeg=base64.b64encode((Path(__file__).parent/'fixtures'/'synthetic.jpg').read_bytes()).decode()
        result=build_job_result('synthetic-ai4',source,
                                lambda t:{'timestamp_sec':t,'image_base64':jpeg})
        self.assertEqual(result['status'],'done')
        self.assertEqual(result['verdict'],'violation')
        self.assertTrue(1<=len(result['violations'][0]['evidence_frames'])<=3)

    def test_final_predictions_are_accepted_by_ai4_evaluator(self):
        truth={'videos':[
            {'video_id':'synthetic_positive','verdict':'violation','timecode_sec':14},
            {'video_id':'synthetic_negative','verdict':'no_violation'},
            {'video_id':'synthetic_unresolved','verdict':'violation','timecode_sec':12},
        ]}
        cases=[video(event_for('cash_counting_without_customer')),video(),video(event_for('safe_left_open'))]
        predictions={'videos':[]}
        for ref,data in zip(truth['videos'],cases):
            data['video_id']=ref['video_id']
            predictions['videos'].append(process_video(data))
        report=evaluate_baseline(truth,predictions,tolerance_sec=2.0)
        self.assertEqual(report['primary_coverage']['failed'],1)
        self.assertEqual(report['primary_coverage']['decision_fraction'],2/3)
        metrics=report['verdict_metrics_on_complete_primary_only']
        self.assertEqual((metrics['tp'],metrics['tn'],metrics['fn'],metrics['fp']),(1,1,0,0))
        self.assertEqual(report['point_localization_on_complete_primary_only']['hits'],1)
        self.assertEqual(report['point_localization_on_complete_primary_only']['tolerance_sec'],2.0)


if __name__=='__main__':
    unittest.main()
