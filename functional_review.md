# Функциональное код-ревью — MegabonkReroll

> Проверены: `player_stats.py`, `live_run_tracker.py`, `twitch_bot.py`, `config.py`, `gui_overlay.py`, `gui_dialogs.py`, `run_control.py`
> Фокус: логические баги, race conditions, утечки, проглоченные исключения, state bugs.

---

## Общая статистика

| Файл | 🔴 Высокий | 🟠 Средний | 🟡 Низкий |
|---|:---:|:---:|:---:|
| `player_stats.py` | 3 | 1 | 1 |
| `live_run_tracker.py` | 2 | 2 | 1 |
| `twitch_bot.py` | 1 | 4 | 3 |
| `config.py` | — | 1 | 1 |
| `gui_overlay.py` | 1 | 2 | 4 |
| `gui_dialogs.py` | 2 | 1 | 2 |
| `run_control.py` | — | 2 | — |
| **Итого** | **9** | **13** | **12** |

---

## 🔴 ВЫСОКИЙ ПРИОРИТЕТ

---

### [F-01] `player_stats.py` — `or` вместо `is None` для адреса памяти
**Строки: 641, 683, 926, 973, 1023, 1043, 1307, 1711**

```python
owner_stats = owner_stats or self._resolve_owner_stats()
```

`owner_stats` — это целочисленный адрес памяти. Если caller передал `0` (нулевой указатель — валидное «нет данных»), выражение `0 or ...` его подменит результатом `_resolve_owner_stats()`. В результате метод читает данные другого объекта или вызывает `MemoryReadError`. Паттерн повторяется в 8 местах.

**Фикс:** Заменить на `if owner_stats is None: owner_stats = self._resolve_owner_stats()`

---

### [F-02] `player_stats.py` — Инвертированная логика инвалидации кэша
**Строки: 1085–1092, 1620–1623**

```python
or (
    not self._cached_chaos_level_address      # ← AND, не OR
    and version != self._cached_chaos_level_version
)
```

Кэш инвалидируется если **адрес НЕ найден** И версия изменилась. Должно быть наоборот: инвалидировать если **адрес найден** и версия изменилась (словарь перестроился). Текущая логика: если адрес найден и словарь Chaos Tome перестроился — кэш **не** инвалидируется, адрес указывает на устаревшие данные. Та же инвертированная логика в `_get_cached_chests_bought`.

**Результат:** После взятия нового Chaos Tome трекер продолжает читать старый адрес.

---

### [F-03] `player_stats.py` — Off-by-one в итерации по C# Dictionary
**Строки: 815–833**

```python
for index in range(count):
    entry = entries + DICT_ENTRY_START_OFFSET + (index * DICT_ENTRY_SIZE)
    # ← нет проверки hash_code перед чтением
```

В словарях C# поле `count` — количество **занятых** слотов, но среди них могут быть «дыры» от удалённых элементов (у них `hash_code < 0`). Правильная версия в `_read_passive_item_dictionary` (строки 896–916) проверяет `hash_code`. Эта версия — нет. При удалении элементов из словаря `_find_passive_item_stack_address` пропустит живые записи и вернёт `0` вместо реального адреса.

**Результат:** `_get_cached_key_count` возвращает `0` — сломана статистика ключей.

---

### [F-04] `live_run_tracker.py` — `_disabled_items_cache` не сбрасывается при reset
**Строки: 896–924**

В `_reset_for_new_run` `_disabled_items_cache` **отсутствует** в списке сбрасываемых полей. После начала нового рана `get_disabled_items()` будет возвращать список задизейбленных предметов **предыдущего рана** до прихода первого снапшота с `disabled_items_available=True`. Новый ран с другим сидом — другие disabled items.

---

### [F-05] `live_run_tracker.py` — Условная очистка expected-счётчиков
**Строки: 910–917**

```python
if self._expected_detected_run_reset:
    self._expected_detected_run_reset = False
    # _expected_key_procs и _expected_tracked_opens НЕ сбрасываются
else:
    self._expected_key_procs = 0.0
    self._expected_tracked_opens = 0
```

Между моментом когда `track_expected_key_procs` поставил флаг (и обнулил счётчики) и вызовом `_reset_for_new_run` может успеть выполниться `update_chests_and_keys`, добавив данные нового рана. Эти данные не будут сброшены и «перетекут» в следующий ран.

