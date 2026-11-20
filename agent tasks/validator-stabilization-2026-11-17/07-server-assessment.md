# 07. Transport, сервер, assessment v4 и отчёты

## Режим работы

Это независимое исследование для отдельного диалога в проекте **Aluiel_MCP**. Через MCP самостоятельно читай Windows-файлы, Git и сохранённые логи. Используй зарегистрированный проект и инструменты `workspace_read`, `git_status` или `shell_run` (PowerShell). Промпты, отчёты и captures находятся в проекте `bonkscanner`. Для исходников выбери соответствующий проект из `project_list`. Локальный Codex для выполнения задачи не нужен.

**Приоритет — исследование и анализ существующих материалов.** Прочитай инструкции затронутых репозиториев, проверь HEAD и рабочее дерево. В индексированном репозитории начни поиск кода с CodeGraph. Можно читать и фильтровать существующие JSONL/JSON/CSV без записи новых данных. Не запускай тесты и replay, Scanner, Validator, GameLab, ETW или сервер, не взаимодействуй с текущей игровой сессией и не меняй системное состояние. В этом диалоге разрешена запись только одного файла, `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/07_REPORT.md`. Код, тесты, captures, настройки и Git оставь как есть. Если источники недоступны, укажи конкретный путь и влияние на вывод.

По границам согласованной функциональности сверяйся с `F:/Python/BonkScanner/docs/updates/functional_updates.md`. Если предлагаешь значимое изменение защиты, кратко обоснуй угрозу, текущее покрытие, независимую пользу, стоимость и доверие к клиенту. Новые сенсоры и обязательные зависимости требуют отдельного решения.

## Задача

P1. Проследи факты от уже собранного события worker до ACK, хранения, версионированной оценки и показа правильного отчёта. Уточни, что уже реализовано, где теряются сведения и какая сквозная приёмка осталась открытой.

## Откуда начать

- Validator `F:/Python/BonkScanner_validator`, проект `bonkscanner_validator`. Смотри `src/bonkscanner_validator/transport.py`, `protocol.py`, `buffer.py`, `report_retention.py`, получение событий `controller.py` и петлю IPC там, где она влияет на доставку. Начни с `tests/test_validator_transport.py`, `test_deferred_controller_delivery.py` и `test_validator_ipc.py`. Остановка потоков и изоляция поколений — работа 04.
- Server `F:/Python/BonkScanner_validator_server`, проект `bonkscanner_validator_server`. `sessions/delivery.py`, `evidence.py`, `models.py`, `rules.py`, `classification.py`, `assessment_quality.py`, `reports.py`, `pilot.py`, `templates/validator/report.html`, `management/commands/review_processes.py`. Начни с `sessions/tests/test_delivery.py`, `test_evidence.py`, `test_assessment_v4.py`, `test_classification.py`, `test_access_correlations.py`, `test_pilot.py`, `contract/v3/schema.json` и `scripts/check_local_durability.py`. Исторический HEAD 904c394 уже содержит assessment v4. В `validator_server/settings.py` есть обязательные переменные для прямого Django-запуска. README и `compose.yaml` описывают существующий локальный Compose с dev defaults.
- Scanner `F:/Python/BonkScanner`, проект `bonkscanner`. Сверь `src/app/validator_reports.py`, `src/ui/validator_reports.py`, `src/ui/validator.py`, `src/tests/test_validator_reports.py` и `test_validator_integration.py`.
- В `F:/Python/BonkScanner/docs/validator` прочитай `lenient_assessment_and_catalogue_policy.md`, `run_boundary_assessment_upgrade_2026-11-17.md`, `validation/run_boundary_assessment_code_review_2026-11-17.md`, `live_contract/v3/README.md` и `live_contract/v3/acceptance.md`. Статус старого design doc не подтверждает отсутствие реализации. Сопоставь итоговые причины Security из `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/FINAL_REAL_STAGE_REVIEW_2026-11-17.md` с тем, что предусмотрено wire и правилом assessment. Ранее процитированные 106 тестов подтверждают лишь тогдашний subset.

## Что выяснить

1. Проследи `localRunId` → v3 enrollment/session → IPC/event buffering → batches/finish → durable ACK → PostgreSQL → pinned rule versions → JSON/private/public/browser/Scanner report link. Проверь sequence conflicts/retries (особенно потерянный ACK после commit), restart/expiry, несколько одновременно незавершённых сессий, service offline, unconfirmed finish и явную потерю evidence при переполнении или закрытии очереди.
2. Составь короткую таблицу важных переходов evidence → quality → public status. Включи known/late start, confirmed/unconfirmed end, Security collected/partial/cancelled/unavailable, clock gap, row truncation, ETW gaps, image load/unload, env/mod evidence и file mismatch. Сверь сохранённые findings, свежесть, версионность v1–v4, старые отчёты без переклассификации и отсутствие утечки private данных в browser/public. Публичный результат не может доказывать легитимность на пользовательском клиенте.
3. Проверь работу каталога и классификатора. Requested ETW и granted Census — возможности, Security used — наблюдение использования при достаточной атрибуции. Неизвестный процесс и одно имя/подпись/PID не дают автоматического finding или автоматического whitelist. Отдельно проверь, где хранятся узкие verified profiles, версии и private triage. Пополнение каталога можно оставить открытым, корректность механизма — критерий приёмки.
4. Предложи прицельные регрессии source, PostgreSQL restart/durability и полный локальный Windows → browser. Для недоступного окружения перечисли точную зависимость. Существующие настройки используй без вывода значений секретов. Отметь стыки с 01/02/03 (качество Security), 04 (IPC/старый ID), 05 (границы) и 06 (coverage, gaps, findings).

## Отчёт

Сохрани один отчёт на английском в `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/07_REPORT.md`. Подтверди, что файл читается из проекта `bonkscanner`, и верни в чат его путь и 2–3 ключевых вывода. В отчёте укажи:

- Какие ревизии, участки кода и сохранённые данные просмотрены. Для наблюдений приведи путь и строку либо номер события/время.
- Что подтверждено, что объясняется штатным ограничением и какие гипотезы остаются открытыми. Отдельно отметь данные, которых нет в записи.
- Минимальные предлагаемые изменения, если они нужны, с функциями, зависимостями и инвариантами. Если причина пока не установлена, укажи минимальную диагностику для её проверки.
- Отложенные проверки для интегратора. Для каждой дай цель, входные условия, ожидаемое наблюдение и критерий провала. Пометь, нужен ли Windows, UAC, игра или сервер. Результаты прежней проверки привязывай к её ревизиям и условиям, а отложенную проверку помечай `NOT TESTED`.
