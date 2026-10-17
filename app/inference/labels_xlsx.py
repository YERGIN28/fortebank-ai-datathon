"""Local XLSX label adapter; explicit columns/labels, no external dependencies."""
import argparse
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

from .evaluate import number
from .evaluate_baseline import reference_records

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


class LabelRow(dict):
    """Keep Excel row position locally; not part of normalized label output."""
    def __init__(self, values, excel_row):
        super().__init__(values)
        self.excel_row = excel_row


def audit_times(table, *, label_column, time_column, positive_label, time_format):
    """Only counts and structural error kinds; never identifiers or cell values."""
    issues, positives, missing = [], 0, 0
    formats = {}
    for index, row in enumerate(table):
        if row.get(label_column) != positive_label:
            continue
        positives += 1
        value = row.get(time_column, '')
        if not value.strip():
            kind = 'empty'
            missing += 1
        else:
            try:
                timestamp(value, time_format)
                continue
            except (ValueError, TypeError, OverflowError):
                if ':' in value:
                    kind = 'clock_like'
                elif 'мин' in value.casefold():
                    kind = 'minute_unit'
                elif len(re.findall(r'\d+(?:[.,]\d+)?', value)) > 1:
                    kind = 'multiple_numbers'
                else:
                    kind = 'other_format'
        formats[kind] = formats.get(kind, 0) + 1
        issues.append({'excel_row': getattr(row, 'excel_row', index + 2), 'problem': kind})
    return {'summary': {'positive_rows': positives, 'missing_positive_times': missing,
                        'invalid_positive_times': len(issues) - missing,
                        'problem_counts': formats}, 'issues': issues}


def safe_error_code(error: Exception) -> str:
    """Return fixed diagnostic codes, never source values or exception text."""
    messages = {
        'Choose a new output path': 'output_already_exists',
        'Missing ID column': 'missing_id_column',
        'Missing label column': 'missing_label_column',
        'Missing time column': 'missing_time_column',
        'Column missing': 'missing_columns',
        'Sheet not found': 'sheet_not_found',
        'Header and data rows required': 'missing_header_or_data',
        'Headers must be unique and nonempty': 'invalid_headers',
        'Nonempty data column has no header': 'data_without_header',
        'Formula/error cells unsupported; use an exported values-only copy': 'formula_or_excel_error',
        'Unknown label; no label inference is performed': 'unrecognized_label',
        'Expected numeric seconds with optional Russian seconds unit': 'invalid_or_missing_time',
        'Expected seconds or a minute-second duration': 'invalid_or_missing_time',
        'Missing positive timestamp': 'missing_positive_time',
        'Expected a finite nonnegative number': 'invalid_or_missing_time',
        'Expected MM:SS or HH:MM:SS': 'invalid_clock_time',
        'Invalid clock time': 'invalid_clock_time',
        'Expected video identifier': 'invalid_video_id',
        'Duplicate ID or invalid reference verdict': 'duplicate_or_invalid_video_id',
        'Label XML exceeds safety limit': 'xml_size_limit',
        'Invalid shared string index': 'invalid_shared_string',
    }
    if isinstance(error, FileNotFoundError):
        return 'input_or_parent_missing'
    if isinstance(error, FileExistsError):
        return 'output_already_exists'
    if isinstance(error, PermissionError):
        return 'file_access_denied'
    if isinstance(error, BadZipFile):
        return 'not_valid_xlsx'
    if isinstance(error, ET.ParseError):
        return 'invalid_excel_xml'
    if isinstance(error, KeyError):
        return 'xlsx_component_missing'
    return messages.get(str(error), 'invalid_value_or_unsupported_structure')


def xml(archive, name):
    if archive.getinfo(name).file_size > 20 * 1024 * 1024:
        raise ValueError('Label XML exceeds safety limit')
    return ET.fromstring(archive.read(name))


