# Twitch Bot & UI Overlay Upgrade Audit Analysis

## 1. Executive Summary

The `codex/overlay-live-tracker` branch is a substantial, well-scoped upgrade: overlay runtime state is split into dedicated modules, the UI now exposes OBS overlay controls and Twitch Bot controls, and the live stats refresh loop feeds overlay/Twitch data even when the Live Stats tab is not open.

Release health is not yet good enough for a stable release. Overlay architecture is mostly sound and has focused unit coverage, but the Twitch bot/auth path has release-blocking issues: OAuth lacks CSRF/state validation and timeout cleanup, bot shutdown is incomplete on app close, IRC reconnect is absent, and `LiveRunTracker` is read from a `QThread` while the GUI thread mutates it without locking.

Functional source note: current `docs/updates/functional_updates.md` contains Twitch Bot integration as item 2, not item 4. Overlay upgrade expectations were found in `docs/updates/functional_updates_archive.md` item 11 and item 12.

Focused tests run:

- `python -m unittest tests.test_live_run_tracker tests.test_overlay_server tests.test_overlay_state` -> OK, 18 tests.
- `python -m unittest tests.test_live_run_tracker tests.test_overlay_server tests.test_overlay_state tests.test_gui_run_control` -> failed because local Python lacks `PySide6`, not because of tested logic.

## 2. Key Strengths

- `live_run_tracker.py` is pure Python, bounded, and unit-testable. This matches overlay source-of-truth guidance for a recording-independent tracker.
- `overlay_server.py` binds overlay traffic to `127.0.0.1`, serves widget-specific routes, uses `ThreadingHTTPServer`, and blocks asset traversal with `Path.resolve().relative_to()`.
- `gui_player_stats.py` correctly refreshes live stats when overlay or Twitch bot is active, even if the Live Stats tab is closed.
- Overlay state serialization is cleanly isolated in `overlay_state.py`, keeping HTTP/UI code out of tracker data shaping.
- Settings dialog numeric controls are a real UX improvement: `QDoubleSpinBox`/`QSpinBox` ranges and suffixes replace fragile free-text parsing for delay, reset hold, and snapshot interval.
- UI status labels consistently use rich-text spans for active/stopped/waiting states, and the Twitch tab follows existing group-box/form-layout patterns.

## 3. Bugs & Logic Gaps

- **Severity:** High
  **Description:** OAuth callback accepts token POSTs without `state` validation, origin validation, one-time nonce, or exact redirect path validation. Any local process/browser page that can reach `localhost:17846` can POST an access token to `/auth/twitch/token`, causing account/token injection. Relevant code: `twitch_auth.py:58-69`, `twitch_auth.py:89-95`.
  **Suggested Fix:** Generate a cryptographic `state` per auth attempt, include it in the Twitch authorize URL, store it in `TwitchAuthThread`, and require POST body `{access_token, state}` to match before calling `handle_token`. Bind to `127.0.0.1`, validate `Content-Type`, reject oversized bodies, and return `400` on malformed JSON.

- **Severity:** High
  **Description:** Twitch auth thread can run forever if the browser is closed, callback never happens, or port is already occupied. `serve_forever()` has no timeout and the UI only re-enables the button on emitted success/error. Relevant code: `twitch_auth.py:83-101`.
  **Suggested Fix:** Add an auth deadline using `QTimer` or server timeout loop, emit `auth_error("Authorization timed out.")`, and always call `server_close()` after shutdown. Add a cancel path when user starts another auth or app closes.

- **Severity:** High
  **Description:** Twitch bot and auth threads are not stopped during app shutdown. `ScannerMixin.on_closing()` stops overlay/player stats/native hooks, but never calls `stop_twitch_bot()` or shuts down `twitch_auth_thread`. A bot socket/auth HTTP server can survive shutdown until process exit, and a waiting auth server can hold port `17846`. Relevant code: `gui_scanner.py:416-454`, `gui_twitch.py:86-88`.
  **Suggested Fix:** In `on_closing()`, call `stop_twitch_bot()`, close the socket to unblock `recv()`, wait briefly with `worker.wait(2000)`, and shut down any active `TwitchAuthThread` server.

