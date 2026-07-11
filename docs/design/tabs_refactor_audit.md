# UI Tabs Refactor Audit

Пошаговый аудит вкладок после завершения data-flow refactor.

Порядок проверки:

1. Session Stats
2. Live Stats
3. Recordings
4. Compare Runs
5. OBS Overlay
6. Twitch Bot
7. In-Game Overlay

## Статусы

- `Open` — найдено несоответствие или возможное улучшение.
- `Verified` — проверено, проблем не найдено.
- `Deferred` — проблема подтверждена, исправление будет выполнено отдельным этапом.

## Session Stats

Статус проверки: `Verified` с одним отложенным performance-улучшением.

### Deferred: запись config.json после каждого reroll

- Файл: `src/gui_scanner.py`
- Участок: `ScannerMixin.log_reroll_stats()`
- Проблема: после каждого reroll выполняется синхронный `config.save_config(config.user_config)`.
- Риск: лишний диск I/O во время активного цикла reroll, возможные микрофризы и нагрузка на файловую систему.
- Несоответствие: в `docs/updates/performance_updates.md` уже указано требование хранить `TOTAL_REROLLS` в памяти и сохранять его периодически, при остановке или корректном завершении приложения.
- План исправления: добавить dirty-флаг/отложенную запись, выполнять flush при остановке сканера и закрытии приложения, а также периодически для защиты от потери данных.

### Проверено

- Session Overview: время сессии, количество reroll и RPM.
- Map Highlights: лучший и худший найденный вариант.
- Average Rerolls per Target: обновление для Templates и Scores.
- Tracked Items: получение данных из `LiveRunTracker` и обновление после изменения настроек.
- Twitch `!session`: использует общий session stats provider.
- Регрессионная проверка: полный набор тестов — `481 passed, 17 subtests passed`.

## Live Stats

Статус проверки: `Verified` с одним документным несоответствием.

### Предварительно проверено

- Вкладка использует `RefreshCoordinator` с разделением full snapshot и fast refresh-задач.
- Основные данные проходят через `LiveRunSnapshot` и `LiveRunTracker`.
- При переключении на вкладку выполняется немедленное обновление.
- VOD recording активирует fast KPS lane даже если вкладка скрыта.
- При временной ошибке чтения items используются последние валидные items,
  а остальные live stats не сбрасываются.
- Завершённый run блокирует все refresh demands до начала следующего run.
- Регрессионная проверка Live Stats: `18 passed, 151 deselected`.

### Open: устаревшее утверждение о stale KPS в архитектурной документации

- Файл: `docs/design/app/data_flow_architecture.md`
- Проблема: раздел `Known Gaps / Current Exceptions` утверждает, что VOD
  recording не активирует fast KPS reads и поэтому может сохранять stale/None
  значения `mob_kills` и `run_timer`.
- Фактическое состояние: `_should_refresh_fast_kps()` возвращает `True` при
  активной VOD-записи, поэтому текущая реализация уже покрывает этот сценарий.
- План исправления: обновить архитектурную документацию и удалить устаревшее
  исключение после завершения аудита вкладок.

## Recordings

Статус проверки: `Verified` с одним performance-улучшением.

### Open: полный load_vod выполняется в UI-потоке

- Файл: `src/gui_player_stats.py`
- Участок: `PlayerStatsMixin.load_selected_vod()`.
- Проблема: при выборе записи вызывается синхронный `load_vod(path)`, который
  полностью разбирает JSONL и создаёт все snapshot objects в главном UI-потоке.
- Риск: большие записи могут временно блокировать интерфейс при выборе,
  переключении записи или повторном открытии после rename.
- План улучшения: вынести полный parsing в фоновую задачу и применить результат
  через UI callback; metadata list уже использует отдельный быстрый путь.

### Проверено

