from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app import config
from app.version import CURRENT_VERSION, parse_version
from core.update_types import PreparedUpdate, ProgressCallback, ReleaseInfo
from infra import updater


UpdateState = Literal["current", "available", "unknown", "unavailable"]


@dataclass(frozen=True)
class UpdateCheckResult:
    """The complete answer to one release check, without any widget work."""

    state: UpdateState
    version: str = ""
    release: ReleaseInfo | None = None
    exe_path: str | None = None
    should_prompt: bool = False
    error: str = ""


def check_for_update(*, force_check: bool = False) -> UpdateCheckResult:
    """Compare the frozen application with GitHub and return a UI-neutral result."""
    try:
        exe_path = updater.frozen_exe_path()
        if exe_path is None:
            return UpdateCheckResult(state="unavailable")
        release = updater.fetch_latest_release()
        latest_is_newer = parse_version(release.version) > parse_version(CURRENT_VERSION)
    except Exception as exc:
        return UpdateCheckResult(state="unknown", error=str(exc))

    if not latest_is_newer:
        return UpdateCheckResult(state="current", version=CURRENT_VERSION)

    skipped = config.SKIPPED_UPDATE_VERSION == release.version
    return UpdateCheckResult(
        state="available",
        version=release.version,
        release=release,
        exe_path=exe_path,
        should_prompt=force_check or not skipped,
    )


def skip_update_version(version: str) -> config.SettingsSaveResult:
    """Persist the explicit choice without changing runtime state on failure."""
    parse_version(version)
    result = config.save_settings_with_game_reset(
        {"SKIPPED_UPDATE_VERSION": version},
        None,
        sync_game=False,
    )
    if result.success:
        config.SKIPPED_UPDATE_VERSION = version
    return result


def prepare_update(
    exe_path: str,
    release: ReleaseInfo,
    *,
    progress: ProgressCallback | None = None,
) -> PreparedUpdate:
    """Application-layer port for the infrastructure download implementation."""
    return updater.prepare_update(exe_path, release, progress=progress)


def launch_prepared_update(prepared: PreparedUpdate):
    """Application-layer port for starting the post-shutdown installer."""
    return updater.launch_prepared_update(prepared)


def consume_update_result() -> tuple[str, str] | None:
    """Application-layer port for the previous installer's restart notice."""
    return updater.consume_update_result()
