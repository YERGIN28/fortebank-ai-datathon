# Правила для AI 2026.10.18.4

Принято исправление rules-ai4.1 в `feat/rules-evaluation` поверх `0af7901`.
Обязательны temporal_policy и совместные точки доказательств: см.
[передачу AI4.1](RULES_AI4_1_HANDOFF.md) и [покрытие/недостающие поля](../RULES_CAPABILITIES.json).
Повторная локальная проверка: 194 теста, 406 подтестов, 0 skipped.
Ниже сохранено описание первоначальной передачи; его число 180 относится
к предыдущей версии. Отчёты исходного архива находятся в `docs/ai4.1_source`.

База изменений: правила `4a21208`, ветка `feat/rules-evaluation`.
AI4 прочитан из предоставленного source-only ZIP; файлы inference не изменены,
не включены в этот коммит и не опубликованы от имени Айсаны.
Проверены SHA-256 всех 34 файлов из PACKAGE_MANIFEST.json.
SHA-256 архива AI4:
`0d32d20f190f455e09e05435d992fdb429fd0815254bdb7e22b32f26c4f9b533`.

## Подключение в backend Ерасыла

Взять текущий commit этой ветки поверх согласованной сборки backend + AI4.
Изменены только правила, evaluation, искусственные fixtures и документация.
Сохранить наблюдения AI4 и передать их непосредственно в финальный адаптер:

```python
result = engine.analyze_video(file_path).to_dict()
response = build_job_result(job_id, result, extract_frame)
```

Модель загружается один раз при старте worker. Новый контекстный вызов из
backend не нужен: AI4 уже содержит condition_checks. Старые внешние
`enrich_service_context` и безусловное переименование cash_left_unattended
в cashier_leaves_during_service не применять. Пакет правил здесь сам ничего
не переименовывает и не вызывает модель. Backend, конфигурация inference и
публичный доступ остаются у Ерасыла; GPU-прогон — у Айсаны.

Новые типы сохранены в RULE_CATALOG, с приоритетом над нейтральным каталогом.
В ACTION_CATALOG кандидаты не добавлены. Подтверждение использует исходный
type и condition_checks, не ключевые слова description и не метки Excel.
Исходные словари не изменяются. Диагностический check_events сохраняет
condition_checks, режим и причину ручной проверки; API не выдаёт candidates.

## Финальные кассовые правила

| Тип | Основание | Возможность окончательного положительного решения |
|---|---|---|
| cashier_leaves_during_service | № 231, п. 22 | Да, если оба условия observed с доказательствами |
| cash_counting_without_customer | № 231, п. 20, абзац 1 | Да, если все пять условий observed с доказательствами |
| previous_cash_outside_storage | № 231, п. 20, абзац 2 | Логика есть, но AI4 принудительно оставляет previous_cash_continuously_tracked=unclear; реальное автоматическое подтверждение пока заблокировано |
| cash_processing_without_controller | № 231, п. 42 | review_only: область операции и назначенная роль не устанавливаются по внешности |

Названия условий двух правил совпадают с AI4 точно. inference_supported=False
в исходном каталоге 4a21208 сохранён: наличие контракта не доказывает точность.
Три узких правила выражают исключения через обязательную область применимости
(например, именно прямой приём денег). Новые нормативные исключения не выдуманы.
Общий механизм исключений проверен на синтетическом условии отдельно от норм.

## Десять новых записей для проверки

Все записи имеют собственные conditions, scope_conditions, exceptions,
time_condition и review_reason в `app/rules/ai4_catalog.py`.
У всех `decision_mode=review_only`, `verified=False`: общая ссылка или видимый
факт не заменяет проверенную применимость нормы.

| Тип | Дополнительная область/основание, которого пока нет |
|---|---|
| workstation_left_with_screen_on | Состояние сессии и возможность несанкционированного доступа; свет экрана не доказывает их |
| safe_left_open | Содержимое и режим хранения, допустимость текущего доступа; п. 20 — только направление проверки |
| key_left_in_safe_lock | Режим хранения ключа и доступ посторонних; п. 80 отсылает к порядку банка |
| documents_left_unattended | Категория документов, требуемое хранение и доступ; содержимое не читается |
| cash_on_desk_with_next_customer | Происхождение денег и этапы операций; не является синонимом предыдущих денег вне хранения |
| customer_leaves_during_cash_check | Прямой приём, именно пересчёт, полная видимость и отсутствие клиента; отход не равен отсутствию |
| customers_overlap_at_counter | Проверенное требование последовательного обслуживания и исключения совместного обслуживания |
| entrance_door_left_open | Назначение двери, нарушение требуемой изоляции и контролируемый проход; п. 8 № 20075 не является запретом любого открытия |
| personal_items_on_work_surface | Проверенная обязанность освободить поверхность и допустимое временное размещение |
| cash_container_left_on_work_surface | Проверенная обязанность убрать контейнер и завершение его разрешённого использования |