---

### [F-06] `gui_overlay.py` — tracked_items пропадают при сохранении вне диалога тегов
**Строки: 582–583, 588**

```python
if getattr(self, "overlay_tags_layout", None) is not None:
    overlay["tracked_items"] = config.OVERLAY.get("tracked_items", [])
# если диалог закрыт — tracked_items не присваивается в overlay
...
config.OVERLAY = overlay  # ← tracked_items пропал
```

`normalize_overlay_config()` (строка 546) возвращает `overlay` без `tracked_items`. Присвоение на строке 582 выполняется **только если диалог настройки тегов открыт прямо сейчас**. Если диалог закрыт — при любом другом сохранении настроек overlay (`persist=True`) список tracked items **стирается** из `config.OVERLAY`.

---

### [F-07] `gui_dialogs.py` — `sender()` == `None` при инициализации SM-полей
**Строки: 122–143**

```python
def _sync_sm_fields(self) -> None:
    sender = self.sender()   # None при прямом вызове
    if sender is self.sm_entry and sm_val > 0:    # False
        ...
    elif sender in (self.shady_entry, self.moai_entry) ...:  # False
        ...
```

`_sync_sm_fields()` вызывается из `load_template()` напрямую (не через сигнал). `self.sender()` возвращает `None`. Оба условия всегда `False`. При загрузке шаблона с ненулевым `sm_total` взаимоисключающие поля `shady_entry`/`moai_entry` **не сбрасываются в "0"**, и пользователь видит некорректные значения одновременно.

---

### [F-08] `gui_dialogs.py` — UI-действия из фонового потока в updater
**Строки: 1178–1181**

```python
threading.Thread(target=updater.check_and_update, args=(self.master, True), daemon=True).start()
self.close()   # диалог закрывается немедленно
```

`self.master` (главное окно) передаётся в фоновый поток. Если `check_and_update` обращается к нему для обновления UI (показ диалога, статуса) — это выполняется **из не-GUI потока**. В PySide6 это undefined behavior: возможен crash или зависание.

---

### [F-09] `twitch_bot.py` — CAP REQ отправляется после JOIN
**Строки: 80–83**

```python
self._send(f"JOIN #{target_channel}")   # 82
self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")  # 83 — ПОСЛЕ JOIN
```

По протоколу Twitch IRC `CAP REQ` должен идти **до** `JOIN`. При текущем порядке первые PRIVMSG после подключения могут приходить без тегов `@badges=...`. `_check_access()` получит `tags_str = None` и заблокирует всех не-Everyone пользователей в начале сессии.

---

## 🟠 СРЕДНИЙ ПРИОРИТЕТ

---

### [F-10] `player_stats.py` — Нет проверки `static_fields != 0` перед разыменованием
**Строки: 1898–1899**

```python
static_fields = self.memory.read_ptr(class_ptr + CLASS_STATIC_FIELDS_OFFSET)
root = self.memory.read_ptr(static_fields + STATIC_ROOT_OFFSET)  # если 0 → чтение по 0
```

Нет проверки `if not static_fields` перед следующим вызовом. Чтение по адресу 0 либо возвращает мусор, либо бросает `MemoryReadError` с непонятным сообщением.

---

### [F-11] `live_run_tracker.py` — RLock-рекурсия: публичный `latest_snapshot()` внутри `@with_lock`
**Строки: 688–695**

`update_chests_and_keys` держит `_lock` через `@with_lock`. Внутри вызывает `self.latest_snapshot()`, который тоже `@with_lock`. Работает из-за `RLock`, но если кто-то поменяет на обычный `Lock` — deadlock. Правильно: вызывать внутренний `_unlocked`-метод напрямую.

---

### [F-12] `live_run_tracker.py` — Преждевременный `break` в обработке chaos-модификаторов
**Строки: 997–1001**

```python
elif self._should_commit_unbudgeted_candidate(stat_id, i, val):
    new_baseline.append(val)
else:
    break   # ← прерывает обработку ВСЕХ оставшихся новых значений
```

