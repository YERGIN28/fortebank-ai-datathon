"""Synthetic tests for compact output, bounded verification and safe diagnostics."""
from pathlib import Path
import json
import tempfile
import unittest

from . import INFERENCE_VERSION, InferenceConfig, InferenceEngine
from .batch_tools import summarize
from .model import ModelOutputError, parse_compact_response, has_complete_json
from .pipeline import parse_observations
from .synthetic import create_video
from .video import SampledFrame


class Fake:
    def __init__(self): self.checks = 0
    def load(self): pass
    def reset_metrics(self): pass
    def metrics(self): return {}
    def observe(self, frames, deadline):
        return [{'start_frame': 0, 'end_frame': 1, 'type': 'cash_transfer', 'object_kind': 'banknote',
                 'description': 'Banknotes are transferred.', 'actors': ['unknown']}]
    def verify_object(self, frames, deadline):
        self.checks += 1
        return 'banknote'


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='forte-compact-test-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'generated.mov'
        create_video(self.path, duration_seconds=8)
        self.config = InferenceConfig(Path('unused'), window_seconds=2,
                                      overlap_seconds=0.5, refine=False, max_object_checks=1)

    def test_compact_document_keeps_public_schema(self):
        result = parse_compact_response('{"events":[{"s":0,"e":1,"a":"document_transfer","o":"id_document","r":["unknown"]}]}')
        observations = parse_observations(result, [SampledFrame(1, None), SampledFrame(2, None)], 1)
        self.assertEqual(observations[0].type, 'document_transfer')
        self.assertIsNone(observations[0].confidence)
        self.assertEqual(observations[0].start_sec, 1)
        self.assertEqual(parse_compact_response('{"events":[]}'), [])
        self.assertEqual(parse_compact_response('```json\n{"events":[]}\n```'), [])

    def test_short_rows_preserve_public_observations(self):
        old = parse_compact_response('{"events":[{"s":0,"e":1,"a":"document_transfer","o":"id_document"}]}')
        new = parse_compact_response('{"events":[[0,1,"document_transfer","id_document"]]}')
        self.assertEqual(new, old)
        self.assertEqual(new[0]['actors'], ['unknown'])
        self.assertIsNone(new[0]['confidence'])
        roles = parse_compact_response('{"events":[[0,1,"document_transfer","id_document",["customer"]]]}')
        self.assertEqual(roles[0]['actors'], ['customer'])

    def test_short_rows_reject_bad_width_and_frame_values(self):
        for value in ('{"events":[[0,1,"unknown"]]}', '{"events":[[0,1,"unknown","unknown",[],0]]}'):
            with self.subTest(value=value), self.assertRaises(ModelOutputError):
                parse_compact_response(value)
        rows = parse_compact_response('{"events":[[true,1,"unknown","unknown"]]}')
        with self.assertRaises(ValueError):
            parse_observations(rows, [SampledFrame(0, None), SampledFrame(1, None)], 1)

    def test_json_stop_waits_for_whole_object(self):
        for text in ('{"events":[]}', '{"events":[{"s":0,"e":1}]}',
                     '```json\n{"events":[]}\n```'):
            self.assertTrue(has_complete_json(text))
        for text in ('', '{"events":[{"s":0}', '{"events":["}"]',
                     '{"events":[', '[]', 'text {"events":[]}'):
            self.assertFalse(has_complete_json(text))

    def test_compact_rejects_invalid_json_schema_and_excess(self):
        for value, code in (('{"events":[', 'invalid_json'), ('{}', 'invalid_event_container'),
                            ('{"events":[{}, {}, {}]}', 'missing_event_fields')):
            with self.subTest(value=value), self.assertRaises(ModelOutputError) as error:
                parse_compact_response(value)
            self.assertEqual(error.exception.code, code)

    def test_verbose_aliases_and_single_role_are_unambiguous(self):
        answer = json.dumps({'observations': [{'start_frame': 0, 'end_frame': 1,
            'type': 'document_transfer', 'object_kind': 'id_document', 'actors': 'customer'}]})
        row = parse_compact_response(answer)[0]
        self.assertEqual(row['actors'], ['customer'])
        self.assertEqual(row['object_kind'], 'id_document')

    def test_missing_object_is_uncertain_not_banknote(self):
        row = parse_compact_response('{"events":[{"s":0,"e":1,"a":"cash_transfer"}]}')[0]
        self.assertEqual(row['object_kind'], 'unknown')
        result = parse_observations([row], [SampledFrame(0, None), SampledFrame(1, None)], 1)
        self.assertEqual(result[0].type, 'object_transfer')

    def test_exact_repeats_do_not_exceed_limit(self):
        row = {'s': 0, 'e': 1, 'a': 'document_transfer', 'o': 'id_document'}
        self.assertEqual(len(parse_compact_response(json.dumps({'events': [row] * 3}))), 1)

    def test_three_distinct_events_are_never_silently_truncated(self):
        rows = [{'s': i, 'e': i, 'a': 'document_handling', 'o': 'paper_document'} for i in range(3)]
        parsed = parse_compact_response(json.dumps({'events': rows}))
        self.assertEqual(len(parsed), 3)
        self.assertEqual(len(parse_observations(parsed, [SampledFrame(i, None) for i in range(3)], 1)), 3)

    def test_defensive_limit_still_rejects_excess(self):
        rows = [{'s': 0, 'e': 1, 'a': 'unknown', 'o': 'unknown'}] * 33
        with self.assertRaises(ModelOutputError) as error:
            parse_compact_response(json.dumps({'events': rows}))
        self.assertEqual(error.exception.code, 'too_many_events')

    def test_multiple_valid_events_do_not_make_video_partial(self):
        class Multiple(Fake):
            def observe(self, frames, deadline):
                return parse_compact_response(json.dumps({'events': [
                    {'s': 0, 'e': 1, 'a': 'document_transfer', 'o': kind, 'r': [role]}
                    for kind, role in [('id_document', 'customer'), ('paper_document', 'cashier'),
                                       ('unknown', 'unknown'), ('id_document', 'unknown')]]}))
        result = InferenceEngine(self.config, model=Multiple()).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.processed_windows, result.planned_windows)
        self.assertTrue(any(message.startswith('event_count_above_target:') for message in result.warnings))

    def test_conflicting_aliases_and_seconds_are_rejected(self):
        for row in ({'s': 0, 'start_frame': 1, 'e': 1, 'a': 'unknown'},
                    {'start_sec': 0, 'end_sec': 1, 'type': 'unknown'}):
            with self.subTest(row=row), self.assertRaises(ModelOutputError):
                parse_compact_response(json.dumps({'events': [row]}))

    def test_malformed_kind_does_not_crash_parser(self):
        with self.assertRaises(ModelOutputError):
            parse_compact_response('{"events":[{"s":0,"e":1,"a":"unknown","o":[]}]}')

    def test_verification_count_is_bounded_per_video(self):
        model = Fake()
        result = InferenceEngine(self.config, model=model).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.checks, 1)
        self.assertEqual(result.processed_windows, result.planned_windows)
        self.assertTrue(any(item.type == 'object_transfer' for item in result.observations))
        self.assertTrue(any(message.startswith('object_check_skipped:') for message in result.warnings))

    def test_documents_do_not_trigger_extra_gpu_passes(self):
        class Document(Fake):
            def observe(self, frames, deadline):
                return [{'start_frame': 0, 'end_frame': 1, 'type': 'document_transfer',
                         'object_kind': 'id_document', 'description': 'A document is transferred.'}]
        model = Document()
        result = InferenceEngine(self.config, model=model).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.checks, 0)
        self.assertTrue(all(item.type == 'document_transfer' for item in result.observations))

    def test_object_timeout_preserves_uncertainty_not_cash(self):
        class Slow(Fake):
            def verify_object(self, frames, deadline):
                self.checks += 1
                raise TimeoutError('synthetic')
        model = Slow()
        result = InferenceEngine(self.config, model=model).analyze_video(self.path)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(model.checks, 1)
        self.assertTrue(all(item.type == 'object_transfer' for item in result.observations))
        self.assertIn('object_check_timeout: 1', result.warnings)

    def test_unverified_unattended_claim_remains_unknown(self):
        frames = [SampledFrame(0, None), SampledFrame(1, None)]
        result = parse_observations([{'start_frame': 0, 'end_frame': 1, 'type': 'cash_left_unattended',
            'object_kind': 'unknown', 'description': 'Cash remains unattended.'}], frames, 1)
        self.assertEqual(result[0].type, 'unknown')

    def test_partial_diagnostic_never_echoes_raw_model_text(self):
        class Broken(Fake):
            def observe(self, frames, deadline):
                raise ModelOutputError('json_token_limit')
        result = InferenceEngine(self.config, model=Broken()).analyze_video(self.path)
        report = summarize({'videos': [result.to_dict()]})
        self.assertEqual(result.status, 'partial')
        self.assertEqual(report['diagnostic_counts']['json_token_limit'], result.planned_windows)
        self.assertEqual(result.processed_windows, 0)

    def test_default_config_uses_bounded_baseline(self):
        config = InferenceConfig(Path('unused'))
        self.assertFalse(config.refine)
        self.assertFalse(config.check_relevance)
        self.assertEqual(config.max_object_checks, 3)
        self.assertEqual(config.object_check_seconds, 6)
        self.assertEqual(config.verification_frame_side, 640)

    def test_result_identifies_loaded_implementation(self):
        result = InferenceEngine(self.config, model=Fake()).analyze_video(self.path)
        self.assertEqual(result.to_dict()['inference_version'], INFERENCE_VERSION)

    def test_stage_timings_are_safe_and_include_failed_calls(self):
        class Broken(Fake):
            def observe(self, frames, deadline):
                raise ModelOutputError('invalid_json')
        result = InferenceEngine(self.config, model=Broken()).analyze_video(self.path)
        self.assertGreater(result.stage_timings_sec['decode'], 0)
        # Very short failed calls can round to zero at 0.1-ms report precision.
        self.assertGreaterEqual(result.stage_timings_sec['observe'], 0)
        self.assertEqual(result.stage_timings_sec['verify_object'], 0)
        report = summarize({'videos': [result.to_dict()]})
        self.assertEqual(report['stage_timings']['decode']['samples'], 1)
        self.assertEqual(report['stage_timings']['observe']['total_sec'], result.stage_timings_sec['observe'])
        # Old reports remain supported; unrecognized keys never leave the machine.
        report = summarize({'videos': [{'status': 'complete', 'stage_timings_sec': {'private': 99}}]})
        self.assertNotIn('private', str(report))
        self.assertIsNone(report['stage_timings']['observe']['total_sec'])

    def test_config_rejects_invalid_check_budgets(self):
        for extra in ({'max_object_checks': -1}, {'max_object_checks': True},
                      {'object_check_seconds': float('nan')}, {'object_check_seconds': 0}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                InferenceConfig(Path('unused'), **extra)


if __name__ == '__main__':
    unittest.main()
