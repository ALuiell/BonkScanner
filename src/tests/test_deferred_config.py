from copy import deepcopy
import threading
import time
from unittest.mock import patch

import src  # noqa: F401

from app import config
from app.deferred_config import DeferredConfigSaves


class Repository:
    def __init__(self, snapshot):
        self.data = deepcopy(snapshot)

    def snapshot(self):
        return deepcopy(self.data)


def finish(saver):
    saver.begin_shutdown()
    deadline = time.monotonic() + 3
    while not saver.complete() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert saver.complete()


def test_rapid_changes_merge_latest_value_with_newer_synchronous_save():
    lock = threading.RLock()
    repo = Repository({"spin": 0, "other": "initial"})
    live = {"spin": 0, "other": "initial"}
    saves = []

    def commit(candidate):
        repo.data = deepcopy(candidate)
        saves.append(deepcopy(candidate))
        return config.ConfigSaveResult(True)

    with patch.object(config, "config_lock", lock), patch.object(config, "_repository", repo), patch.object(config, "user_config", live), patch.object(config, "save_config", commit):
        saver = DeferredConfigSaves(delay=10)
        for value in range(1, 11):
            live["spin"] = value
            saver.request(("spin",), value)
        # A different synchronous save runs while the spinner write is pending.
        with lock:
            live["other"] = "newer"
            commit(live)
        finish(saver)
    assert saves[-1] == {"spin": 10, "other": "newer"}
    assert len(saves) == 2


def test_superseded_queued_value_cannot_overwrite_synchronous_save():
    lock = threading.RLock()
    repo = Repository({"spin": 0})
    live = {"spin": 1}

    def commit(candidate):
        repo.data = deepcopy(candidate)
        return config.ConfigSaveResult(True)

    with patch.object(config, "config_lock", lock), patch.object(config, "_repository", repo), patch.object(config, "user_config", live), patch.object(config, "save_config", commit):
        saver = DeferredConfigSaves(delay=10)
        saver.request(("spin",), 1)
        with lock:
            live["spin"] = 2
            commit(live)
        finish(saver)
    assert repo.data == {"spin": 2}


def test_failed_save_reports_error_without_rolling_back_later_live_changes():
    lock = threading.RLock()
    repo = Repository({"spin": 0})
    live = {"spin": 1, "other": "later"}
    with patch.object(config, "config_lock", lock), patch.object(config, "_repository", repo), patch.object(config, "user_config", live), patch.object(config, "save_config", return_value=config.ConfigSaveResult(False, "conflict")), patch("app.deferred_config.log_runtime_event"):
        saver = DeferredConfigSaves(delay=10)
        saver.request(("spin",), 1)
        finish(saver)
        assert saver.result() == "conflict"
    assert live == {"spin": 1, "other": "later"}
    assert repo.data == {"spin": 0}


def test_requests_do_not_wait_for_repository_disk_lock():
    lock = threading.RLock()
    repo = Repository({"spin": 0})
    live = {"spin": 1}
    with patch.object(config, "config_lock", lock), patch.object(config, "_repository", repo), patch.object(config, "user_config", live), patch.object(config, "save_config", return_value=config.ConfigSaveResult(True)):
        saver = DeferredConfigSaves(delay=0)
        with lock:
            saver.request(("spin",), 1)
            live["spin"] = 2
            saver.request(("spin",), 2)
        finish(saver)


def test_real_repository_flush_keeps_unrelated_synchronous_change(tmp_path):
    from app.config_repository import ConfigRepository

    path = tmp_path / "config.json"
    repository = ConfigRepository(path)
    repository.load()
    assert repository.commit({"spin": 0, "other": "initial"}).success
    live = {"spin": 1, "other": "initial"}
    with patch.object(config, "config_lock", repository.lock), patch.object(config, "_repository", repository), patch.object(config, "config_path", str(path)), patch.object(config, "user_config", live):
        saver = DeferredConfigSaves(delay=10)
        saver.request(("spin",), 1)
        live["other"] = "newer"
        assert config.save_config(live).success
        finish(saver)
        assert not saver.result()
    assert repository.load().snapshot == {"spin": 1, "other": "newer"}


