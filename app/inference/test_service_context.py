"""Synthetic-only validation of context-condition evidence."""
import json
from pathlib import Path
import unittest
import tempfile
from . import InferenceConfig, InferenceEngine
from .model import QwenModel, parse_service_context
from .synthetic import create_video


class ServiceContextTests(unittest.TestCase):
    def payload(self):
        return {'cashier_left_workplace': {'state': 'observed', 'frames': [0, 2]},
                'customer_service_ongoing': {'state': 'refuted', 'frames': [2]}}

    def test_valid_conditions_preserved(self):
        payload = self.payload()
        self.assertEqual(parse_service_context(json.dumps(payload), 3), payload)

    def test_unsupported_confirmation_becomes_unclear(self):
        payload = self.payload()
        payload['cashier_left_workplace']['frames'] = [1]
        payload['customer_service_ongoing']['frames'] = []
        result = parse_service_context(json.dumps(payload), 3)
        self.assertEqual(result['cashier_left_workplace']['state'], 'unclear')
        self.assertEqual(result['customer_service_ongoing']['state'], 'unclear')

    def test_duplicate_frame_not_temporal_evidence(self):
        payload = self.payload()
        payload['cashier_left_workplace']['frames'] = [1, 1]
        self.assertEqual(parse_service_context(json.dumps(payload), 3)['cashier_left_workplace']['state'], 'unclear')

    def test_invalid_indexes_rejected(self):
        for index in (True, -1, 3, 0.5, '1'):
            payload = self.payload()
            payload['customer_service_ongoing']['frames'] = [index]
            with self.subTest(index=index), self.assertRaises(ValueError):
                parse_service_context(json.dumps(payload), 3)

    def test_invalid_schema_rejected(self):
        for text in ('{}', '{', '[]', '{"cashier_left_workplace":null}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_service_context(text, 3)

    def test_context_method_uses_bounded_generation(self):
        model = QwenModel(InferenceConfig(Path('unused')))
        calls = []
        def generate(frames, prompt, deadline, limit):
            calls.append(limit)
            return json.dumps(self.payload())
        model._generate = generate
        self.assertEqual(model.check_service_context([None] * 3, 10), self.payload())
        self.assertEqual(calls, [128])

    def test_departure_context_runs_without_cash_and_preserves_pts(self):
        class FakeModel:
            calls = 0
            def load(self): pass
            def reset_metrics(self): pass
            def metrics(self): return {}
            def observe(self, frames, deadline):
                return [{'start_frame': 1, 'end_frame': 2,
                         'type': 'cashier_leaves_during_service', 'object_kind': 'none',
                         'description': 'A cashier moves away from the workstation.'}]
            def check_service_context(self, frames, deadline):
                self.calls += 1
                return {name: {'state': 'observed', 'frames': [0, len(frames)-1]}
                        for name in ('cashier_left_workplace', 'customer_service_ongoing')}
        with tempfile.TemporaryDirectory(prefix='forte-departure-test-') as directory:
            path = Path(directory) / 'shapes.mov'
            create_video(path)
            model = FakeModel()
            result = InferenceEngine(InferenceConfig(Path('unused')), model=model).analyze_video(path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.calls, 1)
        observation = result.observations[0]
        self.assertEqual(observation.type, 'cashier_leaves_during_service')
        for check in observation.condition_checks.values():
            self.assertEqual(check['state'], 'observed')
            self.assertTrue(all(observation.start_sec <= t <= observation.end_sec
                                for t in check['evidence_timestamps_sec']))
        self.assertIsNone(observation.confidence)

    def test_no_context_budget_keeps_unconfirmed_candidate(self):
        from .test_synthetic import FakeModel
        rows = [{'start_frame': 0, 'end_frame': 1, 'type': 'cashier_leaves_during_service',
                 'object_kind': 'none', 'description': 'A cashier moves away.'}]
        with tempfile.TemporaryDirectory(prefix='forte-departure-test-') as directory:
            path = Path(directory) / 'shapes.mov'
            create_video(path)
            result = InferenceEngine(InferenceConfig(Path('unused'), max_service_checks=0),
                                     model=FakeModel(rows)).analyze_video(path)
        self.assertEqual(result.observations[0].condition_checks, {})
        self.assertIn('service_context_skipped: 1', result.warnings)

    def test_relevance_gate_rejects_only_explicit_false(self):
        from .test_synthetic import FakeModel
        for value in (False, True, None):
            class Gated(FakeModel):
                def check_relevance(self, frames, deadline): return value
            with tempfile.TemporaryDirectory(prefix='forte-relevance-test-') as directory:
                path = Path(directory) / 'shapes.mov'
                create_video(path)
                model = Gated()
                result = InferenceEngine(InferenceConfig(Path('unused'), check_relevance=True), model=model).analyze_video(path)
            self.assertEqual(result.status, 'complete')
            self.assertEqual(model.calls, 0 if value is False else 1)

    def test_relevance_error_falls_back_to_main_pass(self):
        from .test_synthetic import FakeModel
        class Broken(FakeModel):
            def check_relevance(self, frames, deadline): raise ValueError('synthetic')
        with tempfile.TemporaryDirectory(prefix='forte-relevance-test-') as directory:
            path = Path(directory) / 'shapes.mov'
            create_video(path)
            model = Broken()
            result = InferenceEngine(InferenceConfig(Path('unused'), check_relevance=True), model=model).analyze_video(path)
        self.assertEqual(model.calls, 1)
        self.assertIn('relevance_fallback: 1', result.warnings)

    def test_relevance_schema_rejects_numeric_and_string_booleans(self):
        model = QwenModel(InferenceConfig(Path('unused')))
        for value in (0, 1, 'false', []):
            model._generate = lambda *args: json.dumps({'relevant': value})
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.check_relevance([None], 10)


if __name__ == '__main__':
    unittest.main()
