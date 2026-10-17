
# app/rules/catalog.py

# Каталог правил для анализа действий кассира.
#
# ВАЖНО:
# Это шаблоны для дальнейшего заполнения.
# Они НЕ являются подтверждёнными нарушениями ForteBank.
# Нормативные основания добавим после проверки документов.

RULE_CATALOG = {
    "cashier_leaves_during_service": {
        "title": "Уход кассира до окончания обслуживания клиента",
        "description": "Кассир покидает рабочее место до окончания обслуживания клиента.",
        "severity": "high",
        "conditions": ["cashier_left_workplace", "customer_service_ongoing"],
        "exceptions": [],
        "regulation": {
            "document": "Постановление НБРК от 29.11.2019 № 231",
            "paragraph": "22",
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
