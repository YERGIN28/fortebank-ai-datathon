# AI 2026.10.18.4: расширение визуальных наблюдений

Изменены только `app/inference`. Новая версия после настройки; качество на
реальных или отложенных видео ещё не измерено. Идентификаторы, таймкоды из
разметки и описания реальных событий не используются в коде/промпте.

## Контракт для Rule Engine

Публичные поля наблюдения прежние. Добавлены значения `type` и соответствующие
ключи `condition_checks`:

| type | Обязательные визуальные условия |
|---|---|
| workstation_left_with_screen_on | cashier_left_workplace, screen_on_after_departure |
| safe_left_open | cashier_left_workplace, safe_open_after_departure |
| cash_on_desk_with_next_customer | banknotes_on_work_surface, different_customer_approaches, banknotes_remain_during_approach |
| documents_left_unattended | cashier_left_workplace, documents_remain_after_departure |
| customer_leaves_during_cash_check | customer_left_counter, visible_cash_check_continues |
| cash_counting_without_customer | cash_is_identified, direct_customer_cash_receipt, cashier_counts_received_cash, customer_zone_fully_visible, customer_absent_during_counting |
| previous_cash_outside_storage | cash_is_identified, previous_receipt_completed, previous_cash_continuously_tracked, current_customer_receipt_in_progress, previous_cash_remains_outside_storage |
| key_left_in_safe_lock | cashier_left_workplace, key_in_safe_lock_after_departure |
| entrance_door_left_open | operator_enters_room, entrance_remains_open_after_entry |
| personal_items_on_work_surface | operator_starts_work, personal_bag_or_clothing_on_work_surface |
| cash_container_left_on_work_surface | cash_removed_from_container, same_container_remains_on_work_surface |
| customers_overlap_at_counter | previous_customer_still_at_counter, different_customer_starts_document_presentation |

Каждое условие имеет прежний формат:

```json
{"state":"observed","evidence_timestamps_sec":[1.0,3.0]}
```

Это искусственные секунды. Возможны `observed`, `refuted`, `unclear`.
Уход требует двух разных кадров; оставленный предмет/экран — подтверждения
после ухода. Для денег при подходе нового клиента проверяется пересечение
кадров доказательств. Одно фото, открытая крышка, предполагаемая личность,
конец смены или отсутствие проверки вне видимого контекста не подставляются
как факты. Включённый экран здесь не означает распознанные личные данные
или установленное состояние блокировки.

Категория сама по себе не подтверждает нарушение. Пустые/unclear проверки
нельзя считать подтверждёнными. Подтверждение всех визуальных условий также
не заменяет нормативное основание и исключения, которыми владеет Rule Engine.
Причина возврата купюр и необходимость конкретной банковской процедуры по
одному изображению не определяются.

## Поведение inference

* Контекст проверяется независимо от свободного описания кандидата.
* Явно опровергнутый кандидат удаляется; отдельный технический счётчик
  `service_context_refuted` показывает количество. Это новая настройка,
  требующая последующей проверки пропусков на отложенной выборке.
* Unclear/недоступная проверка сохраняет кандидата, без ложного уверенного
  вывода. Общий лимит контекста прежний: максимум 3 проверки на видео,
  по 10 секунд, в общем бюджете. Превышение лимита явно отмечается.
* Старая категория `cashier_leaves_during_service` и публичный метод
  `check_service_context(frames, deadline)` совместимы с backend.
* Новый метод `check_conditions(frames, action, deadline)` не требует
  повторного вызова из backend: AI уже сохраняет проверки в наблюдении.
* Default `check_relevance=False` сохранён. Других моделей, весов или
  дополнительных зависимостей не требуется.

## Необходимая интеграция у владельца правил

Новые правила Айши 4a21208 уже знают cash_counting_without_customer и
previous_cash_outside_storage: их имена и условия здесь совпадают точно.
При редком сэмплировании previous_cash_continuously_tracked принудительно
остаётся unclear: непрерывного трекера нет. inference_supported=False в её
каталоге нельзя менять на True только по наличию схемы/искусственных тестов.

Остальные новые типы пока отсутствуют в проверенном каталоге. До явного
сопоставления они закономерно вернут unresolved/failed. Нельзя заменять
это на no_violation или переименовывать все категории в правило ухода
во время обслуживания.

Нужно сохранить новые типы в classifier, проверить перечисленные условия
и нормативные основания в decision, затем проверить синтетические пути:
все условия observed / одно unclear / одно отсутствует / технический timeout.
Не добавлять эти кандидаты в нейтральный ACTION_CATALOG: текущий decision
пропускает его типы без проверки. Нужны отдельные правила в RULE_CATALOG
с проверенным основанием; поле verified нельзя включать автоматически.
Backend сохраняет condition_checks без повторной загрузки модели и без
нового контекстного прохода для этих типов.

Схема и текущие тесты проверяют реализацию. Они не доказывают распознавание
событий на новых ракурсах. Для этого необходим локальный отдельный прогон
отложенных видео и оценка, не попадающие в облачный контекст.
