"""Generated clips and fake answers only. These are logic tests, not accuracy claims."""
import json
from pathlib import Path
import tempfile
import unittest

from . import InferenceConfig, InferenceEngine
from .model import QwenModel
from .postprocess import normalize_action
from .synthetic import create_video
from app.rules.decision import decide_video


class PositiveVerificationTests(unittest.TestCase):
    def test_context_preserves_seed_close_to_video_end(self):
        from .pipeline import context_targets
        from .schemas import Observation
        event = Observation(9,9.98,'Synthetic.',[9,9.98],1)
        self.assertIn(9.98,context_targets(event,10))

    def test_context_retains_seed_evidence(self):
        from .pipeline import context_targets
        from .schemas import Observation
        event = Observation(10,16,'Synthetic.',[10,12,14,16],2)
        result = context_targets(event,30)
        self.assertTrue(set(event.evidence_timestamps_sec).issubset(result))
        self.assertEqual(len(result),6)
        self.assertLess(result[0],10)
        self.assertGreater(result[-1],16)

    def test_context_budget_cannot_be_taken_only_by_repeated_category(self):
        from .pipeline import context_order
        from .schemas import Observation
        observations = [Observation(i,i+1,'Synthetic.',[i],1,type='safe_left_open') for i in range(4)]
        observations += [Observation(10,11,'Synthetic.',[10],1,type='workstation_left_with_screen_on'),
                         Observation(12,13,'Synthetic.',[12],1,type='cash_on_desk_with_next_customer')]
        first = context_order(observations)[:3]
        self.assertEqual(len({item.type for item in first}),3)

    def run_case(self, second='observed', *, budget=3, broken=False, initial='observed'):
        class Model:
            calls = 0
            def load(self): pass
            def reset_metrics(self): pass
            def metrics(self): return {}
            def observe(self, frames, deadline):
                return [{'start_frame':0, 'end_frame':len(frames)-1,
                         'type':'cashier_leaves_during_service','object_kind':'none',
                         'description':'Synthetic workstation departure candidate.'}]
            def check_service_context(self, frames, deadline):
                return {name:{'state':initial,'frames':[0,len(frames)-1]}
                        for name in ('cashier_left_workplace','customer_service_ongoing')}
            def verify_positive_conditions(self, frames, action, deadline):
                self.calls += 1
                if broken:
                    raise ValueError('Generated invalid output')
                return {name:{'state':second,'frames':[0,len(frames)-1]}
                        for name in ('cashier_left_workplace','customer_service_ongoing')}
        model = Model()
        with tempfile.TemporaryDirectory(prefix='forte-verification-') as folder:
            path = Path(folder) / 'generated.mov'
            create_video(path)
            result = InferenceEngine(InferenceConfig(Path('unused'), verify_positive_conditions=True,
                                     max_positive_checks=budget), model=model).analyze_video(path)
        return result, model

    def test_agreement_preserves_supported_candidate(self):
        result, model = self.run_case()
        self.assertEqual(model.calls, 1)
        self.assertEqual(decide_video(result.to_dict())['verdict'], 'violation')
        self.assertIn('positive_verification_supported: 1', result.warnings)

    def test_disagreement_is_abstention_and_never_negative(self):
        for state in ('unclear','refuted'):
            with self.subTest(state=state):
                result, model = self.run_case(state)
                self.assertEqual(model.calls,1)
                self.assertEqual(len(result.observations),1)
                self.assertTrue(all(check['state']=='unclear' for check in
                                    result.observations[0].condition_checks.values()))
                decision = decide_video(result.to_dict())
                self.assertEqual(decision['status'],'failed')
                self.assertNotIn('verdict',decision)

    def test_unavailable_budget_or_output_cannot_certify_positive(self):
        for kwargs in ({'budget':0},{'broken':True}):
            with self.subTest(kwargs=kwargs):
                result, _ = self.run_case(**kwargs)
                self.assertEqual(decide_video(result.to_dict())['status'],'failed')

    def test_unclear_first_pass_is_not_promoted_by_second_pass(self):
        result, model = self.run_case(initial='unclear')
        self.assertEqual(model.calls,0)
        self.assertEqual(decide_video(result.to_dict())['status'],'failed')

    def test_ordinary_object_handling_is_separate_from_unknown_risk(self):
        row = {'type':'cash_handling','object_kind':'unknown',
               'description':'A small object is handled.'}
        self.assertEqual(normalize_action(row)['type'],'object_handling')
        row['type']='cash_left_unattended'
        self.assertEqual(normalize_action(row)['type'],'unknown')
        row['type']='unknown'
        self.assertEqual(normalize_action(row)['type'],'unknown')

    def test_neutral_action_does_not_hide_unknown_candidate(self):
        event = {'type':'object_handling','start_sec':0,'end_sec':1,
                 'description':'Synthetic ordinary handling.'}
        result = {'status':'complete','observations':[event]}
        self.assertEqual(decide_video(result)['verdict'],'no_violation')
        result['observations'].append({**event,'type':'unknown'})
        self.assertEqual(decide_video(result)['status'],'failed')

    def test_second_prompt_does_not_receive_first_answer(self):
        model = QwenModel(InferenceConfig(Path('unused')))
        calls=[]
        payload={name:{'state':'unclear','frames':[]} for name in
                 ('cashier_left_workplace','customer_service_ongoing')}
        def generate(frames,prompt,deadline,limit,**kwargs):
            calls.append((prompt,limit,kwargs))
            return json.dumps(payload)
        model._generate=generate
        self.assertEqual(model.verify_positive_conditions([None]*4,
                         'cashier_leaves_during_service',100),payload)
        self.assertIn('No earlier answer is supplied',calls[0][0])
        self.assertEqual(calls[0][1],192)
        self.assertEqual(calls[0][2]['output_schema'],tuple(payload))

    def test_invalid_verification_settings_rejected(self):
        for kwargs in ({'verify_positive_conditions':1},{'positive_check_seconds':0},
                       {'positive_check_seconds':float('nan')},{'max_positive_checks':-1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                InferenceConfig(Path('unused'),**kwargs)

    def test_diagnostics_separate_model_answer_and_parser_change(self):
        model = QwenModel(InferenceConfig(Path('unused')))
        model._record_condition_diagnostics(
            '{"synthetic":{"state":"observed","frames":[0]}}',
            {'synthetic': {'state':'unclear','frames':[0]}}, 'context')
        self.assertEqual(model.condition_diagnostics,
                         {'context_raw_observed':1,'context_parser_downgrade':1})