- список записей использует metadata fast path и signature-based refresh;
- выбор записи загружает immutable `LoadedVod` snapshots;
- timeline корректно ограничивает индекс и обновляет детали;
- rename, delete и cleanup синхронизируют выбранную запись и список;
- поддерживаются legacy recordings и новые поля snapshot data;
- VOD recorder использует batch flush и финальный flush summary;
- регрессионная проверка: `29 passed, 149 deselected`.

## Compare Runs

Статус проверки: `Verified` с двумя пунктами для улучшения edge/performance.

### Open: синхронная загрузка двух полных VOD

- Файл: `src/gui_player_stats.py`
- Участок: `PlayerStatsMixin.load_compare_run()`.
- Проблема: каждый выбранный Run A/Run B полностью загружается через
  `load_vod()` в UI-потоке.
- Риск: при выборе двух больших записей интерфейс может быть заблокирован дважды
  подряд.
- План улучшения: использовать общий фоновой loader для VOD и применять
  результаты в UI-потоке с проверкой актуальности стороны/пути.

### Open: stale выбранный VOD после внешнего удаления файла

- Файл: `src/gui_player_stats.py`
- Участок: `refresh_compare_runs_list()`.
- Проблема: если выбранный файл удалён или перемещён вне приложения, список
  перестраивается без найденного selected row, но `compare_run_a_vod` или
  `compare_run_b_vod` может продолжить ссылаться на уже отсутствующий VOD.
- Риск: Compare Runs временно показывает данные записи, которой больше нет на
  диске, пока пользователь не выберет другой элемент.
- План исправления: при отсутствии selected path сбрасывать соответствующую
  сторону и обновлять diff/labels.

### Проверено

- выбор Run A и Run B;
- nearest snapshot synchronization по game time с fallback на elapsed time;
- Swap и синхронизация индексов;
- diff по overview, выбранным stats, items, stage summary, weapons, tomes и chaos;
- включение/выключение секций и сохранение пользовательских настроек;
- обработка пустых записей и ошибок загрузки;
- регрессионная проверка: `16 passed, 153 deselected`.

## OBS Overlay

Статус проверки: `Verified` с одним performance-улучшением.

### Open: лишнее обновление UI при каждом overlay state tick

- Файл: `src/gui_overlay.py`
- Участок: `OverlayMixin.update_overlay_state_from_tracker()`.
- Проблема: после публикации нового state вызывается `refresh_overlay_ui()` при
  каждом обновлении tracker, если `tab_overlay` уже создана, даже когда вкладка
  OBS Overlay скрыта.
- Риск: fast KPS обновления могут создавать лишние операции в UI-потоке
  (перезапись URL/status/style состояния), хотя HTTP-клиентам достаточно нового
  state в `OverlayStateStore`.
- План улучшения: обновлять карточку только если OBS Overlay активна или если
  изменились настройки сервера; публикацию runtime state оставить независимой.

### Проверено

- `LiveRunTracker.runtime_snapshot()` является источником overlay state;
- `OverlayStateStore` публикует thread-safe snapshot для HTTP clients;
- `/api/overlay-state`, full overlay и отдельные widget routes;
- widget config, selected stats/KPS metrics, tracked items, banishes и stage summary;
- refresh gating для OBS widgets и обработка no-game/read-failed состояния;
- layout editor сохраняет positions и canvas resolution с валидацией пути assets;
- server start/stop, auto-start и port error status;
- регрессионная проверка: `24 passed, 159 deselected`.

## Twitch Bot

Статус проверки: `Verified` с двумя пунктами для улучшения.

### Open: `!session` читает mutable UI/session state из worker thread

- Файлы: `src/twitch_bot.py`, `src/gui_overlay.py`.
- Участок: `TwitchBotWorker._handle_session()` и
  `format_twitch_session_summary()`.
- Проблема: большинство Twitch-команд используют immutable
  `LiveRunTracker.runtime_snapshot()`, но `!session` вызывает provider,
  который читает `session_rerolls` и `template_stats` непосредственно из
  объекта GUI/Scanner.
