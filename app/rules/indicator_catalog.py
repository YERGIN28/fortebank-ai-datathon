"""Observable risk indicators for human review, not established legal breaches.

Project checklist rules are identified explicitly. A related legal source is
context for the reviewer, never a claim that unseen applicability is established.
"""
from copy import deepcopy
from .catalog import RULE_CATALOG

RULES_VERSION = 'possible-signs-2026.10.18.1'
NBRK = {'document': 'Правила кассовых операций, постановление НБРК № 231',
        'url': 'https://adilet.zan.kz/rus/docs/V1900019680'}


def indicator(title, description, conditions, anchor, *, after=(), simultaneous=None,
              source=None, minimum_span=None, enabled=True, limitation=''):
    return {
        'title': title, 'description': description, 'conditions': list(conditions),
        'scope_conditions': [], 'exceptions': [], 'time_condition': anchor,
        'temporal_policy': {'simultaneous': list(simultaneous or [anchor]),
                            'after': list(after), 'choose': 'first',
                            'minimum_span': minimum_span or {}},
        'decision_mode': 'possible_indicator', 'enabled': enabled,
        'basis_kind': 'project_visual_checklist', 'related_regulation': source,
        'limitation': limitation, 'severity': 'review',
    }


INDICATOR_CATALOG = {
    'workstation_left_with_screen_on': indicator(
        'Признак риска: включённый экран оставлен после ухода оператора',
        'После ухода оператора экран рабочего места остаётся включённым. Проверьте защиту оставленного рабочего места.',
        ['cashier_left_workplace', 'screen_on_after_departure'], 'screen_on_after_departure',
        after=['cashier_left_workplace'],
        limitation='Блокировка, содержимое экрана и окончание смены не установлены; обязательная норма для этого признака не подтверждена.'),
    'safe_left_open': indicator(
        'Признак риска: открытый сейф после ухода оператора',
        'Оператор отошёл от сейфа, дверца осталась открытой. Проверьте режим доступа и хранения.',
        ['cashier_left_workplace', 'safe_open_after_departure'], 'safe_open_after_departure',
        after=['cashier_left_workplace'], source={**NBRK, 'paragraph': '20'},
        limitation='Содержимое сейфа и допустимость операции не установлены; ссылка относится к хранению ранее принятых наличных.'),
    'key_left_in_safe_lock': indicator(
        'Признак риска: ключ оставлен в замке сейфа после ухода',
        'После ухода оператора в замке сейфа виден ключ. Проверьте доступ к ключу.',
        ['cashier_left_workplace', 'key_in_safe_lock_after_departure'], 'key_in_safe_lock_after_departure',
        after=['cashier_left_workplace'], source={**NBRK, 'paragraph': '80'},
        limitation='Конкретный внутренний порядок хранения ключей не предоставлен; его нарушение не установлено.'),
    'documents_left_unattended': indicator(
        'Признак риска: документы оставлены после ухода оператора',
        'Документы остаются на рабочей поверхности после ухода оператора. Проверьте требуемый режим хранения.',
        ['cashier_left_workplace', 'documents_remain_after_departure'], 'documents_remain_after_departure',
        after=['cashier_left_workplace'],
        limitation='Содержимое документов не читается; конфиденциальность и обязанность хранить их именно в сейфе не установлены.'),
    'stamp_left_unattended': indicator(
        'Признак риска: печать оставлена после ухода оператора',
        'Предмет с различимыми признаками печати или штампа остаётся на рабочей поверхности после ухода оператора.',
        ['cashier_left_workplace', 'stamp_remains_after_departure'], 'stamp_remains_after_departure',
        after=['cashier_left_workplace'], source={**NBRK, 'paragraph': '80'},
        limitation='Внутренний порядок обращения с печатями не предоставлен; неизвестный предмет не считается печатью.'),
    'cash_left_unattended': indicator(
        'Признак риска: наличные оставлены после ухода оператора',
        'Различимые банкноты остаются на рабочей поверхности после ухода оператора.',
        ['cashier_left_workplace', 'banknotes_remain_after_departure'], 'banknotes_remain_after_departure',
        after=['cashier_left_workplace'], source={**NBRK, 'paragraph': '20'},
        limitation='Принадлежность денег и завершение операции не установлены; это повод проверить хранение и контроль.'),
    'cash_on_desk_with_next_customer': indicator(
        'Признак риска: наличные на поверхности при подходе другого клиента',
        'Банкноты видны на рабочей поверхности до и во время подхода другого клиента. Проверьте разделение операций и хранение денег.',
        ['banknotes_on_work_surface', 'different_customer_approaches', 'banknotes_remain_during_approach'],
        'banknotes_remain_during_approach',
        simultaneous=['banknotes_on_work_surface', 'different_customer_approaches', 'banknotes_remain_during_approach'],
        source={**NBRK, 'paragraph': '20'},
        limitation='Непрерывная идентичность купюр, их принадлежность предыдущему клиенту и завершение операции не доказаны.'),
    'customer_leaves_during_cash_check': indicator(
        'Признак риска: клиент отходит при продолжающейся проверке наличных',
        'Клиент отходит от стойки, пока видимая проверка наличных продолжается.',
        ['customer_left_counter', 'visible_cash_check_continues'], 'visible_cash_check_continues',
        simultaneous=['customer_left_counter', 'visible_cash_check_continues'],
        source={**NBRK, 'paragraph': '20'},
        limitation='Отход не равен отсутствию клиента в помещении. Применимость требования о пересчёте при приёме проверяет человек.'),
    'customers_overlap_at_counter': indicator(
        'Признак риска: обслуживание клиентов пересекается',
        'Другой клиент начинает предъявлять документ у той же стойки, пока предыдущий ещё находится там.',
        ['previous_customer_still_at_counter', 'different_customer_starts_document_presentation'],
        'different_customer_starts_document_presentation',
        simultaneous=['previous_customer_still_at_counter', 'different_customer_starts_document_presentation'],
        limitation='Совместное обслуживание не исключено. Запрет такого пересечения в регламенте банка не подтверждён.'),
    'entrance_door_left_open': indicator(
        'Признак риска: дверь остаётся открытой после входа',
        'После входа оператора дверь остаётся открытой. Проверьте назначение двери и требуемый режим доступа.',
        ['operator_enters_room', 'entrance_remains_open_after_entry'], 'entrance_remains_open_after_entry',
        after=['operator_enters_room'], minimum_span={'entrance_remains_open_after_entry': 2.0},
        limitation='Открытая дверь при проходе не достаточна. Принадлежность двери к защищённому кассовому узлу не установлена.'),
    'personal_items_on_work_surface': indicator(
        'Признак риска: личные вещи на рабочей поверхности во время работы',
        'Оператор приступает к работе, а сумка или верхняя одежда остаются на той же рабочей поверхности.',
        ['operator_starts_work', 'personal_bag_or_clothing_on_work_surface'], 'personal_bag_or_clothing_on_work_surface',
        simultaneous=['operator_starts_work', 'personal_bag_or_clothing_on_work_surface'],
        limitation='Принадлежность вещей и конкретный запрет банка не установлены; используется визуальный чек-лист проекта.'),
    'cash_container_left_on_work_surface': indicator(
        'Признак риска: контейнер остаётся после извлечения наличных',
        'После извлечения различимых банкнот тот же видимый контейнер остаётся на рабочей поверхности.',
        ['cash_removed_from_container', 'same_container_remains_on_work_surface'], 'same_container_remains_on_work_surface',
        after=['cash_removed_from_container'], minimum_span={'same_container_remains_on_work_surface': 2.0},
        limitation='Необходимость дальнейшего использования контейнера и обязанность его убрать не установлены.'),
    'cash_on_desk_during_break': indicator(
        'Признак риска: наличные на поверхности во время перерыва',
        'Различимые банкноты остаются на поверхности, пока оператор пьёт напиток.',
        ['banknotes_on_work_surface', 'operator_drinking', 'banknotes_remain_during_break'],
        'banknotes_remain_during_break',
        simultaneous=['banknotes_on_work_surface', 'operator_drinking', 'banknotes_remain_during_break'],
        source={**NBRK, 'paragraph': '20'},
        limitation='Вид напитка, принадлежность денег и окончание операции не установлены; хранение требует проверки.'),
    'cash_left_after_counting': indicator(
        'Признак риска: наличные остаются на поверхности после пересчёта',
        'После видимого пересчёта различимые банкноты остаются на рабочей поверхности во время наблюдаемой паузы.',
        ['cash_counted', 'banknotes_remain_after_counting', 'operator_paused_cash_handling'],
        'banknotes_remain_after_counting', after=['cash_counted'],
        simultaneous=['banknotes_remain_after_counting', 'operator_paused_cash_handling'],
        minimum_span={'banknotes_remain_after_counting': 2.0, 'operator_paused_cash_handling': 2.0},
        source={**NBRK, 'paragraph': '20'},
        limitation='Короткая пауза не доказывает завершение операции. Порог 2 секунды — настройка проекта, не норматив.'),
    'safe_open_during_other_activity': indicator(
        'Признак риска: сейф остаётся открытым при другой деятельности',
        'Дверца сейфа остаётся открытой, пока оператор занят другой видимой деятельностью вне сейфа.',
        ['safe_door_open', 'operator_busy_away_from_safe', 'safe_remains_open'], 'safe_remains_open',
        simultaneous=['safe_door_open', 'operator_busy_away_from_safe', 'safe_remains_open'],
        minimum_span={'safe_remains_open': 2.0}, source={**NBRK, 'paragraph': '20'},
        limitation='Необходимость открытия и содержимое сейфа не установлены; обычное открытие для операции не является этим признаком.'),
}

