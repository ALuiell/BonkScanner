# Twitch Bot High-Severity Fix Verification

Branch checked: `codex/overlay-live-tracker`
HEAD checked: `8e886da Fix high-severity vulnerabilities and stability issues in Twitch Bot`
Source audit: `docs/tasks/twitch_bot_overlay_audit_analysis.md`, High-Severity Blockers

## Verdict

Recent updates resolved most release-blocking OAuth and shutdown behavior, but the `LiveRunTracker` threading blocker is only partially fixed. Public tracker methods now lock shared state, so `latest_snapshot()` and `stage_summary_rows()` no longer iterate or copy mutable tracker data without protection. However, `TwitchBotWorker` still reads `run_id` and `current_stage_index` directly from its `QThread`, while GUI code can mutate those fields through `LiveRunTracker.update()`. That leaves a remaining high-severity race/inconsistent-read path for stage announcements.

## High-Severity Checklist

- [x] OAuth token injection/CSRF protection mostly resolved.
  - `TwitchAuthThread` now generates `state` with `secrets.token_urlsafe(16)`.
  - Twitch authorize URL includes that state.
  - Local callback JS posts `{access_token, state}`.
  - `OAuthRequestHandler.do_POST()` rejects missing/mismatched state before calling `handle_token()`.
  - Malformed JSON, oversized POST bodies, and unsupported POST paths now return errors instead of falling through.
  - Remaining hardening: server still binds to `"localhost"` instead of explicit `127.0.0.1`; POST `Content-Type` is not validated; callback GET uses `startswith()` instead of exact path validation.

- [x] OAuth auth thread no longer waits forever on missing browser callback.
  - `TwitchAuthThread.run()` starts a 120-second `threading.Timer`.
  - Timeout emits `auth_error("Authorization timed out after 2 minutes.")` and calls `_shutdown_server()`.
  - Remaining cleanup gap: `_shutdown_server()` calls `server.shutdown()` from a daemon thread but never calls `server_close()` or waits for thread exit, so port cleanup is less deterministic than requested.

- [x] Twitch bot socket stop path substantially fixed.
  - `TwitchBotWorker.stop()` now flips `running = False`, calls `shutdown(SHUT_RDWR)`, and closes the socket.
  - This should unblock the 0.5s receive loop and prevent the old "only flip running" shutdown hang in normal connected state.

- [~] Application shutdown cleanup partially resolved.
  - `ScannerMixin.on_closing()` now calls `stop_twitch_bot()` and shuts down any active `twitch_auth_thread`.
  - Remaining gap: shutdown does not call `worker.wait(2000)` after stopping the bot, and auth shutdown is asynchronous with no `server_close()`. This likely avoids common hangs but does not fully prove clean thread/resource teardown.

- [~] `LiveRunTracker` data races partially resolved, not fully resolved.
  - `LiveRunTracker` now owns `threading.RLock`.
  - Public mutating/read methods `update()`, `mark_read_failed()`, `set_tracked_item_rules()`, `stage_summary_rows()`, `tracked_item_rows()`, `latest_snapshot()`, and `status()` are decorated with `@with_lock`.
  - This fixes the prior deque iteration race for `stage_summary_rows()` and snapshot read race through `latest_snapshot()`.
  - Remaining high issue: `TwitchBotWorker.run()` and `_check_stage_transitions()` still read `self.run_tracker.run_id` and `self.run_tracker.current_stage_index` directly without locking. These are written under lock by `LiveRunTracker.update()` and `_reset_for_new_run()`, so the worker can still observe an inconsistent run/stage pair.
  - Recommended fix: add a locked public accessor such as `run_identity()` returning `(run_id, current_stage_index)` and use it in `twitch_bot.py`, or stop sharing the tracker object with the worker and pass immutable GUI-thread snapshots.

## Remaining Medium-Severity Issues

- IRC reconnect/backoff still missing. `TwitchBotWorker.run()` exits after socket disconnect or socket error and leaves the bot stopped.
- Twitch IRC message length still uses character-count truncation near 450 chars, not the 512-byte IRC protocol limit. `_send_chat()` has no final byte guard, and stage announcements still include multi-byte flag emoji.
- Access tiers still do not match spec. UI/config allow `Everyone`, `Subs & Mods`, `Mods Only`; spec called for `Everyone`, `Mods & VIPs`, `Subs & Mods`. Current `Subs & Mods` also allows VIPs.
- Cooldown remains global only through `last_command_time`; no per-command cooldown tracking/config exists.
- OAuth token still persists plaintext in config. No Windows Credential Manager/keyring storage, disconnect, or revoke flow found.

## Remaining Low-Severity Issues

- `_handle_items()` still defaults unknown rarity to `"COMMON"`, making `unknown_items` effectively dead.
- Active-run detection still treats retained `map_seed`, `stage_ptr`, items, weapons, or tomes as active, so stale menu-exit pointers can keep overlay/Twitch state looking live until staleness logic catches up.
- Twitch auth handler now catches malformed JSON and unsupported POST paths, but still lacks `Content-Type` validation and exact callback path validation.
- Twitch bot/auth still have no dedicated unit tests for command parsing, access tiers, item collapsing, byte-limit behavior, stage announcements, or auth handler validation.

## Verification Performed

- Static review of `live_run_tracker.py`, `twitch_bot.py`, `twitch_auth.py`, `gui_scanner.py`, `gui_twitch.py`, `gui_layout.py`, and `config.py`.
- `python -m unittest tests.test_live_run_tracker tests.test_overlay_server tests.test_overlay_state` passed: 18 tests.
- `python -m unittest tests.test_gui_run_control` could not run in this local Python because `PySide6` is not installed: `ModuleNotFoundError: No module named 'PySide6'`.

## Release Recommendation

Do not call high-severity verification complete yet. OAuth/account-injection and common shutdown hangs are largely fixed, but `LiveRunTracker` still has direct unlocked cross-thread reads. Fix that accessor path, add deterministic auth server close/wait behavior, then rerun focused tests and add Twitch-specific unit coverage.