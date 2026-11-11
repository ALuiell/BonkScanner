"""Local history and conservative recording links for registered Validator reports."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from math import isfinite
import time
from typing import NamedTuple
from urllib.parse import quote, urlsplit

from app import config
from app.active_recording_feed import RECORDING
from infra.vod_storage import format_recording_kill_count

HISTORY_KEY = 'LIVE_VALIDATOR_REPORTS'
HISTORY_LIMIT = 100


@dataclass(frozen=True)
class ValidatorReport:
    url: str
    started: str
    status: str
    partial: bool = False
    recording_ids: tuple[str, ...] = ()
    name: str | None = None
    kills: int | None = None


class _RecordingSample(NamedTuple):
    captured_at: float
    stage_ptr: int
    stage_index: int | None
    game_time_seconds: float | None


def report_url(base: str, session_id: str | None) -> str:
    if not base or not session_id:
        return ''
    return f"{base}/v2/sessions/{quote(session_id, safe='')}"


def _read_report(value) -> ValidatorReport | None:
    try:
        report = ValidatorReport(**value)
        url = urlsplit(report.url)
        if (
            url.scheme not in ('https', 'http') or not url.hostname
            or url.username or url.password or url.query or url.fragment
        ):
            return None
        datetime.fromisoformat(report.started)
        if not isinstance(report.recording_ids, (tuple, list)) or not all(
            isinstance(value, str) for value in report.recording_ids
        ):
            return None
        if report.kills is not None and type(report.kills) is not int:
            return None
        if report.name is not None and not isinstance(report.name, str):
            return None
    except (TypeError, AttributeError, ValueError):
        return None
    if report.status not in ('finished', 'interrupted', 'failed', 'expired', 'finish_unconfirmed'):
        report = replace(report, status='finish_unconfirmed')
    return replace(report, recording_ids=tuple(report.recording_ids))


def _process_identity(client):
    try:
        pid, ticks = map(int, client.memory.process_identity().split(':'))
        if pid > 0 and ticks > 0:
            created = datetime.fromtimestamp((ticks - 116444736000000000) / 1e7, timezone.utc)
            return pid, created.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (AttributeError, OSError, OverflowError, ValueError):
        pass
    return None


def _recording_name(metadata, kills) -> str:
    character = metadata.character_name or 'Run'
    generated = {f'{character} {metadata.created_label}'}
    if kills is not None:
        generated.add(f'{character} {format_recording_kill_count(kills)} {metadata.created_label}')
    return character if metadata.name in generated else metadata.name


def _matches_recording(samples, snapshot) -> bool:
    timer = snapshot.game_time_seconds
    if not snapshot.stage_ptr or snapshot.stage_index is None or timer is None or not isfinite(timer):
        return False
    for before, after in zip(samples, samples[1:]):
        left, right = before[0], after[0]
        if left is None or right is None or not 0 < right - left <= 2.5:
            continue
        if not left <= snapshot.captured_at <= right:
            continue
        stage = (snapshot.stage_ptr, snapshot.stage_index)
        if tuple(before[1:3]) == tuple(after[1:3]) == stage and before[3] <= timer <= after[3]:
            return True
    return False


class ValidatorReports:
    """Keeps report links and display metadata. Transport and write keys stay in RAM."""

    def __init__(self):
        raw = config.user_config.get(HISTORY_KEY, [])
        saved = [_read_report(value) for value in raw[:HISTORY_LIMIT]] if isinstance(raw, list) else []
        self._reports = {report.url: report for report in saved if report is not None}
        self._saved = tuple(self._reports.values())
        self._run_reports = {}
        self._pending_recordings = deque(maxlen=32)
        self._recording_runs = {}
        self._recording_details = {}
        self._active_id = None
        self._last_url = ''
        self._base = ''
        self._enabled = False
        self._last_save_attempt = float('-inf')
        self.save_failed = False

    def observe_recording(self, state, stats_client, game_client):
        recording_id = state.metadata.recording_id
        if not recording_id or not state.snapshots:
            return
        if not self._enabled and recording_id not in self._recording_runs:
            return
        snapshot = state.snapshots[-1]
        previous = self._recording_details.get(recording_id)
        kills = state.metadata.mob_kills
        if kills is None:
            kills = snapshot.mob_kills
        if previous and (kills is None or previous[1] is not None and previous[1] > kills):
            kills = previous[1]
        self._recording_details[recording_id] = (state.metadata, kills, snapshot.captured_at)
        if len(self._recording_details) > HISTORY_LIMIT:
            old = next(iter(self._recording_details))
            del self._recording_details[old]
            self._recording_runs.pop(old, None)
        if (
            state.status == RECORDING and recording_id not in self._recording_runs
            and (previous is None or previous[2] != snapshot.captured_at)
        ):
            process = _process_identity(stats_client)
            if process is not None and process == _process_identity(game_client):
                self._pending_recordings.append((recording_id, process, _RecordingSample(
                    snapshot.captured_at, snapshot.stage_ptr, snapshot.stage_index, snapshot.game_time_seconds,
                )))

    def refresh(self, snapshot, base=None, *, force=False):
        if base is not None:
            self._base = base
        base = self._base
        runs = (snapshot.get('delivery') or {}).get('runs', {})
        self._enabled = snapshot.get('enabled', False)
        self._active_id = snapshot.get('active_run_id')
        self._match_recordings(runs)
        self._run_reports = {}
        for run_id, run in runs.items():
            previous_url = report_url(base, run.get('previous_session_id'))
            if previous_url in self._reports:
                self._reports[previous_url] = replace(
                    self._reports[previous_url], status='interrupted', partial=True,
                )
            url = report_url(base, run.get('session_id'))
            if not url:
                continue
            report = self._reports.get(url)
            if report is None:
                report = ValidatorReport(url, run.get('started_at') or datetime.now(timezone.utc).isoformat(), 'active')
            status = run['status']
            if status == 'finished' and run.get('finish_reason') not in (None, 'run_ended'):
                status = 'interrupted'
            elif run.get('finish_requested') and status in ('active', 'enrolling', 'retrying'):
                status = 'finish_pending'
            report = replace(report, status=status, partial=bool(run.get('partial')))
            self._reports[url] = report
            self._run_reports[run_id] = url

        self._apply_recording_details()
        for run in runs.values():
            previous_url = report_url(base, run.get('previous_session_id'))
            if previous_url in self._reports and run.get('session_id'):
                self._reports[previous_url] = replace(self._reports[previous_url], recording_ids=())
        ordered = sorted(self._reports.values(), key=lambda item: item.started, reverse=True)[:HISTORY_LIMIT]
        self._reports = {report.url: report for report in ordered}
        for url in self._run_reports.values():
            if url in self._reports and (
                self._last_url not in self._reports
                or self._reports[url].started >= self._reports[self._last_url].started
            ):
                self._last_url = url
        self.save(force=force)

    def _match_recordings(self, runs):
        if not self._pending_recordings:
            return
        for recording_id, process, snapshot in self._pending_recordings:
            if recording_id in self._recording_runs or recording_id not in self._recording_details:
                continue
            # Both samples must bracket the recording's actual capture on
            # the Windows monotonic clock, on the same process and stage.
            # Timer rollback and reused seeds alone cannot establish a link.
            candidates = [
                run_id for run_id, run in runs.items()
                if run.get('process') == process and _matches_recording(run.get('samples', ()), snapshot)
            ]
            if len(candidates) == 1:
                self._recording_runs[recording_id] = candidates[0]
        self._pending_recordings = deque(
            (entry for entry in self._pending_recordings
             if entry[0] in self._recording_details and entry[0] not in self._recording_runs),
            maxlen=self._pending_recordings.maxlen,
        )

    def _apply_recording_details(self):
        for recording_id, run_id in self._recording_runs.items():
            url = self._run_reports.get(run_id)
            if not url:
                continue
            report = self._reports[url]
            metadata, kills, _ = self._recording_details[recording_id]
            recording_ids = tuple(dict.fromkeys((*report.recording_ids, recording_id)))
            name = _recording_name(metadata, kills) if recording_ids[0] == recording_id else report.name
            kills = max((count for count in (report.kills, kills) if count is not None), default=None)
            self._reports[url] = replace(
                report, recording_ids=recording_ids, name=name, kills=kills,
            )

    def save(self, *, force=False):
        reports = tuple(
            replace(report, status='finish_unconfirmed', kills=None)
            if report.status in ('active', 'retrying', 'finish_pending', 'enrolling') else report
            for report in self._reports.values()
        )
        now = time.monotonic()
        if reports == self._saved or not force and now - self._last_save_attempt < 2:
            return
        self._last_save_attempt = now
        if config.profile_read_only_reason():
            self.save_failed = True
            return
        result = config.update_config(lambda settings: settings.update({
            HISTORY_KEY: [asdict(report) for report in reports],
        }))
        self.save_failed = not result.success
        if result.success:
            self._saved = reports

    def recent(self, recordings=()):
        by_id = {recording.recording_id: recording for recording in recordings if recording.recording_id}
        reports = []
        for report in self._reports.values():
            metadata = by_id.get(report.recording_ids[0]) if report.recording_ids else None
            if metadata is not None:
                kills = metadata.mob_kills if metadata.mob_kills is not None else report.kills
                report = replace(report, name=_recording_name(metadata, kills), kills=kills)
            reports.append(report)
        return tuple(reports)

    def live(self) -> ValidatorReport | None:
        url = self._run_reports.get(self._active_id) if self._active_id else self._last_url
        return self._reports.get(url)

    def for_recording(self, recording_id) -> ValidatorReport | None:
        if not recording_id:
            return None
        run_id = self._recording_runs.get(recording_id)
        if url := self._run_reports.get(run_id):
            return self._reports.get(url)
        return next((report for report in self._reports.values() if recording_id in report.recording_ids), None)