# Existing explicit cash-service checks remain available. Their outcomes now
# use the same possible-sign wording, without changing their required evidence.
for _name in ('cashier_leaves_during_service', 'cash_counting_without_customer', 'previous_cash_outside_storage'):
    _rule = deepcopy(RULE_CATALOG[_name])
    _rule.update(enabled=True, basis_kind='conditional_regulatory_context',
                 related_regulation=_rule['regulation'], decision_mode='possible_indicator',
                 limitation='Наблюдаемые признаки требуют проверки человеком; юридическое заключение не формируется.')
    _rule['title'] = 'Признак возможного нарушения: ' + _rule['title']
    INDICATOR_CATALOG[_name] = _rule

# Negative procedural claims need full-operation coverage, unavailable from the
# sparse sampler. Keep them recognizable and reviewable, never invent absence.
for _name, _title, _conditions in (
    ('cash_received_without_visible_id_check', 'Проверка личности при приёме наличных требует уточнения',
     ['cash_received_from_customer', 'receipt_area_visible', 'id_check_not_visible_in_receipt']),
    ('cash_stored_without_visible_check', 'Проверка банкнот перед помещением в сейф требует уточнения',
     ['banknotes_put_into_safe', 'preceding_handling_visible', 'banknote_check_not_visible_before_storage']),
):
    INDICATOR_CATALOG[_name] = indicator(_title, _title, _conditions, _conditions[0], enabled=False,
        limitation='Редкие кадры не покрывают всю процедуру. Требуется дополнительная проверка полного контекста; отсутствие проверки не установлено.')

