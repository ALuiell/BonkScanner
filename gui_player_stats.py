from __future__ import annotations

import datetime
import html
import re
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

import config
from game_data import GameDataClient
from gui_dialogs import CleanupRecordingsDialog, ConfirmDeleteRecordingDialog
from gui_shared import _clear_layout, _clear_text_input, _read_text, _set_text, _set_text_input
from gui_styles import (
    COLOR_MAP,
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    ITEM_RARITY_FOLDED_NAME_ALIASES,
    ITEM_RARITY_NAME_ALIASES,
    ITEM_RARITY_NAME_BY_FOLDED_NAME,
    ITEM_DISPLAY_NAME_ALIASES,
    ITEM_RARITY_SORT_ORDER,
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
    PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS,
    PLAYER_STATS_LABEL_FONT_SIZE,
    PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS,
    PLAYER_STATS_REFRESH_MS,
    PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS,
    PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS,
    PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS,
    PLAYER_STATS_VALUE_FONT_SIZE,
    _button_state_stylesheet,
    _fold_item_name_for_rarity,
)
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from player_stats import PLAYER_STAT_GROUPS, PlayerStatsClient, TomeSnapshot, WeaponSnapshot, calculate_chests_per_minute
from vod_storage import delete_vod, delete_vods_below_snapshot_count, list_vods, load_vod, rename_vod


def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else PlayerStatsMixin.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(PlayerStatsMixin.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)

