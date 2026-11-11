from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config
from app.active_recording_feed import ActiveRecordingState, RECORDING
from app.validator_reports import HISTORY_KEY, ValidatorReports
from infra.vod_storage import VodMetadata, VodSnapshot

BASE = 'https://validator.example'
CREATED = '2026-11-11T15:00:00.000000Z'
PROCESS = (42, CREATED)
FILETIME = 116444736000000000 + int(datetime.fromisoformat(CREATED).timestamp()) * 10_000_000


@pytest.fixture
def settings(monkeypatch):
    data = {}
    monkeypatch.setattr(config, 'user_config', data)
    monkeypatch.setattr(config, 'profile_read_only_reason', lambda: '')

    def save(mutate):
        mutate(data)
        return config.ConfigSaveResult(True)

    monkeypatch.setattr(config, 'update_config', save)
    return data


def run(session, samples=(), **fields):
    return {
        'session_id': session, 'status': 'active', 'started_at': '2026-11-11T18:42:00Z',
        'process': PROCESS, 'samples': samples, **fields,
    }


def snapshot(active, **runs):
    return {'enabled': True, 'active_run_id': active, 'delivery': {'runs': runs}}


def recording(recording_id, captured_at, timer):
    path = Path(f'{recording_id}.jsonl')
    metadata = VodMetadata(
        path, 'Dice 2026-11-11 18:42:00', '2026-11-11T18:42:00', 3, 0, 1,
        run_seed=123, character_name='Dice', recording_id=recording_id, mob_kills=19,
    )
    sample = VodSnapshot(0, captured_at, {}, game_time_seconds=timer, mob_kills=19,
                         stage_ptr=500, stage_index=0)
    return ActiveRecordingState(path, metadata, (sample,), 1, RECORDING)


def client(pid=42):
    return SimpleNamespace(memory=SimpleNamespace(process_identity=lambda: f'{pid}:{FILETIME}'))


def test_recording_link_survives_restart_and_same_seed_does_not_link_old_attempt(settings):
    history = ValidatorReports()
    before_restart = run('old', ((10, 500, 0, 100), (11, 500, 0, 101)))
    after_restart = run('new', ((11.3, 500, 0, .3), (12.3, 500, 0, 1.3)))
    history.refresh(snapshot('new', old=before_restart, new=after_restart), BASE)
    state = recording('new-recording', 11.8, .8)
    history.observe_recording(state, client(), client())
    history.refresh(snapshot('new', old=before_restart, new=after_restart), force=True)
    assert history.for_recording('new-recording').url.endswith('/new')
    assert history.for_recording('new-recording').name == 'Dice'
    assert next(report for report in history.recent() if report.url.endswith('/old')).recording_ids == ()
    assert 'process' not in repr(settings[HISTORY_KEY])
    assert 'samples' not in repr(settings[HISTORY_KEY])

    reloaded = ValidatorReports()
    assert reloaded.for_recording('new-recording').status == 'finish_unconfirmed'
    renamed = replace(state.metadata, name='My tournament run')
    assert any(report.name == 'My tournament run' and report.kills == 19 for report in reloaded.recent([renamed]))


def test_recording_requires_same_process_and_bracketing_samples(settings):
    history = ValidatorReports()
    current = run('one', ((10, 500, 0, 2), (11, 500, 0, 3)))
    history.refresh(snapshot('current', current=current), BASE)
    history.observe_recording(recording('other-process', 10.5, 2.5), client(43), client(43))
    history.observe_recording(recording('earlier', 9.5, 2.5), client(), client())
    history.observe_recording(recording('restarted', 10.5, .2), client(), client())
    history.refresh(snapshot('current', current=current))
    assert history.live().recording_ids == ()
    assert len(history.recent()) == 1


def test_pending_enrollment_does_not_offer_previous_link_and_final_status_is_retained(settings):
    history = ValidatorReports()
    ended = run('ended', status='finished', finish_requested=True, finish_reason='run_ended', partial=True)
    history.refresh(snapshot(None, ended=ended), BASE)
    assert history.live().status == 'finished'
    history.refresh(snapshot('next', ended=ended, next=run(None, status='enrolling')), force=True)
    assert history.live() is None
    restored = ValidatorReports().recent()
    assert len(restored) == 1 and restored[0].status == 'finished' and restored[0].partial
