"""Visible condition contracts shared by prompts, validation and local consumers.

These are observation candidates, not regulatory verdicts. No label/video IDs,
personal text or assumptions about hidden computer state are used.
"""
import json

UNSUPPORTED_ABSENCE_ACTIONS = frozenset({
    'cash_received_without_visible_id_check', 'cash_stored_without_visible_check',
})

CONDITION_SPECS = {
    'cash_left_unattended': {
        'cashier_left_workplace': 'The operator visibly moves away from the workstation; show before and after.',
        'banknotes_remain_after_departure': 'Currency-specific detail confirms banknotes on the same work surface after departure, not documents or cards.',
    },
    'stamp_left_unattended': {
        'cashier_left_workplace': 'The operator visibly moves away from the workstation; show before and after.',
        'stamp_remains_after_departure': 'A distinguishable stamp body remains on the same workstation after departure; an unidentified small object is insufficient.',
    },
    'cash_on_desk_during_break': {
        'banknotes_on_work_surface': 'Currency-specific detail confirms banknotes on the work surface, not documents.',
        'operator_drinking': 'The operator visibly brings a drinking vessel to the mouth; a cup on a desk alone is insufficient. Do not identify the beverage.',
        'banknotes_remain_during_break': 'Recognizable banknotes remain on that surface at the same sampled moments as drinking.',
    },
    'cash_left_after_counting': {
        'cash_counted': 'A visible sequence shows the operator counting distinguishable banknotes.',
        'banknotes_remain_after_counting': 'Distinguishable banknotes remain on the same surface in later frames after the counting action.',
        'operator_paused_cash_handling': 'Later frames show a pause in handling that cash. Do not infer that the transaction has finished.',
    },
    'safe_open_during_other_activity': {
        'safe_door_open': 'An identifiable safe door is visibly open; a drawer or dark rectangle is insufficient.',
        'operator_busy_away_from_safe': 'The operator performs another visible activity away from the safe; merely handling contents of the safe is insufficient.',
        'safe_remains_open': 'The same safe door remains visibly open across multiple frames during the other activity.',
    },
    'cash_received_without_visible_id_check': {
        'cash_received_from_customer': 'A visible before/after sequence shows distinguishable banknotes being received from a customer.',
        'receipt_area_visible': 'The relevant receipt and document-handling area is visible.',
        'id_check_not_visible_in_receipt': 'Sparse frames cannot establish the absence of an identity check across the full receipt procedure. Use unclear.',
    },
    'cash_stored_without_visible_check': {
        'banknotes_put_into_safe': 'A visible before/after sequence shows distinguishable banknotes placed into an identifiable safe.',
        'preceding_handling_visible': 'The preceding handling of these banknotes is visible.',
        'banknote_check_not_visible_before_storage': 'Sparse frames cannot establish absence of preceding authenticity checks. Use unclear.',
    },
    'customers_overlap_at_counter': {
        'previous_customer_still_at_counter': 'The earlier customer remains at the same service counter.',
        'different_customer_starts_document_presentation': 'A different customer starts presenting a document there while the earlier customer is still at the counter; show before and after without identifying people.',
    },
    'cash_counting_without_customer': {
        'cash_is_identified': 'Visible currency-specific detail confirms banknotes, not documents.',
        'direct_customer_cash_receipt': 'Cash is visibly received directly from a customer, not internal processing.',
        'cashier_counts_received_cash': 'The cashier visibly counts that received cash.',
        'customer_zone_fully_visible': 'The whole relevant customer area is visible; an off-camera customer cannot be excluded otherwise.',
        'customer_absent_during_counting': 'The fully visible customer area is empty while that cash is being counted.',
    },
    'previous_cash_outside_storage': {
        'cash_is_identified': 'Currency-specific detail confirms banknotes, not documents.',
        'previous_receipt_completed': 'The previous cash-receipt operation visibly finished. A person stepping aside alone is insufficient.',
        'previous_cash_continuously_tracked': 'The same earlier cash is tracked without temporal gaps or occlusion. Sparse sampled frames cannot establish continuous tracking; use unclear.',
        'current_customer_receipt_in_progress': 'Cash receipt from a different customer is visibly in progress.',
        'previous_cash_remains_outside_storage': 'That same previously received cash remains outside storage during the new receipt.',
    },
    'key_left_in_safe_lock': {
        'cashier_left_workplace': 'The operator moves away from the safe; show before and after.',
        'key_in_safe_lock_after_departure': 'A key is distinguishable in the safe lock after departure, not just a handle or reflection.',
    },
    'entrance_door_left_open': {
        'operator_enters_room': 'The operator enters through an identifiable entrance; show before and after.',
        'entrance_remains_open_after_entry': 'That entrance door visibly remains open after entry.',
    },
    'personal_items_on_work_surface': {
        'operator_starts_work': 'Visible work starts at the workstation.',
        'personal_bag_or_clothing_on_work_surface': 'A bag or outer clothing remains on that work surface during work; do not infer ownership or contents.',
    },
    'cash_container_left_on_work_surface': {
        'cash_removed_from_container': 'Visible banknotes are removed from a visible container; show before and after.',
        'same_container_remains_on_work_surface': 'That same container remains on the work surface after removal.',
    },
    'workstation_left_with_screen_on': {
        'cashier_left_workplace': 'The same workstation operator moves away; show before and after.',
        'screen_on_after_departure': 'The same workstation screen visibly emits light after the operator leaves. Do not read its content or infer lock state.',
    },
    'safe_left_open': {
        'cashier_left_workplace': 'The operator moves away from the safe; show before and after.',
        'safe_open_after_departure': 'The safe door is visibly open after the operator moves away. A closed door or visible key alone is insufficient.',
    },
    'cash_on_desk_with_next_customer': {
        'banknotes_on_work_surface': 'Recognizable banknotes remain on the same work surface.',
        'different_customer_approaches': 'A different customer approaches that workstation while the previous customer departs or moves away; show before and after, without identifying people.',
        'banknotes_remain_during_approach': 'The same banknotes are still on the surface when the different customer approaches.',
    },
    'documents_left_unattended': {
        'cashier_left_workplace': 'The operator moves away from the workstation; show before and after.',
        'documents_remain_after_departure': 'Documents visibly remain on that workstation after departure. Do not read personal text.',
    },
    'customer_leaves_during_cash_check': {
        'customer_left_counter': 'The customer moves away from the counter; show before and after.',
        'visible_cash_check_continues': 'Visible banknote counting or detector use continues at that departure. Do not infer a hidden transaction state.',
    },
}
TEMPORAL_CONDITIONS = {'cashier_left_workplace', 'different_customer_approaches',
                       'customer_left_counter', 'operator_enters_room', 'cash_removed_from_container',
                       'operator_starts_work', 'direct_customer_cash_receipt', 'previous_receipt_completed'}
