from __future__ import annotations

import threading
import types
import unittest
from unittest.mock import patch

import gui
import scanner_loop
from game_data import MapStat
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError


class FakeClient:
    def __init__(self, *, raw_stats, shady_guy_items, generation_state=None, map_stats=None) -> None:
        self.raw_stats = raw_stats
        self.shady_guy_items = shady_guy_items
        self.generation_state = generation_state or object()
        self.map_stats = map_stats or {"Moais": 999}
        self.get_map_stats_calls = 0
        self.get_shady_guy_items_calls = 0
        self.wait_calls = 0

    def wait_for_map_ready(self, **_kwargs):
        self.wait_calls += 1
        return self.raw_stats

    def get_map_generation_state(self):
        return self.generation_state

    def get_map_stats(self):
        self.get_map_stats_calls += 1
        return self.map_stats

    def get_shady_guy_items(self):
        self.get_shady_guy_items_calls += 1
        return self.shady_guy_items


class FailingClient(FakeClient):
    def __init__(self, exc: Exception) -> None:
        super().__init__(raw_stats={}, shady_guy_items=[])
        self.exc = exc

    def wait_for_map_ready(self, **_kwargs):
        raise self.exc


class ScannerLoopTests(unittest.TestCase):
    def make_harness(
        self,
        client,
        *,
        adapt_map_stats=None,
        evaluate_candidate=None,
        wait_for_game_window_focus=None,
        handle_confirmed_target_window=None,
        client_factory=None,
    ):
        state = types.SimpleNamespace(client=client, is_running=True, is_ready_to_start=True)
        stop_event = threading.Event()
        scan_event = threading.Event()
        scan_event.set()
        logs: list[tuple[object, str | None]] = []
        status_updates: list[str] = []
        close_calls: list[str] = []
        reroll_calls: list[str] = []
        target_found_calls: list[str] = []
        handle_calls: list[str] = []

        def log(message, tag=None):
            logs.append((message, tag))

        def after(_delay, callback):
            callback()

        def update_status_ui():
            status_updates.append("update_status_ui")

        def close_client():
            if state.client is not None:
                close_calls.append("close_client")
                state.client = None
                stop_event.set()

        def reroll_map():
            reroll_calls.append("reroll_map")
            stop_event.set()

        def log_target_found(template_name):
            target_found_calls.append(template_name)

        def handle_target(process_name):
            handle_calls.append(process_name)
            if handle_confirmed_target_window is None:
                return True
            return handle_confirmed_target_window(process_name)

        loop = scanner_loop.ScannerLoop(
            state=state,
            config=gui.config,
            game_data_client_factory=client_factory or (lambda process_name: client),
            adapt_map_stats=adapt_map_stats or (lambda raw_stats: raw_stats),
            scanner_logic=gui.scanner_logic,
            stop_event=stop_event,
            scan_event=scan_event,
            log=log,
            after=after,
            update_status_ui=update_status_ui,
            wait_for_game_window_focus=wait_for_game_window_focus or (lambda _process_name: True),
            check_best_map=lambda _stats: None,
            check_worst_map=lambda _stats: None,
            evaluate_candidate=evaluate_candidate or (lambda _stats: None),
            log_target_found=log_target_found,
            handle_confirmed_target_window=handle_target,
            reroll_map=reroll_map,
            close_client=close_client,
            sleep=lambda _seconds: None,
        )

        return types.SimpleNamespace(
            loop=loop,
            state=state,
            stop_event=stop_event,
            scan_event=scan_event,
            logs=logs,
            status_updates=status_updates,
            close_calls=close_calls,
            reroll_calls=reroll_calls,
            target_found_calls=target_found_calls,
            handle_calls=handle_calls,
        )

    def test_stop_cleanup_clears_events_and_updates_status(self) -> None:
        harness = self.make_harness(client=object())
        harness.stop_event.set()

        harness.loop.run()

        self.assertFalse(harness.scan_event.is_set())
        self.assertFalse(harness.state.is_running)
        self.assertFalse(harness.state.is_ready_to_start)
        self.assertIsNone(harness.state.client)
        self.assertEqual(harness.close_calls, ["close_client"])
        self.assertEqual(harness.status_updates, ["update_status_ui"])

    def test_stable_snapshot_reuse_does_not_read_map_stats_again_before_candidate_validation(self) -> None:
        client = FakeClient(
            raw_stats={
                MapStat.SHADY_GUY: types.SimpleNamespace(max=1),
                "Moais": 4,
                "Microwaves": 1,
            },
            shady_guy_items=[
                types.SimpleNamespace(name="SoulHarvester"),
                types.SimpleNamespace(name="SoulHarvester"),
                types.SimpleNamespace(name="SoulHarvester"),
            ],
        )
        harness = self.make_harness(
            client,
            adapt_map_stats=lambda _raw_stats: {"Moais": 4, "Microwaves": 1, "Shady Guy": 1},
            evaluate_candidate=lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None,
        )
        def confirm_target(process_name):
            harness.handle_calls.append(process_name)
            harness.stop_event.set()
            return True

        harness.loop.handle_confirmed_target_window = confirm_target

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(client.get_map_stats_calls, 0)
        self.assertEqual(client.get_shady_guy_items_calls, 1)
        self.assertEqual(harness.target_found_calls, ["Perfect"])
        self.assertEqual(harness.handle_calls, ["Megabonk.exe"])
        self.assertIn(
            ("Shady Guy items: [SoulHarvester, SoulHarvester, SoulHarvester]", "success"),
            harness.logs,
        )
        self.assertTrue(any(str(message).startswith("Map Stats: ") and tag == "success" for message, tag in harness.logs))

    def test_candidate_rejection_logs_when_shady_guy_items_are_empty(self) -> None:
        client = FakeClient(
            raw_stats={"Moais": 4, "Microwaves": 1},
            shady_guy_items=[],
        )
        harness = self.make_harness(
            client,
            adapt_map_stats=lambda _raw_stats: {"Moais": 4, "Microwaves": 1},
            evaluate_candidate=lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None,
        )

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(harness.target_found_calls, [])
        self.assertEqual(harness.handle_calls, [])
        self.assertEqual(harness.reroll_calls, ["reroll_map"])
        self.assertTrue(
            any(
                tag == "warning" and "rejected: Shady Guy items are empty" in str(message)
                for message, tag in harness.logs
            )
        )

    def test_candidate_rejection_logs_when_required_shady_guy_items_are_missing(self) -> None:
        client = FakeClient(
            raw_stats={"Moais": 4, "Microwaves": 1},
            shady_guy_items=[types.SimpleNamespace(name="GymSauce"), types.SimpleNamespace(name="Beacon")],
        )
        harness = self.make_harness(
            client,
            adapt_map_stats=lambda raw_stats: raw_stats,
            evaluate_candidate=lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None,
        )

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(harness.target_found_calls, [])
        self.assertEqual(harness.handle_calls, [])
        self.assertEqual(harness.reroll_calls, ["reroll_map"])
        self.assertTrue(
            any(
                tag == "warning" and "none of the required Shady Guy items were found" in str(message)
                for message, tag in harness.logs
            )
        )

    def test_candidate_rejection_logs_when_shady_guy_item_read_fails(self) -> None:
        class ItemReadFailClient(FakeClient):
            def get_shady_guy_items(self):
                raise MemoryReadError("boom")

        client = ItemReadFailClient(
            raw_stats={"Moais": 4, "Microwaves": 1},
            shady_guy_items=[],
        )
        harness = self.make_harness(
            client,
            adapt_map_stats=lambda _raw_stats: {"Moais": 4, "Microwaves": 1},
            evaluate_candidate=lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None,
        )

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(harness.target_found_calls, [])
        self.assertEqual(harness.handle_calls, [])
        self.assertEqual(harness.reroll_calls, ["reroll_map"])
        self.assertTrue(
            any(
                tag == "warning" and "rejected: failed to read Shady Guy items" in str(message)
                for message, tag in harness.logs
            )
        )

    def test_candidate_rejection_logs_when_shady_guy_vendor_count_does_not_match_item_count(self) -> None:
        client = FakeClient(
            raw_stats={
                MapStat.SHADY_GUY: types.SimpleNamespace(max=2),
                "Moais": 4,
                "Microwaves": 1,
            },
            shady_guy_items=[types.SimpleNamespace(name="SoulHarvester")],
        )
        harness = self.make_harness(
            client,
            adapt_map_stats=lambda raw_stats: {"Moais": 4, "Microwaves": 1, "Shady Guy": 2},
            evaluate_candidate=lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None,
        )

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(harness.target_found_calls, [])
        self.assertEqual(harness.handle_calls, [])
        self.assertEqual(harness.reroll_calls, ["reroll_map"])
        self.assertTrue(
            any(
                tag == "warning" and "expected 6 Shady Guy items from 2 vendors, but read 1" in str(message)
                for message, tag in harness.logs
            )
        )

    def test_timeout_forces_reroll_and_resets_cached_state(self) -> None:
        client = FailingClient(TimeoutError("stuck"))
        harness = self.make_harness(client)
        harness.loop.last_state = object()
        harness.loop.last_stats = {"cached": True}

        with patch.object(gui.config, "MIN_DELAY", 0):
            harness.loop.run()

        self.assertEqual(harness.reroll_calls, ["reroll_map"])
        self.assertIsNone(harness.loop.last_state)
        self.assertIsNone(harness.loop.last_stats)
        self.assertTrue(
            any(tag == "warning" and "Map loading timeout: stuck" in str(message) for message, tag in harness.logs)
        )
        self.assertTrue(
            any(tag == "warning" and "Forcing reroll to unstick" in str(message) for message, tag in harness.logs)
        )

    def test_lost_process_module_and_memory_errors_clear_state_and_log_the_same_message(self) -> None:
        for exc in (
            ProcessNotFoundError("lost process"),
            ModuleNotFoundError("lost module"),
            MemoryReadError("lost memory"),
        ):
            with self.subTest(exc=type(exc).__name__):
                client = FailingClient(exc)
                harness = self.make_harness(client)
                harness.loop.wait_state = "process"

                with patch.object(gui.config, "MIN_DELAY", 0):
                    harness.loop.run()

                self.assertFalse(harness.state.is_running)
                self.assertFalse(harness.state.is_ready_to_start)
                self.assertFalse(harness.scan_event.is_set())
                self.assertIsNone(harness.state.client)
                self.assertIsNone(harness.loop.wait_state)
                self.assertEqual(harness.close_calls, ["close_client"])
                self.assertTrue(
                    any(
                        tag == "error" and "Lost connection to the game: " in str(message)
                        for message, tag in harness.logs
                    )
                )


if __name__ == "__main__":
    unittest.main()
