"""Builder for the VOD capture service.

The same contract as `tests/support/run_lifecycle.py` and
`tests/support/player_stats.py`: call the component's **real** constructor with
explicit fakes, rather than borrowing `MegabonkApp`'s MRO through
`object.__new__`. Adding a dependency to `VodCapture` breaks every call site
here loudly, where `object.__new__` absorbs it silently and surfaces it as an
`AttributeError` at the first read, in whichever test happens to reach it
first.

**Deliberately not used by every recording test.** The `_sync_run_state`
scenarios in `test_gui_run_control.py` keep `build_recording_app`, because what
they exercise is the round trip through the *real* memory-reading code path --
`FakeSeedStateClient` feeding `_read_player_stats_recording_state_safe`, and a
real `LiveRunTracker` keeping the update -> runtime_snapshot round trip honest.
Swapping those for two lambdas would replace a real collaborator with a fiction
and turn an integration test into a restatement of the fake, which §5 of the
roadmap names as how fiction gets into this suite. They reach the service
through `vod_capture(app)` instead. This builder is for the cases that genuinely
have no app in them.

Every argument is a callable because every dependency of `VodCapture` is: a
mixin method read `self` late, a constructor argument reads it once, and step 20
shipped that difference as a bug twice in one commit.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from app.vod_capture import VodCapture


def build_vod_capture(
    *,
    recorder: Any = None,
    recording_states: Any = None,
    run_timers: Any = None,
    run_lifecycle: Any = None,
    refresh_now: Callable[..., Any] | None = None,
    player_stats_view: Any = None,
    recordings_list_view: Any = None,
    is_live_stats_tab_active: bool | Callable[[], bool] = True,
    clock: Callable[[], float] | None = None,
    read_character_identity: Callable[[], tuple[int, str] | None] | None = None,
    read_game_build_id: Callable[[], str | None] | None = None,
    read_process_environment: Callable[[], dict[str, Any] | None] | None = None,
    world: Any = None,
) -> tuple[VodCapture, Any]:
    """A real `VodCapture` with its collaborators faked.

    Returns `(service, world)`, where `world` records what the service asked of
    each collaborator: `world.log`, `world.refresh_calls`, `world.view_calls`,
    `world.closed_clients`, `world.snapshot_resets`.

    `recording_states` / `run_timers` accept either a callable (used as the
    reader directly) or an iterable consumed one per read, with `None` returned
    once exhausted -- which is what a failed memory read looks like to this
    service, and the branch that turns a missing seed into the grace window.
    """
    if world is None:
        world = SimpleNamespace()
    world.log = getattr(world, "log", [])
    world.refresh_calls = getattr(world, "refresh_calls", [])
    world.view_calls = getattr(world, "view_calls", [])
    world.closed_clients = getattr(world, "closed_clients", [])
    world.snapshot_resets = getattr(world, "snapshot_resets", [])

    if recorder is None:
        recorder = _FakeRecorder()
    world.recorder = recorder

    if player_stats_view is None:
        player_stats_view = SimpleNamespace(
            refresh_player_stats_timeline_ui=lambda **k: world.view_calls.append(
                ("timeline", dict(sorted(k.items())))
            ),
            set_recording_status_text=lambda text: world.view_calls.append(("status", text)),
        )
    if recordings_list_view is None:
        recordings_list_view = SimpleNamespace(
            _refresh_vods_list_if_visible=lambda: world.view_calls.append(("vods_list", None))
        )
    if run_lifecycle is None:
        run_lifecycle = SimpleNamespace(
            state_or_unknown=lambda _context=None: None,
            state_for_refresh=lambda _context=None: None,
            set_completed=lambda value: None,
            mark_completed_on_tracker=lambda: None,
        )

    def _refresh(**kwargs):
        world.refresh_calls.append(dict(sorted(kwargs.items())))
        if refresh_now is not None:
            return refresh_now(**kwargs)
        return None

    service = VodCapture(
        recorder=lambda: recorder,
        read_recording_state=_reader(recording_states),
        read_run_timer=_reader(run_timers),
        close_game_data_client=lambda: world.closed_clients.append(True),
        run_lifecycle=(run_lifecycle if callable(run_lifecycle) else (lambda: run_lifecycle)),
        refresh_now=_refresh,
        player_stats_view=lambda: player_stats_view,
        recordings_list_view=lambda: recordings_list_view,
        is_live_stats_tab_active=(
            is_live_stats_tab_active
            if callable(is_live_stats_tab_active)
            else (lambda: is_live_stats_tab_active)
        ),
        log=lambda message, tag=None: world.log.append((message, tag)),
        reset_snapshot_buffer=lambda: world.snapshot_resets.append(True),
        read_character_identity=read_character_identity,
        read_game_build_id=read_game_build_id,
        read_process_environment=read_process_environment,
        **({"clock": clock} if clock is not None else {}),
    )
    return service, world


def _reader(source) -> Callable[[], Any]:
    if source is None:
        return lambda: None
    if callable(source):
        return source
    items = iter(source)

    def read():
        try:
            return next(items)
        except StopIteration:
            return None

    return read


class _FakeRecorder:
    """The recorder surface `VodCapture` actually touches, and nothing else."""

    def __init__(self) -> None:
        self.is_recording = False
        self.start_calls: list[dict] = []
        self.stop_calls = 0

    def start(
        self,
        *,
        seed=None,
        name=None,
        character_id=None,
        character_name=None,
    ):
        self.start_calls.append(
            {
                "seed": seed,
                "name": name,
                **(
                    {
                        "character_id": character_id,
                        "character_name": character_name,
                    }
                    if character_id is not None or character_name is not None
                    else {}
                ),
            }
        )
        self.is_recording = True
        return SimpleNamespace(name=f"vod-{seed}.json")

    def stop(self) -> None:
        self.stop_calls += 1
        self.is_recording = False
