# 06. Polling, ETW/Census и производительность Scanner

## Режим работы

Это независимое исследование для отдельного диалога в проекте **Aluiel_MCP**. Через MCP самостоятельно читай Windows-файлы, Git и сохранённые логи. Используй зарегистрированный проект и инструменты `workspace_read`, `git_status` или `shell_run` (PowerShell). Промпты, отчёты и captures находятся в проекте `bonkscanner`. Для исходников выбери соответствующий проект из `project_list`. Локальный Codex для выполнения задачи не нужен.

**Приоритет — исследование и анализ существующих материалов.** Прочитай инструкции затронутых репозиториев, проверь HEAD и рабочее дерево. В индексированном репозитории начни поиск кода с CodeGraph. Можно читать и фильтровать существующие JSONL/JSON/CSV без записи новых данных. Не запускай тесты и replay, Scanner, Validator, GameLab, ETW или сервер, не взаимодействуй с текущей игровой сессией и не меняй системное состояние. В этом диалоге разрешена запись только одного файла, `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/06_REPORT.md`. Код, тесты, captures, настройки и Git оставь как есть. Если источники недоступны, укажи конкретный путь и влияние на вывод.

По границам согласованной функциональности сверяйся с `F:/Python/BonkScanner/docs/updates/functional_updates.md`. Если предлагаешь значимое изменение защиты, кратко обоснуй угрозу, текущее покрытие, независимую пользу, стоимость и доверие к клиенту. Новые сенсоры и обязательные зависимости требуют отдельного решения.

## Задача

P1. Локализуй по существующим данным эпизодические длинные интервалы опроса, вклад Scanner в CPU, состояние сенсоров и пробелы в ресурсной приёмке. Подготовь план измерений с минимальным вмешательством.

## Откуда начать

- Validator `F:/Python/BonkScanner_validator`, проект `bonkscanner_validator`. В каталоге `src/bonkscanner_validator` исследуй `engine.py` (`poll/next_poll_delay/_census_period/_poll_access`), `process_access.py`, `direct_open.py`, `direct_open_evidence.py`, `image_events.py`, `collectors.py`, `worker.py` и `startup_trace.py`. Начни с тестов `tests/test_process_access.py`, `test_image_events.py`, `test_direct_open_stop.py`, `test_validator_collectors.py` и `test_coverage_diagnostics.py`.
- Scanner `F:/Python/BonkScanner`, проект `bonkscanner`. Через CodeGraph пройди `src/gui_scanner.py`, `src/app/run_lifecycle.py`, `src/app/refresh_coordinator.py`, GUI/статистику/запись и адаптеры чтения памяти. Различай Scanner PID, повышенный worker и игру. В коде ориентир сенсора ~100 мс, healthy Census ~10 с, fallback Census ~100 мс при активном наблюдении и ~10 с в фоне. Проверь реальную семантику этих интервалов.
- `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md` и JSONL показывают C01 ~576, C05 ~683, C14 ~639, C15 cleanup ~636 мс. `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-091510-f305cc/QA_HEAVY_FINAL_2026-11-17.md` и `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/FINAL_REAL_STAGE_REVIEW_2026-11-17.md` дают поздние сценарии без >500 мс. В полном просмотре 6909 опросов, p99 ~217 мс, максимум ~454 мс. В отрезке реальной финализации ~1,54 с было 12 свежих опросов.
- `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-084736-6cb590/wave-perf-heavy-20261117-090438/HEAVY_WAVE_ANALYSIS.md` и его `heavy_wave_analysis.json`, A4/B4/B5/A5 и telemetry показывают порядок 36–42% *одного логического ядра* для Scanner и прирост порядка 7,3–7,6 п.п. одного ядра для Scanner + worker между OFF и ON. Разные волны не дают причинного FPS-эффекта. Прежнюю OFF/ON FPS-серию повторять не требуется.

## Что выяснить

1. По имеющимся трассам сделай краткую таблицу gap >500 мс и параллельных событий. Проверь разницу между свежим sample, cached input, ожиданием планировщика, длительностью чтения, синхронной частью ETW, применением Census/env/hash результатов, IPC, диагностикой и фоновой финализацией. Совпадение по времени укажи как корреляцию; вывод о причине привязывай к конкретному интервалу или call path.
2. Проверь границы ETW Direct-Open, ImageLoad/ImageUnload и Census при штатном старте, loss/drop/stop, fallback, смене рана и прекращении наблюдения. Отдельно сверяй поддержку loader/DLL/environment и key file integrity. Покажи, что существующее тестами покрыто, что только видно в сохранённом native trace и где требуется отдельное подтверждение timestamp, session ownership, loss/gap или unload. Первый healthy marker не доказывает полное покрытие.
3. По коду перечисли обоснованные кандидаты CPU и краткую схему будущего CPU-профилирования по потокам и функциям в idle/menu/active, OFF и ON, с трассировкой и без неё. Сохрани точность и свежесть данных. Для длинного прогона 20–30 минут с прогревом и Stop предложи сбор private bytes/working set, handles, threads, ETW sessions, IPC/transport очередей, finalizers, частоты env/hash и polling percentiles. Отдели удерживаемые кэши от невозвращаемых ресурсов.
4. Для будущей приёмки укажи проверки cadence и отсутствия необъяснимых пауз без требования hard-real-time; ETW/census/image/env/files с явными gaps при деградации; раздельные CPU/ресурсы и возврат после Stop. Отметь стыки с 04 (shutdown/queue), 05 (свежесть границ) и 07 (доставка coverage). Оптимизацию предлагай после идентификации затрат и оценки потерь наблюдения.

## Отчёт

Сохрани один отчёт на английском в `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/06_REPORT.md`. Подтверди, что файл читается из проекта `bonkscanner`, и верни в чат его путь и 2–3 ключевых вывода. В отчёте укажи:

- Какие ревизии, участки кода и сохранённые данные просмотрены. Для наблюдений приведи путь и строку либо номер события/время.
- Что подтверждено, что объясняется штатным ограничением и какие гипотезы остаются открытыми. Отдельно отметь данные, которых нет в записи.
- Минимальные предлагаемые изменения, если они нужны, с функциями, зависимостями и инвариантами. Если причина пока не установлена, укажи минимальную диагностику для её проверки.
- Отложенные проверки для интегратора. Для каждой дай цель, входные условия, ожидаемое наблюдение и критерий провала. Пометь, нужен ли Windows, UAC, игра или сервер. Результаты прежней проверки привязывай к её ревизиям и условиям, а отложенную проверку помечай `NOT TESTED`.