class PlayerStatsMixin:

    def update_player_stats_timer(self):
        if self._is_shutting_down:
            return

        recording_state_action = self._sync_player_stats_recording_run_state()
        should_refresh = self._is_live_stats_tab_active() or self.player_stats_vod_recorder.is_recording
        if should_refresh:
            status_text = (
                "Live player stats"
                if recording_state_action != "stopped"
                else "Live player stats (recording auto-stopped after run end)"
            )
            self.refresh_live_player_stats_now(status_text=status_text)

        self.after(PLAYER_STATS_REFRESH_MS, self.update_player_stats_timer)

    def _get_player_stats_client(self) -> PlayerStatsClient:
        if self.player_stats_client is None:
            self.player_stats_client = PlayerStatsClient(config.PROCESS_NAME)
        return self.player_stats_client

    def read_player_stats_only(self):
        client = self._get_player_stats_client()
        owner_stats = client.resolve_owner_stats()
        return client.get_player_stats(owner_stats), owner_stats

    def read_passive_items_only(self, owner_stats: int | None = None):
        client = self._get_player_stats_client()
        return client.get_passive_items(owner_stats)

    def read_player_stats(self):
        stats, owner_stats = self.read_player_stats_only()
        return stats, self.read_passive_items_only(owner_stats)

    def read_player_stats_recording_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_map_generation_state()

    def read_player_stats_recording_seed(self) -> int | None:
        return self.read_player_stats_recording_state().map_seed

    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self.player_stats_status_label, status_text)
        for label in self.player_stats_rows.values():
            _set_text(label, "--")
        self.player_stats_items_expanded = False
        self._update_items_section("live", items_text=items_text)
        _set_text(self.player_stats_chests_per_minute_label, "Average chests/min: --")
        _set_text(self.player_stats_in_game_time_label, "In-Game Time: --")
        _set_text(self.player_stats_mob_kills_label, "Mob Kills: --")
        _set_text(self.player_stats_level_label, "Level: --")
        _set_text(self.player_stats_new_items_label, "Live snapshot")
        _set_text(self.player_stats_banishes_label, "No banishes yet")
        self.player_stats_live_banishes = ()
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, None)
        self.player_stats_weapon_signature = None
        self.display_weapon_cards(
            (),
            scope="live",
            status_text="Waiting for weapon data...",
        )
        self.player_stats_tome_signature = None
        self.display_tome_cards(
            (),
            scope="live",
            status_text="Waiting for tome data...",
        )

    def _read_live_player_stats_data(self):
        stats, owner_stats = self.read_player_stats_only()
        items = ()
        items_available = True
        weapons: tuple[WeaponSnapshot, ...] = ()
        weapons_available = False
        tomes: tuple[TomeSnapshot, ...] = ()
        tomes_available = False
        banishes: tuple[str, ...] = ()
        banishes_available = False
        run_timer_seconds = None
        stage_timer_seconds = None
        mob_kills = None
        player_level = None
        map_seed = None
        stage_ptr = 0
        try:
            items = self.read_passive_items_only(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            items_available = False
        except Exception:
            items_available = False
        if self.player_stats_vod_recorder.is_recording or self._is_live_stats_tab_active():
            try:
                client = self._get_player_stats_client()
                weapons = client.get_live_weapons(owner_stats)
                weapons_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                weapons = ()
                weapons_available = False
            except Exception:
                weapons = ()
                weapons_available = False
            try:
                client = self._get_player_stats_client()
                tomes = client.get_live_tomes(owner_stats)
                tomes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                tomes = ()
                tomes_available = False
            except Exception:
                tomes = ()
                tomes_available = False
            try:
                client = self._get_player_stats_client()
                banishes = client.get_live_banishes()
                banishes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                banishes = ()
                banishes_available = False
            except Exception:
                banishes = ()
                banishes_available = False
        try:
            client = self._get_player_stats_client()
            run_timer_seconds = client.get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            run_timer_seconds = None
        except Exception:
            run_timer_seconds = None
        try:
            client = self._get_player_stats_client()
            stage_timer_seconds = client.get_stage_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            stage_timer_seconds = None
        except Exception:
            stage_timer_seconds = None
        try:
            client = self._get_player_stats_client()
            mob_kills = client.get_killed_mobs()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            mob_kills = None
        except Exception:
            mob_kills = None
        try:
            client = self._get_player_stats_client()
            player_level = client.get_player_level(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            player_level = None
        except Exception:
            player_level = None
        try:
            recording_state = self.read_player_stats_recording_state()
            map_seed = recording_state.map_seed
            stage_ptr = recording_state.current_stage_ptr
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0
        except Exception:
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0
        return (
            stats,
            items,
            items_available,
            weapons,
            weapons_available,
            tomes,
            tomes_available,
            banishes,
            banishes_available,
            run_timer_seconds,
            stage_timer_seconds,
            mob_kills,
            player_level,
            map_seed,
            stage_ptr,
        )

    def refresh_live_player_stats_now(
        self,
        *,
        status_text: str = "Live player stats",
        waiting_status_text: str = "Waiting for game/player stats...",
        unavailable_status_prefix: str = "Player stats unavailable",
    ) -> bool:
        try:
            (
                stats,
                items,
                items_available,
                weapons,
                weapons_available,
                tomes,
                tomes_available,
                banishes,
                banishes_available,
                run_timer_seconds,
                stage_timer_seconds,
                mob_kills,
                player_level,
                map_seed,
                stage_ptr,
            ) = self._read_live_player_stats_data()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_client()
            self._reset_live_player_stats_ui(waiting_status_text)
            return False
        except Exception as exc:
            self.close_player_stats_client()
            self._reset_live_player_stats_ui(f"{unavailable_status_prefix}: {exc}")
            return False

        chests_per_minute = self.calculate_player_chests_per_minute(stats)
        items_text = None if items_available else "Items unavailable"
        if banishes_available:
            banishes = self.merge_banish_appearance_order(self.player_stats_live_banishes, banishes)
            self.player_stats_live_banishes = banishes
        else:
            banishes = self.player_stats_live_banishes
        is_live_tab_active = self._is_live_stats_tab_active()

        if self.player_stats_vod_recorder.should_capture():
            snapshot = self.player_stats_vod_recorder.capture(
                stats,
                items if items_available else (),
                weapons if weapons_available else (),
                tomes if tomes_available else (),
                banishes if banishes_available else (),
                chests_per_minute=chests_per_minute,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                player_level=player_level,
                map_seed=map_seed,
                stage_ptr=stage_ptr,
                stage_time_seconds=stage_timer_seconds,
            )
            self.player_stats_vod_snapshots.append(snapshot)
            self.player_stats_selected_snapshot_index = len(self.player_stats_vod_snapshots) - 1
            self.refresh_player_stats_timeline_ui()
            self._refresh_vods_list_if_visible()
            if is_live_tab_active:
                self.display_player_stats_snapshot(snapshot, items_text=items_text)
            return True

        if is_live_tab_active:
            if self.player_stats_vod_recorder.is_recording:
                self.display_player_stats(
                    stats,
                    items,
                    weapons=weapons if weapons_available else (),
                    tomes=tomes if tomes_available else (),
                    banishes=banishes if banishes_available else (),
                    weapons_available=weapons_available,
                    tomes_available=tomes_available,
                    status_text="Live player stats (recording)",
                    chests_per_minute=chests_per_minute,
                    items_text=items_text,
                    game_time_seconds=run_timer_seconds,
                    mob_kills=mob_kills,
                    player_level=player_level,
                    stage_summary_rows=self.build_stage_summary(self.player_stats_vod_snapshots),
                )
                return True

            self.player_stats_selected_snapshot_index = None
            self.display_player_stats(
                stats,
                items,
                weapons=weapons if weapons_available else (),
                tomes=tomes if tomes_available else (),
                banishes=banishes if banishes_available else (),
                weapons_available=weapons_available,
                tomes_available=tomes_available,
                status_text=status_text,
                chests_per_minute=chests_per_minute,
                items_text=items_text,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                player_level=player_level,
                stage_summary_rows=None,
            )
        return True

    def display_player_stats(
        self,
        stats,
        items=(),
        *,
        weapons=(),
        tomes=(),
        banishes=(),
        weapons_available: bool = True,
        tomes_available: bool = True,
        status_text: str | None = None,
        chests_per_minute: float | None = None,
        items_text: str | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        player_level: int | None = None,
        new_items_text: str | None = None,
        stage_summary_rows: list[dict[str, str]] | None = None,
    ):
        if status_text:
            _set_text(self.player_stats_status_label, status_text)
        for label, stat in stats.items():
            value_label = self.player_stats_rows.get(label)
            if value_label is not None:
                _set_text(value_label, stat.display_value)
        self._update_items_section("live", items, items_text=items_text)
        if chests_per_minute is None:
            chests_per_minute = self.calculate_player_chests_per_minute(stats)
        _set_text(
            self.player_stats_chests_per_minute_label,
            self.format_chests_per_minute(chests_per_minute),
        )
        _set_text(
            self.player_stats_in_game_time_label,
            self.format_in_game_time(game_time_seconds),
        )
        _set_text(
            self.player_stats_mob_kills_label,
            self.format_mob_kills(mob_kills),
        )
        _set_text(
            self.player_stats_level_label,
            self.format_player_level(player_level),
        )
        if new_items_text is not None:
            _set_text(self.player_stats_new_items_label, new_items_text)
        else:
            _set_text(self.player_stats_new_items_label, "Live snapshot")
        _set_text(self.player_stats_banishes_label, self.format_banishes_rich_text(banishes))
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, stage_summary_rows)
        self.display_weapon_cards(
            weapons if weapons_available else (),
            scope="live",
            status_text=None if weapons_available else "Weapons unavailable",
        )
        self.display_tome_cards(
            tomes if tomes_available else (),
            scope="live",
            status_text=None if tomes_available else "Tomes unavailable",
        )

    def display_player_stats_snapshot(self, snapshot, *, items_text: str | None = None):
        index = self.player_stats_vod_snapshots.index(snapshot) + 1
        total = len(self.player_stats_vod_snapshots)
        self.display_player_stats(
            snapshot.stats,
            snapshot.items,
            weapons=getattr(snapshot, "weapons", ()),
            tomes=getattr(snapshot, "tomes", ()),
            banishes=getattr(snapshot, "banishes", ()),
            status_text=(
                f"Recorded snapshot {index}/{total} at {snapshot.time_label}"
                f" | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
            chests_per_minute=self.resolve_snapshot_chests_per_minute(snapshot),
            items_text=items_text,
            game_time_seconds=snapshot.game_time_seconds,
            mob_kills=getattr(snapshot, "mob_kills", None),
            player_level=getattr(snapshot, "player_level", None),
            new_items_text=self.format_snapshot_item_gains_preview(
                self._previous_player_stats_snapshot(snapshot),
                snapshot,
                segment_snapshots=self._player_stats_snapshot_segment(snapshot),
            ),
            stage_summary_rows=self.build_stage_summary(
                self.player_stats_vod_snapshots[:index]
            ),
        )

    def _previous_player_stats_snapshot(self, snapshot):
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return None
        if index <= 0:
            return None
        return self.player_stats_vod_snapshots[index - 1]

    def _player_stats_snapshot_segment(self, snapshot) -> tuple[object, ...]:
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return (snapshot,)
        start_index = max(0, index - 1)
        return tuple(self.player_stats_vod_snapshots[start_index : index + 1])

    def toggle_player_stats_recording(self):
        if self.player_stats_vod_recorder.is_recording:
            self._stop_player_stats_recording(log_message="[*] Player stats recording stopped.")
        else:
            state = self._read_player_stats_recording_state_safe()
            seed = state.map_seed if state is not None else None
            stage_ptr = state.current_stage_ptr if state is not None else 0
            run_time_seconds = self._read_player_stats_recording_run_timer_safe()
            vod_path = self._start_player_stats_recording(
                seed=seed,
                stage_ptr=stage_ptr,
                run_time_seconds=run_time_seconds,
            )
            self.log(f"[*] Player stats recording started: {vod_path.name}", tag="success")
            self.refresh_live_player_stats_now(
                waiting_status_text="Recording stats; waiting for game/player stats...",
                unavailable_status_prefix="Recording stats; player stats unavailable",
            )
            self._refresh_vods_list_if_visible()

        self.refresh_player_stats_timeline_ui()

    def _read_player_stats_recording_seed_safe(self) -> int | None:
        try:
            return self.read_player_stats_recording_seed()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_state_safe(self):
        try:
            return self.read_player_stats_recording_state()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_game_data_client()
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_run_timer_safe(self) -> float | None:
        try:
            return self._get_player_stats_client().get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            self.close_player_stats_client()
            return None
        except Exception:
            self.close_player_stats_client()
            return None

    @staticmethod
    def _seed_change_looks_like_same_run(
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if previous_run_time_seconds is None or current_run_time_seconds is None:
            return False
        return (
            current_run_time_seconds + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            >= previous_run_time_seconds
        )

    @staticmethod
    def _stage_change_looks_like_same_run(
        previous_stage_ptr: int,
        current_stage_ptr: int,
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr == current_stage_ptr
        ):
            return False
        return PlayerStatsMixin._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        )

    def _start_player_stats_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        run_time_seconds: float | None = None,
    ):
        vod_path = self.player_stats_vod_recorder.start(seed=seed)
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = run_time_seconds
        return vod_path

    def _stop_player_stats_recording(
        self,
        *,
        log_message: str | None = None,
        log_tag: str | None = None,
        refresh_live_stats: bool = True,
    ) -> None:
        self.player_stats_vod_recorder.stop()
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.close_player_stats_game_data_client()
        if log_message:
            self.log(log_message, tag=log_tag)
        if refresh_live_stats:
            self.refresh_live_player_stats_now()
        self._refresh_vods_list_if_visible()

    def _sync_player_stats_recording_run_state(self) -> str | None:
        if not self.player_stats_vod_recorder.is_recording:
            return None

        now = time.monotonic()
        current_state = self._read_player_stats_recording_state_safe()
        current_seed = current_state.map_seed if current_state is not None else None
        current_stage_ptr = (
            current_state.current_stage_ptr if current_state is not None else 0
        )
        current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
        if current_seed is None:
            if self.player_stats_recording_seed_missing_since is None:
                self.player_stats_recording_seed_missing_since = now
                return None
            if now - self.player_stats_recording_seed_missing_since < PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS:
                return None
            self._stop_player_stats_recording(
                log_message="[*] Player stats recording auto-stopped: run seed disappeared.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            self.refresh_player_stats_timeline_ui()
            return "stopped"

        self.player_stats_recording_seed_missing_since = None
        if self.player_stats_recording_seed is None:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None
        if (
            current_seed == self.player_stats_recording_seed
            and current_stage_ptr == self.player_stats_recording_stage_ptr
        ):
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        previous_seed = self.player_stats_recording_seed
        previous_stage_ptr = self.player_stats_recording_stage_ptr
        previous_run_time_seconds = self.player_stats_recording_run_time_seconds
        if self._stage_change_looks_like_same_run(
            previous_stage_ptr,
            current_stage_ptr,
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None
        if self._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        self._stop_player_stats_recording(refresh_live_stats=False)
        vod_path = self._start_player_stats_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            run_time_seconds=current_run_time_seconds,
        )
        self.log(
            f"[*] Player stats recording auto-split: seed {previous_seed} -> {current_seed}; new file {vod_path.name}",
            tag="success",
        )
        self.refresh_player_stats_timeline_ui()
        return "split"

    def on_player_stats_slider_changed(self, value):
        snapshot_count = len(self.player_stats_vod_snapshots)
        if snapshot_count == 0:
            return
        index = min(max(int(round(float(value))), 0), snapshot_count - 1)
        if self.player_stats_selected_snapshot_index == index:
            return
        self.player_stats_selected_snapshot_index = index
        self.display_player_stats_snapshot(self.player_stats_vod_snapshots[index])
        self.refresh_player_stats_timeline_ui(update_slider=False)

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        snapshot_count = len(self.player_stats_vod_snapshots)

        if self.player_stats_vod_recorder.is_recording:
            self.player_stats_record_btn.setText("Stop Recording")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
                )
            )
        else:
            self.player_stats_record_btn.setText(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
                )
            )

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            self.player_stats_slider.setEnabled(True)
            self.player_stats_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                index = self.player_stats_selected_snapshot_index
                self.player_stats_slider.setValue(index if index is not None else snapshot_count - 1)
        else:
            self.player_stats_slider.setEnabled(False)
            self.player_stats_slider.setMaximum(1)
            self.player_stats_slider.setValue(0)

        if self.player_stats_vod_recorder.is_recording:
            prefix = f"Recording {self.player_stats_vod_recorder.elapsed_label()} | "
            if snapshot_count:
                selected = self.player_stats_selected_snapshot_index
                mode = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
                self.player_stats_timeline_label.setText(f"{prefix}{snapshot_count} snapshots | {mode}")
            else:
                self.player_stats_timeline_label.setText(f"{prefix}No snapshots")
        else:
            self.player_stats_timeline_label.setText("Live stats")

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            first = self.player_stats_vod_snapshots[0].time_label
            last = self.player_stats_vod_snapshots[-1].time_label
            selected = self.player_stats_selected_snapshot_index
            current = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
            self.player_stats_slider_time_label.setText(f"Timeline: {first} - {last} | Selected: {current}")
        elif self.player_stats_vod_recorder.is_recording:
            self.player_stats_slider_time_label.setText(
                f"Timeline: recording {self.player_stats_vod_recorder.elapsed_label()} | waiting for first snapshot"
            )
        else:
            self.player_stats_slider_time_label.setText("Timeline: live stats")

    def refresh_vods_list(self):
        if self.vods_list_frame is None:
            return

        vods = list_vods()
        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        signature = (
            str(selected_path) if selected_path is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        if self.vods_list_signature == signature:
            return

        self.vods_list_frame.blockSignals(True)
        self.vods_list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            self.vods_list_frame.addItem(item)
            self.vods_list_frame.blockSignals(False)
            self.vods_list_signature = signature
            return

        selected_row = None
        for row, vod in enumerate(vods):
            duration = self.format_duration(vod.duration_seconds)
            item = QListWidgetItem(f"{vod.name}\n{vod.snapshot_count} snapshots | {duration}")
            item.setData(Qt.UserRole, str(vod.path))
            self.vods_list_frame.addItem(item)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            self.vods_list_frame.setCurrentRow(selected_row)
        self.vods_list_frame.blockSignals(False)
        self.vods_list_signature = signature

    def _on_vod_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if current is None:
            return
        path_str = current.data(Qt.UserRole)
        if path_str:
            self.load_selected_vod(path_str)

    def load_selected_vod(self, path):
        path = Path(path)
        try:
            self.loaded_vod = load_vod(path)
        except Exception as exc:
            self.loaded_vod = None
            self.loaded_vod_snapshot_index = None
            self.loaded_vod_compare_start_index = None
            _set_text(self.vods_status_label, f"Could not load recording: {exc}")
            return

        self.loaded_vod_snapshot_index = 0 if self.loaded_vod.snapshots else None
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        _clear_text_input(self.vods_name_entry)
        _set_text_input(self.vods_name_entry, self.loaded_vod.metadata.name)
        self.refresh_loaded_vod_ui()
        self.refresh_vods_list()

    def refresh_loaded_vod_ui(self, *, update_slider: bool = True):
        if self.loaded_vod is None:
            return

        snapshot_count = len(self.loaded_vod.snapshots)
        metadata = self.loaded_vod.metadata
        duration = self.format_duration(metadata.duration_seconds)
        _set_text(self.vods_status_label, f"{metadata.created_label} | {snapshot_count} snapshots | {duration}")

        if snapshot_count:
            self.vods_slider.setEnabled(True)
            self.vods_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                self.vods_slider.setValue(self.loaded_vod_snapshot_index or 0)
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self.vods_slider.setEnabled(False)
            self.vods_slider.setMaximum(1)
            self.vods_slider.setValue(0)
            for label in self.vods_rows.values():
                _set_text(label, "--")
            _set_text(self.vods_slider_time_label, "Timeline: --")
            self.vods_items_expanded = False
            self._update_items_section("vod", items_text="--")
            _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
            _set_text(self.vods_in_game_time_label, "In-Game Time: --")
            _set_text(self.vods_mob_kills_label, "Mob Kills: --")
            _set_text(self.vods_level_label, "Level: --")
            _set_text(self.vods_new_items_label, "No previous snapshot")
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
            _set_text(self.vods_banishes_label, "No banishes yet")
            self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
            self.vods_weapon_signature = None
            self.display_weapon_cards((), scope="vod", status_text="No weapon data in this recording")
            self.vods_tome_signature = None
            self.display_tome_cards((), scope="vod", status_text="No tome data in this recording")

    def display_loaded_vod_snapshot(self, index: int):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(index, 0), len(self.loaded_vod.snapshots) - 1)
        self.loaded_vod_snapshot_index = index
        snapshot = self.loaded_vod.snapshots[index]
        _set_text(
            self.vods_status_label,
            (
                f"{self.loaded_vod.metadata.name} | {index + 1}/{len(self.loaded_vod.snapshots)}"
                f" at {snapshot.time_label} | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
        )
        first = self.loaded_vod.snapshots[0].time_label
        last = self.loaded_vod.snapshots[-1].time_label
        _set_text(self.vods_slider_time_label, f"Timeline: {first} - {last} | Selected: {snapshot.time_label}")
        for spec_group in PLAYER_STAT_GROUPS:
            for spec in spec_group:
                value_label = self.vods_rows.get(spec.label)
                if value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(value_label, stat.display_value if stat is not None else "--")
        self._update_items_section("vod", snapshot.items)
        _set_text(
            self.vods_chests_per_minute_label,
            self.format_chests_per_minute(self.resolve_snapshot_chests_per_minute(snapshot)),
        )
        _set_text(
            self.vods_in_game_time_label,
            self.format_in_game_time(snapshot.game_time_seconds),
        )
        _set_text(
            self.vods_mob_kills_label,
            self.format_mob_kills(getattr(snapshot, "mob_kills", None)),
        )
        _set_text(
            self.vods_level_label,
            self.format_player_level(getattr(snapshot, "player_level", None)),
        )
        self._set_stage_summary_labels(
            self.vods_stage_summary_labels,
            self.build_stage_summary(self.loaded_vod.snapshots[: index + 1]),
        )
        previous_snapshot = self._resolve_vod_compare_base_snapshot(index)
        segment_snapshots = self._vod_compare_segment_snapshots(index)
        _set_text(
            self.vods_new_items_label,
            self.format_snapshot_item_gains_preview(previous_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(previous_snapshot, snapshot, index=index, segment_snapshots=segment_snapshots)
        _set_text(
            self.vods_banishes_label,
            self.format_banishes_rich_text(getattr(snapshot, "banishes", ())),
        )
        self.display_weapon_cards(getattr(snapshot, "weapons", ()), scope="vod")
        self.display_tome_cards(getattr(snapshot, "tomes", ()), scope="vod")

    def on_vods_slider_changed(self, value):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(self.loaded_vod.snapshots) - 1)
        if self.loaded_vod_snapshot_index == index:
            return
        self.display_loaded_vod_snapshot(index)

    def set_vod_compare_start(self):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = self.loaded_vod_snapshot_index
        if index is None:
            index = 0
        self.loaded_vod_compare_start_index = min(max(int(index), 0), len(self.loaded_vod.snapshots) - 1)
        self.vods_compare_details_expanded = True
        self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)

    def clear_vod_compare_start(self):
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        if self.loaded_vod is not None and self.loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)

    def toggle_vod_compare_details(self):
        self.vods_compare_details_expanded = not bool(getattr(self, "vods_compare_details_expanded", False))
        if self.loaded_vod is not None and self.loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self._refresh_vod_compare_details(None, None, index=None)

    def _resolve_vod_compare_base_snapshot(self, index: int):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return None
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        if compare_index is not None:
            compare_index = min(max(int(compare_index), 0), len(self.loaded_vod.snapshots) - 1)
            return self.loaded_vod.snapshots[compare_index]
        if index <= 0:
            return None
        return self.loaded_vod.snapshots[index - 1]

    def _vod_compare_segment_snapshots(self, index: int) -> tuple[object, ...]:
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return ()
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        if compare_index is None:
            start_index = max(0, index - 1)
        else:
            start_index = min(max(int(compare_index), 0), len(self.loaded_vod.snapshots) - 1)
        end_index = min(max(int(index), 0), len(self.loaded_vod.snapshots) - 1)
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return tuple(self.loaded_vod.snapshots[start_index : end_index + 1])

    def _refresh_vod_compare_controls(self) -> None:
        has_snapshots = bool(self.loaded_vod is not None and self.loaded_vod.snapshots)
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        set_btn = getattr(self, "vods_compare_set_btn", None)
        clear_btn = getattr(self, "vods_compare_clear_btn", None)
        details_btn = getattr(self, "vods_compare_details_btn", None)
        if set_btn is not None:
            set_btn.setEnabled(has_snapshots)
        if clear_btn is not None:
            clear_btn.setEnabled(has_snapshots and compare_index is not None)
        if details_btn is not None:
            details_btn.setVisible(has_snapshots)
            expanded = bool(getattr(self, "vods_compare_details_expanded", False))
            details_btn.setText("Hide details" if expanded else "Show details")

    def _refresh_vod_compare_details(self, base_snapshot, snapshot, *, index: int | None, segment_snapshots=()) -> None:
        self._refresh_vod_compare_controls()
        expanded = bool(getattr(self, "vods_compare_details_expanded", False))
        group = getattr(self, "vods_compare_details_group", None)
        if group is not None:
            group.setVisible(expanded and base_snapshot is not None and snapshot is not None)
        if base_snapshot is None or snapshot is None:
            _set_text(getattr(self, "vods_compare_details_summary_label", None), "--")
            _set_text(getattr(self, "vods_compare_details_items_label", None), "--")
            return

        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        base_index = compare_index if compare_index is not None else (index - 1 if index is not None else None)
        summary = self.format_snapshot_compare_summary(
            base_snapshot,
            snapshot,
            base_index=base_index,
            current_index=index,
            segment_snapshots=segment_snapshots,
        )
        _set_text(getattr(self, "vods_compare_details_summary_label", None), summary)
        _set_text(
            getattr(self, "vods_compare_details_items_label", None),
            self.format_snapshot_item_changes_details(base_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )

    def rename_selected_vod(self):
        if self.loaded_vod is None or self.vods_name_entry is None:
            return
        new_name = _read_text(self.vods_name_entry).strip()
        try:
            metadata = rename_vod(self.loaded_vod.metadata.path, new_name)
            self.loaded_vod = load_vod(metadata.path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not rename recording: {exc}")
            return
        self.refresh_loaded_vod_ui(update_slider=False)
        self.refresh_vods_list()

    def _clear_loaded_vod_selection(self) -> None:
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        _clear_text_input(self.vods_name_entry)
        _set_text(self.vods_status_label, "Select a recording")
        self.vods_slider.setEnabled(False)
        self.vods_slider.setMaximum(1)
        self.vods_slider.setValue(0)
        _set_text(self.vods_slider_time_label, "Timeline: --")
        for label in self.vods_rows.values():
            _set_text(label, "--")
        self.vods_items_expanded = False
        self._update_items_section("vod", items_text="--")
        _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
        _set_text(self.vods_in_game_time_label, "In-Game Time: --")
        _set_text(self.vods_mob_kills_label, "Mob Kills: --")
        _set_text(self.vods_level_label, "Level: --")
        _set_text(self.vods_new_items_label, "No previous snapshot")
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(None, None, index=None)
        _set_text(self.vods_banishes_label, "No banishes yet")
        self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
        self.vods_weapon_signature = None
        self.display_weapon_cards((), scope="vod", status_text="Select a recording")
        self.vods_tome_signature = None
        self.display_tome_cards((), scope="vod", status_text="Select a recording")

    def cleanup_recordings_by_snapshot_count(self):
        dialog = CleanupRecordingsDialog(self.window)
        if dialog.exec() != QDialog.Accepted or dialog.threshold is None:
            return

        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        try:
            removed = delete_vods_below_snapshot_count(dialog.threshold)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not clean recordings: {exc}")
            return

        if selected_path is not None and not selected_path.exists():
            self._clear_loaded_vod_selection()

        self.refresh_vods_list()
        self.log(f"[*] Removed {removed} recordings with snapshot count below {dialog.threshold}.", tag="success")

    def delete_selected_vod(self):
        if self.loaded_vod is None:
            return
        dialog = ConfirmDeleteRecordingDialog(self.window, self.loaded_vod.metadata.name)
        dialog.exec()
        if not dialog.result:
            return
        path = self.loaded_vod.metadata.path
        try:
            delete_vod(path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not delete recording: {exc}")
            return
        self._clear_loaded_vod_selection()
        self.refresh_vods_list()

    def toggle_player_items_expanded(self) -> None:
        self.player_stats_items_expanded = not self.player_stats_items_expanded
        self._update_items_section(
            "live",
            self.player_stats_items_current,
            items_text=self.player_stats_items_text_current,
        )

    def toggle_vod_items_expanded(self) -> None:
        self.vods_items_expanded = not self.vods_items_expanded
        self._update_items_section(
            "vod",
            self.vods_items_current,
            items_text=self.vods_items_text_current,
        )

    def on_items_sort_changed(self, scope: str) -> None:
        prefix = self._scope_prefix(scope)
        combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        mode = ITEM_SORT_DEFAULT
        if combo is not None and hasattr(combo, "currentData"):
            mode = combo.currentData() or ITEM_SORT_DEFAULT
        setattr(self, f"{prefix}_items_sort_mode", mode)
        self._update_items_section(
            scope,
            self.__dict__.get(f"{prefix}_items_current", ()),
            items_text=self.__dict__.get(f"{prefix}_items_text_current"),
        )

    def _update_items_section(self, scope: str, items=(), *, items_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        group = self.__dict__.get(f"{prefix}_items_group")
        label = self.__dict__.get(f"{prefix}_items_label")
        rarity_label = self.__dict__.get(f"{prefix}_items_rarity_label")
        button = self.__dict__.get(f"{prefix}_items_toggle_btn")
        sort_combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        expanded = bool(self.__dict__.get(f"{prefix}_items_expanded", False))
        setattr(self, f"{prefix}_items_current", tuple(items or ()))
        setattr(self, f"{prefix}_items_text_current", items_text)

        if label is None:
            return

        if items_text is not None:
            self._set_items_group_title(group, None)
            _set_items_text(label, items_text=items_text)
            self._set_items_rarity_summary_label(rarity_label, ())
            if button is not None:
                button.setVisible(False)
            if sort_combo is not None:
                sort_combo.setEnabled(False)
            return

        items = tuple(items or ())
        self._set_items_group_title(group, self._item_total_count(items))
        self._set_items_rarity_summary_label(rarity_label, items)
        sorted_items = self.sort_items_for_display(
            items,
            self.__dict__.get(f"{prefix}_items_sort_mode", ITEM_SORT_DEFAULT),
        )
        preview_items, has_more = self._items_preview(sorted_items)
        visible_items = sorted_items if expanded or not has_more else preview_items
        if sort_combo is not None:
            sort_combo.setEnabled(bool(items))
        if hasattr(label, "setTextFormat"):
            text = self.format_items_rich_text(visible_items)
            if has_more and not expanded:
                text = f'{text} <span style="color:#98A7BA;">...</span>'
            label.setText(text)
        else:
            text = self.format_items(visible_items)
            if has_more and not expanded:
                text = f"{text} ..."
            _set_text(label, text)

        if button is not None:
            button.setVisible(has_more)
            button.setText("Show less" if expanded and has_more else "Show all")

    @classmethod
    def _item_total_count(cls, items) -> int:
        return sum(cls._item_counts(items).values())

    @classmethod
    def _item_rarity_totals(cls, items) -> dict[str, int]:
        rarity_totals = {
            "LEGENDARY": 0,
            "RARE": 0,
            "UNCOMMON": 0,
            "COMMON": 0,
        }
        for item_name, count in cls._item_counts(items).items():
            display_name = cls._normalize_item_name_for_display(item_name)
            rarity_name = cls._normalize_item_name_for_rarity(display_name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_totals:
                rarity_totals[rarity] += count
        return rarity_totals

    @classmethod
    def _empty_item_rarity_totals(cls) -> dict[str, int]:
        return {
            "LEGENDARY": 0,
            "RARE": 0,
            "UNCOMMON": 0,
            "COMMON": 0,
        }

    @classmethod
    def format_items_rarity_summary_rich_text(cls, items) -> str:
        rarity_totals = cls._item_rarity_totals(items)
        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = rarity_totals.get(rarity, 0)
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
            )
        return "  ".join(parts)

    @staticmethod
    def _set_items_rarity_summary_label(label, items) -> None:
        if label is None:
            return
        text = PlayerStatsMixin.format_items_rarity_summary_rich_text(items)
        label.setVisible(bool(text))
        label.setText(text)

    @staticmethod
    def _set_items_group_title(group, total_count: int | None) -> None:
        if group is None or not hasattr(group, "setTitle"):
            return
        title = "Items" if total_count is None else f"Items ({total_count} total)"
        group.setTitle(title)

    @classmethod
    def sort_items_for_display(cls, items, mode: str | None) -> tuple[str, ...]:
        items = tuple(items or ())
        if mode == ITEM_SORT_DEFAULT or not items:
            return items
        reverse = mode == ITEM_SORT_RARITY_DESC
        if mode not in (ITEM_SORT_RARITY_ASC, ITEM_SORT_RARITY_DESC):
            return items

        def sort_key(entry) -> tuple[int, int]:
            index, item = entry
            rarity_rank = cls._item_rarity_rank(str(item))
            return (-rarity_rank if reverse else rarity_rank, index)

        return tuple(item for _index, item in sorted(enumerate(items), key=sort_key))

    @classmethod
    def _item_rarity_rank(cls, item_text: str) -> int:
        item_name, _suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        return ITEM_RARITY_SORT_ORDER.get(rarity, -1)

    @staticmethod
    def _items_preview(items) -> tuple[tuple[str, ...], bool]:
        items = tuple(items or ())
        if len(items) <= 1:
            return items, False

        preview: list[str] = []
        max_chars = 90
        current_length = 0
        for item in items:
            separator_length = 2 if preview else 0
            projected_length = current_length + separator_length + len(item)
            if preview and projected_length > max_chars:
                break
            preview.append(item)
            current_length = projected_length

        if not preview:
            preview.append(items[0])
        return tuple(preview), len(preview) < len(items)

    def display_weapon_cards(self, weapons, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_weapons_layout"
        status_attr = f"{prefix}_weapons_status_label"
        cards_attr = f"{prefix}_weapon_cards"
        signature_attr = f"{prefix}_weapon_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        weapons = tuple(weapons or ())
        signature = self._weapon_signature(weapons)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if weapons else "No weapons available")

        if not weapons:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, weapon in enumerate(weapons):
            card = self._build_weapon_card(weapon)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)

    def _build_weapon_card(self, weapon: WeaponSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        weapon_name_label = QLabel(weapon.name)
        weapon_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(weapon_name_label, 1)
        header_layout.addWidget(weapon_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        has_rows = False
        for stat_id in weapon.upgrade_stat_ids:
            stat = weapon.upgraded_stats.get(stat_id)
            if stat is None:
                continue
            value_label = QLabel(stat.display_value)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rows.addRow(stat.label, value_label)
            has_rows = True
        if has_rows:
            layout.addLayout(rows)
        else:
            layout.addWidget(QLabel("No upgraded stats decoded"))
        return card

    @staticmethod
    def _weapon_signature(weapons) -> tuple:
        return tuple(
            (
                weapon.weapon_id,
                weapon.level,
                tuple(
                    (stat_id, weapon.upgraded_stats[stat_id].display_value)
                    for stat_id in weapon.upgrade_stat_ids
                    if stat_id in weapon.upgraded_stats
                ),
            )
            for weapon in weapons
        )

    def display_tome_cards(self, tomes, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_tomes_layout"
        status_attr = f"{prefix}_tomes_status_label"
        cards_attr = f"{prefix}_tome_cards"
        signature_attr = f"{prefix}_tome_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        tomes = tuple(tomes or ())
        signature = self._tome_signature(tomes)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if tomes else "No tomes available")

        if not tomes:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, tome in enumerate(tomes):
            card = self._build_tome_card(tome)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)

    def _build_tome_card(self, tome: TomeSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        tome_name_label = QLabel(tome.name)
        tome_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        tome_level_label = QLabel(f"Lv. {tome.level}")
        tome_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tome_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(tome_name_label, 1)
        header_layout.addWidget(tome_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        value_label = QLabel(tome.display_value)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rows.addRow(tome.stat_label, value_label)
        layout.addLayout(rows)
        return card

    @staticmethod
    def _tome_signature(tomes) -> tuple:
        return tuple(
            (
                tome.tome_id,
                tome.level,
                tome.stat_id,
                tome.stat_label,
                tome.display_value,
            )
            for tome in tomes
        )

    @staticmethod
    def format_duration(seconds: int) -> str:
        return PlayerStatsMixin.format_elapsed_time(seconds)

    @staticmethod
    def format_elapsed_time(seconds: float | int) -> str:
        minutes, seconds = divmod(max(int(seconds), 0), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod
    def format_in_game_time(cls, seconds: float | None) -> str:
        if seconds is None:
            return "In-Game Time: --"
        return f"In-Game Time: {cls.format_elapsed_time(seconds)}"

    @staticmethod
    def format_mob_kills(value: int | None) -> str:
        if value is None:
            return "Mob Kills: --"
        return f"Mob Kills: {PlayerStatsMixin.format_count(value)}"

    @staticmethod
    def format_count(value: int | float) -> str:
        return f"{max(0, int(value)):,}"

    @staticmethod
    def format_player_level(value: int | None) -> str:
        if value is None:
            return "Level: --"
        return f"Level: {max(0, int(value))}"

    @staticmethod
    def format_items(items) -> str:
        if not items:
            return "--"
        return ", ".join(items)

    @classmethod
    def format_snapshot_new_items(cls, previous_snapshot, snapshot) -> str:
        if previous_snapshot is None:
            return "No previous snapshot"
        new_items = cls.diff_new_items(getattr(previous_snapshot, "items", ()), getattr(snapshot, "items", ()))
        if not new_items:
            return "No new items since previous snapshot"
        return cls.format_new_items_rich_text(new_items)

    @classmethod
    def format_snapshot_item_gains_preview(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        if previous_snapshot is None:
            return "No previous snapshot"
        changes = cls.summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
        gains = changes["gained"]
        broken = changes["broken"]
        lost = changes["lost"]
        total = sum(gain for _name, gain in gains)
        items_summary = cls.format_item_gain_rarity_totals(gains)
        if total > 0:
            items_summary = f'{items_summary} <span style="color:#98A7BA;">+{cls.format_count(total)}</span>'
        rows = [f'<span style="color:#98A7BA;">Items:</span> {items_summary}']
        time_delta = cls._snapshot_time_delta(previous_snapshot, snapshot)
        if time_delta is not None:
            rows.append(f'<span style="color:#98A7BA;">Time:</span> {cls.format_elapsed_time(time_delta)}')

        kill_delta = cls._snapshot_int_delta(previous_snapshot, snapshot, "mob_kills")
        if kill_delta is not None and kill_delta > 0:
            rows.append(f'<span style="color:#98A7BA;">Kills:</span> +{cls.format_count(kill_delta)}')

        level_delta = cls._snapshot_int_delta(previous_snapshot, snapshot, "player_level")
        if level_delta is not None and level_delta > 0:
            rows.append(f'<span style="color:#98A7BA;">Levels:</span> +{cls.format_count(level_delta)}')

        return "<br>".join(rows)

    @classmethod
    def diff_new_items(cls, previous_items, current_items) -> tuple[str, ...]:
        return tuple(f"{name} x{gain}" for name, gain in cls.diff_item_gains(previous_items, current_items))

    @classmethod
    def diff_item_gains(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        changes = cls.summarize_item_count_changes(previous_items, current_items)
        return changes["gained"]

    @classmethod
    def diff_item_losses(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        changes = cls.summarize_item_count_changes(previous_items, current_items)
        return changes["lost"]

    @classmethod
    def summarize_item_count_changes(cls, previous_items, current_items) -> dict[str, tuple[tuple[str, int], ...]]:
        previous_counts = cls._item_counts(previous_items)
        current_counts = cls._item_counts(current_items)
        gained: dict[str, int] = {}
        lost: dict[str, int] = {}
        broken: dict[str, int] = {}
        for name in set(previous_counts) | set(current_counts):
            current_count = current_counts.get(name, 0)
            delta = current_count - previous_counts.get(name, 0)
            if delta > 0:
                gained[name] = gained.get(name, 0) + delta
            elif delta < 0:
                target = broken if cls._is_breakable_consumed_item(name) else lost
                target[name] = target.get(name, 0) + abs(delta)
        return {
            "gained": cls._sort_item_delta_pairs(gained.items()),
            "lost": cls._sort_item_delta_pairs(lost.items()),
            "broken": cls._sort_item_delta_pairs(broken.items()),
        }

    @classmethod
    def summarize_item_segment_changes(cls, snapshots) -> dict[str, tuple[tuple[str, int], ...]]:
        snapshots = tuple(snapshots or ())
        gained: dict[str, int] = {}
        lost: dict[str, int] = {}
        broken: dict[str, int] = {}
        if len(snapshots) < 2:
            return {"gained": (), "lost": (), "broken": ()}

        previous_items = getattr(snapshots[0], "items", ())
        for snapshot in snapshots[1:]:
            changes = cls.summarize_item_count_changes(previous_items, getattr(snapshot, "items", ()))
            for bucket_name, target in (("gained", gained), ("lost", lost), ("broken", broken)):
                for name, count in changes[bucket_name]:
                    target[name] = target.get(name, 0) + count
            previous_items = getattr(snapshot, "items", ())

        return {
            "gained": cls._sort_item_delta_pairs(gained.items()),
            "lost": cls._sort_item_delta_pairs(lost.items()),
            "broken": cls._sort_item_delta_pairs(broken.items()),
        }

    @classmethod
    def _sort_item_delta_pairs(cls, items) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted(
                ((str(name), int(count)) for name, count in items if int(count) > 0),
                key=lambda item: (-cls._item_rarity_rank(item[0]), -item[1], item[0].casefold()),
            )
        )

    @classmethod
    def _is_breakable_consumed_item(cls, item_name: str) -> bool:
        rarity_name = cls._normalize_item_name_for_rarity(item_name)
        return rarity_name in {"Za Warudo", "Ze Warudo"}

    @classmethod
    def format_snapshot_item_changes_details(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        changes = cls.summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
        sections: list[str] = []
        if changes["gained"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Gained</span><br>'
                f'{cls.format_item_gains_by_rarity(changes["gained"])}'
            )
        if changes["broken"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Broken</span><br>'
                f'{cls.format_item_losses_by_rarity(changes["broken"], suffix="broken")}'
            )
        if changes["lost"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Lost</span><br>'
                f'{cls.format_item_losses_by_rarity(changes["lost"])}'
            )
        if not sections:
            return '<span style="color:#98A7BA;">No item changes in this segment</span>'
        return "<br>".join(sections)

    @classmethod
    def format_item_gains_by_rarity(
        cls,
        gains: tuple[tuple[str, int], ...],
        *,
        max_items: int | None = None,
    ) -> str:
        if not gains:
            return '<span style="color:#98A7BA;">No item gains</span>'

        grouped: dict[str, list[tuple[str, int]]] = {
            "LEGENDARY": [],
            "RARE": [],
            "UNCOMMON": [],
            "COMMON": [],
            "UNKNOWN": [],
        }
        for name, gain in gains:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
            if rarity not in grouped:
                rarity = "UNKNOWN"
            grouped[rarity].append((cls._normalize_item_name_for_display(name), int(gain)))

        remaining = max_items
        hidden_count = 0
        rows: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
            items = grouped[rarity]
            if not items:
                continue
            if remaining is not None:
                visible_items = items[:remaining]
                hidden_count += max(0, len(items) - len(visible_items))
                remaining -= len(visible_items)
                if not visible_items:
                    continue
            else:
                visible_items = items
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            item_text = " | ".join(
                f"{html.escape(name)} +{cls.format_count(gain)}"
                for name, gain in visible_items
            )
            rows.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{item_text}</span>'
            )
            if remaining is not None and remaining <= 0:
                break

        if hidden_count > 0:
            rows.append(f'<span style="color:#98A7BA;">+{hidden_count} more gains...</span>')
        return "<br>".join(rows)

    @classmethod
    def format_item_losses_by_rarity(
        cls,
        losses: tuple[tuple[str, int], ...],
        *,
        suffix: str | None = None,
    ) -> str:
        if not losses:
            return '<span style="color:#98A7BA;">No item losses</span>'

        grouped: dict[str, list[tuple[str, int]]] = {
            "LEGENDARY": [],
            "RARE": [],
            "UNCOMMON": [],
            "COMMON": [],
            "UNKNOWN": [],
        }
        for name, loss in losses:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
            if rarity not in grouped:
                rarity = "UNKNOWN"
            grouped[rarity].append((cls._normalize_item_name_for_display(name), int(loss)))

        rows: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
            items = grouped[rarity]
            if not items:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            item_text = " | ".join(
                f"{html.escape(name)} -{cls.format_count(loss)}{f' {suffix}' if suffix else ''}"
                for name, loss in items
            )
            rows.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{item_text}</span>'
            )
        return "<br>".join(rows)

    @classmethod
    def format_item_loss_inline(cls, losses: tuple[tuple[str, int], ...]) -> str:
        if not losses:
            return '<span style="color:#98A7BA;">--</span>'
        return " | ".join(
            f'<span style="color:#E5E7EB;">{html.escape(cls._normalize_item_name_for_display(name))} -{cls.format_count(count)}</span>'
            for name, count in losses
        )

    @classmethod
    def format_item_gain_rarity_totals(cls, gains: tuple[tuple[str, int], ...]) -> str:
        rarity_totals = cls._empty_item_rarity_totals()
        for name, gain in gains:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_totals:
                rarity_totals[rarity] += int(gain)

        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = rarity_totals.get(rarity, 0)
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{cls.format_count(total)}</span>'
            )
        return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'

    @classmethod
    def format_snapshot_compare_summary(
        cls,
        base_snapshot,
        snapshot,
        *,
        base_index: int | None,
        current_index: int | None,
        segment_snapshots=(),
    ) -> str:
        pieces: list[str] = []
        if base_index is not None and current_index is not None:
            pieces.append(f"Snapshot {int(base_index) + 1} -> {int(current_index) + 1}")
        base_time = getattr(base_snapshot, "game_time_seconds", None)
        current_time = getattr(snapshot, "game_time_seconds", None)
        if base_time is not None and current_time is not None:
            pieces.append(f"{cls.format_elapsed_time(base_time)} -> {cls.format_elapsed_time(current_time)}")
        kill_delta = cls._snapshot_int_delta(base_snapshot, snapshot, "mob_kills")
        if kill_delta is not None and kill_delta > 0:
            pieces.append(f"+{cls.format_count(kill_delta)} kills")
        level_delta = cls._snapshot_int_delta(base_snapshot, snapshot, "player_level")
        if level_delta is not None and level_delta > 0:
            pieces.append(f"+{cls.format_count(level_delta)} levels")
        changes = cls.summarize_item_segment_changes(segment_snapshots or (base_snapshot, snapshot))
        item_total = sum(gain for _name, gain in changes["gained"])
        pieces.append(f"+{cls.format_count(item_total)} items")
        broken_total = sum(count for _name, count in changes["broken"])
        if broken_total:
            pieces.append(f"{cls.format_count(broken_total)} broken")
        lost_total = sum(count for _name, count in changes["lost"])
        if lost_total:
            pieces.append(f"-{cls.format_count(lost_total)} lost")
        return " | ".join(pieces)

    @staticmethod
    def _snapshot_int_delta(base_snapshot, snapshot, attr_name: str) -> int | None:
        base_value = getattr(base_snapshot, attr_name, None)
        current_value = getattr(snapshot, attr_name, None)
        if base_value is None or current_value is None:
            return None
        return max(0, int(current_value) - int(base_value))

    @staticmethod
    def _snapshot_time_delta(base_snapshot, snapshot) -> float | None:
        base_time = getattr(base_snapshot, "game_time_seconds", None)
        current_time = getattr(snapshot, "game_time_seconds", None)
        if base_time is None or current_time is None:
            return None
        return max(0.0, float(current_time) - float(base_time))

    @classmethod
    def format_new_items_rich_text(cls, items) -> str:
        if not items:
            return "No new items since previous snapshot"
        return ", ".join(cls._format_single_item_rich_text(item) for item in items)

    @classmethod
    def format_banishes_rich_text(cls, banishes) -> str:
        banishes = tuple(str(item) for item in (banishes or ()))
        if not banishes:
            return "No banishes yet"
        return ", ".join(cls._format_single_banish_rich_text(item) for item in banishes)

    @classmethod
    def _format_single_banish_rich_text(cls, banish_text: str) -> str:
        if banish_text.endswith(" Tome"):
            tome_name = html.escape(banish_text)
            return f'<span style="font-weight: 700;">{tome_name}</span>'
        return cls._format_single_item_rich_text(banish_text)

    @staticmethod
    def merge_banish_appearance_order(previous_banishes, current_banishes) -> tuple[str, ...]:
        current = tuple(str(item) for item in (current_banishes or ()))
        if not current:
            return ()
        previous = tuple(str(item) for item in (previous_banishes or ()))
        merged = [item for item in previous if item in current]
        for item in current:
            if item not in merged:
                merged.append(item)
        return tuple(merged)

    @classmethod
    def _item_counts(cls, items) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items or ():
            name, suffix = cls._split_item_stack_suffix(str(item))
            name = cls._normalize_item_name_for_display(name)
            count = 1
            if suffix.startswith(" x") and suffix[2:].isdigit():
                count = int(suffix[2:])
            counts[name] = counts.get(name, 0) + max(1, count)
        return counts

    @classmethod
    def build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        if not snapshots:
            return rows

        stage_buckets: dict[int, list[object]] = {index: [] for index in range(1, 5)}
        stage_item_gains: dict[int, dict[str, int]] = {
            index: cls._empty_item_rarity_totals() for index in range(1, 5)
        }
        stage_kill_baselines: dict[int, int] = {1: 0}
        last_known_mob_kills: int | None = None
        current_stage_index = 1
        item_gain_tracker = None
        previous_snapshot = None
        for snapshot in snapshots:
            snapshot_mob_kills = getattr(snapshot, "mob_kills", None)
            if item_gain_tracker is None:
                item_gain_tracker = cls._create_stage_item_gain_tracker(getattr(snapshot, "items", ()))
            if previous_snapshot is not None:
                previous_stage_index = current_stage_index
                next_stage_index = cls._resolve_next_stage_index(
                    current_stage_index,
                    previous_snapshot,
                    snapshot,
                )
                current_stage_index = min(max(next_stage_index, current_stage_index), 4)
                if (
                    current_stage_index > previous_stage_index
                    and cls._is_stage_transition_boundary_snapshot(snapshot)
                ):
                    stage_buckets[previous_stage_index].append(snapshot)
                if current_stage_index > previous_stage_index:
                    baseline = getattr(snapshot, "mob_kills", None)
                    if baseline is None:
                        baseline = last_known_mob_kills
                    if baseline is not None:
                        stage_kill_baselines[current_stage_index] = max(0, int(baseline))
                item_gains = cls._update_stage_item_gain_tracker(
                    item_gain_tracker,
                    getattr(snapshot, "items", ()),
                )
                for rarity, count in item_gains.items():
                    stage_item_gains[current_stage_index][rarity] += count
            stage_buckets[current_stage_index].append(snapshot)
            if snapshot_mob_kills is not None:
                last_known_mob_kills = max(0, int(snapshot_mob_kills))
            previous_snapshot = snapshot

        for stage_index, bucket in stage_buckets.items():
            if not bucket:
                continue
            first_snapshot = bucket[0]
            last_snapshot = bucket[-1]
            start_run_time = getattr(first_snapshot, "game_time_seconds", None)
            if stage_index == 1 and start_run_time is not None:
                start_run_time = 0.0
            end_run_time = getattr(last_snapshot, "game_time_seconds", None)
            duration_text = "--"
            if start_run_time is not None and end_run_time is not None:
                duration_text = cls.format_elapsed_time(max(0.0, end_run_time - start_run_time))

            kills_text = "--"
            kill_snapshots = [
                candidate
                for candidate in bucket
                if getattr(candidate, "mob_kills", None) is not None
            ]
            if kill_snapshots:
                first_kills = stage_kill_baselines.get(stage_index)
                if first_kills is None:
                    first_kills = getattr(kill_snapshots[0], "mob_kills", None)
                last_kills = getattr(kill_snapshots[-1], "mob_kills", None)
                kills_text = cls.format_count(int(last_kills) - int(first_kills))

            items_text = cls._format_stage_item_rarity_summary(stage_item_gains[stage_index])
            rows[stage_index - 1] = {
                "label": f"Stage {stage_index}",
                "kills": kills_text,
                "time": duration_text,
                "items": items_text,
            }

        return rows

    @classmethod
    def _resolve_next_stage_index(cls, current_stage_index: int, previous_snapshot, snapshot) -> int:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        if (
            current_stage_index < 3
            and (
                (
                    previous_stage_ptr
                    and current_stage_ptr
                    and current_stage_ptr != previous_stage_ptr
                )
                or (
                    previous_stage_ptr == 0
                    and current_stage_ptr == 0
                    and previous_seed is not None
                    and current_seed is not None
                    and current_seed != previous_seed
                )
            )
        ):
            return current_stage_index + 1

        if current_stage_index == 3 and cls._looks_like_stage_four_transition(previous_snapshot, snapshot):
            return 4
        return current_stage_index

    @staticmethod
    def _is_stage_transition_boundary_snapshot(snapshot) -> bool:
        stage_time = getattr(snapshot, "stage_time_seconds", None)
        if stage_time is None:
            return False
        return 0.0 <= float(stage_time) <= PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS

    @classmethod
    def _looks_like_stage_four_transition(cls, previous_snapshot, snapshot) -> bool:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        previous_stage_time = getattr(previous_snapshot, "stage_time_seconds", None)
        current_stage_time = getattr(snapshot, "stage_time_seconds", None)
        previous_run_time = getattr(previous_snapshot, "game_time_seconds", None)
        current_run_time = getattr(snapshot, "game_time_seconds", None)
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr != current_stage_ptr
            or previous_seed != current_seed
            or previous_stage_time is None
            or current_stage_time is None
            or previous_run_time is None
            or current_run_time is None
        ):
            return False
        if current_run_time <= previous_run_time:
            return False
        if current_stage_time < 10.0 and current_stage_time + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS < previous_stage_time:
            return True
        return (
            previous_stage_time < 60.0
            and current_stage_time - previous_stage_time >= PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS
        )

    @classmethod
    def _item_gain_between_snapshots(cls, first_snapshot, last_snapshot) -> int:
        first_counts = cls._item_counts(getattr(first_snapshot, "items", ()))
        last_counts = cls._item_counts(getattr(last_snapshot, "items", ()))
        total_gain = 0
        for name, current_count in last_counts.items():
            total_gain += max(0, current_count - first_counts.get(name, 0))
        return total_gain

    @classmethod
    def _item_rarity_gain_between_snapshots(cls, first_snapshot, last_snapshot) -> dict[str, int]:
        first_counts = cls._item_counts(getattr(first_snapshot, "items", ()))
        last_counts = cls._item_counts(getattr(last_snapshot, "items", ()))
        rarity_gains = cls._empty_item_rarity_totals()
        for name, current_count in last_counts.items():
            gain = max(0, current_count - first_counts.get(name, 0))
            if gain <= 0:
                continue
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_gains:
                rarity_gains[rarity] += gain
        return rarity_gains

    @classmethod
    def _create_stage_item_gain_tracker(cls, items) -> dict[str, dict[str, int]]:
        return {
            "confirmed_counts": cls._item_counts(items),
            "pending_drop_streaks": {},
        }

    @classmethod
    def _update_stage_item_gain_tracker(cls, tracker: dict[str, dict[str, int]], items) -> dict[str, int]:
        confirmed_counts = tracker.setdefault("confirmed_counts", {})
        pending_drop_streaks = tracker.setdefault("pending_drop_streaks", {})
        current_counts = cls._item_counts(items)
        rarity_gains = cls._empty_item_rarity_totals()

        for name in set(confirmed_counts) | set(current_counts) | set(pending_drop_streaks):
            current_count = current_counts.get(name, 0)
            confirmed_count = confirmed_counts.get(name, 0)
            if current_count >= confirmed_count:
                pending_drop_streaks.pop(name, None)
                gain = current_count - confirmed_count
                if gain > 0:
                    rarity_name = cls._normalize_item_name_for_rarity(name)
                    rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
                    if rarity in rarity_gains:
                        rarity_gains[rarity] += gain
                if current_count > 0:
                    confirmed_counts[name] = current_count
                else:
                    confirmed_counts.pop(name, None)
                continue

            streak = int(pending_drop_streaks.get(name, 0)) + 1
            if streak >= PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS:
                pending_drop_streaks.pop(name, None)
                if current_count > 0:
                    confirmed_counts[name] = current_count
                else:
                    confirmed_counts.pop(name, None)
                continue
            pending_drop_streaks[name] = streak

        return rarity_gains

    @classmethod
    def _format_stage_item_rarity_summary(cls, rarity_totals: dict[str, int]) -> str:
        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = int(rarity_totals.get(rarity, 0))
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
            )
        return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'

    @staticmethod
    def _set_stage_summary_labels(labels, rows) -> None:
        default_rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        rows = rows or default_rows
        for labels_by_column, row in zip(labels, rows):
            if isinstance(labels_by_column, dict):
                labels_by_column["stage"].setText(str(row["label"]).replace("Stage ", ""))
                labels_by_column["time"].setText(row["time"])
                labels_by_column["kills"].setText(row["kills"])
                labels_by_column["items"].setText(row["items"])
            else:
                labels_by_column.setText(
                    f"{row['label']}: Kills {row['kills']} | Time {row['time']} | Items {row['items']}"
                )

    @classmethod
    def format_items_rich_text(cls, items) -> str:
        if not items:
            return "--"
        return ", ".join(cls._format_single_item_rich_text(item) for item in items)

    @classmethod
    def _format_single_item_rich_text(cls, item_text: str) -> str:
        item_name, suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        color = ITEM_RARITY_COLOR_MAP.get(rarity)
        escaped_name = html.escape(display_name)
        if color:
            escaped_name = f'<span style="color: {color}; font-weight: 700;">{escaped_name}</span>'
        escaped_suffix = html.escape(suffix)
        return f"{escaped_name}{escaped_suffix}"

    @staticmethod
    def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
        if not item_text:
            return "", ""
        name, separator, suffix = item_text.rpartition(" x")
        if separator and suffix.isdigit():
            return name, f"{separator}{suffix}"
        return item_text, ""

    @staticmethod
    def _normalize_item_name_for_rarity(item_name: str) -> str:
        normalized = " ".join(item_name.split())
        if normalized in ITEM_RARITY_NAME_ALIASES:
            return ITEM_RARITY_NAME_ALIASES[normalized]
        if normalized.startswith("Gloves "):
            normalized = f"Glove {normalized[len('Gloves '):]}"

        folded = _fold_item_name_for_rarity(normalized)
        folded = ITEM_RARITY_FOLDED_NAME_ALIASES.get(folded, folded)
        return ITEM_RARITY_NAME_BY_FOLDED_NAME.get(folded, normalized)

    @staticmethod
    def _normalize_item_name_for_display(item_name: str) -> str:
        normalized = " ".join(item_name.split())
        return ITEM_DISPLAY_NAME_ALIASES.get(normalized, normalized)

    @staticmethod
    def calculate_player_chests_per_minute(stats) -> float | None:
        elite_stat = stats.get("Elite Spawn Increase")
        powerup_stat = stats.get("Powerup Drop Chance")
        elite_spawn_increase = getattr(elite_stat, "value", None)
        powerup_drop_chance = getattr(powerup_stat, "value", None)
        if elite_spawn_increase is None or powerup_drop_chance is None:
            return None
        return calculate_chests_per_minute(elite_spawn_increase, powerup_drop_chance)

    @classmethod
    def resolve_snapshot_chests_per_minute(cls, snapshot) -> float | None:
        stored_value = getattr(snapshot, "chests_per_minute", None)
        if stored_value is not None:
            return stored_value
        return cls.calculate_player_chests_per_minute(snapshot.stats)

    @staticmethod
    def format_chests_per_minute(value: float | None) -> str:
        if value is None:
            return "Average chests/min: --"
        return f"Average chests/min: {value:.2f}"

    def close_player_stats_client(self):
        player_stats_client = self.__dict__.get("player_stats_client")
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self.player_stats_client = None

    def close_player_stats_game_data_client(self):
        game_data_client = self.__dict__.get("player_stats_game_data_client")
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self.player_stats_game_data_client = None
