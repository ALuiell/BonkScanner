# 04. Остановка Scanner/Validator, IPC и финализация

## Режим работы

Это независимое исследование для отдельного диалога в проекте **Aluiel_MCP**. Через MCP самостоятельно читай Windows-файлы, Git и сохранённые логи. Используй зарегистрированный проект и инструменты `workspace_read`, `git_status` или `shell_run` (PowerShell). Промпты, отчёты и captures находятся в проекте `bonkscanner`. Для исходников выбери соответствующий проект из `project_list`. Локальный Codex для выполнения задачи не нужен.

**Приоритет — исследование и анализ существующих материалов.** Прочитай инструкции затронутых репозиториев, проверь HEAD и рабочее дерево. В индексированном репозитории начни поиск кода с CodeGraph. Можно читать и фильтровать существующие JSONL/JSON/CSV без записи новых данных. Не запускай тесты и replay, Scanner, Validator, GameLab, ETW или сервер, не взаимодействуй с текущей игровой сессией и не меняй системное состояние. В этом диалоге разрешена запись только одного файла, `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/04_REPORT.md`. Код, тесты, captures, настройки и Git оставь как есть. Если источники недоступны, укажи конкретный путь и влияние на вывод.

По границам согласованной функциональности сверяйся с `F:/Python/BonkScanner/docs/updates/functional_updates.md`. Если предлагаешь значимое изменение защиты, кратко обоснуй угрозу, текущее покрытие, независимую пользу, стоимость и доверие к клиенту. Новые сенсоры и обязательные зависимости требуют отдельного решения.

## Задача

P0. Исследуй повторяющийся `Validator · Stopping`, хвост IPC, смену ранов во время финализации и возврат ресурсов. Нужна проверяемая последовательность событий от действия GUI до завершения всех владельцев.

## Откуда начать

- Validator `F:/Python/BonkScanner_validator`, проект `bonkscanner_validator`. Проследи `controller.py` (`enable/disable/_observe/_send/try_snapshot`), `worker.py` (`WorkerClient.stop`, IPC credits), `ipc.py`, `transport.py` (`TransportManager.close/tick/snapshot`), `engine.py` (`_finish/_freeze_finalization/_collect_finalizations`) в `src/bonkscanner_validator`.
- Scanner `F:/Python/BonkScanner`, проект `bonkscanner`. Начни с `src/ui/validator.py` (`ValidatorTab._disable/refresh`), `src/app/validator.py`, `src/app/runtime.py` и `src/app/shutdown.py`. Подними `src/tests/test_validator_ui.py`, `test_validator_shutdown_ui.py`, `test_validator_integration.py`, а в Validator `tests/test_validator_controller.py`, `test_validator_worker.py`, `test_validator_ipc.py`, `test_nonblocking_finalization.py` и `test_deferred_controller_delivery.py`.
- `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-093004-1afdfe/FINAL_REAL_STAGE_REVIEW_2026-11-17.md` фиксирует минимум 11 секунд `Stopping` после исчезновения worker. Сверь исходные JSONL. `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/QA_DIRECT_GAME_LAB_INTERIM_2026-11-17.md` и `F:/Python/BonkScanner/.local/validator-start-trace/retest-kit/captures/session-20261117-080026-ba7a2e/C05_direct_restart_during_finalization_r1.json` подтверждают старый `run_end` под старым ID и живой sensor, но финиш C05 не принят из-за незапланированной смерти.
- В коде `disable` определяет `stopping` по двум потокам после bounded join. `_observe` отдельно записывает `disabled`, а `_send` после drain не публикует terminal state в показанном пути. `refresh` пропускает занятой snapshot, а Enable зависит от `busy`. Возможен порядок, когда позднее завершение не корректирует `stopping`. Требуется сверка с trace и всеми ветками, включая запись ошибочного состояния.

## Что выяснить

1. Восстанови порядок Stop, worker exit, tail IPC/ACK, `_interrupt`, observer-done, sender drain, завершения потоков и Qt refresh. Проверь, где выставляются `enabled`, `busy` и terminal state, кто может их перезаписать, как работает bounded close при медленной сети, и как очередной Enable взаимодействует с предыдущим поколением и с pending UAC.
2. Разбери ограничение очереди frozen finalizers, отказ постановки, исключение при достижении лимита, порядок выдачи событий и принадлежность ETW, Security recovery и IPC к старому `localRunId`. Выясни, как fail/cancel/crash сохраняют явную потерю покрытия или доставки без ложного завершённого отчёта.
3. Предложи минимальную корректировку только для подтверждённого дефекта или план диагностики с минимальными событиями. Удерживай правдивый `Stopping` пока cleanup реально продолжается, терминальное состояние после него и отзывчивость GUI. Не привязывай окончание cleanup только к исчезновению PID.
4. Опиши будущие проверки Enable → active → Stop → OFF → Enable, UAC cancel и закрытия приложения, медленного/отключённого сервера, Stop во время Security query, tail IPC под давлением, и 5–10 контролируемых C05 overlap без случайной смерти. Добавь offline case на лимит очереди и очистку ресурсов, а в Windows-проверке проверь свежие опросы, старые/новые IDs, отдельные ETW sessions, восстановление Security и отсутствие orphaned finalizers. Стыки с 01–03, 05, 06 и 07 перечисли только там, где есть конкретный общий инвариант.

## Отчёт

Сохрани один отчёт на английском в `F:/Python/BonkScanner/agent tasks/validator-stabilization-2026-11-17/04_REPORT.md`. Подтверди, что файл читается из проекта `bonkscanner`, и верни в чат его путь и 2–3 ключевых вывода. В отчёте укажи:

- Какие ревизии, участки кода и сохранённые данные просмотрены. Для наблюдений приведи путь и строку либо номер события/время.
- Что подтверждено, что объясняется штатным ограничением и какие гипотезы остаются открытыми. Отдельно отметь данные, которых нет в записи.
- Минимальные предлагаемые изменения, если они нужны, с функциями, зависимостями и инвариантами. Если причина пока не установлена, укажи минимальную диагностику для её проверки.
- Отложенные проверки для интегратора. Для каждой дай цель, входные условия, ожидаемое наблюдение и критерий провала. Пометь, нужен ли Windows, UAC, игра или сервер. Результаты прежней проверки привязывай к её ревизиям и условиям, а отложенную проверку помечай `NOT TESTED`.
