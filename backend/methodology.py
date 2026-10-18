"""Public explanation of static project rules. No video data or credentials."""
from html import escape
from app.rules.indicator_catalog import INDICATOR_CATALOG, RULES_VERSION, SCENARIO_COVERAGE


def render_methodology():
    cards = []
    for name, rule in INDICATOR_CATALOG.items():
        source = rule.get('related_regulation')
        basis = ('Связанный источник для проверки применимости: '
                 + '<a href="' + escape(source['url'], quote=True) + '">'
                 + escape(source['document'] + ', п. ' + source['paragraph']) + '</a>. '
                 if source else 'Подтверждённого обязательного норматива для этого признака пока нет. ')
        numbers = ', '.join(str(number) for number, names in SCENARIO_COVERAGE.items() if name in names)
        cards.append('<article id="' + escape(name, quote=True) + '"><h2>' + escape(rule['title'])
                     + '</h2><p>' + escape(rule['description']) + '</p><p>' + basis
                     + escape(rule.get('limitation', '')) + '</p><p>'
                     + ('Включён как визуальный признак для проверки.' if rule['enabled'] else
                        'Автоматический вывод отключён: текущие кадры не покрывают всю процедуру.')
                     + '</p><small>Пункты перечня: ' + numbers + '</small></article>')
    return ('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Методика проверки</title>'
            '<style>body{font:17px/1.6 system-ui;max-width:960px;margin:40px auto;padding:0 24px;color:#222}'
            'article{border-top:1px solid #ddd;padding:20px 0}h2{font-size:21px}small{color:#555}</style>'
            '<a href="/">Вернуться к анализу</a><h1>Что означает результат</h1>'
            '<p>«violation» означает обнаруженные признаки возможного нарушения по визуальным правилам проекта. '
            'Это подсказка проверяющему, а не юридическое заключение. Связанный норматив не доказывает его '
            'применимость к конкретному видео. Часть признаков основана на чек-листе проекта и требует '
            'согласования с заказчиком.</p><p>«no_violation» означает, что поддерживаемые признаки не обнаружены. '
            'Неопределённость не считается отсутствием нарушения.</p><p>Версия: '
            + escape(RULES_VERSION) + '</p>' + ''.join(cards)
            + '<article><h2>Возврат купюр после проверки — пункт 3</h2>'
            '<p>Распознаётся как наблюдение. Причина возврата неизвестна; сам по себе возврат не создаёт '
            'положительный вердикт. Обычная операция не должна автоматически становиться тревогой.</p></article></html>')
