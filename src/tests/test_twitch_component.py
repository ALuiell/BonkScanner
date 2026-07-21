"""The Twitch component (step 23).

Nine tests here were `test_gui_run_control.py`'s. They drove
`MegabonkApp.<twitch method>(fake)` unbound against hand-built
`SimpleNamespace`s, which is how the mixin had to be tested: it had no
constructor to inject into. Their subject moved, so they moved with it rather
than being duplicated -- the same call step 22c made for its four.

What is deliberately *not* here: `test_twitch_bot.py` (43 tests) and
`test_twitch_auth.py` (5) already cover the worker and the auth thread, and
neither mentions `MegabonkApp`. Step 23 does not change either, so neither
grows a parallel copy.

`TwitchTabTests` covers the widget half without building widgets -- see its
docstring. `test_twitch_bot_status_value_does_not_repeat_status_label` landed
there rather than here, because the formatting it asserts on is now the tab's.
"""

from __future__ import annotations

import ast
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app import config
import gui_twitch
from tests.support.twitch import FakeTab, FakeTimer, build_session

SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TwitchSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_twitch = {key: value for key, value in config.TWITCH_BOT.items()}
        self.original_user_config = dict(config.user_config)

    def tearDown(self) -> None:
        config.TWITCH_BOT.clear()
        config.TWITCH_BOT.update(self.original_twitch)
        config.user_config.clear()
        config.user_config.update(self.original_user_config)

    # -- settings ---------------------------------------------------------

    def test_save_settings_writes_every_widget_value(self) -> None:
        """Was `test_save_twitch_settings_does_not_depend_on_main_interval_widget`."""
        tab = FakeTab(
            settings={
                "access_tier": "Everyone",
                "target_channel": "bonk",
                "global_cooldown_seconds": 5,
                "cooldown_seconds": 7,
                "stage_announcements": True,
                "commands_announcements": True,
                "commands": {"stats": True, "bans": False},
            }
        )
        harness = build_session(tab=tab)

        with patch.object(config, "save_config") as save_config:
            harness.session.save_settings()

        self.assertEqual(config.TWITCH_BOT["target_channel"], "bonk")
        self.assertEqual(config.TWITCH_BOT["global_cooldown_seconds"], 5)
        self.assertEqual(config.TWITCH_BOT["cooldown_seconds"], 7)
        self.assertTrue(config.TWITCH_BOT["commands_announcements"])
        self.assertTrue(config.TWITCH_BOT["commands"]["stats"])
        self.assertFalse(config.TWITCH_BOT["commands"]["bans"])
        self.assertTrue(save_config.called)

    def test_save_settings_leaves_untouched_commands_alone(self) -> None:
        """The commands dict is updated, not replaced.

        `TwitchCommandSettingsDialog` writes keys into the same dict that the
        tab does not render (`highlighted_disabled_items` lives elsewhere, but
        `templates` and the legacy `commands` alias do not). Replacing the dict
        wholesale would drop them silently on the next checkbox click.
        """
        config.TWITCH_BOT["commands"] = {"stats": False, "legacy": True}
        tab = FakeTab(settings={"commands": {"stats": True}})
        harness = build_session(tab=tab)

        with patch.object(config, "save_config"):
            harness.session.save_settings()

        self.assertTrue(config.TWITCH_BOT["commands"]["stats"])
        self.assertTrue(config.TWITCH_BOT["commands"]["legacy"])

    def test_save_auto_connect_persists_checkbox_state(self) -> None:
        """Was `test_save_twitch_auto_connect_persists_checkbox_state`."""
        harness = build_session(tab=FakeTab(auto_connect=True))

        with patch.dict(config.TWITCH_BOT, {"auto_connect": False}), patch.object(
            config, "save_config"
        ) as save_config:
            harness.session.save_auto_connect()

            self.assertTrue(config.TWITCH_BOT["auto_connect"])
            save_config.assert_called_once_with(config.user_config)

    def test_enabling_bonkhelp_shows_alias_dialog(self) -> None:
        """Was `test_enabling_twitch_help_shows_alias_dialog`."""
        shown = []

        def dialog_factory():
            shown.append(True)
            return SimpleNamespace(exec=lambda: 1, dont_show_again=True)

        harness = build_session(
            tab=FakeTab(bonkhelp=True), commands_help_dialog=dialog_factory
        )
        config.user_config["SKIP_TWITCH_HELP_WARNING"] = False

        with patch.object(config, "save_config"):
            harness.session.on_bonkhelp_toggled()

        self.assertEqual(shown, [True])
        self.assertTrue(config.user_config["SKIP_TWITCH_HELP_WARNING"])

    def test_bonkhelp_dialog_is_not_shown_when_the_warning_is_suppressed(self) -> None:
        """The default-exploding dialog factory is the assertion.

        `build_session` raises if a dialog is opened without arrangement, so
        this test passing *is* the proof that the suppressed branch opens none.
        """
        harness = build_session(tab=FakeTab(bonkhelp=True))
        config.user_config["SKIP_TWITCH_HELP_WARNING"] = True

        with patch.object(config, "save_config"):
            harness.session.on_bonkhelp_toggled()

    def test_command_settings_primes_stats_before_opening_the_dialog(self) -> None:
        """The order is behaviour: the dialog renders the cache it is handed."""
        order = []
        harness = build_session(
            command_settings_dialog=lambda: SimpleNamespace(
                exec=lambda: order.append("dialog")
            )
        )
        harness.session._prime_disabled_items = lambda: order.append("prime")
        harness.session._refresh_player_stats = lambda: order.append("refresh")

        harness.session.open_command_settings()

        self.assertEqual(order, ["prime", "refresh", "dialog"])

    # -- auth -------------------------------------------------------------

    def test_auth_success_starts_bot_when_auto_connect_is_enabled(self) -> None:
        """Was `test_twitch_auth_success_starts_bot_when_auto_connect_is_enabled`."""
        harness = build_session()
        seen = {}
        harness.session.validate_async = lambda **kwargs: seen.update(kwargs) or True

        with patch.dict(config.TWITCH_BOT, {"auto_connect": True}), patch(
            "app.twitch_session.set_twitch_oauth_token"
        ), patch.object(config, "save_config"):
            harness.session.on_auth_success("bonk", "token")

        self.assertEqual(
            seen,
            {
                "log_on_success": False,
                "start_bot_on_success": True,
                "fallback_username": "bonk",
                "context": "auth",
            },
        )
        self.assertIn(("show_validating",), harness.tab.calls)

    def test_auth_success_reports_a_credential_storage_failure(self) -> None:
        harness = build_session()
        harness.session.validate_async = lambda **kwargs: self.fail(
            "validation must not run when the token could not be stored"
        )

        with patch(
            "app.twitch_session.set_twitch_oauth_token", side_effect=OSError("locked")
        ):
            harness.session.on_auth_success("bonk", "token")

        self.assertIn(("show_auth_failed",), harness.tab.calls)
        self.assertEqual(harness.logs[-1][1], "error")

    def test_auth_error_re_enables_connect_and_logs(self) -> None:
        harness = build_session()

        harness.session.on_auth_error("denied")

        self.assertIn(("show_auth_failed",), harness.tab.calls)
        self.assertEqual(harness.logs, [("Twitch auth error: denied", "error")])

    # -- validation -------------------------------------------------------

    def test_validation_success_starts_bot_when_requested(self) -> None:
        """Was `test_twitch_validation_success_starts_bot_when_requested`."""
        harness = build_session()

        with patch.dict(config.TWITCH_BOT, {"username": "", "auto_connect": True}), patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch.object(config, "save_config"):
            harness.session._on_validation_finished(
                "token",
                SimpleNamespace(valid=True, login="bonk"),
                False,
                True,
                "fallback",
                "auth",
            )
            self.assertEqual(config.TWITCH_BOT["username"], "bonk")

        self.assertEqual(harness.timer.starts, 1)
        self.assertEqual(len(harness.calls["bot_workers"]), 1)

    def test_stale_validation_does_not_keep_pending_bot_start(self) -> None:
        """Was `test_stale_twitch_validation_does_not_keep_pending_bot_start`."""
        harness = build_session()
        harness.session._start_bot_after_validation = True

        with patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="new-token"
        ):
            harness.session._on_validation_finished(
                "old-token",
                SimpleNamespace(valid=True, login="bonk"),
                False,
                True,
                "fallback",
                "start_bot",
            )

        self.assertFalse(harness.session._start_bot_after_validation)
        self.assertEqual(harness.calls["bot_workers"], [])

    def test_a_validation_that_starts_the_bot_clears_the_pending_flag(self) -> None:
        """Otherwise the *next* validation starts a second bot unasked.

        The stale-token test above clears the flag through a different branch,
        so it does not cover this one -- measured: the "pending bot start never
        cleared" mutation survived the whole module until this test existed.
        """
        harness = build_session()
        # The flag must be *set* going in, or removing the line that clears it
        # changes nothing and the test passes either way. Measured: it did.
        harness.session._start_bot_after_validation = True

        with patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch.object(config, "save_config"):
            harness.session._on_validation_finished(
                "token", SimpleNamespace(valid=True, login="bonk"),
                False, False, "", "periodic",
            )
            self.assertFalse(harness.session._start_bot_after_validation)
            self.assertEqual(len(harness.calls["bot_workers"]), 1)

            # The first worker is still running, so a second start would be
            # suppressed by the "already running" guard and prove nothing.
            harness.session.stop_bot()
            harness.session._on_validation_finished(
                "token", SimpleNamespace(valid=True, login="bonk"),
                False, False, "", "periodic",
            )

        self.assertEqual(len(harness.calls["bot_workers"]), 1)

    def test_transient_validation_failure_keeps_the_token(self) -> None:
        harness = build_session()

        with patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch("app.twitch_session.delete_twitch_oauth_token") as delete_token:
            harness.session._on_validation_finished(
                "token",
                SimpleNamespace(valid=False, transient_error=True, error_message="down"),
                False,
                False,
                "",
                "periodic",
            )

        delete_token.assert_not_called()
        self.assertEqual(harness.timer.starts, 1)
        self.assertNotIn(("show_disconnected",), harness.tab.calls)

    def test_validate_clears_an_invalid_token(self) -> None:
        """Was `test_validate_twitch_session_clears_invalid_token`."""
        harness = build_session(
            validate_token=lambda _token: SimpleNamespace(
                valid=False,
                transient_error=False,
                error_message="Token is no longer valid.",
            )
        )

        with patch.dict(config.TWITCH_BOT, {"username": "bonk"}), patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch(
            "app.twitch_session.delete_twitch_oauth_token"
        ) as delete_token, patch.object(config, "save_config"):
            valid = harness.session.validate(log_on_success=False)
            self.assertEqual(config.TWITCH_BOT["username"], "")

        self.assertFalse(valid)
        delete_token.assert_called_once_with()
        self.assertEqual(harness.timer.stops, 1)
        self.assertIn(("show_disconnected",), harness.tab.calls)

    def test_validate_async_stops_the_timer_without_a_token(self) -> None:
        harness = build_session()

        with patch("app.twitch_session.get_twitch_oauth_token", return_value=""):
            self.assertFalse(harness.session.validate_async())

        self.assertEqual(harness.timer.stops, 1)
        self.assertEqual(harness.calls["validation"], [])

    def test_validate_async_does_not_stack_workers(self) -> None:
        harness = build_session(validation_running=True)

        with patch("app.twitch_session.get_twitch_oauth_token", return_value="token"):
            self.assertTrue(harness.session.validate_async())
            self.assertTrue(
                harness.session.validate_async(start_bot_on_success=True)
            )

        self.assertEqual(len(harness.calls["validation"]), 1)
        self.assertTrue(harness.session._start_bot_after_validation)

    def test_the_validation_timer_runs_hourly_and_asks_for_no_logging(self) -> None:
        """The periodic re-validation the mixin wired with a lambda."""
        harness = build_session()
        self.assertEqual(harness.timer.interval, 60 * 60 * 1000)

        seen = {}
        harness.session.validate_async = lambda **kwargs: seen.update(kwargs)
        harness.timer.fire()

        self.assertEqual(seen, {"log_on_success": False, "context": "periodic"})

    # -- disconnect / revoke ----------------------------------------------

    def test_disconnect_logs_revoke_warning_without_restoring_token(self) -> None:
        """Was `test_disconnect_twitch_logs_revoke_warning_without_restoring_token`."""
        harness = build_session(revoke_outcome=(False, "timeout"))

        with patch.dict(config.TWITCH_BOT, {"username": "bonk"}), patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch(
            "app.twitch_session.delete_twitch_oauth_token"
        ) as delete_token, patch.object(config, "save_config"):
            harness.session.disconnect()
            self.assertEqual(config.TWITCH_BOT["username"], "")

        delete_token.assert_called_once_with()
        self.assertEqual(harness.calls["revoke"][0].token, "token")
        self.assertEqual(
            harness.logs[-1], ("Twitch token revoke warning: timeout", "warning")
        )
        self.assertIn(("show_disconnected",), harness.tab.calls)

    def test_disconnect_without_a_token_revokes_nothing(self) -> None:
        harness = build_session()

        with patch(
            "app.twitch_session.get_twitch_oauth_token", return_value=""
        ), patch("app.twitch_session.delete_twitch_oauth_token"), patch.object(
            config, "save_config"
        ):
            harness.session.disconnect()

        self.assertEqual(harness.calls["revoke"], [])

    def test_a_successful_revoke_logs_nothing(self) -> None:
        harness = build_session(revoke_outcome=(True, ""))

        with patch(
            "app.twitch_session.get_twitch_oauth_token", return_value="token"
        ), patch("app.twitch_session.delete_twitch_oauth_token"), patch.object(
            config, "save_config"
        ):
            harness.session.disconnect()

        self.assertEqual(harness.logs, [])

    # -- bot lifecycle ----------------------------------------------------

    def test_composition_root_passes_the_explicit_session_stats_owner(self) -> None:
        provider = SimpleNamespace(format_twitch_session_summary=lambda: "summary")
        app = SimpleNamespace(window=None)

        with patch.object(gui_twitch, "QTimer", lambda _parent=None: FakeTimer()):
            session = gui_twitch.build_twitch_session(
                app,
                FakeTab(),
                session_stats_provider=provider,
            )

        self.assertIs(session._session_stats_provider(), provider)
        self.assertTrue(
            callable(
                getattr(
                    session._session_stats_provider(),
                    "format_twitch_session_summary",
                    None,
                )
            )
        )

    def test_starting_the_bot_hands_the_worker_the_tracker_and_the_provider(self) -> None:
        """The `!session` coupling, pinned.

        `TwitchBotWorker` finds `format_twitch_session_summary` on whatever it
        is given. If the provider ever became the session or the tab, the
        command would answer empty with no exception -- so what arrives here is
        asserted rather than assumed.
        """
        tracker = object()
        provider = SimpleNamespace(format_twitch_session_summary=lambda: "summary")
        harness = build_session(tracker=tracker, provider=provider)

        harness.session._start_bot_worker()

        worker = harness.calls["bot_workers"][0]
        self.assertIs(worker.tracker, tracker)
        self.assertIs(worker.provider, provider)
        self.assertTrue(
            callable(getattr(worker.provider, "format_twitch_session_summary", None))
        )
        self.assertIn(("show_bot_running",), harness.tab.calls)

    def test_starting_the_bot_twice_does_not_replace_a_running_worker(self) -> None:
        harness = build_session()
        harness.session._start_bot_worker()
        harness.session._start_bot_worker()

        self.assertEqual(len(harness.calls["bot_workers"]), 1)

    def test_stop_waits_for_the_worker(self) -> None:
        harness = build_session()
        harness.session._start_bot_worker()

        harness.session.stop_bot()

        worker = harness.calls["bot_workers"][0]
        self.assertEqual(worker.stopped, 1)
        self.assertEqual(worker.waited, [2000])
        self.assertFalse(harness.session.is_bot_active())

    def test_start_bot_without_a_token_reports_not_connected(self) -> None:
        harness = build_session()

        with patch("app.twitch_session.get_twitch_oauth_token", return_value=""):
            harness.session.start_bot()

        self.assertEqual(
            harness.logs, [("Cannot start Twitch Bot: Not connected.", "error")]
        )
        self.assertEqual(harness.calls["bot_workers"], [])

    def test_a_finished_worker_keeps_an_error_status_visible(self) -> None:
        harness = build_session(tab=FakeTab(bot_status="Error: banned"))

        harness.session.on_bot_finished()

        self.assertIn(("show_bot_stopped",), harness.tab.calls)
        self.assertNotIn(("show_bot_status", "Stopped"), harness.tab.calls)

    def test_a_finished_worker_falls_back_to_stopped(self) -> None:
        harness = build_session(tab=FakeTab(bot_status="Connected"))

        harness.session.on_bot_finished()

        self.assertIn(("show_bot_status", "Stopped"), harness.tab.calls)