def load_table(path: Path, sheet_name=None) -> list[dict]:
    """Read plain cell values only. Formulas/error cells are deliberately rejected."""
    with ZipFile(path) as archive:
        sheets = xml(archive, 'xl/workbook.xml').findall('m:sheets/m:sheet', NS)
        selected = next((sheet for sheet in sheets if sheet.get('name') == sheet_name), None) if sheet_name else next(iter(sheets), None)
        if selected is None:
            raise ValueError('Sheet not found')
        relationship_id = selected.get(f'{{{NS["r"]}}}id')
        relationships = xml(archive, 'xl/_rels/workbook.xml.rels')
        relation = next((item for item in relationships if item.get('Id') == relationship_id), None)
        if relation is None or relation.get('TargetMode') == 'External':
            raise ValueError('Local sheet relationship required')
        target = relation.get('Target', '')
        sheet_path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
        if not sheet_path.startswith('xl/'):
            raise ValueError('Invalid sheet path')
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(item.itertext()) for item in xml(archive, 'xl/sharedStrings.xml')]
        table = []
        for row in xml(archive, sheet_path).findall('m:sheetData/m:row', NS):
            values = LabelRow({}, int(row.get('r', '0')))
            for cell in row.findall('m:c', NS):
                if cell.find('m:f', NS) is not None or cell.get('t') == 'e':
                    raise ValueError('Formula/error cells unsupported; use an exported values-only copy')
                address = re.match(r'([A-Z]+)\d+$', cell.get('r', ''))
                if address is None:
                    raise ValueError('Cell address missing')
                text = cell.find('m:v', NS)
                value = text.text if text is not None and text.text is not None else ''
                if cell.get('t') == 's':
                    index = int(value)
                    if not 0 <= index < len(shared):
                        raise ValueError('Invalid shared string index')
                    value = shared[index]
                elif cell.get('t') == 'inlineStr':
                    inline = cell.find('m:is', NS)
                    value = ''.join(inline.itertext()) if inline is not None else ''
                elif cell.get('t') not in ('str', 'b', 'd') and value:
                    numeric = float(value)
                    value = str(int(numeric)) if numeric.is_integer() else str(numeric)
                # Styled-but-empty Excel cells are not extra header columns.
                if value.strip():
                    values[address.group(1)] = value.strip()
            if any(values.values()):
                table.append(values)
    if len(table) < 2:
        raise ValueError('Header and data rows required')
    headers = table[0]
    if len(set(headers.values())) != len(headers) or any(not value for value in headers.values()):
        raise ValueError('Headers must be unique and nonempty')
    if any(row.keys() - headers.keys() for row in table[1:]):
        raise ValueError('Nonempty data column has no header')
    return [LabelRow({name: row.get(column, '') for column, name in headers.items()}, row.excel_row)
            for row in table[1:]]


def timestamp(value: str, time_format: str) -> float:
    if time_format == 'duration-text':
        try:
            return timestamp(value, 'seconds-text')
        except ValueError:
            pass
        match = re.fullmatch(
            r'\s*(\d+(?:[.,]\d+)?)\s*(?:минута|минуты|минут|мин\.?)'
            r'(?:\s*(?:,|и)?\s*(\d+(?:[.,]\d+)?)\s*'
            r'(?:секунда|секунды|секунд|сек\.?|с\.?))?\s*',
            value, flags=re.IGNORECASE)
        if match is None:
            raise ValueError('Expected seconds or a minute-second duration')
        minutes = number(float(match.group(1).replace(',', '.')))
        seconds = number(float(match.group(2).replace(',', '.'))) if match.group(2) is not None else 0.0
        if match.group(2) is not None and (not minutes.is_integer() or seconds >= 60):
            raise ValueError('Expected seconds or a minute-second duration')
        return number(minutes * 60 + seconds)
    if time_format == 'seconds':
        return number(float(value))
    if time_format == 'seconds-text':
        match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(?:секунда|секунды|секунд|сек\.?|с\.?)?\s*',
                             value, flags=re.IGNORECASE)
        if match is None:
            raise ValueError('Expected numeric seconds with optional Russian seconds unit')
        return number(float(match.group(1).replace(',', '.')))
    if time_format == 'excel-time':
        fraction = number(float(value))
        if fraction >= 1:
            raise ValueError('Excel time must be a fractional day below 1; dates unsupported')
        return fraction * 86400
    if time_format != 'clock':
        raise ValueError('Unsupported time format')
    pieces = value.split(':')
    if len(pieces) not in (2, 3):
        raise ValueError('Expected MM:SS or HH:MM:SS')
    values = [number(float(piece)) for piece in pieces]
    if any(value >= 60 for value in values[1:]) or any(not value.is_integer() for value in values[:-1]):
        raise ValueError('Invalid clock time')
    return sum(value * 60 ** power for power, value in enumerate(reversed(values)))


