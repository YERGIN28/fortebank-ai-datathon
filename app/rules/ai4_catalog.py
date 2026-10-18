"""AI4 visual candidates. Related laws are research leads, not verified grounds."""

NBRK_231 = "https://adilet.zan.kz/rus/docs/V1900019680"
ROOM_RULES = "https://adilet.zan.kz/rus/docs/V2000020075"


def _review(title, conditions, scopes, exceptions, time_condition, reason, references=()):
    return {
        "title": title, "description": title + ". Требуется проверка применимости основания.",
        "severity": "review", "conditions": conditions, "scope_conditions": scopes,
        "exceptions": exceptions, "time_condition": time_condition,
        "decision_mode": "review_only", "verified": False, "regulation": None,
        "inference_supported": False,
        "basis_status": "requires_verified_applicability_or_procedure",
        "review_reason": reason, "related_regulations": list(references),
    }


AI4_REVIEW_RULES = {
    "workstation_left_with_screen_on": _review(
        "Включённый экран после ухода оператора",
        ["cashier_left_workplace", "screen_on_after_departure"],
        ["session_is_unlocked", "unauthorized_access_possible"],
        ["authorized_staff_controls_workstation"], "screen_on_after_departure",
        "Светящийся экран не доказывает отсутствие блокировки или раскрытие данных; нужно проверенное правило доступа."),
    "safe_left_open": _review(
        "Открытый сейф после ухода оператора",
        ["cashier_left_workplace", "safe_open_after_departure"],
        ["previously_received_cash_in_safe", "cash_storage_scope_established"],
        ["authorized_safe_operation_in_progress"], "safe_open_after_departure",
        "Нужно установить режим хранения, содержимое и допустимость доступа; открытая дверца сама по себе недостаточна.",
        [{"url": NBRK_231, "paragraph": "20", "use": "storage_scope_only"}]),
    "key_left_in_safe_lock": _review(
        "Ключ в замке сейфа после ухода оператора",
        ["cashier_left_workplace", "key_in_safe_lock_after_departure"],
        ["cash_storage_lock_identified", "key_accessible_to_unauthorized_person"],
        ["authorized_operator_controls_key"], "key_in_safe_lock_after_departure",
        "Пункт 80 отсылает к внутреннему порядку обращения с ключами; конкретная процедура не предоставлена.",
        [{"url": NBRK_231, "paragraph": "80", "use": "requires_bank_procedure"}]),
    "documents_left_unattended": _review(
        "Документы остались после ухода оператора",
        ["cashier_left_workplace", "documents_remain_after_departure"],
        ["restricted_storage_required_for_documents", "unauthorized_access_possible"],
        ["authorized_staff_controls_documents"], "documents_remain_after_departure",
        "Не установлены категория документов, обязательный режим хранения и доступ посторонних; содержимое не читается."),
    "cash_on_desk_with_next_customer": _review(
        "Наличные на поверхности при подходе другого клиента",
        ["banknotes_on_work_surface", "different_customer_approaches", "banknotes_remain_during_approach"],
        ["previous_receipt_completed", "previous_cash_continuously_tracked", "current_customer_receipt_in_progress"],
        ["cash_belongs_to_current_operation"], "banknotes_remain_during_approach",
        "Подход другого клиента не доказывает нарушение п. 20; происхождение денег и этапы операций требуют отдельных фактов.",
        [{"url": NBRK_231, "paragraph": "20", "use": "requires_full_receipt_context"}]),
    "customer_leaves_during_cash_check": _review(
        "Клиент отходит во время видимой проверки наличных",
        ["customer_left_counter", "visible_cash_check_continues"],
        ["direct_customer_cash_receipt", "cashier_counts_received_cash", "customer_zone_fully_visible",
         "customer_absent_during_counting", "cash_is_identified"],
        ["customer_still_present_outside_sampled_area"], "visible_cash_check_continues",
        "Отход от стойки не доказывает отсутствие клиента. Проверка детектором не равна пересчёту при прямом приёме.",
        [{"url": NBRK_231, "paragraph": "20, абзац 1", "use": "requires_receipt_and_presence_context"}]),
    "customers_overlap_at_counter": _review(
        "Одновременное присутствие клиентов у стойки",
        ["previous_customer_still_at_counter", "different_customer_starts_document_presentation"],
        ["sequential_service_required_by_verified_procedure"],
        ["joint_or_authorized_service"], "different_customer_starts_document_presentation",
        "Не подтверждено публичное основание, запрещающее само пересечение клиентов у стойки; требуется конкретная процедура."),
    "entrance_door_left_open": _review(
        "Входная дверь осталась открытой после входа",
        ["operator_enters_room", "entrance_remains_open_after_entry"],
        ["door_is_cash_unit_service_entrance", "required_isolation_compromised"],
        ["controlled_passage_in_progress"], "entrance_remains_open_after_entry",
        "Пункт 8 касается изоляции кассового узла. Нужно установить назначение двери и условия прохода; открытие при входе не равно нарушению.",
        [{"url": ROOM_RULES, "paragraph": "8", "use": "requires_door_and_isolation_scope"}]),
    "personal_items_on_work_surface": _review(
        "Личные вещи на рабочей поверхности",
        ["operator_starts_work", "personal_bag_or_clothing_on_work_surface"],
        ["clear_surface_required_by_verified_procedure"],
        ["temporary_placement_permitted_by_procedure"], "personal_bag_or_clothing_on_work_surface",
        "Обязательная публичная норма для такого размещения не подтверждена; нужны правила рабочего места."),
    "cash_container_left_on_work_surface": _review(
        "Контейнер остался на поверхности после извлечения денег",
        ["cash_removed_from_container", "same_container_remains_on_work_surface"],
        ["container_removal_required_by_verified_procedure"],
        ["container_still_in_authorized_use"], "same_container_remains_on_work_surface",
        "Пустой контейнер на столе сам по себе не устанавливает нарушение хранения; необходима конкретная обязанность убрать его."),
}

# Negative visibility is uncertainty, not counterevidence of a violation.
AI4_REVIEW_RULES["cash_on_desk_with_next_customer"]["visibility_conditions"] = ["previous_cash_continuously_tracked"]
AI4_REVIEW_RULES["customer_leaves_during_cash_check"]["visibility_conditions"] = ["customer_zone_fully_visible"]