SCENARIO_COVERAGE = {
    1: ['cash_received_without_visible_id_check'],
    2: ['cash_on_desk_with_next_customer'],
    3: ['cash_returned_after_check'],
    4: ['key_left_in_safe_lock', 'safe_left_open', 'workstation_left_with_screen_on'],
    5: ['cash_stored_without_visible_check'],
    6: ['cash_container_left_on_work_surface'],
    7: ['customer_leaves_during_cash_check', 'cash_received_without_visible_id_check'],
    8: ['customers_overlap_at_counter'],
    9: ['safe_left_open', 'safe_open_during_other_activity'],
    10: ['workstation_left_with_screen_on', 'key_left_in_safe_lock'],
    11: ['documents_left_unattended', 'stamp_left_unattended'],
    12: ['cash_left_unattended'], 13: ['workstation_left_with_screen_on'],
    14: ['entrance_door_left_open'], 15: ['customer_leaves_during_cash_check'],
    16: ['cash_on_desk_with_next_customer'], 17: ['cash_on_desk_during_break'],
    18: ['cash_left_after_counting'], 19: ['personal_items_on_work_surface'],
    20: ['cash_received_without_visible_id_check', 'cash_on_desk_with_next_customer'],
}


def indicator_description(name, rule):
    text = rule['description'] + ' Это признак для проверки человеком.'
    source = rule.get('related_regulation')
    if source:
        text += (' Связанный источник для проверки применимости: ' + source['document']
                 + ', п. ' + source['paragraph'] + '. ' + source['url'])
    else:
        text += ' Основание отбора: визуальный чек-лист проекта; обязательная нормативная норма не подтверждена.'
    text += ' ' + rule.get('limitation', '')
    return text + ' Методика: /methodology#' + name