- **Severity:** High
  **Description:** `LiveRunTracker` is mutated by GUI timer code and read directly by `TwitchBotWorker` on a background `QThread`. No lock protects `snapshots`, `run_id`, `current_stage_index`, `_tracked_counts`, or `_last_*` fields. Concurrent `update()`/`stage_summary_rows()` can produce stale/inconsistent Twitch responses or raise during deque iteration. Relevant code: `gui_player_stats.py:379-380`, `twitch_bot.py:219`, `twitch_bot.py:374-386`, `live_run_tracker.py:165-183`.
  **Suggested Fix:** Add `threading.RLock` inside `LiveRunTracker` and guard all public read/write methods, or expose immutable snapshots via a Qt signal copied from the GUI thread into the bot worker.

- **Severity:** Medium
  **Description:** IRC connection has no reconnect/backoff. Any socket timeout beyond the short read timeout, server disconnect, TLS failure, laptop sleep, or Twitch restart exits the worker and leaves the bot stopped. Relevant code: `twitch_bot.py:55-80`.
  **Suggested Fix:** Wrap connect/read loop in reconnect supervisor with capped exponential backoff, status updates, and user-initiated stop escape. Handle Twitch `NOTICE` auth failures distinctly.

- **Severity:** Medium
  **Description:** `stop()` only flips `running`; it does not close/shutdown the socket. Worker exits after next 0.5s receive timeout in normal cases, but can still block during connect/TLS/auth or if socket state changes unexpectedly. Relevant code: `twitch_bot.py:36-41`, `twitch_bot.py:86-88`.
  **Suggested Fix:** In `stop()`, call `shutdown(SHUT_RDWR)` and `close()` under a small lock. Use `wait()` in UI shutdown and disable Start until finished.

- **Severity:** Medium
  **Description:** Twitch message length enforcement uses character count and a 450-character soft cap, not the Twitch IRC 512-byte protocol limit. Multi-byte characters in stage announcements and item names can exceed byte limits; `_send_chat()` has no final guard. Relevant code: `twitch_bot.py:98-100`, `twitch_bot.py:267-306`, `twitch_bot.py:396-404`.
  **Suggested Fix:** Before sending, measure encoded IRC line bytes including `PRIVMSG #channel :` and `\r\n`; truncate on UTF-8 byte boundary. Remove emoji from default announcements or count bytes strictly.

- **Severity:** Medium
  **Description:** Access-tier implementation does not match functional spec. Spec calls for Everyone, Moderators & VIPs only, and Subscribers & Mods only. UI exposes Everyone, Subs & Mods, Mods Only; `Mods Only` excludes VIP. Relevant code: `gui_layout.py:1126-1128`, `twitch_bot.py:154-178`.
  **Suggested Fix:** Rename/add tiers exactly: `Everyone`, `Mods & VIPs`, `Subs & Mods`. Implement `Mods & VIPs` as broadcaster/mod/vip and `Subs & Mods` as broadcaster/mod/sub/founder.

- **Severity:** Medium
  **Description:** Command cooldown is global only, despite spec requiring global and per-command cooldown. A single viewer using `!stats` suppresses all other commands until the global cooldown expires. Relevant code: `twitch_bot.py:18`, `twitch_bot.py:120-152`.
  **Suggested Fix:** Track `last_global_command_time` and `last_command_time_by_name`. Add config/UI for per-command cooldown or document global-only MVP if intentional.

- **Severity:** Medium
  **Description:** OAuth token is persisted in plaintext config. This is not unusual for local desktop apps, but it is a credential with chat write scope and should be treated as sensitive. Relevant code: `gui_twitch.py:50-54`, `config.py:84-100`.
  **Suggested Fix:** Store token in Windows Credential Manager/keyring if available. At minimum, add Disconnect/Revoke action, never log token values, and document local storage behavior.

- **Severity:** Low
  **Description:** `_handle_items()` never creates `unknown_items` because unknown rarity defaults to `"COMMON"`. This collapses unknown items as common and makes the unknown branch dead. Relevant code: `twitch_bot.py:238-253`.
  **Suggested Fix:** Use `ITEM_RARITY_BY_NAME.get(norm_name)` and branch unknown when result is `None`.

