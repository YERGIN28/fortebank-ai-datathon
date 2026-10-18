
# app/rules/actions.py

ACTION_CATALOG = {
    'cash_returned_after_check': {'title': 'Возврат банкнот после проверки; причина не установлена', 'is_violation': False},
    "cash_handling": {"title": "Работа с наличными", "is_violation": False},
    "cash_transfer": {"title": "Передача наличных", "is_violation": False},
    "cash_drawer_opened": {"title": "Открытие кассового ящика", "is_violation": False},
    "cash_drawer_closed": {"title": "Закрытие кассового ящика", "is_violation": False},
    "document_handling": {"title": "Работа с документом", "is_violation": False},
    "document_transfer": {"title": "Передача документа", "is_violation": False},
    "object_transfer": {"title": "Передача предмета", "is_violation": False},
    "object_handling": {"title": "Работа с предметом неустановленного вида", "is_violation": False},
    "person_enters": {
        "title": "Человек входит в помещение",
        "is_violation": False,
    },
    "banknote_handover": {
        "title": "Передача банкноты",
        "is_violation": False,
    },
    "banknote_handling": {
        "title": "Работа с банкнотой",
        "is_violation": False,
    },
    "banknote_placed_on_table": {
        "title": "Банкнота положена на стол",
        "is_violation": False,
    },
    "unknown": {
        "title": "Неизвестное действие",
        "is_violation": False,
    },
}
