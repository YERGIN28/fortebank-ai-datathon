"""Manifest/summary tests on invented references and placeholder local MOV paths."""
from pathlib import Path
import tempfile
import unittest
import json

from .batch_tools import build_manifest, safe_batch_error, summarize


class BatchToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='forte-batch-tools-test-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.normal, self.positive = self.directory / 'copy_normal.mov', self.directory / 'copy_positive.MOV'
        # Validation must never decode these placeholders as videos.
        self.normal.write_bytes(b'not a video; artificial metadata test')
        self.positive.write_bytes(b'not a video; artificial metadata test')
        self.labels = {'videos': [
            {'video_id': 'FAKE-NORMAL', 'verdict': 'no_violation', 'timecode_sec': None},
            {'video_id': 'FAKE-POSITIVE', 'verdict': 'violation', 'timecode_sec': 123},
            {'video_id': 'X-4', 'verdict': 'violation', 'timecode_sec': 4},
            {'video_id': 'X-47', 'verdict': 'violation', 'timecode_sec': 9}]}

    def test_manifest_uses_reference_ids_without_decoding(self):
        manifest = build_manifest(self.labels, [(self.normal, 'fake-normal'),
            (self.positive, 'fake-positive')], self.directory / 'manifest.json')
        self.assertEqual([row['video_id'] for row in manifest['videos']], ['FAKE-NORMAL', 'FAKE-POSITIVE'])
        self.assertNotIn('observations', json.dumps(manifest))

    def test_cyrillic_x_labels_accept_latin_x_input(self):
        labels = {'videos': [
            {'video_id': 'Х-101', 'verdict': 'no_violation'},
            {'video_id': 'Х-102', 'verdict': 'violation', 'timecode_sec': 123}]}
        manifest = build_manifest(labels, [(self.normal, 'X-101'),
            (self.positive, 'X-102')], self.directory / 'manifest.json')
        self.assertEqual([row['video_id'] for row in manifest['videos']], ['Х-101', 'Х-102'])
        self.assertEqual(safe_batch_error(ValueError('PRIVATE_FAKE_DATA')), 'invalid_local_input')

    def test_reject_ambiguous_unknown_same_id_same_file(self):
        for selections in (
            [(self.normal, 'fake-normal'), (self.positive, 'X4.mov')],
            [(self.normal, 'fake-normal'), (self.positive, 'check_001')],
            [(self.normal, 'fake-normal'), (self.positive, 'fake-normal')],
            [(self.normal, 'fake-normal'), (self.normal, 'fake-positive')],
        ):
            with self.subTest(selections=selections), self.assertRaises(ValueError):
                build_manifest(self.labels, selections, self.directory / 'manifest.json')

    def test_requires_one_of_each_reference_label(self):
        labels = {'videos': [self.labels['videos'][0],
                            {'video_id': 'OTHER-NORMAL', 'verdict': 'no_violation'}]}
        with self.assertRaises(ValueError):
            build_manifest(labels, [(self.normal, 'FAKE-NORMAL'),
                (self.positive, 'OTHER-NORMAL')], self.directory / 'manifest.json')

    def test_summary_contains_no_private_fields(self):
        marker = 'PRIVATE_SYNTHETIC_SENTINEL'
        document = {'videos': [
            {'video_id': marker, 'status': 'complete', 'observations': [{'description': marker}],
             'elapsed_sec': 100, 'duration_sec': 60, 'gpu_peak_allocated_mib': 4000,
             'gpu_peak_reserved_mib': 4100},
            {'video_id': marker, 'status': 'timeout', 'observations': [],
             'elapsed_sec': 301, 'gpu_peak_allocated_mib': 4200}]}
        report = summarize(document, planned_videos=3, wall_elapsed_sec=430)
        self.assertNotIn(marker, json.dumps(report))
        self.assertEqual(report['missing_results'], 1)
        self.assertEqual(report['timing']['mean_elapsed_sec'], 200.5)
        self.assertEqual(report['timing']['complete_only_mean_elapsed_sec'], 100)
        self.assertEqual(report['timing']['results_over_300_sec'], 1)
        self.assertEqual(report['gpu']['peak_allocated_mib'], 4200)
        self.assertEqual(report['gpu']['reserved_samples'], 1)
        self.assertFalse(report['all_complete'])

    def test_missing_metrics_are_null_not_zero(self):
        report = summarize({'videos': [{'status': 'failed'}]}, planned_videos=2)
        self.assertIsNone(report['gpu']['peak_allocated_mib'])
        self.assertIsNone(report['timing']['mean_elapsed_sec'])
        self.assertEqual(report['missing_results'], 1)

    def test_summary_rejects_invalid_metrics_and_status(self):
        for row in ({'status': 'done'}, {'status': 'complete', 'elapsed_sec': float('nan')},
                    {'status': 'complete', 'gpu_peak_allocated_mib': -1}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                summarize({'videos': [row]})
        with self.assertRaises(ValueError):
            summarize({'videos': [{'status': 'complete'}]}, planned_videos=0)


if __name__ == '__main__':
    unittest.main()