class TwitchBoundaryTests(unittest.TestCase):
    """Step 23's third exit criterion, checked once and structurally.

    "No Twitch code reaches `tabview`, `window`, tracker, player-stats client,
    or logging through ambient `MegabonkApp.self`." One AST pass over the two
    component modules proves it for every name at once, which is why there is
    no per-name test.
    """

    FORBIDDEN = (
        "window",
        "tabview",
        "live_run_tracker",
        "tab_in_game_overlay",
        "refresh_live_player_stats_now",
        "player_stats_disabled_items_cache",
        "player_stats_disabled_items_refresh_pending",
    )

    COMPONENT_MODULES = (
        os.path.join("app", "twitch_session.py"),
        os.path.join("ui", "tabs", "twitch", "panel.py"),
    )

    def test_the_component_names_no_application_attribute(self) -> None:
        for relative in self.COMPONENT_MODULES:
            path = os.path.join(SRC_ROOT, relative)
            with self.subTest(module=relative):
                tree = ast.parse(open(path, encoding="utf-8").read())
                reached = {
                    node.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN
                }
                self.assertEqual(
                    sorted(reached),
                    [],
                    f"{relative} reaches application state: {sorted(reached)}",
                )

    def test_the_scan_would_notice(self) -> None:
        """The guard above passes trivially if the walk reads nothing."""
        tree = ast.parse("self.window.show()\nx.tabview.addTab(1, 2)\n")
        reached = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN
        }
        self.assertEqual(sorted(reached), ["tabview", "window"])

    def test_the_session_takes_no_qt_import(self) -> None:
        """`app/` gets its timer and its threads as factories, not imports.

        This is what keeps `app.twitch_session` off `twitch_auth`/`twitch_bot`,
        which would otherwise need new `TOPLEVEL_DEBT` entries in an allowlist
        that may only shrink.
        """
        path = os.path.join(SRC_ROOT, "app", "twitch_session.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(
            imported & {"PySide6", "twitch_auth", "twitch_bot", "gui_dialogs"},
            set(),
        )


