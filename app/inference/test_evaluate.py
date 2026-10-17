"""Evaluator tests: only invented event labels, times and generated MOV files."""
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from .evaluate import Event, evaluate, match_events
from .integration_examples import MockModel
from .pipeline import InferenceEngine
from .schemas import InferenceConfig
from .synthetic import create_video
from .run_local import read_manifest, run_batch


def event(start=10, end=15, category='demo_action_a', **extra):
    return {'type': category, 'start_sec': start, 'end_sec': end, **extra}


def document(events, *, status=None, video_id='synthetic_demo_001'):
    row = {'video_id': video_id, 'observations': events}
    if status is not None:
        row['status'] = status
    return row


class EvaluationTests(unittest.TestCase):
    def metrics(self, expected, found, **kwargs):
        return evaluate(document(expected), document(found, status='complete'), **kwargs)[
            'metrics_on_complete_videos_only']

    def test_optional_fields_ignored(self):
        metrics = self.metrics([event(observation_id='fake', actors=['actor_1'])], [event()])
        self.assertEqual((metrics['tp'], metrics['fp'], metrics['fn']), (1, 0, 0))
        self.assertEqual(metrics['f1'], 1)

    def test_duplicates_do_not_inflate_tp(self):
        metrics = self.metrics([event()], [event(), event()])
        self.assertEqual((metrics['tp'], metrics['fp'], metrics['fn']), (1, 1, 0))

    def test_type_mismatch_and_unknown(self):
        self.assertEqual(self.metrics([event()], [event(category='unknown')])['tp'], 0)
        self.assertEqual(self.metrics([event(category='unknown')], [event(category='unknown')])['tp'], 1)

    def test_boundary_tolerance_and_errors(self):
        metrics = self.metrics([event()], [event(11, 17)], tolerance_sec=2)
        self.assertEqual(metrics['tp'], 1)
        self.assertEqual(metrics['mean_start_error_sec'], 1)
        self.assertEqual(metrics['mean_end_error_sec'], 2)
        self.assertEqual(self.metrics([event()], [event(11, 17.01)])['tp'], 0)

    def test_iou_and_point_events(self):
        self.assertEqual(self.metrics([event(10, 20)], [event(15, 25)], mode='iou')['tp'], 1)
        self.assertEqual(self.metrics([event(10, 20)], [event(15, 25)], mode='iou', iou_threshold=0.5)['tp'], 0)
        self.assertEqual(self.metrics([event(10, 10)], [event(11, 11)], mode='iou')['tp'], 1)
        self.assertEqual(self.metrics([event(10, 10)], [event(10, 15)], mode='iou')['tp'], 0)

    def test_empty_sets_and_negatives(self):
        metrics = self.metrics([], [])
        self.assertIsNone(metrics['precision'])
        self.assertIsNone(metrics['recall'])
        self.assertIsNone(metrics['f1'])
        self.assertEqual(metrics['negative_videos'], 1)
        self.assertEqual(self.metrics([], [event()])['negative_videos_with_false_alarms'], 1)

    def test_incomplete_and_missing_excluded_visibly(self):
        truth = {'videos': [document([event()], video_id=str(i)) for i in range(5)]}
        pred = {'videos': [document([event()], status=status, video_id=str(i))
                           for i, status in enumerate(('complete', 'partial', 'timeout', 'failed'))]}
        report = evaluate(truth, pred)
        self.assertFalse(report['evaluation_complete'])
        self.assertEqual(report['coverage']['missing'], 1)
        self.assertEqual(report['metrics_on_complete_videos_only']['tp'], 1)
        self.assertEqual(report['coverage']['complete_fraction'], 0.2)

    def test_no_predictions_means_all_missing(self):
        report = evaluate(document([event()]), {'videos': []})
        self.assertEqual(report['coverage']['missing'], 1)
        self.assertFalse(report['evaluation_complete'])
        self.assertEqual(report['coverage']['complete_fraction'], 0)
        self.assertIsNone(report['metrics_on_complete_videos_only']['f1'])

    def test_private_fields_not_in_report(self):
        sentinel = 'PRIVATE_SYNTHETIC_SENTINEL'
        report = evaluate(document([event(description=sentinel)], video_id=sentinel),
                          document([event(description=sentinel, actors=[sentinel])],
                                   status='complete', video_id=sentinel))
        self.assertNotIn(sentinel, json.dumps(report))

    def test_invalid_inputs(self):
        valid_truth, valid_pred = document([event()]), document([event()], status='complete')
        for bad in (event(-1, 15), event(15, 10), event(True, 15), event(float('nan'), 15)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                evaluate(document([bad]), valid_pred)
        for pred in (document([event()]), document([event()], status='complete', video_id='other'),
                     {'videos': [valid_pred, valid_pred]}):
            with self.assertRaises(ValueError):
                evaluate(valid_truth, pred)
        for kwargs in ({'mode': 'bad'}, {'iou_threshold': 0}, {'tolerance_sec': -1}):
            with self.assertRaises(ValueError):
                evaluate(valid_truth, valid_pred, **kwargs)

    def test_augmenting_path_beats_greedy(self):
        truth = [Event('demo', 0, 0), Event('demo', 2, 2)]
        pred = [Event('demo', 1, 1), Event('demo', 0, 0)]
        pairs = match_events(truth, pred, mode='boundaries', tolerance=1, iou_threshold=0.3)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len({left for left, _ in pairs}), 2)

    def test_matching_against_exhaustive_small_cases(self):
        # A small exhaustive oracle verifies maximum cardinality, including ties.
        for reference_times in itertools.product(range(3), repeat=2):
            for prediction_times in itertools.product(range(3), repeat=3):
                truth = [Event('demo', t, t) for t in reference_times]
                pred = [Event('demo', t, t) for t in prediction_times]
                actual = match_events(truth, pred, mode='boundaries', tolerance=0, iou_threshold=0.3)
                best = 0
                for assignments in itertools.product((-1, 0, 1), repeat=3):
                    chosen = [i for i in assignments if i >= 0]
                    if len(chosen) != len(set(chosen)):
                        continue
                    if all(i == -1 or prediction_times[p] == reference_times[i]
                           for p, i in enumerate(assignments)):
                        best = max(best, len(chosen))
                self.assertEqual(len(actual), best)

    def test_runner_failure_stops_and_hides_private_error(self):
        import contextlib
        import io
        class BrokenEngine:
            def load(self):
                pass

            def analyze_video(self, path):
                raise RuntimeError('PRIVATE_SYNTHETIC_EXCEPTION')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'results.json'
            console = io.StringIO()
            with contextlib.redirect_stdout(console):
                statuses = run_batch([('PRIVATE_SYNTHETIC_ID', Path('not_opened.mov')),
                                      ('unused', Path('not_opened.mov'))], BrokenEngine(), path)
            self.assertEqual(statuses, {'failed': 1})
            self.assertNotIn('PRIVATE', console.getvalue())
            saved = json.loads(path.read_text())
            self.assertEqual(len(saved['videos']), 1)
            self.assertNotIn('PRIVATE_SYNTHETIC_EXCEPTION', path.read_text())

    def test_manifest_rejects_urls_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            path = directory / 'manifest.json'
            create_video(directory / 'generated.mov')
            for rows in ([{'video_id': 'fake', 'path': 'https://example.invalid/test.mov'}],
                         [{'video_id': 'fake', 'path': 'generated.mov'}] * 2):
                path.write_text(json.dumps({'videos': rows}))
                with self.assertRaises(ValueError):
                    read_manifest(path)

    def test_local_batch_runner_with_mock(self):
        with tempfile.TemporaryDirectory(prefix='forte-eval-test-') as directory:
            directory = Path(directory)
            create_video(directory / 'generated.mov')
            manifest = directory / 'manifest.json'
            manifest.write_text(json.dumps({'videos': [{'video_id': 'fake', 'path': 'generated.mov'}]}))
            videos = read_manifest(manifest)
            engine = InferenceEngine(InferenceConfig(Path('unused'), refine=False), model=MockModel('complete'))
            output = directory / 'predictions.json'
            statuses = run_batch(videos, engine, output)
            self.assertEqual(statuses, {'complete': 1})
            self.assertEqual(json.loads(output.read_text())['videos'][0]['video_id'], 'fake')
            with self.assertRaises(ValueError):
                run_batch(videos, engine, output)


if __name__ == '__main__':
    unittest.main()