- Риск: worker может прочитать session counters в момент их изменения UI/scan
  потоком и получить несогласованный summary; это также нарушает единый
  consumer boundary нового data-flow.
- План улучшения: добавить thread-safe immutable session snapshot/provider или
  передавать session projection вместе с runtime snapshot.

### Open: reconnect sleep усложняет гарантированную остановку worker

- Файл: `src/twitch_bot.py`
- Участок: `TwitchBotWorker.run()`.
- Проблема: после socket failure worker выполняет `time.sleep(2)` перед
  reconnect, а `stop()` не может прервать этот sleep.
- Риск: `stop_twitch_bot().wait(2000)` может завершиться ровно на границе
  таймаута, оставив QThread в процессе остановки.
- План улучшения: заменить sleep на interruptible `threading.Event.wait(2)` и
  использовать его же в stop lifecycle.

### Проверено

- OAuth validation/revoke и автоподключение;
- start/stop/reconnect IRC worker;
- access tiers, aliases и global/per-command cooldowns;
- команды stats, session, bans, items, weapons, tomes, chaos, stages,
  powerups, KPS, chests, presets, disabled и help;
- chat byte-limit truncation и SafeFormatter fallback;
- команды читают runtime data через projection/snapshot boundary;
- изолированная регрессионная проверка: `47 unittest tests OK`.
- Примечание: запуск через pytest был отдельно отнесён из-за Windows access
  violation внутри `pytestqt` event processing, а не из-за assertion failure.

## In-Game Overlay

Статус проверки: `Verified` с двумя пунктами для улучшения.

### Open: slow widgets обходят общий in-game projection

- Файл: `src/gui_in_game_overlay.py`
- Участок: `InGameOverlayMixin._refresh_in_game_overlay_slow_widgets()`.
- Проблема: fast tick получает `RuntimeStateSnapshot` через
  `project_in_game_overlay()`, но slow widgets читают `latest_snapshot()`
  напрямую.
- Риск: два разных consumer path для одного runtime state и потенциальное
  расхождение boundary при дальнейшем расширении projection.
- План исправления: передавать/получать один immutable
  `InGameOverlayProjection` для fast и slow обновлений.

### Open: повторные ticks при применении настроек

- Файл: `src/gui_in_game_overlay.py`
- Участок: `apply_in_game_overlay_settings()` и `start_in_game_overlay()`.
- Проблема: при включённом overlay `start_in_game_overlay()` уже вызывает
  fast/slow tick, после чего `apply_in_game_overlay_settings()` вызывает их ещё
  раз после обновления widget visibility/scale.
- Риск: лишние memory-independent UI render operations и двойная публикация
  widget HTML при каждом изменении настроек.
- План улучшения: разделить запуск timers и принудительный initial refresh,
  оставив один согласованный refresh после применения конфигурации.

### Проверено

- auto-start, start/stop и скрытие overlay при неактивном игровом окне;
- fast KPS/powerups/event timer lane и slow scanner/recording/luck widgets;
- `RuntimeStateSnapshot` -> `project_in_game_overlay()` boundary;
- stats widget с cap-aware Difficulty/XP Gain coloring;
- event timer warnings, active waves, graveyard rules и edit-mode preview;
- luck rarity probabilities/bar, powerups rendering и KPS metrics;
- window geometry, transparent input mode, edit mode, drag and save layout;
- stats row alignment согласно `docs/design/in_game_overlay_stats_alignment_task.md`;
- регрессионная проверка: `20 passed` GUI tests и `13 unittest tests OK`.

## Общий этап исправлений

После завершения аудита всех вкладок найденные пункты будут исправляться отдельным проходом, сгруппированным по приоритету:

1. функциональные регрессии;
2. нарушения нового data-flow;
3. проблемы производительности;
4. UI/UX-улучшения.
