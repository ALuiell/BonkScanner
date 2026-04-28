from __future__ import annotations

import time
from typing import Any, Callable

from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError


LogFunction = Callable[[str, str | None], None]


class ScannerLoop:
    def __init__(
        self,
        *,
        state,
        config,
        game_data_client_factory,
        adapt_map_stats: Callable[[dict[Any, Any]], dict[str, int]],
        scanner_logic,
        stop_event,
        scan_event,
        log: LogFunction,
        after: Callable[[int, Callable[[], None]], object],
        update_status_ui: Callable[[], None],
        wait_for_game_window_focus: Callable[[str], bool],
        check_best_map: Callable[[dict[str, int]], None],
        check_worst_map: Callable[[dict[str, int]], None],
        evaluate_candidate: Callable[[dict[str, int]], dict[str, Any] | None],
        log_target_found: Callable[[str], None],
        handle_confirmed_target_window: Callable[[str], bool],
        reroll_map: Callable[[], None],
        close_client: Callable[[], None],
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.state = state
        self.config = config
        self.game_data_client_factory = game_data_client_factory
        self.adapt_map_stats = adapt_map_stats
        self.scanner_logic = scanner_logic
        self.stop_event = stop_event
        self.scan_event = scan_event
        self.log = log
        self.after = after
        self.update_status_ui = update_status_ui
        self.wait_for_game_window_focus = wait_for_game_window_focus
        self.check_best_map = check_best_map
        self.check_worst_map = check_worst_map
        self.evaluate_candidate = evaluate_candidate
        self.log_target_found = log_target_found
        self.handle_confirmed_target_window = handle_confirmed_target_window
        self.reroll_map = reroll_map
        self.close_client = close_client
        self.sleep = sleep
        self.monotonic = monotonic

        self.wait_state: str | None = None
        self.last_state = None
        self.last_stats = None
        self.last_reroll_time = self.monotonic()
        self.is_first_scan = True

    def _get_client(self):
        return getattr(self.state, "client", None)

    def _set_client(self, value) -> None:
        setattr(self.state, "client", value)

    def _set_running(self, value: bool) -> None:
        setattr(self.state, "is_running", value)

    def _set_ready(self, value: bool) -> None:
        setattr(self.state, "is_ready_to_start", value)

    def _cleanup(self) -> None:
        self.close_client()
        self._set_running(False)
        self._set_ready(False)
        self.scan_event.clear()
        self.after(0, self.update_status_ui)

    def _handle_candidate(self, process_name: str, raw_stats: dict[Any, Any], stats: dict[str, int], candidate: dict[str, Any]) -> bool:
        t_name = candidate.get("name")
        t_color = candidate.get("color", "BLUE").upper()
        score_text = (
            f" (Score: {candidate.get('score', 0):.1f})"
            if getattr(self.config, "EVALUATION_MODE", "templates") == "scores"
            else ""
        )

        try:
            shady_guy_items = self._get_client().get_shady_guy_items()
        except MemoryReadError as exc:
            self.log(
                f"[WAIT] Candidate '{t_name}{score_text}' rejected: failed to read Shady Guy items ({exc}).",
                tag="warning",
            )
            return False

        if not shady_guy_items:
            self.log(
                f"[WAIT] Candidate '{t_name}{score_text}' rejected: Shady Guy items are empty.",
                tag="warning",
            )
            return False

        if not self.scanner_logic.has_required_shady_guy_item(shady_guy_items):
            required_items_text = ", ".join(sorted(self.scanner_logic.REQUIRED_SHADY_GUY_ITEMS))
            self.log(
                f"[WAIT] Candidate '{t_name}{score_text}' rejected: none of the required "
                f"Shady Guy items were found ({required_items_text}).",
                tag="warning",
            )
            return False

        shady_guy_count = self.scanner_logic.shady_guy_count(raw_stats, stats)
        expected_item_count = shady_guy_count * 3
        actual_item_count = len(shady_guy_items)
        if actual_item_count != expected_item_count:
            self.log(
                f"[WAIT] Candidate '{t_name}{score_text}' rejected: expected "
                f"{expected_item_count} Shady Guy items from {shady_guy_count} vendors, "
                f"but read {actual_item_count}.",
                tag="warning",
            )
            return False

        shady_guy_items_text = ", ".join(self.scanner_logic.item_name(item) for item in shady_guy_items)
        self.log([f"\n[$$$] TARGET MAP FOUND! Profile: ", f"{t_name}{score_text}"], tag=["success", t_color])
        self.log(f"Map Stats: {self.scanner_logic.format_stats(stats, self.config.SCORES_SYSTEM)}", tag="success")
        self.log(
            f"Shady Guy items: [{shady_guy_items_text}]",
            tag="success",
        )
        self.log_target_found(t_name)

        if not self.handle_confirmed_target_window(process_name):
            return True

        self._set_running(False)
        self.scan_event.clear()
        self.after(0, self.update_status_ui)
        return True

    def run(self) -> None:
        process_name = getattr(self.config, "PROCESS_NAME", "").strip()

        while not self.stop_event.is_set():
            if self._get_client() is None:
                try:
                    self._set_client(self.game_data_client_factory(process_name=process_name))
                    self.log(f"[+] Game connected! Press '{self.config.HOTKEY}' to start auto-reroll.", tag="success")
                    self._set_ready(True)
                    self.after(0, self.update_status_ui)
                except ProcessNotFoundError:
                    if self.wait_state != "process":
                        self.log(f"[WAIT] Waiting for process '{process_name}'...", tag="warning")
                        self.wait_state = "process"
                        self.after(0, self.update_status_ui)
                    self.sleep(1)
                    continue
                except ModuleNotFoundError:
                    if self.wait_state != "module":
                        self.log("[WAIT] Process found. Waiting for GameAssembly.dll...", tag="warning")
                        self.wait_state = "module"
                        self.after(0, self.update_status_ui)
                    self.sleep(1)
                    continue

            was_waiting = not self.scan_event.is_set()
            self.scan_event.wait()
            if was_waiting:
                self.is_first_scan = True
                self.last_state = None
                self.last_stats = None

            if self.stop_event.is_set():
                break

            try:
                if not self.wait_for_game_window_focus(process_name):
                    continue

                try:
                    raw_stats = self._get_client().wait_for_map_ready(
                        previous_state=self.last_state,
                        previous_stats=self.last_stats,
                        require_change=not self.is_first_scan,
                        abort_condition=lambda: self.stop_event.is_set() or not self.scan_event.is_set(),
                        timeout=10.0,
                    )
                except InterruptedError:
                    continue

                self.is_first_scan = False
                self.last_state = self._get_client().get_map_generation_state()
                self.last_stats = raw_stats

                stats = self.adapt_map_stats(raw_stats)
                self.check_best_map(stats)
                self.check_worst_map(stats)

                candidate = self.evaluate_candidate(stats)
                if candidate is not None:
                    if not self.wait_for_game_window_focus(process_name):
                        continue

                    if not self._handle_candidate(process_name, raw_stats, stats, candidate):
                        candidate = None
                    else:
                        continue

                if candidate is None:
                    self.log(f"Stats: {self.scanner_logic.format_stats(stats, self.config.SCORES_SYSTEM)}")

                if not self.wait_for_game_window_focus(process_name):
                    continue

                elapsed = self.monotonic() - self.last_reroll_time
                while elapsed < self.config.MIN_DELAY:
                    if self.stop_event.is_set() or not self.scan_event.is_set():
                        break
                    self.sleep(0.05)
                    elapsed = self.monotonic() - self.last_reroll_time

                if self.stop_event.is_set() or not self.scan_event.is_set():
                    continue

                self.reroll_map()
                self.last_reroll_time = self.monotonic()

            except TimeoutError as exc:
                self.log(f"[-] Map loading timeout: {exc}", tag="warning")
                self.log("[*] Forcing reroll to unstick...", tag="warning")
                self.reroll_map()
                self.last_reroll_time = self.monotonic()
                self.last_state = None
                self.last_stats = None
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
                self._set_running(False)
                self._set_ready(False)
                self.scan_event.clear()
                self.close_client()
                self.log(f"[-] Lost connection to the game: {exc}", tag="error")
                self.wait_state = None
                self.last_state = None
                self.last_stats = None
                self.after(0, self.update_status_ui)
                self.sleep(1)
            except Exception as exc:
                self.log(f"[-] Error during execution: {exc}", tag="error")
                self.sleep(1)

        self._cleanup()
