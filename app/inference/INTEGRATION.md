# Inference → Rule Engine → backend

## Наблюдения для Айши

Поля согласованного предварительного формата:
`type`, `start_sec`, `end_sec`, `description`, `evidence_timestamps_sec`,
`timing_resolution_sec`, `refined`, `confidence`, `actors`.

Пока `type`: `cash_left_unattended` или `unknown`. Полную таксономию согласуем
после исследования правил. Прочие кассовые действия временно получают `unknown`.
Rule Engine должен явно обрабатывать unknown как неклассифицированное наблюдение,
а не выбирать для него случайное правило. `confidence` всегда null до появления
проверенной калибровки. Роли: cashier / customer / unknown, без распознавания личности.

`refined` означает повторную локализацию, не подтверждение нарушения. Сами
наблюдения не учитывают нормативные исключения и не заменяют check_events().

## Точный config для текущего ноутбука

```python
from pathlib import Path
from app.inference import InferenceConfig, InferenceEngine

config = InferenceConfig(
    model_path=Path(r'C:\Users\Айсана\Documents\Codex\fortebank-local\models\Qwen3-VL-2B-Instruct'),
    window_seconds=8.0,
    overlap_seconds=2.0,
    frames_per_window=4,
    max_frame_side=448,
    max_new_tokens=256,
    time_budget_seconds=300.0,
    refine=False,
    refinement_frames=6,
)

# Выполняется ВНУТРИ единственного worker-процесса при его старте.
engine = InferenceEngine(config)
engine.load()

def process_video(job_id, file_path):
    result = engine.analyze_video(file_path)
    return result.to_dict()
```

`job_id` здесь показан для контекста интеграции, inference его не использует.
Это пример вызова, не реализация backend/очереди. На другом компьютере заменить
model_path локальной папкой весов. engine нельзя создавать внутри process_video().
engine.load() идемпотентен при последовательном вызове; CUDA и модель проверяются
до принятия заданий. При ошибке старта worker не должен считаться готовым.

`refine=False` — начальная интеграционная настройка: замеры GPU выполнены для
грубого прохода. Уточнение реализовано, но его качество на кассовых сценах и
добавочную стоимость ещё нужно проверить; затем можно включить refine=True.

Рабочий Python на этом ноутбуке:
`C:\Users\Айсана\Documents\Codex\fortebank-local\.venv\Scripts\python.exe`.
Не системный Python 3.14. Зависимости перечислены в requirements.txt.

## Политика статусов для Ерасыла

| Внутреннее состояние | Предлагаемый статус API жюри | Значение |
| --- | --- | --- |
| Очередь / выполняется | processing | Финального результата ещё нет |
| complete и успешно отработал Rule Engine | done | Полный проход, итог определяется правилами |
| partial | failed | Есть пропущенные/невалидные окна |
| timeout | failed | Не завершён весь запланированный анализ |
| Исключение открытия / загрузки / CUDA / правил | failed | Ошибка выполнения |

partial сохраняет структурно валидные наблюдения успешно обработанных окон.
Их можно сохранить для диагностики или предварительно передать правилам,
обязательно сохраняя признак неполноты. Это не годится для окончательного
no_violation. Для публичного API рекомендуем failed, а не done. Решение mapping
реализует Ерасыл в backend, здесь код чужого модуля не меняется.

complete с observations=[] означает отсутствие найденных AI наблюдений;
окончательный вердикт и обработку unknown определяет Rule Engine.

## Полные result.to_dict()

```powershell
python -B -m app.inference.integration_examples --output-dir C:\local\synthetic_contract_examples
```

Команда генерирует result_complete.json, result_partial.json, result_timeout.json.
Все поля верхнего уровня присутствуют. Это явно маркированные mock-примеры:
временный MOV состоит из фигур, модель подменена, вымышленные события заданы
программно. Они не являются результатами распознавания кассовых действий Qwen.
partial и timeout в примерах намеренно сохраняют уже полученные наблюдения.
Исторические JSON предыдущих этапов могут не содержать новых полей; использовать
нужно свежие result_*.json, созданные этой командой.

300 секунд — кооперативный лимит inference, без очереди и времени Rule Engine.
Backend должен учитывать общий срок задания, очередь и внешний жёсткий дедлайн.
