"""CPU contract/decoder tests. All video is generated inside a temporary folder."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from . import InferenceConfig, InferenceEngine
from .pipeline import parse_observations
from .model import parse_model_response
from .synthetic import create_video
from .video import SampledFrame, VideoReader, iter_windows


class FakeModel:
    load_seconds = 0.0

    def __init__(self, rows=None, error=None):
        self.rows = [] if rows is None else rows
        self.error = error
        self.calls = 0

    def load(self):
        pass

    def reset_metrics(self):
        pass

    def metrics(self):
        return {}

    def observe(self, frames, deadline):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='forte-test-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'generated.mov'
        create_video(self.path)
        self.config = InferenceConfig(Path('unused'), window_seconds=2,
                                      overlap_seconds=0.5, refine=False)

    def test_invalid_config(self):
        for values in ({'overlap_seconds': 8}, {'frames_per_window': 0},
                       {'time_budget_seconds': float('nan')}, {'max_new_tokens': True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                InferenceConfig(Path('unused'), **values)

    def test_window_coverage(self):
        self.assertEqual(list(iter_windows(4, 2, 0.5)), [(0, 2), (1.5, 3.5), (3, 4)])
        self.assertEqual(list(iter_windows(0.5, 2, 0.5)), [(0, 0.5)])

    def test_long_video_sampling_across_overlapping_windows(self):
        create_video(self.path, duration_seconds=16)
        reader = VideoReader(self.path)
        self.addCleanup(reader.close)
        windows = list(iter_windows(reader.duration, 8, 2))
        self.assertEqual(windows, [(0, 8), (6, 14), (12, 16)])
        for count in (4, 6):
            for start, end in windows:
                frames = reader.sample(start, end, count, time.perf_counter() + 10)
                self.assertEqual(len(frames), count)
                for index, frame in enumerate(frames):
                    self.assertGreaterEqual(frame.timestamp_sec + 1e-6, start + index * (end - start) / count)
                    self.assertLess(frame.timestamp_sec, end)
                self.assertEqual(len(set(f.timestamp_sec for f in frames)), count)

    def test_synthetic_generator_validation(self):
        for values in ({'duration_seconds': -1}, {'width': 319}, {'height': 0}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                create_video(self.path, **values)

    def test_model_json_parser(self):
        self.assertEqual(parse_model_response('{"observations":[]}'), [])
        self.assertEqual(parse_model_response('```json\n{"observations":[]}\n```'), [])
        for text in ('{"observations":[', 'prefix {"observations":[]}',
                     '[]', '{"observations":null}', '{}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_model_response(text)

    def test_actual_pts_and_seek(self):
        reader = VideoReader(self.path)
        self.addCleanup(reader.close)
        self.assertAlmostEqual(reader.duration, 4)
        for start, end in ((0, 2), (1.5, 3.5), (3, 4)):
            frames = reader.sample(start, end, 4, time.perf_counter() + 10)
            self.assertEqual(len(frames), 4)
            for index, frame in enumerate(frames):
                target = start + (end - start) * index / 4
                self.assertGreaterEqual(frame.timestamp_sec + 1e-6, target)
                self.assertLess(frame.timestamp_sec - target, 0.101)
                self.assertEqual(frame.image.mode, 'RGB')

    def test_decoder_deadline(self):
        reader = VideoReader(self.path)
        self.addCleanup(reader.close)
        with self.assertRaises(TimeoutError):
            reader.sample(0, 2, 4, time.perf_counter() - 1)

    def test_empty_observations(self):
        model = FakeModel()
        result = InferenceEngine(self.config, model=model).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.processed_windows, 3)
        self.assertEqual(result.planned_windows, 3)
        self.assertEqual(result.observations, [])

    def test_bad_response_is_partial(self):
        result = InferenceEngine(self.config, model=FakeModel(
            [{'start_frame': 99, 'end_frame': 100, 'description': 'synthetic'}]
        )).analyze_video(self.path)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.processed_windows, 0)
        self.assertEqual(len(result.warnings), 3)

    def test_timeout_is_not_complete(self):
        result = InferenceEngine(self.config, model=FakeModel(
            error=TimeoutError())).analyze_video(self.path)
        self.assertEqual(result.status, 'timeout')
        self.assertEqual(result.processed_windows, 0)

    def test_source_timestamps_not_model_numbers(self):
        frames = [SampledFrame(10.25, None), SampledFrame(11.75, None)]
        result = parse_observations([{'start_frame': 0, 'end_frame': 1,
                                     'description': 'synthetic transfer'}], frames, 1.5)
        self.assertEqual(result[0].start_sec, 10.25)
        self.assertEqual(result[0].end_sec, 11.75)
        self.assertEqual(result[0].evidence_timestamps_sec, [10.25, 11.75])

    def test_rule_engine_fields_and_uncalibrated_confidence(self):
        frames = [SampledFrame(55, None), SampledFrame(62, None)]
        row = {'start_frame': 0, 'end_frame': 1, 'description': 'synthetic cash action',
               'type': 'cash_left_unattended', 'actors': ['cashier'], 'confidence': 0.99}
        observation = parse_observations([row], frames, 2)[0]
        self.assertEqual(observation.type, 'cash_left_unattended')
        self.assertEqual(observation.actors, ['cashier'])
        self.assertIsNone(observation.confidence)

    def test_unknown_types_roles_and_missing_fields(self):
        for extra in ({}, {'type': 'not_agreed', 'actors': ['person_name', 'person_name']},
                      {'type': None, 'actors': []}):
            row = {'start_frame': 0, 'end_frame': 0, 'description': 'synthetic', **extra}
            observation = parse_observations([row], [SampledFrame(0, None)], 1)[0]
            self.assertEqual(observation.type, 'unknown')
            self.assertEqual(observation.actors, ['unknown'])
            self.assertIsNone(observation.confidence)

    def test_malformed_actors_rejected(self):
        for actors in ('cashier', [123], None):
            row = {'start_frame': 0, 'end_frame': 0, 'description': 'synthetic', 'actors': actors}
            with self.subTest(actors=actors), self.assertRaises(ValueError):
                parse_observations([row], [SampledFrame(0, None)], 1)

    def test_worker_preload_once_across_jobs(self):
        class CountingModel(FakeModel):
            loads = 0

            def load(self):
                self.loads += 1
        model = CountingModel()
        engine = InferenceEngine(self.config, model=model)
        engine.load()
        engine.load()
        for _ in range(2):
            result = engine.analyze_video(self.path)
            self.assertEqual(result.status, 'complete')
            self.assertEqual(result.model_load_sec, 0)
        self.assertEqual(model.loads, 1)

    def test_full_integration_fixtures(self):
        import json
        from .integration_examples import create_results
        results = create_results()
        for status, payload in results.items():
            self.assertEqual(payload['status'], status)
            self.assertEqual(payload['planned_windows'], 3)
            self.assertTrue(payload['observations'])
            self.assertTrue(payload['warnings'])
            self.assertEqual(json.loads(json.dumps(payload)), payload)
            for observation in payload['observations']:
                self.assertEqual(observation['type'], 'cash_left_unattended')
                self.assertIsNone(observation['confidence'])
                self.assertEqual(observation['actors'], ['cashier'])
        self.assertEqual(results['complete']['processed_windows'], 3)
        self.assertEqual(results['partial']['processed_windows'], 2)
        self.assertEqual(results['timeout']['processed_windows'], 1)

    def test_schema_rejects_bad_indexes(self):
        for value in (True, -1, 0.5, 2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_observations([{'start_frame': value, 'end_frame': value,
                                     'description': 'synthetic'}], [SampledFrame(0, None)], 1)

    def test_schema_rejects_too_many_observations(self):
        rows = [{'start_frame': 0, 'end_frame': 0, 'description': 'synthetic'}] * 4
        with self.assertRaises(ValueError):
            parse_observations(rows, [SampledFrame(0, None)], 1)

    def test_refinement(self):
        model = FakeModel([{'start_frame': 0, 'end_frame': 1, 'description': 'synthetic motion'}])
        result = InferenceEngine(replace(self.config, refine=True), model=model).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.calls, 6)
        self.assertTrue(all(item.refined for item in result.observations))
        self.assertTrue(all(0 <= item.start_sec <= item.end_sec < 4 for item in result.observations))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            InferenceEngine(self.config, model=FakeModel()).analyze_video(self.path.with_name('missing.mov'))

    def test_empty_refinement_preserves_coarse_evidence(self):
        class Alternating(FakeModel):
            def observe(self, frames, deadline):
                self.calls += 1
                if self.calls <= 3:
                    return [{'start_frame': 0, 'end_frame': 1, 'description': 'synthetic'}]
                return []
        result = InferenceEngine(replace(self.config, refine=True), model=Alternating()).analyze_video(self.path)
        self.assertEqual(len(result.observations), 3)
        self.assertEqual(len(result.warnings), 3)
        self.assertTrue(all(not item.refined for item in result.observations))

    def test_model_failure_propagates(self):
        with self.assertRaises(RuntimeError):
            InferenceEngine(self.config, model=FakeModel(error=RuntimeError('synthetic OOM'))).analyze_video(self.path)


if __name__ == '__main__':
    unittest.main()
