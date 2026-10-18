"""Artificial-only tests; fake models validate plumbing, not visual accuracy."""
import json
from pathlib import Path
import tempfile
import unittest

from . import InferenceConfig, InferenceEngine
from .conditions import CONDITION_SPECS, parse_condition_checks
from .model import ACTION_DESCRIPTIONS, QwenModel, parse_compact_response
from .pipeline import parse_observations
from .synthetic import create_video
from .video import SampledFrame


def supported(action):
    return {name: {'state': 'observed', 'frames': [0, 3]}
            for name in CONDITION_SPECS[action]}


class ConditionTests(unittest.TestCase):
    def test_all_categories_roundtrip_with_required_object_kind(self):
        for action in CONDITION_SPECS:
            with self.subTest(action=action):
                rows = parse_compact_response(json.dumps({'events': [
                    {'s': 0, 'e': 1, 'a': action,
                     'o': 'banknote' if action == 'cash_left_unattended' else 'none', 'r': ['cashier']}]}))
                result = parse_observations(rows, [SampledFrame(4, None), SampledFrame(6, None)], 2)
                self.assertEqual(result[0].type, action)
                self.assertEqual(result[0].start_sec, 4)
                self.assertEqual(result[0].description, ACTION_DESCRIPTIONS[action])
                self.assertIsNone(result[0].confidence)

    def test_supported_conditions(self):
        for action in CONDITION_SPECS:
            with self.subTest(action=action):
                expected = supported(action)
                if action == 'previous_cash_outside_storage':
                    expected['previous_cash_continuously_tracked']['state'] = 'unclear'
                for name in ('id_check_not_visible_in_receipt', 'banknote_check_not_visible_before_storage'):
                    if name in expected:
                        expected[name]['state'] = 'unclear'
                self.assertEqual(parse_condition_checks(json.dumps(supported(action)), action, 4), expected)

    def test_sparse_frames_cannot_claim_continuous_cash_tracking(self):
        result = parse_condition_checks(json.dumps(supported('previous_cash_outside_storage')),
                                        'previous_cash_outside_storage', 4)
        self.assertEqual(result['previous_cash_continuously_tracked']['state'], 'unclear')

    def test_occluded_customer_zone_is_not_refutation_or_absence(self):
        action = 'cash_counting_without_customer'
        payload = supported(action)
        payload['customer_zone_fully_visible']['state'] = 'refuted'
        result = parse_condition_checks(json.dumps(payload), action, 4)
        self.assertEqual(result['customer_zone_fully_visible']['state'], 'unclear')
        self.assertEqual(result['customer_absent_during_counting']['state'], 'unclear')

    def test_container_before_removal_is_not_container_left_afterwards(self):
        action = 'cash_container_left_on_work_surface'
        payload = supported(action)
        payload['same_container_remains_on_work_surface']['frames'] = [0]
        result = parse_condition_checks(json.dumps(payload), action, 4)
        self.assertEqual(result['same_container_remains_on_work_surface']['state'], 'unclear')

    def test_human_presence_must_be_boolean_or_unknown_and_consistent(self):
        self.assertEqual(parse_compact_response('{"human_visible":false,"events":[]}'), [])
        for value in (0, 'false', []):
            with self.assertRaises(ValueError):
                parse_compact_response(json.dumps({'human_visible': value, 'events': []}))
        with self.assertRaises(ValueError):
            parse_compact_response(json.dumps({'human_visible': False, 'events': [
                {'s': 0, 'e': 1, 'a': 'cash_drawer_closed', 'o': 'none'}]}))

    def test_explicit_no_action_placeholder_is_not_a_schema_failure(self):
        rows = parse_compact_response(json.dumps({'human_visible': False, 'events': [
            {'s': 0, 'e': 1, 'a': 'unknown', 'o': 'none'}]}))
        self.assertEqual(parse_observations(rows, [SampledFrame(0, None), SampledFrame(1, None)], 1), [])

    def test_lit_screen_before_departure_is_not_after_evidence(self):
        action = 'workstation_left_with_screen_on'
        payload = supported(action)
        payload['screen_on_after_departure']['frames'] = [0]
        result = parse_condition_checks(json.dumps(payload), action, 4)
        self.assertEqual(result['screen_on_after_departure']['state'], 'unclear')

    def test_stationary_person_and_duplicate_indexes_cannot_confirm_departure(self):
        for indexes in ([1], [1, 1], []):
            payload = supported('safe_left_open')
            payload['cashier_left_workplace']['frames'] = indexes
            result = parse_condition_checks(json.dumps(payload), 'safe_left_open', 4)
            self.assertEqual(result['cashier_left_workplace']['state'], 'unclear')
            self.assertEqual(result['safe_open_after_departure']['state'], 'unclear')

    def test_nonoverlapping_cash_and_new_customer_cannot_confirm_cooccurrence(self):
        action = 'cash_on_desk_with_next_customer'
        payload = supported(action)
        payload['banknotes_on_work_surface']['frames'] = [0]
        payload['banknotes_remain_during_approach']['frames'] = [3]
        result = parse_condition_checks(json.dumps(payload), action, 4)
        self.assertEqual(result['banknotes_remain_during_approach']['state'], 'unclear')

    def test_invalid_indexes_schema_and_facts_are_rejected(self):
        action = 'safe_left_open'
        for index in (True, -1, 4, '1', 0.5):
            payload = supported(action)
            payload['safe_open_after_departure']['frames'] = [index]
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_condition_checks(json.dumps(payload), action, 4)
        for payload in ({}, [], {'is_violation': True}):
            with self.assertRaises(ValueError):
                parse_condition_checks(json.dumps(payload), action, 4)

    def test_prompt_does_not_claim_screen_lock_state_or_read_content(self):
        model = QwenModel(InferenceConfig(Path('unused')))
        calls = []
        def generate(frames, prompt, deadline, limit, **kwargs):
            calls.append((prompt, limit))
            return json.dumps(supported('workstation_left_with_screen_on'))
        model._generate = generate
        model.check_conditions([None] * 4, 'workstation_left_with_screen_on', 123)
        self.assertIn('lock state', calls[0][0])
        self.assertIn('Do not read personal text', calls[0][0])
        self.assertEqual(calls[0][1], 192)

    def run_candidate(self, state='observed', *, budget=3, broken=False):
        action = 'workstation_left_with_screen_on'
        class Fake:
            calls = 0
            def load(self): pass
            def reset_metrics(self): pass
            def metrics(self): return {}
            def observe(self, frames, deadline):
                return [{'start_frame': 0, 'end_frame': len(frames)-1,
                         'type': action, 'object_kind': 'none',
                         'description': ACTION_DESCRIPTIONS[action]}]
            def check_conditions(self, frames, category, deadline):
                self.calls += 1
                if broken:
                    raise ValueError('synthetic failure')
                return {name: {'state': state, 'frames': [0, len(frames)-1]}
                        for name in CONDITION_SPECS[category]}
        model = Fake()
        with tempfile.TemporaryDirectory(prefix='forte-condition-test-') as directory:
            path = Path(directory) / 'generated.mov'
            create_video(path)
            result = InferenceEngine(InferenceConfig(Path('unused'), max_service_checks=budget),
                                     model=model).analyze_video(path)
        return result, model

    def test_observed_candidate_has_source_timestamps_and_no_verdict(self):
        result, model = self.run_candidate()
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.calls, 1)
        observation = result.observations[0]
        self.assertEqual(set(observation.condition_checks), set(CONDITION_SPECS[observation.type]))
        for check in observation.condition_checks.values():
            self.assertEqual(check['state'], 'observed')
            self.assertTrue(all(observation.start_sec <= t <= observation.end_sec
                                for t in check['evidence_timestamps_sec']))
        self.assertNotIn('verdict', result.to_dict())

    def test_explicit_refutation_removes_false_candidate(self):
        result, _ = self.run_candidate('refuted')
        self.assertEqual(result.observations, [])
        self.assertIn('service_context_refuted: 1', result.warnings)

    def test_unclear_remains_visible_to_rules(self):
        result, _ = self.run_candidate('unclear')
        self.assertEqual(len(result.observations), 1)
        self.assertTrue(all(c['state'] == 'unclear'
                            for c in result.observations[0].condition_checks.values()))

    def test_unavailable_verification_never_silently_drops_candidate(self):
        for kwargs, warning in (({'budget': 0}, 'service_context_skipped: 1'),
                                ({'broken': True}, 'service_context_invalid_output: 1')):
            result, _ = self.run_candidate(**kwargs)
            self.assertEqual(len(result.observations), 1)
            self.assertEqual(result.observations[0].condition_checks, {})
            self.assertIn(warning, result.warnings)


if __name__ == '__main__':
    unittest.main()
