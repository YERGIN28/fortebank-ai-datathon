"""Artificial actions only: object gating, irrelevant output and conservative dedup."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from . import InferenceConfig, InferenceEngine, Observation
from .pipeline import parse_observations
from .postprocess import deduplicate, normalize_action
from .synthetic import create_video
from .video import SampledFrame


def row(action='cash_transfer', kind='banknote', description='A banknote is handed over.'):
    return {'start_frame': 0, 'end_frame': 1, 'description': description,
            'type': action, 'object_kind': kind, 'actors': ['unknown']}


def observation(start, end, *, action='cash_transfer', description='Banknotes are transferred.'):
    return Observation(start, end, description, [start, end], 2, type=action)


class PostprocessTests(unittest.TestCase):
    def test_returned_document_is_not_reported_as_banknotes(self):
        self.assertEqual(normalize_action(row('cash_returned_after_check','id_document'))['type'],
                         'document_transfer')
        self.assertEqual(normalize_action(row('cash_returned_after_check','unknown'))['type'],
                         'object_transfer')
        self.assertEqual(normalize_action(row('cash_returned_after_check','banknote'))['type'],
                         'cash_returned_after_check')
    def test_id_card_not_cash(self):
        result = normalize_action(row(kind='id_document'))
        self.assertEqual(result['type'], 'document_transfer')
        self.assertNotIn('banknote', result['description'].lower())

    def test_paper_is_document(self):
        self.assertEqual(normalize_action(row('cash_handling', 'paper_document'))['type'], 'document_handling')

    def test_verified_banknote_can_correct_document_label(self):
        self.assertEqual(normalize_action(row('document_transfer', 'banknote'))['type'], 'cash_transfer')

    def test_unclear_object_does_not_remain_cash(self):
        result = normalize_action(row(kind='unknown'))
        self.assertEqual(result['type'], 'object_transfer')
        self.assertNotIn('banknote', result['description'].lower())
        self.assertEqual(normalize_action(row('cash_left_unattended', 'unknown'))['type'], 'unknown')
        for kind in ('id_document', 'paper_document', 'none'):
            self.assertIsNone(normalize_action(row('cash_left_unattended', kind)))

    def test_no_object_is_not_an_event(self):
        self.assertIsNone(normalize_action(row(kind='none')))

    def test_future_intention_not_reported_as_a_transfer(self):
        self.assertIsNone(normalize_action(row(description='A person is preparing to hand over banknotes.')))

    def test_generic_and_negative_narration_removed(self):
        for description in ('A person walks into the room.', 'A person sits at the desk.',
                            'A person opens the door.', 'No cash action is visible.'):
            self.assertIsNone(normalize_action(row('unknown', 'unknown', description)))

    def test_static_scene_and_shapes_not_unknown_events(self):
        for description in ('A red square and a blue circle on a white background.',
                            'Banknotes are visible on a desk.',
                            'A person stands near a desk with a cash drawer open.'):
            self.assertIsNone(normalize_action(row('unknown', 'unknown', description)))

    def test_real_action_not_removed_by_walking_word(self):
        result = normalize_action(row('cash_handling', 'banknote', 'A person walks while handling banknotes.'))
        self.assertIsNotNone(result)

    def test_merge_overlapping_equal_actions(self):
        result = deduplicate([observation(0, 6), observation(2, 6)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].evidence_timestamps_sec, [0, 2, 6])

    def test_repeated_transfers_must_not_merge_on_touching_or_gap(self):
        self.assertEqual(len(deduplicate([observation(0, 2), observation(2, 4)])), 2)
        self.assertEqual(len(deduplicate([observation(0, 2), observation(3, 5)])), 2)

    def test_merge_continuous_touching_handling(self):
        result = deduplicate([observation(0, 2, action='cash_handling'),
                              observation(2, 4, action='cash_handling')])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].end_sec, 4)

    def test_roles_or_descriptions_differ_no_merge(self):
        first, second = observation(0, 6), observation(2, 6)
        self.assertEqual(len(deduplicate([first, replace(second, actors=['cashier'])])), 2)
        self.assertEqual(len(deduplicate([first, replace(second, description='A different action.')])), 2)

    def test_malformed_object_or_type_not_treated_as_cash(self):
        frames = [SampledFrame(0, None), SampledFrame(1, None)]
        result = parse_observations([row(kind=[])], frames, 1)
        self.assertEqual(result[0].type, 'object_transfer')
        self.assertEqual(parse_observations([row(action=[])], frames, 1)[0].type, 'unknown')

    def test_pipeline_verifies_from_larger_source_frames(self):
        class Fake:
            verifications = 0

            def load(self): pass
            def reset_metrics(self): pass
            def metrics(self): return {}
            def observe(self, frames, deadline): return [row()]
            def verify_object(inner, frames, deadline):
                inner.verifications += 1
                self.assertLessEqual(len(frames), 2)
                self.assertEqual(frames[0].image.width, 640)
                return 'id_document'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'generated.mov'
            create_video(path, width=1280, height=720)
            config = InferenceConfig(Path('unused'), window_seconds=2, overlap_seconds=0.5, refine=False)
            fake = Fake()
            result = InferenceEngine(config, model=fake).analyze_video(path)
            self.assertEqual(result.status, 'complete')
            self.assertEqual(fake.verifications, 3)
            self.assertEqual(len(result.observations), 3)
            self.assertTrue(all(item.type == 'document_transfer' for item in result.observations))

    def test_verification_disabled_cannot_certify_cash(self):
        class Fake:
            def load(self): pass
            def reset_metrics(self): pass
            def metrics(self): return {}
            def observe(self, frames, deadline): return [row()]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'generated.mov'
            create_video(path)
            result = InferenceEngine(InferenceConfig(Path('unused'), refine=False, verify_objects=False),
                                     model=Fake()).analyze_video(path)
            self.assertEqual(result.observations[0].type, 'object_transfer')


if __name__ == '__main__':
    unittest.main()