TEMPORAL_CONDITIONS.add('different_customer_starts_document_presentation')
TEMPORAL_CONDITIONS.update({'cash_counted', 'cash_received_from_customer', 'banknotes_put_into_safe'})
AFTER_DEPARTURE = {'screen_on_after_departure', 'safe_open_after_departure',
                   'documents_remain_after_departure', 'key_in_safe_lock_after_departure'}
AFTER_DEPARTURE.update({'stamp_remains_after_departure', 'banknotes_remain_after_departure'})


def parse_condition_checks(answer, action, frame_count):
    """Reject invented schema/evidence; insufficient temporal support is unclear."""
    from .model import strip_json_fence
    if action not in CONDITION_SPECS:
        raise ValueError('Unsupported condition category')
    try:
        payload = json.loads(strip_json_fence(answer))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid condition JSON') from None
    if not isinstance(payload, dict) or set(payload) != set(CONDITION_SPECS[action]):
        raise ValueError('Invalid condition schema')
    result = {}
    for name, value in payload.items():
        if not isinstance(value, dict) or set(value) != {'state', 'frames'}:
            raise ValueError('Invalid condition entry')
        state, indexes = value['state'], value['frames']
        if state not in ('observed', 'refuted', 'unclear') or not isinstance(indexes, list):
            raise ValueError('Invalid condition state')
        if any(type(i) is not int or not 0 <= i < frame_count for i in indexes):
            raise ValueError('Invalid condition evidence')
        indexes = sorted(set(indexes))
        if not indexes or (state == 'observed' and name in TEMPORAL_CONDITIONS and len(indexes) < 2):
            state = 'unclear'
        result[name] = {'state': state, 'frames': indexes}
    departure = result.get('cashier_left_workplace')
    for name in ('id_check_not_visible_in_receipt', 'banknote_check_not_visible_before_storage'):
        if name in result:
            result[name]['state'] = 'unclear'
    for name in AFTER_DEPARTURE & result.keys():
        check = result[name]
        if check['state'] == 'observed' and (departure['state'] != 'observed'
                or max(check['frames']) < max(departure['frames'])):
            check['state'] = 'unclear'
    # Both facts must share at least one sampled moment for simultaneous claims.
    if action == 'cash_on_desk_with_next_customer':
        simultaneous = result['banknotes_remain_during_approach']
        cash = result['banknotes_on_work_surface']
        approach = result['different_customer_approaches']
        if simultaneous['state'] == 'observed' and (
                cash['state'] != 'observed' or approach['state'] != 'observed'
                or not set(simultaneous['frames']) & set(cash['frames']) & set(approach['frames'])):
            simultaneous['state'] = 'unclear'
    if action == 'previous_cash_outside_storage':
        # This adapter receives sparse samples, never a continuous identity track.
        result['previous_cash_continuously_tracked']['state'] = 'unclear'
    if action == 'cash_counting_without_customer':
        visibility = result['customer_zone_fully_visible']
        if visibility['state'] == 'refuted':
            visibility['state'] = 'unclear'  # Occlusion does not prove absence or presence.
        absent = result['customer_absent_during_counting']
        names = ('cash_is_identified', 'cashier_counts_received_cash', 'customer_zone_fully_visible')
        if absent['state'] == 'observed' and (
                any(result[name]['state'] != 'observed' for name in names)
                or not set(absent['frames']).intersection(*(set(result[name]['frames']) for name in names))):
            absent['state'] = 'unclear'
    if action == 'customers_overlap_at_counter':
        earlier = result['previous_customer_still_at_counter']
        another = result['different_customer_starts_document_presentation']
        if another['state'] == 'observed' and (earlier['state'] != 'observed'
                or not set(earlier['frames']) & set(another['frames'])):
            another['state'] = 'unclear'
    for before, after in (('operator_enters_room', 'entrance_remains_open_after_entry'),
                          ('cash_removed_from_container', 'same_container_remains_on_work_surface')):
        if before in result and result[after]['state'] == 'observed':
            if (result[before]['state'] != 'observed'
                    or max(result[after]['frames']) < max(result[before]['frames'])):
                result[after]['state'] = 'unclear'
    return result