Если второе из трёх новых значений не набрало нужного числа наблюдений — третье вообще не обрабатывается. `new_baseline` не дорастает до нужной длины, следующий `range(len(old_values), len(new_values))` некорректно смещает индексы.

---

### [F-13] `live_run_tracker.py` — Условие валидации chest-счётчиков блокирует до накопления истории
**Строки: 753–754**

```python
if not (0 <= chests_purchased <= chests_bought <= total_opened):
    return False
```

Если `chests_bought > known_total` (история ещё не накопилась) — `total_opened = known_total < chests_bought` → условие False → метод блокирует обновление счётчиков при каждом вызове. Счётчики появятся только когда история «догонит» покупки.

---

### [F-14] `twitch_bot.py` — `time.time()` для cooldown вместо `time.monotonic()`
**Строки: 190, 251**

Cooldown использует `time.time()` (wall clock). При синхронизации NTP или переходе на летнее время часы могут прыгнуть назад. `time_since_global = now - last_global` станет отрицательным → все команды заблокированы на время прыжка.

---

### [F-15] `twitch_bot.py` — Проглоченный `except` в `_send()` — бот не знает о разрыве
**Строки: 154–159**

```python
try:
    self.sock.send(...)
except:
    pass   # ← любая ошибка молча игнорируется
```

После ошибки отправки сокет не закрывается. Могут потеряться `PASS`, `NICK`, `JOIN`, `CAP REQ`. Бот продолжает считать себя подключённым до следующего `recv`.

---

### [F-16] `twitch_bot.py` — Проглоченный `except` в `_handle_powerups` даёт неверный ответ
**Строки: 664–665**

```python
try:
    snapshot = powerups_snapshot()
    ...
except Exception:
    pass   # ← падаем в резервную ветку из stat-данных
```

При сломанном провайдере снапшота пользователь получает ответ из неактуальных статов вместо явной ошибки.

---

### [F-17] `config.py` — `bool("false") == True`
**Строки: 505–506 и аналоги**

```python
bot_cfg["commands_announcements"] = bool(bot_cfg.get("commands_announcements", False))
```

Если пользователь вручную написал в `config.json` `"commands_announcements": "false"` (JSON-строка вместо boolean) — `bool("false") == True`. Объявления включены вопреки настройке. Аналогично для `enabled`, `auto_connect`, `stage_announcements`.

---

### [F-18] `gui_overlay.py` — Потенциальный deadlock: `refresh_overlay_ui()` внутри `config_lock`
**Строки: 536–598**

`save_overlay_settings_from_ui` удерживает `config.config_lock`. Внутри вызывает `refresh_overlay_ui()`, который обновляет виджеты и может триггерить сигналы. Если `config_lock` — не реентерабельный и сигнал снова пытается взять лок — deadlock.

---

### [F-19] `gui_overlay.py` — Утечка: старый overlay-сервер не останавливается + рекурсия при смене порта
**Строки: 514–529, 594–597**

При смене порта: `save_overlay_settings_from_ui` → `start_overlay_server()` → `save_overlay_settings_from_ui(persist=False)` — рекурсия. Если старый сервер не был `is_running` — он не получает `stop()` и «теряется».

---

### [F-20] `gui_dialogs.py` — Twitch tracked items не сохраняются при закрытии «X»
**Строки: 1834–1877**

`add_twitch_tracked_item` и `remove_twitch_tracked_item` пишут только в `config.TWITCH_BOT` в памяти, без `save_config()`. Закрытие диалога через «X» (не «Save Settings») теряет все изменения. При этом UI уже показывает их как применённые — несоответствие ожиданий.

---

### [F-21] `run_control.py` — Нет ожидания при `snapshot_ready=True + client != None`
**Строки: 84–97**

```python
if client is not None and not snapshot_ready:
    client.wait_for_map_ready(...)
elif client is None:
    self._sleep_abortable(...)
# Если snapshot_ready=True И client != None — никакого ожидания
```

Если снапшот сигнализирует о готовности раньше времени (флапающий баг хуков) — следующее чтение памяти происходит до полной загрузки карты.

---

### [F-22] `run_control.py` — `restart_run` непрерываем во время удержания клавиши
**Строки: 145–154**

```python
self.keyboard.press(reset_hotkey)
try:
    self._sleep(self._reset_hold_duration())   # time.sleep — непрерываем
finally:
    self.keyboard.release(reset_hotkey)
```