related_regulations — направления дальнейшей сверки, не подтверждённые
основания автоматического вердикта. Визуальное опровержение обязательного факта
или observed-исключение отклоняет именно этот кандидат. Все визуальные факты
observed при непроверенном основании всё равно оставляют ручную проверку.
Неполная видимость/отслеживание дают неопределённость, а не отрицательное решение.
Подтверждённое другое событие не теряется из-за такого кандидата.

## Оценка

`python -B -m evaluation.run_rules predictions.json --output rule_predictions.json`

В этом диагностическом файле статус финального решения нормализуется в
`complete` для AI4 evaluate_baseline. В публичном build_job_result остаётся
`done`. failed сохраняется без verdict. Неподтверждённые случаи не становятся
no_violation. Диагностические candidates не являются нарушениями для evaluator.

```powershell
python -B -m app.inference.evaluate_baseline --truth labels_normalized.json --predictions rule_predictions.json --report evaluation_summary.json --tolerance-sec 2
```

Используется разметка «метка + момент», не строгие type/start/end. Отчёт
показывает coverage/decision_fraction, пропуски, ложные тревоги и ошибку времени
на принятых решениях. Известные дубли/неоднозначные группы обрабатываются
отдельно существующим evaluator AI4; его политика не переписывалась.
Источники разметки и локальные реальные predictions в этот пакет не включены.

## Проверки

`python -B -m evaluation.check_rules`

При наличии точного исходного AI4 в общей сборке:
`python -B -m evaluation.check_rules --with-inference`.

В локальной изолированной CPU-проверке: 180 тестов, 403 подтеста, 0 skipped.
Проверены все 12 контрактных типов, три кассовых правила, required/scoped
условия, observed/unclear/refuted, пропущенные условия и timestamps, исключения,
видимость, time_condition, нейтральные действия и положительное событие рядом
с unresolved. Изменённый CLI проверен настоящим evaluator из неизменённого AI4,
публичный адаптер — dataclass AI4 и JPEG из искусственного fixture.

Это проверка кода/контрактов на искусственных данных. Вызов настоящей Qwen,
качество на банковских видео, VRAM и общий лимит 300 секунд здесь не измерялись.
Правило хранения остаётся ограничено отсутствующим непрерывным трекером.

## Покрытие общего перечня

Номера относятся к общему перечню сценариев, не к видео или их меткам.

| № | Типы/граница покрытия |
|---|---|
| 1 | document_handling/document_transfer нейтральны; полная процедура ID не установлена |
| 2 | cash_on_desk_with_next_customer review; previous_cash_outside_storage ограничен трекером |
| 3 | cash_transfer нейтрален; причина передачи не определяется |
| 4 | key_left_in_safe_lock, workstation_left_with_screen_on, safe_left_open — отдельные review |
| 5 | cash_handling нейтрален; всей процедуры определения подлинности нет |
| 6 | cash_container_left_on_work_surface — review |
| 7 | customer_leaves_during_cash_check — review; cash_counting_without_customer — условное правило |
| 8 | customers_overlap_at_counter — review |
| 9 | cash_drawer_opened нейтрален; safe_left_open — review |
| 10 | workstation_left_with_screen_on и key_left_in_safe_lock — review |
| 11 | documents_left_unattended — review; отдельное различение печати не реализовано |
| 12 | cash_left_unattended — кандидат; не переименовывается в уход при обслуживании |
| 13 | workstation_left_with_screen_on — review, состояние сессии не установлено |
| 14 | entrance_door_left_open — review |
| 15 | customer_leaves_during_cash_check — review; cash_counting_without_customer — условное правило |
| 16 | те же два типа хранения, что № 2 |
| 17 | cash_handling нейтрален; cash_left_unattended требует отдельного основания |
| 18 | previous_cash_outside_storage требует полного контекста и трекера |
| 19 | personal_items_on_work_surface — review |
| 20 | несколько независимых типов; ID-процедура и непрерывное отслеживание не подтверждены |