class TwitchTabTests(unittest.TestCase):
    """The widget half, without building widgets.

    `TwitchTab.build()` needs real offscreen Qt, and the suite does not run it
    -- the same rule `tests/support/templates_panel.py` states for
    `TemplatesPanel.build()`, and for a measured reason: constructing the real
    widgets here crashes the interpreter partway through the run once earlier
    modules have already made a `QApplication` (the 0xC0000409 teardown fault
    the roadmap records). So these tests assign the private fields they assert
    on, and the **built** tab is driven by `tools/step23_twitch_trace.py`
    across its scenarios, which is where widget construction belongs.
    """

    def _tab(self, **fields):
        from ui.tabs.twitch import TwitchTab

        tab = TwitchTab()
        for name, value in fields.items():
            setattr(tab, name, value)
        return tab

    def test_the_command_grid_holds_every_command_the_session_saves(self) -> None:
        from ui.tabs.twitch.panel import _COMMAND_KEYS

        self.assertEqual(
            sorted(_COMMAND_KEYS),
            sorted(
                [
                    "bans",
                    "bonkhelp",
                    "chaos",
                    "chests",
                    "disabled",
                    "items",
                    "kps",
                    "powerups",
                    "presets",
                    "scanner",
                    "session",
                    "stages",
                    "stats",
                    "tomes",
                    "weapons",
                ]
            ),
        )

    def test_bonkhelp_falls_back_to_the_legacy_commands_key(self) -> None:
        """The checkbox was `commands` before it was `bonkhelp`."""
        from ui.tabs.twitch.panel import command_checked

        self.assertFalse(command_checked({"commands": False}, "bonkhelp"))
        self.assertTrue(command_checked({"commands": False, "bonkhelp": True}, "bonkhelp"))
        self.assertTrue(command_checked({}, "bonkhelp"))

    def test_the_three_opt_in_commands_start_unchecked(self) -> None:
        from ui.tabs.twitch.panel import command_checked

        for key in ("chests", "presets", "disabled"):
            with self.subTest(command=key):
                self.assertFalse(command_checked({}, key))
        self.assertTrue(command_checked({}, "stats"))

    def test_read_settings_normalises_the_target_channel(self) -> None:
        tab = self._tab(
            _tier_combo=SimpleNamespace(currentText=lambda: "Mods & VIPs"),
            _target_channel_entry=SimpleNamespace(text=lambda: "  #BonkChannel "),
            _global_cooldown_spin=SimpleNamespace(value=lambda: 3),
            _cooldown_spin=SimpleNamespace(value=lambda: 9),
            _stage_announcements_cb=SimpleNamespace(isChecked=lambda: True),
            _commands_announcements_cb=SimpleNamespace(isChecked=lambda: False),
            _command_cbs={"stats": SimpleNamespace(isChecked=lambda: True)},
        )

        settings = tab.read_settings()

        self.assertEqual(settings["target_channel"], "bonkchannel")
        self.assertEqual(settings["access_tier"], "Mods & VIPs")
        self.assertEqual(settings["global_cooldown_seconds"], 3)
        self.assertEqual(settings["cooldown_seconds"], 9)
        self.assertEqual(settings["commands"], {"stats": True})

    def test_connected_and_disconnected_swap_the_two_buttons(self) -> None:
        label, connect, disconnect, entry = [], [], [], []
        tab = self._tab(
            _auth_status_label=SimpleNamespace(setText=label.append),
            _connect_btn=SimpleNamespace(setVisible=connect.append),
            _disconnect_btn=SimpleNamespace(setVisible=disconnect.append),
            _target_channel_entry=SimpleNamespace(setPlaceholderText=entry.append),
        )

        tab.show_connected("bonk")
        self.assertIn("bonk", label[-1])
        self.assertEqual((connect[-1], disconnect[-1]), (False, True))
        self.assertEqual(entry, ["bonk"])

        tab.show_disconnected()
        self.assertIn("Not connected", label[-1])
        self.assertEqual((connect[-1], disconnect[-1]), (True, False))

    def test_bot_status_colours_follow_the_message(self) -> None:
        for status, colour in (
            ("Error: banned", "#f08b72"),
            ("Connected", "#4fd67a"),
            ("Connecting...", "#ffd23f"),
            ("Stopped", "#f08b72"),
            ("Idle", "#A0B0C5"),
        ):
            with self.subTest(status=status):
                shown = []
                tab = self._tab(_bot_status_label=SimpleNamespace(setText=shown.append))
                tab.show_bot_status(status)
                self.assertIn(colour, shown[0])
                self.assertNotIn("Status:", shown[0])


if __name__ == "__main__":
    unittest.main()
