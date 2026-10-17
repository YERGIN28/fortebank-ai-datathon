
# app/rules/catalog.py

# Каталог правил для анализа действий кассира.
#
# verified означает проверенный источник, а не подтверждение события на видео.
# Для окончательного решения нужны condition_checks и наблюдаемые доказательства.
from .ai4_catalog import AI4_REVIEW_RULES

RULE_CATALOG = {
    "cashier_leaves_during_service": {
        "title": "Уход кассира до окончания обслуживания клиента",
        "description": "Кассир покидает рабочее место до окончания обслуживания клиента.",
        "severity": "high",
        "conditions": ["cashier_left_workplace", "customer_service_ongoing"],
        "exceptions": [],
        "time_condition": "cashier_left_workplace",
        "regulation": {
            "document": "Постановление НБРК от 29.11.2019 № 231",
            "paragraph": "22",
            "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        },
        "verified": True,
    },
    "cash_counting_without_customer": {
        "title": "Пересчёт принимаемых наличных без присутствия клиента",
        "description": (
            "При прямом приёме наличных от клиента кассир пересчитывает их "
            "в отсутствие клиента при полностью наблюдаемой клиентской зоне."
        ),
        "severity": "high",
        "conditions": [
            "cash_is_identified",
            "direct_customer_cash_receipt",
            "cashier_counts_received_cash",
            "customer_zone_fully_visible",
            "customer_absent_during_counting",
        ],
        "exceptions": [],
        "time_condition": "cashier_counts_received_cash",
        "visibility_conditions": ["customer_zone_fully_visible"],
        "limitations": [
            "Человек вне кадра не доказывает отсутствие клиента",
            "Инкассация и внутренний пересчёт не являются прямым приёмом от клиента",
            "Нужен временной контекст операции и подтверждение наличных",
        ],
        "inference_supported": False,
        "regulation": {
            "document": "Постановление НБРК от 29.11.2019 № 231",
            "paragraph": "20, абзац 1",
            "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        },
        "verified": True,
    },
    "previous_cash_outside_storage": {
        "title": "Ранее принятые наличные оставлены вне специального хранилища",
        "description": (
            "Во время приёма денег текущего клиента ранее принятые наличные "
            "от завершённой операции остаются вне специальных устройств хранения."
        ),
        "severity": "high",
        "conditions": [
            "cash_is_identified",
            "previous_receipt_completed",
            "previous_cash_continuously_tracked",
            "current_customer_receipt_in_progress",
            "previous_cash_remains_outside_storage",
        ],
        "exceptions": [],
        "time_condition": "previous_cash_remains_outside_storage",
        "visibility_conditions": ["previous_cash_continuously_tracked"],
        "limitations": [
            "Наличные текущего клиента могут находиться на рабочем месте",
            "Без непрерывного контекста нельзя установить происхождение денег",
            "Открытый ящик сам по себе не доказывает наличие ранее принятых денег",
            "Проверка не устанавливает по изображению состояние невидимого замка",
        ],
        "inference_supported": False,
        "regulation": {
            "document": "Постановление НБРК от 29.11.2019 № 231",
            "paragraph": "20, абзац 2",
            "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        },
        "verified": True,
    },
    "cash_processing_without_controller": {
        "title": "Пересчёт, сортировка или упаковка без контролирующего работника",
        "description": "Требуется проверить участие контролирующего работника и вид операции.",
        "severity": "high",
        "conditions": ["internal_cash_processing", "controller_absent"],
        "exceptions": ["direct_customer_receipt_or_payout"],
        "decision_mode": "review_only",
        "inference_supported": False,
        "limitations": [
            "Приём и выдача наличных клиенту исключены из требования пункта 42",
            "Назначенную контролирующую роль нельзя достоверно определить по внешности",
        ],
        "regulation": {
            "document": "Постановление НБРК от 29.11.2019 № 231",
            "paragraph": "42",
            "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        },
        "verified": True,
    },
    "cash_left_unattended": {
        "title": "Наличные оставлены без присмотра",
        "description": (
            "Возможно, наличные оставлены без контроля "
            "во время кассовой операции."
        ),
        "severity": "high",
        "conditions": [
            "Наличные находятся в рабочей зоне",
            "Кассир отсутствует или не контролирует наличные",
        ],
        "exceptions": [
            "Кассир продолжает контролировать рабочую зону",
            "Ситуация не связана с кассовой операцией",
        ],
        "regulation": None,
        "verified": False,
    },
    "unauthorized_phone_use": {
        "title": "Использование телефона во время операции",
        "description": (
            "Возможно использование телефона "
            "во время обслуживания клиента."
        ),
        "severity": "medium",
        "conditions": [
            "Кассир использует телефон",
            "В это время выполняется кассовая операция",
        ],
        "exceptions": [
            "Использование телефона разрешено процедурой",
            "Телефон используется вне кассовой операции",
        ],
        "regulation": None,
        "verified": False,
    },
}

RULE_CATALOG.update(AI4_REVIEW_RULES)

# Проверенные нормативные основания.
# Это не автоматические вердикты о нарушениях.

REGULATORY_REFERENCES = {
    "NBRK_231_P3": {
        "document": "Постановление НБРК № 231",
        "paragraph": "3",
        "summary": "Виды кассовых операций банка",
        "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        "verified": True,
        "automatic_violation": False,
    },
    "NBRK_231_P9": {
        "document": "Постановление НБРК № 231",
        "paragraph": "9",
        "summary": (
            "Обеспечение банка специальным оборудованием "
            "для определения платежности и подлинности банкнот"
        ),
        "url": "https://adilet.zan.kz/rus/docs/V1900019680",
        "verified": True,
        "automatic_violation": False,
    },
}
