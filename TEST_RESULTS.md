# Проверка сборки в папке VS Code

Дата: 18 октября 2026. Папка: C:\Users\Erassul\Desktop\fortebank-ai-datathon.
Локальная ветка backend, изменения на GitHub не отправлялись.

## Среда

Создан отдельный .venv (Python 3.12.14); исходный venv не менялся.
Проверенные импорты: torch 2.5.1+cu121, CUDA=True, NumPy 1.26.4,
OpenCV 4.11.0, FastAPI 0.143.3. pip check: No broken requirements found.
Web overlay requirements-web.txt с constraints-ai.txt проверен через dry-run:
изменения установленного AI-стека не требуются.

## Автоматические проверки

В новом .venv: 174 passed, 82 subtests passed.
Один предупреждающий сигнал Starlette о будущем переходе httpx→httpx2.

Проверены авторизация, безопасные загрузки, API/UI-маршруты, Swagger,
последовательная очередь, однократная загрузка движка, ошибки и очистка,
настоящие JPEG из тестового MOV, оба финальных вердикта правил, неизвестные
события, проверка контекста, тесты текущих ai и feat/rules-evaluation.
Тесты подставной модели сами по себе не измеряют точность Qwen.

## Реальная проверка

Qwen загрузился на CUDA, сервер прошёл startup и отдаёт HTML интерфейса.
HTTP-пробник автора AI на искусственном четырёхсекундном MOV прошёл успешно.
Результат: done / no_violation, violations=[], negative_control_passed=True. Время 225.619 с. HTML интерфейса, загрузка MOV и polling проверены. Интерактивный браузерный сценарий отдельно не проверялся. Это отрицательный контроль на фигурах, а не измерение точности на банковских видео.

## Происхождение

app/inference совпадает с origin/ai (3092f9e).
app/rules и evaluation совпадают с origin/feat/rules-evaluation (dcc124c).
Контекстный проход из eeea756 размещён в backend/services/service_context.py;
файлы inference не редактировались. Публичный результат выдаёт build_job_result.
