
# app/rules/actions.py

ACTION_CATALOG = {
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
