# Сквозная проверка на искусственном MOV

## Что уже проверено и что требуется

Проверка Qwen и тесты inference выполняются отдельно от backend.
В доступном локальном снимке origin/backend обработчик process_video ещё
возвращает Test violation после sleep(20), без вызова модели и правил.
Это снимок remote-tracking ref, не проверка свежего состояния GitHub.
В снимке origin/feat/rules-evaluation функция evaluation.run_rules.process_video
принимает словарь video_id/status/observations и возвращает verdict/violations/candidates.
Сейчас она всегда выдаёт needs_review: нормативные условия ещё не реализованы.

Ерасыл собирает совместимую версию backend + app/inference + rules + evaluation.
Рабочую ветку Айсаны не переключать. Копировать venv из другой ветки не нужно.
Пример подключения в его обработчике (изменения в backend делает Ерасыл):

```python
from evaluation.run_rules import process_video as apply_rules
from app.inference import InferenceConfig, InferenceEngine

# Внутри единственного worker, перед очередью:
engine = InferenceEngine(InferenceConfig(model_path=LOCAL_MODEL_PATH))
engine.load()

# В обработчике одного задания:
result = engine.analyze_video(file_path)
if result.status != 'complete':
    jobs[job_id] = {'job_id': job_id, 'status': 'failed',
                    'error': 'incomplete_inference'}
else:
    ruled = apply_rules({'video_id': job_id, **result.to_dict()})
    jobs[job_id] = {'job_id': job_id, 'status': 'done',
                    'verdict': ruled['verdict'],
                    'violations': ruled['violations'],
                    'candidates': ruled.get('candidates', [])}
```

LOCAL_MODEL_PATH — локальная Path папки Qwen. Исключения обрабатывает backend.
Шаблоны и финальный HTTP формат остаются ответственностью Ерасыла.
needs_review не превращать в подтверждённое violation или no_violation.

## Проверка существующего сервиса

Запустить backend одним worker без reload по инструкции Ерасыла, дождаться
загрузки Qwen. Для GPU запускать на штатном зарядном устройстве. Одновременно
не запускать run-batch и второй экземпляр Qwen.

В терминале той же собранной папки, используя подготовленный Python:

```powershell
# API_KEY должен быть задан локально тем же значением, что у сервера.
# Не присылайте ключ в чат.
& $inferencePython -B -m app.inference.smoke_http --base-url http://127.0.0.1:8000
```

Команда сама создаёт четырёхсекундный MOV с фигурами. Реальные файлы она
не принимает. Проверяет HTML корневой страницы, загрузку через /api/v1/analyze,
опрос /api/v1/jobs/{job_id}, статус и формат вердикта. Запрещены внешние URL
и перенаправления. Результат — только техническая сводка. Заведомое нарушение
на фигурах считается провалом отрицательного контроля.

Это проверка HTTP-контракта. Она не доказывает вызов Qwen/правил: это подтверждается
кодом собранного worker. Отдельно открыть http://127.0.0.1:8000 в браузере,
загрузить искусственный MOV и проверить отображение processing → done/failed.
Сам HTTP-пробник проверяет доставку HTML, но не интерактивный интерфейс.

Полный сквозной запуск здесь пока не выполнен: в ветке ai нет собранного backend.
