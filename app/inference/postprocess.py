"""Conservative object gating and temporal deduplication; no rule verdicts."""
from dataclasses import replace
import re
import unicodedata

from .schemas import OBSERVATION_TYPES, Observation

HANDHELD_ACTIONS = {'cash_handling', 'cash_transfer', 'cash_left_unattended',
                    'document_handling', 'document_transfer', 'object_transfer', 'object_handling',
                    'cash_returned_after_check'}
CONTINUOUS_ACTIONS = {'cash_handling', 'document_handling', 'cash_left_unattended'}
DOCUMENTS = {'id_document', 'paper_document'}


def normalize_action(row: dict) -> dict | None:
    """Object evidence can downgrade cash claims; never infer cash from a rectangle."""
    row = dict(row)
    action, kind = row.get('type', 'unknown'), row.get('object_kind', 'unknown')
    if not isinstance(action, str):
        action = 'unknown'
        row['type'] = action
    if action not in OBSERVATION_TYPES and action not in ('irrelevant', 'scene_description', 'no_cash_action'):
        action = 'unknown'
        row['type'] = action
    if not isinstance(kind, str):
        kind = 'unknown'
    if kind == 'none' and action == 'unknown':
        return None
    text = row['description'].strip()
    negative = re.search(r'\bno (?:observable )?cash (?:action|handling)|нет действий с наличными', text, re.I)
    speculative = re.search(r'\b(?:preparing to|about to|intends? to|wants? to)\b|готовится|собирается', text, re.I)
    generic = re.search(r'\b(?:walk\w*|enter\w*|leav\w*|sit\w*|stand\w*|typ\w*)\b|\bopen\w* (?:a |the )?door', text, re.I)
    object_words = re.search(r'banknote|cash|document|\bcard\b|drawer|\bobject\b|\bitem\b|налич|банкнот|документ|удостовер|предмет', text, re.I)
    action_words = re.search(r'\b(?:hand\w*|transfer\w*|pass\w*|receiv\w*|giv\w*|tak\w*|plac\w*|put\w*|mov\w*|remov\w*|open(?:s|ed|ing)|clos\w*|count\w*|hold\w*|pick\w*)\b|переда|получ|клад|откры|закры|держ', text, re.I)
    if action in ('irrelevant', 'scene_description', 'no_cash_action') or (negative and action == 'unknown') or speculative:
        return None
    if action == 'unknown' and generic and not object_words:
        return None
    if action == 'unknown' and (not object_words or not action_words):
        return None
    if action not in HANDHELD_ACTIONS:
        return row
    if kind == 'none':
        return None
    if action == 'cash_returned_after_check':
        if kind == 'banknote':
            return row
        row['type'] = 'document_transfer' if kind in DOCUMENTS else 'object_transfer'
        row['description'] = ('A document is transferred.' if kind in DOCUMENTS else
                              'A small object is transferred; its type is unclear.')
        return row
    if action == 'cash_left_unattended':
        # A document or an unidentified object cannot justify an unattended-cash claim.
        if kind == 'banknote':
            return row
        if kind == 'unknown':
            row['type'] = 'unknown'
            row['description'] = 'An object remains on the work surface; whether it is cash is unclear.'
            row['actors'] = ['unknown']
            return row
        return None
    transfer = action in ('cash_transfer', 'document_transfer', 'object_transfer')
    if kind == 'banknote':
        row['type'] = 'cash_transfer' if transfer else 'cash_handling'
        if action.startswith('document') or action == 'object_transfer':
            row['description'] = 'Banknotes are transferred between people.' if transfer else 'Banknotes are handled.'
    elif kind in DOCUMENTS:
        row['type'] = 'document_transfer' if transfer else 'document_handling'
        if action.startswith('cash') or action == 'object_transfer':
            subject = 'An identity document' if kind == 'id_document' else 'A paper document'
            row['description'] = subject + (' is transferred between people.' if transfer else ' is handled.')
    else:
        row['type'] = 'object_transfer' if transfer else 'object_handling'
        row['description'] = ('A small object is transferred; its type is unclear.' if transfer
                              else 'A small object is handled; its type is unclear.')
    return row


def text_key(text: str) -> str:
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def deduplicate(observations: list[Observation]) -> list[Observation]:
    """Merge only equal descriptions/roles with strong temporal evidence of duplication."""
    result = []
    for candidate in sorted(observations, key=lambda item: (item.start_sec, item.end_sec)):
        match = None
        for index in range(len(result) - 1, -1, -1):
            previous = result[index]
            if (previous.type != candidate.type or set(previous.actors) != set(candidate.actors)
                    or text_key(previous.description) != text_key(candidate.description)):
                continue
            overlap = min(previous.end_sec, candidate.end_sec) - max(previous.start_sec, candidate.start_sec)
            shortest = min(previous.end_sec - previous.start_sec, candidate.end_sec - candidate.start_sec)
            identical = (previous.start_sec, previous.end_sec) == (candidate.start_sec, candidate.end_sec)
            substantial = overlap > 0 and shortest > 0 and overlap / shortest >= 0.5
            continuous_touch = (candidate.type in CONTINUOUS_ACTIONS
                                and 0 <= candidate.start_sec - previous.end_sec <= 0.25)
            if identical or substantial or continuous_touch:
                match = index
                break
        if match is None:
            result.append(candidate)
            continue
        previous = result[match]
        timestamps = sorted(set(previous.evidence_timestamps_sec + candidate.evidence_timestamps_sec))
        largest_gap = max((b - a for a, b in zip(timestamps, timestamps[1:])), default=0)
        result[match] = replace(previous,
            start_sec=min(previous.start_sec, candidate.start_sec),
            end_sec=max(previous.end_sec, candidate.end_sec),
            evidence_timestamps_sec=timestamps,
            timing_resolution_sec=max(previous.timing_resolution_sec, candidate.timing_resolution_sec, largest_gap),
            refined=previous.refined and candidate.refined)
    return sorted(result, key=lambda item: (item.start_sec, item.end_sec))
