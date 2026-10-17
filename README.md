# ForteBank: интеграция backend, AI и правил

Ветка сборки: backend. AI: 2026.10.18.3 (52883e6), правила: dcc124c.
По умолчанию выполняется настоящий локальный inference, а затем финальный адаптер
app.rules.decision.build_job_result. Заглушка доступна только через --mode fake.

## Запуск в терминале VS Code

```powershell
.\.venv\Scripts\python.exe start_backend.py --mode real
```

Дождаться загрузки модели и строки Application startup complete.
Открыть http://127.0.0.1:8000/ и загрузить MOV. Swagger: /docs.
Остановка: Ctrl+C; сервер завершает уже принятые задания перед выходом.
В VS Code также есть задача «ForteBank: real server» (Terminal → Run Task).
Запускать один экземпляр сервера. Ключ из .env в JavaScript не передаётся.

Финальный GPU-хост для приёмки — ноутбук Айсаны (RTX 4050). Перед проверкой
остановить прежний сервер, получить согласованный коммит backend и проверить
`git rev-parse HEAD`. Активировать рабочее AI-окружение этого ноутбука,
указать в локальном .env его MODEL_PATH и свой API_KEY, затем выполнить
`python start_backend.py --mode real`. В терминале должна появиться строка
`Inference loaded: 2026.10.18.3`. Старый запущенный worker сам не обновляется.
Время RTX 3050 не является оценкой времени или приёмкой на RTX 4050.

## Окружение

Локальный .venv подготовлен отдельно от старого venv. Если окружение нужно создать заново:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt -r requirements-test.txt
```

В уже рабочем AI-окружении НЕ устанавливать весь requirements.txt. Добавить
только web-компоненты, сохранив проверенные CUDA/AI-версии:

```powershell
python -m pip install -r requirements-web.txt -c constraints-ai.txt
python -m pip check
```

Здесь `python` должен быть интерпретатором нужного AI-окружения. При конфликте
ограничений установка должна остановиться; не удаляйте ограничения ради обновления.

API_KEY и MODEL_PATH читаются из .env. Не отправляйте .env в Git.
Используются версии inference-команды: torch 2.5.1+cu121, transformers 4.57.6,
NumPy 1.26.4, huggingface-hub>=0.34.0,<1.0. refine=False.

## Что делает сборка

Один worker загружает engine один раз, затем последовательно обрабатывает задания.
complete передаётся в правила; partial/timeout/исключения дают failed.
Для кандидатов cash_left_unattended выполняется дополнительная проверка контекста
в backend/services/service_context.py через публичный
`engine.model.check_service_context(frames, deadline)` из AI 2026.10.18.3.
Кандидаты cashier_leaves_during_service уже получают condition_checks внутри AI;
backend передаёт эти проверки правилам без повторного контекстного вызова.
Эксперимент check_relevance=False, refine=False; базовый бюджет — 300 секунд.
Условия не выводятся из одного названия события: нужен отдельный ответ модели.
Финальные нарушения и 1–3 JPEG формирует адаптер команды правил.
Нерешённые события дают failed; это не подменяется отрицательным вердиктом.

API жюри сохранён: POST /api/v1/analyze и GET /api/v1/jobs/{job_id}, X-API-Key.
UI endpoints скрыты из Swagger. Технические timestamps хранятся только внутри.
Файлы удаляются после обработки; jobs хранятся в памяти. Публичного tunnel нет.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# Пока запущен real-сервер, отрицательный контроль с искусственными фигурами:
.\.venv\Scripts\python.exe -m app.inference.smoke_http --base-url http://127.0.0.1:8000
# Проверка исходного клиента на X-1.mov:
.\.venv\Scripts\python.exe test_client.py
```

Реальное видео может завершиться failed из-за лимита 300 с или недостатка контекста.
Это не означает, что нарушение отсутствует. Тесты с подставной моделью проверяют
интеграцию, но не точность Qwen. Подробности фактических проверок: TEST_RESULTS.md.
После inference журнал выводит `Inference metrics:`: число обработанных окон,
время decode/relevance/observe/verify_object/service_context и память PyTorch.
Это метрики самого inference; отдельный контекстный проход backend и правила
в эти счётчики не входят. Кадры, ответы модели и пути видео в эту запись не попадают.