def convert(table, *, id_column, label_column, time_column, positive_label,
            negative_label, time_format='seconds'):
    if positive_label == negative_label or not positive_label or not negative_label:
        raise ValueError('Distinct nonempty label values required')
    if len({id_column, label_column, time_column}) != 3:
        raise ValueError('Three distinct columns required')
    if time_format not in ('seconds', 'seconds-text', 'duration-text', 'clock', 'excel-time'):
        raise ValueError('Unsupported time format')
    output = []
    for row in table:
        for column, message in ((id_column, 'Missing ID column'),
                                (label_column, 'Missing label column'),
                                (time_column, 'Missing time column')):
            if column not in row:
                raise ValueError(message)
        label = row[label_column]
        if label not in (positive_label, negative_label):
            raise ValueError('Unknown label; no label inference is performed')
        positive = label == positive_label
        if positive and not row[time_column].strip():
            raise ValueError('Missing positive timestamp')
        output.append({'video_id': row[id_column],
                       'verdict': 'violation' if positive else 'no_violation',
                       'timecode_sec': timestamp(row[time_column], time_format) if positive else None})
    document = {'videos': output}
    reference_records(document)
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sheet')
    for name in ('id-column', 'label-column', 'time-column', 'positive-label', 'negative-label'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--time-format', choices=('seconds', 'seconds-text', 'duration-text', 'clock', 'excel-time'), default='seconds')
    args = parser.parse_args()
    stage = 'validate_output'
    try:
        if args.output.exists() or args.output.resolve() == args.input.resolve():
            raise ValueError('Choose a new output path')
        stage = 'read_xlsx'
        table = load_table(args.input, args.sheet)
        stage = 'convert_labels'
        result = convert(table, id_column=args.id_column,
                         label_column=args.label_column, time_column=args.time_column,
                         positive_label=args.positive_label, negative_label=args.negative_label,
                         time_format=args.time_format)
        stage = 'write_json'
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, ET.ParseError, BadZipFile) as error:
        code = safe_error_code(error)
        if stage == 'convert_labels' and code in ('invalid_or_missing_time', 'missing_positive_time', 'invalid_clock_time'):
            audit = audit_times(table, label_column=args.label_column, time_column=args.time_column,
                                positive_label=args.positive_label, time_format=args.time_format)
            print('TIME_DIAGNOSTICS ' + json.dumps(audit['summary'], ensure_ascii=False), flush=True)
            # Private row positions help the user inspect their own Excel locally.
            # No source identifiers, times, descriptions or labels are included.
            diagnostic = args.output.with_name(args.output.stem + '_conversion_issues.json')
            try:
                diagnostic.parent.mkdir(parents=True, exist_ok=True)
                diagnostic.write_text(json.dumps(audit, indent=2), encoding='utf-8')
                print('Local Excel row positions saved in baseline_labels_conversion_issues.json; do not send source rows.', flush=True)
            except OSError:
                print('Could not save local issue positions; aggregate counts are shown above.', flush=True)
        raise SystemExit(f'XLSX conversion failed [stage={stage}; code={code}]') from None
    print('Converted labels locally. No source rows printed.')


if __name__ == '__main__':
    main()