def test_failure_callback_reports_reason():
    lock = threading.RLock()
    repo = Repository({"spin": 0})
    live = {"spin": 1}
    reported = []
    with patch.object(config, "config_lock", lock), patch.object(config, "_repository", repo), patch.object(config, "user_config", live), patch.object(config, "save_config", return_value=config.ConfigSaveResult(False, "read only")), patch("app.deferred_config.log_runtime_event"):
        saver = DeferredConfigSaves(delay=10)
        saver.request(("spin",), 1, reported.append)
        finish(saver)
    assert reported == ["read only"]


def test_external_config_change_is_reported_and_preserved(tmp_path):
    from app.config_repository import ConfigRepository

    path = tmp_path / "config.json"
    repository = ConfigRepository(path)
    repository.load()
    assert repository.commit({"spin": 0}).success
    live = {"spin": 1, "other": "current session"}
    reported = []
    with patch.object(config, "config_lock", repository.lock), patch.object(config, "_repository", repository), patch.object(config, "config_path", str(path)), patch.object(config, "user_config", live), patch("app.deferred_config.log_runtime_event"):
        saver = DeferredConfigSaves(delay=10)
        saver.request(("spin",), 1, reported.append)
        path.write_text('{"spin": 42}', encoding="utf-8")
        finish(saver)
    assert 'changed outside' in reported[0]
    assert path.read_text(encoding="utf-8") == '{"spin": 42}'
    assert live == {"spin": 1, "other": "current session"}


def test_new_application_lifetime_can_restart_stopped_singleton():
    from app import deferred_config

    saver = DeferredConfigSaves()
    with patch.object(deferred_config, "_saves", saver):
        saver.begin_shutdown()
        assert saver.complete()
        deferred_config.start_config_saves()
        assert deferred_config._saves is not saver
        assert not deferred_config._saves.is_closing()


def test_deferred_twitch_settings_apply_without_synchronous_save():
    from types import SimpleNamespace
    from app.twitch_session import TwitchSession

    bot = {"commands": {"test": True}}
    live = {"TWITCH_BOT": bot}
    view = SimpleNamespace(read_settings=lambda: {"global_cooldown": 12, "commands": {"test": False}})
    owner = SimpleNamespace(_view=view, _log=lambda *_args, **_kwargs: None)
    with patch.object(config, "TWITCH_BOT", bot), patch.object(config, "user_config", live), patch.object(config, "save_config") as sync, patch("app.twitch_session.request_config_save") as queued:
        TwitchSession.save_settings(owner, deferred=True)
    assert bot == {"global_cooldown": 12, "commands": {"test": False}}
    sync.assert_not_called()
    assert queued.call_args.args[:2] == (("TWITCH_BOT",), bot)


def test_deferred_obs_rows_publish_without_synchronous_save():
    from types import SimpleNamespace
    from gui_overlay import Overlay

    overlay = {"widgets": [{"id": "build_progression", "max_rows": 5}]}
    live = {"OVERLAY": overlay}
    published = []
    owner = SimpleNamespace(update_overlay_state_from_tracker=lambda: published.append(True), _log=lambda *_args, **_kwargs: None)
    with patch.object(config, "OVERLAY", overlay), patch.object(config, "user_config", live), patch.object(config, "save_config") as sync, patch("gui_overlay.request_config_save") as queued:
        Overlay._on_overlay_build_rows_changed(owner, 8)
    assert overlay["widgets"][0]["max_rows"] == 8
    assert published == [True]
    sync.assert_not_called()
    assert queued.call_args.args[:2] == (("OVERLAY",), overlay)


def test_deferred_recording_threshold_is_immediately_readable():
    from app.vod_library import minimum_snapshot_count, set_minimum_snapshot_count

    live = {}
    with patch.object(config, "user_config", live), patch.object(config, "save_config") as sync, patch("app.deferred_config.request_config_save") as queued:
        set_minimum_snapshot_count(9)
        assert minimum_snapshot_count() == 9
    sync.assert_not_called()
    assert queued.call_args.args[:2] == (("recordings_minimum_snapshot_count",), 9)