В отличие от `HookRunControlProvider`, нет `abort_condition`. При нажатии «Stop» во время удержания клавиши перезапуска — клавиша остаётся зажатой до конца `_sleep`.

---

## 🟡 НИЗКИЙ ПРИОРИТЕТ

---

### [F-23] `player_stats.py` — Проглоченное исключение в `get_passive_items`
**Строки: 663–676**

После `except MemoryReadError: pass` код безусловно переходит к строке 666 (не в try/except). Если эта строка тоже бросит `MemoryReadError` — оно пойдёт необработанным вверх.

---

### [F-24] `twitch_bot.py` — `_last_stage_index` не в `__init__`
**Строки: 43–54, 93**

Атрибут создаётся только в `run()`. Прямой вызов `_check_stage_transitions` до `run()` → `AttributeError`.

---

### [F-25] `twitch_bot.py` — Первый переход стадии всегда даёт упрощённый анонс
**Строки: 931–937**

При `_last_stage_index = 0` поиск `"Stage 0"` в `stage_summary_rows()` всегда пустой → анонс без статистики.

---

### [F-26] `twitch_bot.py` — Dead code в `_check_commands_announcement`
**Строка: 907**

`_last_commands_announcement_at is None` в этой точке невозможно — значение всегда уже установлено выше по коду.

---

### [F-27] `config.py` — `save_config()` вызывается при каждом импорте модуля
**Строка: 737**

`config.json` перезаписывается при каждом старте. Нестандартные поля, не прошедшие через известные ключи, потеряются.

---

### [F-28] `gui_overlay.py` — Item selector не перестраивается при повторном открытии диалога
**Строки: 629–636**

```python
if selector.count() == 0:
    for item_name in getattr(self, "overlay_item_names", ()):
        selector.addItem(item)
```

`overlay_item_names` вычисляется один раз при открытии. При повторном открытии диалога (после закрытия) `count() > 0` — список не обновляется.

---

### [F-29] `gui_overlay.py` — `setUpdatesEnabled(False)` до создания виджетов
**Строки: 273–274**

Подавление обновлений до добавления 150+ виджетов — может привести к тому, что часть не отрисуется при первом открытии.

---

### [F-30] `gui_overlay.py` — Мёртвая ветка суффикса T1
**Строки: 1026–1033**

```python
if label.casefold().endswith(" t1"):   # никогда True — суффикс только что удалён
    return label
return f"{label} T1"
```

Для `"Sword t1 t1"`: суффикс удаляется один раз → `"Sword t1"`, добавляется T1 → `"Sword t1 T1"` вместо `"Sword T1"`.

---

### [F-31] `gui_overlay.py` — `session_clear_all_tags_btn` не обнуляется при закрытии диалога
**Строки: 1115–1121**

Qt-объект не освобождается, сохранённый signal-connection ведёт на закрытый диалог.

---

### [F-32] `gui_dialogs.py` — Двойная запись `stats_tpl_entry` в `reset_to_defaults`
**Строки: 1940–1962**

Строка 1945 устанавливает шаблон, затем цикл на строке 1957 снова его перезаписывает. Если источники разойдутся — строка 1945 станет мёртвым кодом.

---

### [F-33] `gui_dialogs.py` — Auto thresholds не пересчитываются при изменении весов/множителей
**Строки: 399–412**

`auto_update_thresholds()` вызывается только при переключении чекбокса, не при изменении полей. В UI отображаются устаревшие пороговые значения пока пользователь работает в автоматическом режиме.

---

## Топ-5 самых опасных для пользователя

| # | Баг | Видимый эффект |
|---|-----|----------------|
| F-02 | Инвертированная инвалидация кэша chaos | Неверная статистика Chaos Tome после взятия нового |
| F-04 | `_disabled_items_cache` не сбрасывается | Список disabled items из прошлого рана на новом ране |
| F-06 | tracked_items пропадают при сохранении overlay | Пользователь не понимает почему настройки исчезли |
| F-09 | CAP REQ после JOIN | Команды в начале сессии не работают для mod/sub |
| F-20 | Twitch tracked items теряются при «X» | Пользователь думает что сохранил, а данные пропали |
