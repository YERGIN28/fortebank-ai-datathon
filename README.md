# ForteBank AI Datathon

Локальная интеграционная сборка на ветке `backend`: FastAPI, существующий web UI,
актуальный inference и Rule Engine команды.

**Готов демонстрационный режим. Финальные AI-вердикты пока не готовы:** текущий
Rule Engine возвращает `needs_review`. В реальном режиме backend честно завершает
такое задание как `failed`, не подменяя его на `no_violation` или тестовое нарушение.

## Быстрый запуск демонстрации

Из корня проекта, Python 3.11 или 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Только если своего .env ещё нет:
Copy-Item .env.example .env
# Указать собственный API_KEY в .env.
.\.venv\Scripts\python.exe start_backend.py --mode fake
```

UI: http://127.0.0.1:8000/ ; Swagger: http://127.0.0.1:8000/docs .
`fake` сохраняет исходный Test violation и паузу 20 секунд. В UI есть подпись,
что это демонстрация. Ключ хранится только на сервере и в клиенте из `.env`.
Архив сборки не содержит `.env`, весов, видео и виртуальных окружений.
В локальной рабочей папке `.env` и тестовые видео сохранены из исходного архива.

Альтернативная команда:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Не использовать несколько Uvicorn workers. Блокировка в `uploads/.worker.lock`
не допускает второй worker для этой же папки проекта; она не координирует разные
копии проекта на одном GPU. Задания и их метаданные хранятся в памяти и теряются
при перезапуске. При штатном завершении сервер дожидается принятых заданий.

## Реальный AI, для проверки интеграции

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
# В .env указать MODEL_PATH — свою локальную папку Qwen3-VL-2B-Instruct.
.\.venv\Scripts\python.exe start_backend.py --mode real
```

В `requirements-ai.txt` сохранены версии команды для CUDA 12.1 и ограничение
`huggingface-hub>=0.34.0,<1.0`. Backend использует NumPy 1.26.4 и OpenCV 4.11,
чтобы устранить конфликт с зависимостями inference.

`InferenceEngine` создаётся и загружается один раз в единственном worker, до
приёма запросов. При ошибке модели сервер не проходит startup. Во время job
`partial`, `timeout`, исключение CUDA/модели/правил дают `failed`.

Для `complete` вызывается **существующий** интерфейс команды:
`evaluation.run_rules.process_video` через `backend/services/rules_adapter.py`.
Его нынешний `needs_review` даёт `failed` с объяснением. Ни candidates, ни unknown
не объявляются подтверждённым нарушением. После согласования финального интерфейса
нужно доработать этот адаптер; нормативные правила здесь не придуманы.

## API

- `POST /api/v1/analyze`: multipart, поле `file`, `.mov`, заголовок `X-API-Key`.
  Ответ: `{"job_id": "..."}`.
- `GET /api/v1/jobs/{job_id}`: тот же заголовок. `processing`, затем `done` с
  `verdict` и `violations` либо `failed` с `error`.
- Отсутствующий/неверный ключ: `401`; неподходящее расширение/пустой файл: `400`;
  неизвестное задание: `404`; битый MOV: принятое задание затем `failed`.
- `/ui/analyze`, `/ui/jobs/{job_id}` и `/` скрыты из Swagger. UI предназначен для
  локального использования; публичный доступ не настраивался.

Внутренние `created_at`, `started_at`, `finished_at`, `processing_time_sec`
находятся в `backend.main.job_lifecycle` и не добавляются в API.
Загруженные видео удаляются после обработки. Ошибка удаления записывается в лог
и метаданные, не останавливая worker; оставшийся файл тогда надо удалить вручную.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest tests app/rules evaluation/test_rules.py evaluation/test_run_rules.py app/inference -q
# В другом терминале, пока fake-сервер запущен, с локальным X-1.mov:
.\.venv\Scripts\python.exe test_client.py
```

Клиент читает `API_KEY` из `.env`. При необходимости можно задать окружением
`API_URL` и `VIDEO_PATH`. Без видео из исходного архива синтетические тесты работают;
для `test_client.py` укажите собственный MOV.

Проверки inference в этой команде синтетические, без загрузки Qwen. Они не
подтверждают качество распознавания или скорость работы на GPU. Подробности
сборки и оставшаяся задача команды: `HANDOFF.md`.