- **Severity:** Low
  **Description:** `_is_active_snapshot()` intentionally treats retained `map_seed`, `stage_ptr`, items, weapons, or tomes as active. This matches current weak-signal reality but conflicts with the known "Exit to Menu leaves stale pointers" caveat in functional updates. Relevant code: `live_run_tracker.py:232-243`.
  **Suggested Fix:** Keep as MVP only. Add a real gameplay/menu discriminator when reverse work finds one; until then, label overlay/Twitch state as potentially stale after menu exit and prefer timer/status staleness over hard "live".

- **Severity:** Low
  **Description:** Twitch auth POST handler does not handle malformed JSON and does not send a response for unsupported POST paths. A bad local POST can throw through the handler and leave UI waiting. Relevant code: `twitch_auth.py:58-69`.
  **Suggested Fix:** Add `else: 404`, catch `JSONDecodeError`, cap `Content-Length`, and emit `auth_error` only for actual auth route failures.

- **Severity:** Low
  **Description:** Twitch feature has no unit tests. Core command parsing, access tiers, item collapsing, byte-limit truncation, and stage announcements are untested. Test gap is large compared with risk. Relevant files: `twitch_bot.py`, `twitch_auth.py`.
  **Suggested Fix:** Add tests with fake tracker/socket/config for `_handle_line`, `_check_access`, `_handle_items`, `_check_stage_transitions`, and auth handler validation.

## 4. Security & Threading Review

OAuth security is the weakest part. The browser fragment-to-local-POST pattern is workable for implicit OAuth, but the implementation needs `state`, bounded input, loopback-only binding, timeout, and cleanup. Persisting a chat-write token in plaintext config should be either moved to OS credential storage or clearly disclosed with a Disconnect/Revoke flow.

IRC security is mostly acceptable at transport level because TLS is used against `irc.chat.twitch.tv:6697` with default certificate validation. The bot should still classify auth failures, avoid logging credential material, and reconnect safely.

Threading is not release-safe. Qt UI updates are routed through signals, which is good, but shared app state is not isolated: `TwitchBotWorker` directly reads `LiveRunTracker` while the main GUI timer writes it. Add locks or immutable cross-thread copies before release.

Overlay server threading is better. `OverlayStateStore` uses a lock, `ThreadingHTTPServer` daemon threads are suitable for local OBS polling, and asset traversal is blocked. Config writes from overlay POSTs use `config.config_lock`, but the local editor endpoints are unauthenticated loopback controls; acceptable for local-only MVP, still worth documenting.

## 5. Design & UX Consistency

The OBS Overlay tab mostly satisfies archived Overlay Upgrade requirements: status row is simpler, widget-specific URLs exist, overlay server is loopback-only, `Stats` widget is configurable, and live tracker data updates without recording.

The Twitch Bot tab is visually consistent with existing Qt group/form controls and uses the requested purple `#TwitchConnectButton` styling. Status labels use same rich-text color vocabulary as scanner/overlay status labels.

UX gaps remain: no Disconnect/Reauthorize button, no auth timeout/cancel feedback, no reconnect status, no per-command cooldown controls, and access tier labels do not match the spec. Stage announcements use emoji, which may look lively but increases IRC byte-limit risk and may feel inconsistent with the restrained app UI.

Settings dialog numeric controls are consistent and safer than text inputs. Boundaries are reasonable: min delay 0-60s, reset hold 0.01-10s, snapshot interval 1-3600s.

## 6. Final Recommendation

Do not release this branch as stable yet. Overlay work is close and structurally strong, but Twitch bot/auth needs fixes before a release commit.

Minimum release blockers:

- Add OAuth `state`, timeout, malformed POST handling, and clean server shutdown.
- Stop Twitch bot/auth threads on app close and make bot stop close its socket.
- Add thread-safety around `LiveRunTracker` or use immutable GUI-thread snapshots for bot reads.
- Add IRC reconnect/backoff and byte-based Twitch message length guarding.
- Align access tiers/cooldowns with functional spec or explicitly mark unsupported pieces.

After those fixes, rerun focused overlay tests and add Twitch bot unit tests before release.