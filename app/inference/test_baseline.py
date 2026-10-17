"""Baseline evaluation/XLSX tests using invented labels and in-memory XML only."""
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from .evaluate_baseline import evaluate_baseline, select_reference_by_manifest, video_key
from .labels_xlsx import LabelRow, audit_times, convert, load_table, safe_error_code, timestamp


def reference(key, positive, time=10):
    return {'video_id': key, 'verdict': 'violation' if positive else 'no_violation',
            'timecode_sec': time if positive else None}


def prediction(key, positive, times=(10,), status='complete'):
    return {'video_id': key, 'status': status,
            'verdict': 'violation' if positive else 'no_violation',
            'violations': [{'timecode_sec': time} for time in times] if positive else []}


def evaluate(truth, pred, **kwargs):
    return evaluate_baseline({'videos': truth}, {'videos': pred}, **kwargs)


class BaselineTests(unittest.TestCase):
    def test_manifest_subset_keeps_only_planned_references(self):
        truth = {'videos': [reference('Х-101', True), reference('Х-102', False), reference('fake_other', True)]}
        manifest = {'videos': [{'video_id': 'X101'}, {'video_id': 'x-102.mov'}]}
        subset = select_reference_by_manifest(truth, manifest)
        self.assertEqual(len(subset['videos']), 2)
        self.assertEqual(len(truth['videos']), 3)
        report = evaluate_baseline(subset, {'videos': [prediction('X101', True), prediction('X102', False)]})
        self.assertEqual(report['primary_coverage']['missing'], 0)
        self.assertTrue(report['evaluation_complete'])

    def test_manifest_subset_does_not_hide_missing_jobs(self):
        truth = {'videos': [reference('a', True), reference('b', False), reference('not_planned', True)]}
        manifest = {'videos': [{'video_id': 'a'}, {'video_id': 'b'}]}
        subset = select_reference_by_manifest(truth, manifest)
        report = evaluate_baseline(subset, {'videos': [prediction('a', True)]})
        self.assertEqual(report['primary_coverage']['reference_records'], 2)
        self.assertEqual(report['primary_coverage']['missing'], 1)
        self.assertFalse(report['evaluation_complete'])

    def test_manifest_subset_rejects_unknown_duplicate_and_empty(self):
        truth = {'videos': [reference('Х-101', True)]}
        for entries in ([], [{'video_id': 'unknown'}], [{'video_id': 'X101'}, {'video_id': 'Х-101'}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                select_reference_by_manifest(truth, {'videos': entries})

    def test_subset_does_not_disable_ambiguity_exclusion(self):
        truth = {'videos': [reference('Х-4', True), reference('a', False)]}
        subset = select_reference_by_manifest(truth, {'videos': [{'video_id': 'X4'}, {'video_id': 'a'}]})
        report = evaluate_baseline(subset, {'videos': [prediction('X4', True), prediction('a', False)]})
        self.assertEqual(report['ambiguity']['groups_present'], 1)
        self.assertEqual(report['primary_coverage']['reference_records'], 1)

    def test_selected_reference_cli_on_artificial_files(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory(prefix='forte-subset-test-') as directory:
            directory = Path(directory)
            truth, manifest, pred, subset, report = [directory / name for name in
                ('truth.json', 'manifest.json', 'pred.json', 'subset.json', 'report.json')]
            truth.write_text(json.dumps({'videos': [reference('a', True), reference('b', False), reference('c', False)]}))
            manifest.write_text(json.dumps({'videos': [{'video_id': 'a'}, {'video_id': 'b'}]}))
            pred.write_text(json.dumps({'videos': [prediction('a', True), prediction('b', False)]}))
            selected = subprocess.run([sys.executable, '-B', '-m', 'app.inference.batch_tools',
                'select-labels', '--labels', str(truth), '--manifest', str(manifest), '--output', str(subset)],
                capture_output=True, text=True)
            self.assertEqual(selected.returncode, 0, selected.stderr)
            self.assertEqual(json.loads(selected.stdout)['selected_reference_records'], 2)
            evaluated = subprocess.run([sys.executable, '-B', '-m', 'app.inference.evaluate_baseline',
                '--truth', str(truth), '--manifest', str(manifest), '--predictions', str(pred),
                '--report', str(report)], capture_output=True, text=True)
            self.assertEqual(evaluated.returncode, 0, evaluated.stderr)
            payload = json.loads(report.read_text())
            self.assertEqual(payload['selection']['selected_reference_records'], 2)
            self.assertEqual(payload['selection']['available_reference_records'], 3)
            self.assertEqual(payload['primary_coverage']['missing'], 0)

    def test_needs_review_is_not_positive_or_negative(self):
        review = {'video_id': 'a', 'status': 'complete', 'verdict': 'needs_review',
                  'violations': [{'timecode_sec': 10, 'status': 'needs_review', 'regulation': None}]}
        for positive in (True, False):
            report = evaluate([reference('a', positive)], [review])
            metrics = report['verdict_metrics_on_complete_primary_only']
            self.assertEqual(sum(metrics[key] for key in ('tp', 'fp', 'fn', 'tn')), 0)
            self.assertIsNone(metrics['f1'])
            self.assertEqual(report['primary_coverage']['needs_review'], 1)
            self.assertEqual(report['primary_coverage']['decision_fraction'], 0)
            self.assertFalse(report['evaluation_complete'])

    def test_review_points_do_not_match_confirmed_violation(self):
        pred = {'video_id': 'a', 'status': 'complete', 'verdict': 'violation',
                'violations': [{'timecode_sec': 10, 'status': 'needs_review'},
                               {'timecode_sec': 30, 'status': 'violation'}]}
        report = evaluate([reference('a', True, 10)], [pred])
        self.assertEqual(report['verdict_metrics_on_complete_primary_only']['tp'], 1)
        self.assertEqual(report['point_localization_on_complete_primary_only']['hits'], 0)
        self.assertEqual(report['point_localization_on_complete_primary_only']['predicted_points_total'], 1)

    def test_violation_requires_confirmed_item(self):
        with self.assertRaises(ValueError):
            evaluate([reference('a', True)], [{'video_id': 'a', 'status': 'complete',
                'verdict': 'violation', 'violations': [{'timecode_sec': 10, 'status': 'needs_review'}]}])

    def test_private_time_audit_distinguishes_empty_and_format(self):
        import json
        table = [LabelRow({'flag': 'yes', 'time': ''}, 17),
                 LabelRow({'flag': 'yes', 'time': '02:03'}, 23),
                 LabelRow({'flag': 'yes', 'time': 'PRIVATE_FAKE_VALUE'}, 31),
                 LabelRow({'flag': 'yes', 'time': '123 секунды'}, 42),
                 LabelRow({'flag': 'no', 'time': ''}, 50)]
        audit = audit_times(table, label_column='flag', time_column='time',
                            positive_label='yes', time_format='seconds-text')
        self.assertEqual(audit['summary']['positive_rows'], 4)
        self.assertEqual(audit['summary']['missing_positive_times'], 1)
        self.assertEqual(audit['summary']['invalid_positive_times'], 2)
        self.assertEqual(audit['issues'][0]['excel_row'], 17)
        self.assertEqual(audit['summary']['problem_counts']['clock_like'], 1)
        self.assertNotIn('PRIVATE_FAKE_VALUE', json.dumps(audit))
        self.assertNotIn('02:03', json.dumps(audit))

    def test_missing_positive_time_is_not_filled_or_skipped(self):
        with self.assertRaisesRegex(ValueError, '^Missing positive timestamp$'):
            convert([{'id': 'synthetic', 'flag': 'yes', 'time': ''}], id_column='id',
                    label_column='flag', time_column='time', positive_label='yes', negative_label='no')

    def test_safe_diagnostic_codes(self):
        self.assertEqual(safe_error_code(ValueError('Missing time column')), 'missing_time_column')
        self.assertEqual(safe_error_code(ValueError('Expected numeric seconds with optional Russian seconds unit')),
                         'invalid_or_missing_time')
        self.assertEqual(safe_error_code(ValueError('PRIVATE_FAKE_EVENT')), 'invalid_value_or_unsupported_structure')
        self.assertEqual(safe_error_code(FileNotFoundError('PRIVATE_FAKE_PATH')), 'input_or_parent_missing')
        self.assertEqual(safe_error_code(ValueError('Choose a new output path')), 'output_already_exists')

    def test_verdict_confusion_matrix(self):
        truth = [reference('a', True), reference('b', True), reference('c', False), reference('d', False)]
        pred = [prediction('a', True), prediction('b', False), prediction('c', True), prediction('d', False)]
        report = evaluate(truth, pred)
        metrics = report['verdict_metrics_on_complete_primary_only']
        self.assertEqual([metrics[key] for key in ('tp', 'fp', 'fn', 'tn')], [1, 1, 1, 1])
        self.assertEqual(metrics['f1'], 0.5)
        self.assertEqual(metrics['accuracy'], 0.5)

    def test_localization_does_not_change_detection_tp(self):
        report = evaluate([reference('a', True)], [prediction('a', True, (12.01,))])
        self.assertEqual(report['verdict_metrics_on_complete_primary_only']['tp'], 1)
        self.assertEqual(report['point_localization_on_complete_primary_only']['hits'], 0)
        report = evaluate([reference('a', True)], [prediction('a', True, (12,))])
        self.assertEqual(report['point_localization_on_complete_primary_only']['hits'], 1)

    def test_localization_includes_missed_positive_as_miss(self):
        report = evaluate([reference('a', True)], [prediction('a', False)])
        timing = report['point_localization_on_complete_primary_only']
        self.assertEqual(timing['hit_rate'], 0)
        self.assertEqual(timing['misses'], 1)
        self.assertIsNone(timing['mean_nearest_error_on_detected_positives_sec'])

    def test_multiple_points_counted_and_nearest_used(self):
        report = evaluate([reference('a', True)], [prediction('a', True, (0, 10, 100))])
        timing = report['point_localization_on_complete_primary_only']
        self.assertEqual(timing['hits'], 1)
        self.assertEqual(timing['predicted_points_total'], 3)

    def test_ambiguous_pair_excluded_even_with_different_times(self):
        truth = [reference('X-4.mov', True, 4), reference('X_47', True, 9), reference('normal', False)]
        pred = [prediction('x4', False), prediction('X47.MOV', True, (9,)), prediction('normal', False)]
        report = evaluate(truth, pred)
        self.assertEqual(report['ambiguity']['groups_present'], 1)
        self.assertEqual(report['ambiguity']['reference_records_excluded'], 2)
        self.assertFalse(report['ambiguity']['metrics_computed'])
        self.assertEqual(report['primary_coverage']['reference_records'], 1)
        self.assertEqual(report['verdict_metrics_on_complete_primary_only']['tn'], 1)
        self.assertEqual(report['verdict_metrics_on_complete_primary_only']['tp'], 0)

    def test_only_one_ambiguous_member_also_excluded(self):
        report = evaluate([reference('X-4', True)], [prediction('X4', True)])
        self.assertFalse(report['evaluation_complete'])
        self.assertEqual(report['primary_coverage']['reference_records'], 0)

    def test_statuses_and_missing(self):
        truth = [reference(str(i), True) for i in range(4)]
        pred = [prediction(str(i), True, status=status) for i, status in enumerate(('partial', 'timeout', 'failed'))]
        report = evaluate(truth, pred)
        self.assertFalse(report['evaluation_complete'])
        self.assertEqual(report['primary_coverage']['missing'], 1)
        self.assertIsNone(report['verdict_metrics_on_complete_primary_only']['f1'])

    def test_ai_observations_are_not_verdicts(self):
        with self.assertRaises(ValueError):
            evaluate([reference('a', True)], [{'video_id': 'a', 'status': 'complete', 'observations': [{}]}])

    def test_invalid_and_duplicate_inputs(self):
        for pred in ([prediction('other', True)], [prediction('a', True), prediction('A', True)],
                     [prediction('a', True, ())], [prediction('a', True, (float('nan'),))]):
            with self.assertRaises(ValueError):
                evaluate([reference('a', True)], pred)
        with self.assertRaises(ValueError):
            evaluate([reference('X4', True), reference('X-4.mov', True)], [])
        self.assertEqual(video_key('X_047.mov'), 'x47')
        for value in ('Х-047.mov', 'х47', 'Х – 47.MOV', 'X-47'):
            self.assertEqual(video_key(value), 'x47')
        with self.assertRaises(ValueError):
            evaluate([reference('Х-101', True), reference('X-101', True)], [])

    def test_report_hides_private_identifiers(self):
        import json
        marker = 'PRIVATE_FAKE_ID'
        report = evaluate([reference(marker, True)], [prediction(marker, True)])
        self.assertNotIn(marker.casefold(), json.dumps(report).casefold())

    def test_time_formats(self):
        self.assertEqual(timestamp('62.5', 'seconds'), 62.5)
        self.assertEqual(timestamp('01:02.5', 'clock'), 62.5)
        self.assertEqual(timestamp('01:02:03', 'clock'), 3723)
        self.assertAlmostEqual(timestamp(str(60 / 86400), 'excel-time'), 60)
        for value in ('00:99', '-1:20', '1.5:20'):
            with self.assertRaises(ValueError):
                timestamp(value, 'clock')

    def test_russian_seconds_units(self):
        for value in ('123 секунда', '123 секунды', '123 секунд', '123 сек.',
                      '123 с', '123', ' 123\u00a0СЕКУНД '):
            with self.subTest(value=value):
                self.assertEqual(timestamp(value, 'seconds-text'), 123)
        self.assertEqual(timestamp('123,5 секунды', 'seconds-text'), 123.5)

    def test_minutes_and_seconds_durations(self):
        for value, expected in (
            ('2 минуты 15 секунд', 135), ('2 мин. 15 сек.', 135),
            ('2минуты15секунд', 135), ('2 минуты и 15 секунд', 135),
            ('2 минуты, 15 секунд', 135), ('2 минуты', 120),
            ('0,5 минуты', 30), ('2 МИНУТЫ 15,5 СЕКУНД', 135.5),
            ('123 секунда', 123), ('123', 123),
        ):
            with self.subTest(value=value):
                self.assertEqual(timestamp(value, 'duration-text'), expected)

    def test_ambiguous_duration_text_rejected(self):
        for value in ('2 минуты 75 секунд', '0.5 минуты 10 секунд',
                      'от 2 до 3 минут', '-2 минуты', '2 минуты 15',
                      '2 минуты либо 3 минуты', 'NaN минут'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value, 'duration-text')

    def test_mixed_duration_conversion_keeps_all_rows(self):
        table = [{'id': 'synthetic_a', 'flag': 'yes', 'time': '123 секунда'},
                 {'id': 'synthetic_b', 'flag': 'yes', 'time': '2 минуты 15 секунд'},
                 {'id': 'synthetic_c', 'flag': 'no', 'time': ''}]
        result = convert(table, id_column='id', label_column='flag', time_column='time',
                         positive_label='yes', negative_label='no', time_format='duration-text')
        self.assertEqual([row['timecode_sec'] for row in result['videos']], [123, 135, None])

    def test_invalid_text_seconds_rejected(self):
        for value in ('', '-1 секунда', '01:23', '123 минуты', 'NaN', '1e3 секунд',
                      'текст 123 секунда'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value, 'seconds-text')

    def test_confirmed_headers_on_invented_rows(self):
        table = [
            {'наименование файла': 'synthetic_positive', 'таймстемп': '123 секунда',
             'нарушение / без нарушения': 'нарушение'},
            {'наименование файла': 'synthetic_negative', 'таймстемп': '',
             'нарушение / без нарушения': 'без нарушения'},
        ]
        result = convert(table, id_column='наименование файла', time_column='таймстемп',
                         label_column='нарушение / без нарушения', positive_label='нарушение',
                         negative_label='без нарушения', time_format='seconds-text')
        self.assertEqual(result['videos'][0]['timecode_sec'], 123)
        self.assertIsNone(result['videos'][1]['timecode_sec'])

    def test_conversion_has_no_column_or_label_guessing(self):
        table = [{'Clip': 'fake_a.mov', 'Flag': 'YES', 'When': '01:02'},
                 {'Clip': 'fake_b.mov', 'Flag': 'NO', 'When': ''}]
        kwargs = dict(id_column='Clip', label_column='Flag', time_column='When',
                      positive_label='YES', negative_label='NO', time_format='clock')
        result = convert(table, **kwargs)
        self.assertEqual(result['videos'][0]['timecode_sec'], 62)
        self.assertIsNone(result['videos'][1]['timecode_sec'])
        with self.assertRaises(ValueError):
            convert(table, **{**kwargs, 'positive_label': 'OTHER'})

    def test_plain_xlsx_and_formula_rejection(self):
        main_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        rel_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
        workbook = f'<workbook xmlns="{main_ns}" xmlns:r="{rel_ns}"><sheets><sheet name="Fake" r:id="rId1"/></sheets></workbook>'
        relationships = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
        sheet = f'''<worksheet xmlns="{main_ns}"><sheetData>
          <row r="1"><c r="A1" t="inlineStr"><is><t>Clip</t></is></c><c r="B1" t="s"><v>0</v></c><c r="C1" t="inlineStr"><is><t>When</t></is></c><c r="D1" s="1"/></row>
          <row r="2"><c r="A2" t="inlineStr"><is><t>fake.mov</t></is></c><c r="B2"><v>1</v></c><c r="C2"><v>12.5</v></c></row>
        </sheetData></worksheet>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fake.xlsx'
            for with_formula in (False, True):
                with ZipFile(path, 'w') as archive:
                    archive.writestr('xl/workbook.xml', workbook)
                    archive.writestr('xl/_rels/workbook.xml.rels', relationships)
                    archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{main_ns}"><si><t>Flag</t></si></sst>')
                    archive.writestr('xl/worksheets/sheet1.xml', sheet.replace('<v>12.5</v>', '<f>1+1</f><v>2</v>') if with_formula else sheet)
                if with_formula:
                    with self.assertRaises(ValueError):
                        load_table(path)
                else:
                    self.assertEqual(load_table(path, 'Fake'), [{'Clip': 'fake.mov', 'Flag': '1', 'When': '12.5'}])


if __name__ == '__main__':
    unittest.main()
