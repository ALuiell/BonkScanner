"""Source attribution, recording compatibility, and controlled-game regressions."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import src  # noqa: F401
from app.active_recording_feed import ActiveRecordingFeed
from app.refresh_coordinator import RefreshTickContext
from core.powerup_history import PowerupHistory, PowerupObservation, RecordedEffect
from core.stats.types import PowerupTrackingSnapshot, PowerupReadHealth
from core.vod_capture import VodCapturePayload
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError
from infra.vod_storage import VodRecorder, load_vod
from projections.powerup_history import PowerupProjection
from tests.test_player_stats import FakeMemory
from tests.support.vod_capture import build_vod_capture
from tests.support.refresh_tasks import build_refresh_tasks


def sample(at, effects=(), *, stock=3, pickups=0, run='run', valid=True):
    return PowerupObservation(at, at if valid else None, at if valid else None, run, valid,
                              tuple(RecordedEffect(*e) for e in effects), stock, pickups)


class ClockAttributionTests(unittest.TestCase):
    def test_controlled_live_cases_at_scanner_cadence(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/clock_pickup_sources.json').read_text())
        for case in fixture['cases']:
            with self.subTest(case=case['name']):
                rows = tuple(PowerupObservation.from_record(r) for r in case['observations'])
                previous = None
                for end in range(1, len(rows) + 1):
                    history = PowerupHistory(rows[:end], finalized=end == len(rows))
                    incremental = PowerupProjection(history, previous=previous)
                    full = PowerupProjection(history)
                    self.assertEqual(incremental.counts(rows[end-1].captured_at, 0),
                                     full.counts(rows[end-1].captured_at, 0))
                    self.assertEqual(incremental.unattributed_clock_events(rows[end-1].captured_at, 0),
                                     full.unattributed_clock_events(rows[end-1].captured_at, 0))
                    previous = incremental
                self.assertEqual(previous.counts(rows[-1].captured_at, 0)[4],
                                 case['expected_clock_pickups_in_range'])

    def test_waits_for_stock_confirmation_and_does_not_mutate_previous_revision(self):
        rows = (sample(0), sample(.5, ((4, .25, 15.25),), stock=2),
                sample(1, ((4, .25, 15.25),), stock=2))
        pending = PowerupProjection(PowerupHistory(rows[:2]))
        self.assertEqual(pending.counts(.5)[4], 0)
        self.assertEqual(pending.unattributed_clock_events(.5), 1)
        confirmed = PowerupProjection(PowerupHistory(rows), previous=pending)
        self.assertEqual(confirmed.counts(1)[4], 0)
        self.assertEqual(confirmed.unattributed_clock_events(1), 0)
        self.assertEqual(pending.unattributed_clock_events(.5), 1)
        self.assertIn('excluded Za Warudo activations: 1', confirmed.tooltip(4, 1))
        self.assertGreater(confirmed.totals(1)[4], 0)

    def test_clock_at_duration_collision_and_repeat_after_warudo(self):
        rows = (sample(0), sample(.5, ((4, .25, 15.25),), stock=2),
                sample(1, ((4, .25, 15.25),), stock=2),
                sample(1.5, ((4, .25, 16.25),), stock=2, pickups=1),
                sample(2, ((4, .25, 16.25),), stock=2, pickups=1))
        projection = PowerupProjection(PowerupHistory(rows, True))
        self.assertEqual(projection.counts(2)[4], 1)
        self.assertEqual(projection.counts(2, 1)[4], 1)
        self.assertEqual(projection.counts(1, 2)[4], 1)
        self.assertEqual(projection.counts(1, 1)[4], 0)

    def test_source_conflicts_failures_gaps_and_new_runs_are_unknown(self):
        before, event = sample(0), sample(.5, ((4, .25, 15.25),), stock=2)
        scenarios = (
            (before, replace(event, powerups_used=1), sample(1, stock=2, pickups=1)),
            (before, event, sample(1, stock=3)),  # transient low inventory
            (before, event, sample(1, stock=None)),
            (before, event, sample(1, valid=False)),
            (before, event, sample(5, stock=2)),
            (before, event, sample(1, stock=2, run='other')),
            (sample(0, pickups=4), replace(event, powerups_used=0), sample(1, stock=2)),
        )
        for rows in scenarios:
            with self.subTest(rows=rows):
                projection = PowerupProjection(PowerupHistory(rows))
                self.assertEqual(projection.counts(rows[-1].captured_at)[4], 0)
                self.assertGreater(projection.unattributed_clock_events(rows[-1].captured_at), 0)

    def test_legacy_history_and_late_attachment_keep_time_and_mark_unattributed_clock(self):
        rows = (sample(0, ((4, 0, 15),), stock=None, pickups=None),
                sample(.5, ((4, 0, 15),), stock=None, pickups=None))
        projection = PowerupProjection(PowerupHistory(rows))
        self.assertEqual(projection.counts(.5)[4], 0)
        self.assertEqual(projection.unattributed_clock_events(.5), 1)
        self.assertEqual(projection.totals(.5)[4], .5)
        self.assertIn('Observed pickups: 0+', projection.tooltip(4, .5))
        self.assertEqual(projection.counts(.5, 0)[4], 0)

    def test_no_pickup_counter_growth_cannot_confirm_clock(self):
        rows = (sample(0), sample(.5, ((4, .25, 12.25),)), sample(1))
        projection = PowerupProjection(PowerupHistory(rows))
        self.assertEqual(projection.counts(1)[4], 0)
        self.assertEqual(projection.unattributed_clock_events(1), 1)

    def test_ambiguous_event_preserves_confirmed_count_and_respects_range(self):
        rows = (sample(0), sample(.5, ((4, .25, 12.25),), pickups=1),
                sample(1, ((4, .25, 12.25),), pickups=1),
                sample(1.5, ((4, .25, 16.25),), stock=2, pickups=2),
                sample(2, ((4, .25, 16.25),), stock=2, pickups=2))
        pending = PowerupProjection(PowerupHistory(rows[:4]))
        projection = PowerupProjection(PowerupHistory(rows, True), previous=pending)
        for state in (pending, projection):
            self.assertEqual(state.counts(2)[4], 1)
            self.assertEqual(state.unattributed_clock_events(2), 1)
        self.assertIn('Observed pickups: 1+', projection.tooltip(4, 2))
        self.assertIn('confirmed minimum', projection.tooltip(4, 2))
        self.assertEqual(projection.counts(1, 0)[4], 1)
        self.assertEqual(projection.unattributed_clock_events(1, 0), 0)
        self.assertEqual(projection.counts(2, 1)[4], 0)
        self.assertEqual(projection.unattributed_clock_events(2, 1), 1)
        self.assertEqual(projection.unattributed_clock_events(1, 2), 1)
        self.assertEqual(projection.unattributed_clock_events(1.5, 1.5), 0)

    def test_sources_roundtrip_and_missing_fields_remain_unavailable(self):
        row = sample(.5, ((4, .25, 15.25),), stock=2)
        self.assertEqual(PowerupObservation.from_record(row.to_record()), row)
        legacy = row.to_record()
        del legacy['pickup_sources']
        self.assertIsNone(PowerupObservation.from_record(legacy).za_warudo_count)
        for invalid in ([1], [True, 1], [-1, 1], [1, 1.5], [1, 2**25], 'bad'):
            with self.assertRaises(ValueError):
                PowerupObservation.from_record(dict(legacy, pickup_sources=invalid))

    def test_recording_and_live_feed_retain_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = VodRecorder(vods_dir=Path(directory), clock=lambda: 100)
            recorder.start(name='Sources')
            recorder.capture(VodCapturePayload(stats={}))
            feed = ActiveRecordingFeed()
            feed.start(recorder.current_metadata())
            service, _ = build_vod_capture(recorder=recorder, active_recording_feed=feed)
            for i in range(3):
                raw = PowerupTrackingSnapshot(i, i, i, 0, 600, 1, '1x',
                      timing_health=PowerupReadHealth(captured_at=100+i),
                      za_warudo_count=3, powerups_used=i)
                service.observe_powerups(raw, 'run')
            self.assertEqual(feed.active_state.powerup_history.observations[-1].powerups_used, 2)
            recorder.stop()
            loaded = load_vod(recorder.path)
            self.assertEqual(loaded.powerup_history.observations[-1].za_warudo_count, 3)
            self.assertEqual(loaded.powerup_history.observations[-1].powerups_used, 2)


class PickupSourceMemoryTests(unittest.TestCase):
    def memory(self, stock=3, free=False):
        c = PlayerStatsClient
        owner, inventory, items, dictionary, entries, value = 0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000
        memory = FakeMemory(pointers={owner+c.PLAYER_INVENTORY_OFFSET: inventory,
            inventory+c.ITEM_INVENTORY_OFFSET: items, items+c.ITEM_INVENTORY_ITEMS_DICT_OFFSET: dictionary,
            dictionary+c.DICT_ENTRIES_OFFSET: entries, entries+c.DICT_ENTRY_START_OFFSET+c.DICT_ENTRY_VALUE_OFFSET: value},
            ints={dictionary+c.DICT_COUNT_OFFSET: 1, dictionary+c.DICT_FREE_COUNT_OFFSET: int(free),
                  dictionary+c.DICT_VERSION_OFFSET: 2, entries+c.ARRAY_LENGTH_OFFSET: 4,
                  entries+c.DICT_ENTRY_START_OFFSET+c.DICT_ENTRY_HASH_CODE_OFFSET: -1 if free else 25,
                  entries+c.DICT_ENTRY_START_OFFSET+c.DICT_ENTRY_KEY_OFFSET: 25,
                  value+c.ITEM_STACK_COUNT_OFFSET: stock})
        return PlayerStatsClient(memory=memory), memory, owner, dictionary, value

    def test_reads_stock_by_id_and_zero_before_first_native_pickup(self):
        client, memory, owner, dictionary, value = self.memory()
        with patch.object(client, 'get_run_stat_values', return_value={}):
            self.assertEqual(client.get_powerup_pickup_sources(owner), (3, 0))
        client, *_ = self.memory(free=True)
        with patch.object(client, 'get_run_stat_values', return_value={'powerupsUsed': 8.0}):
            self.assertEqual(client.get_powerup_pickup_sources(owner), (0, 8))

    def test_invalid_or_torn_inventory_and_counter_never_become_zero(self):
        for kind in ('missing', 'negative_free', 'capacity', 'unstable_stack', 'counter_failure', 'counter_nan', 'counter_fraction'):
            client, memory, owner, dictionary, value = self.memory()
            c = PlayerStatsClient
            if kind == 'missing': del memory.pointers[owner+c.PLAYER_INVENTORY_OFFSET]
            if kind == 'negative_free': memory.ints[dictionary+c.DICT_FREE_COUNT_OFFSET] = -1
            if kind == 'capacity': memory.ints[0x5000+c.ARRAY_LENGTH_OFFSET] = 0
            counter = {'powerupsUsed': float('nan') if kind == 'counter_nan' else 1.5 if kind == 'counter_fraction' else 5}
            with patch.object(client, 'get_run_stat_values', side_effect=MemoryReadError('failed') if kind=='counter_failure' else None, return_value=counter):
                if kind == 'unstable_stack':
                    with patch.object(client, '_read_stable_item_stack_count', side_effect=MemoryReadError('torn')):
                        self.assertEqual(client.get_powerup_pickup_sources(owner), (None, None))
                else:
                    self.assertEqual(client.get_powerup_pickup_sources(owner), (None, None))

    def test_dictionary_mutation_and_missing_occupied_entries_are_unavailable(self):
        for kind in ('version_changed', 'missing_occupied'):
            client, memory, owner, dictionary, _ = self.memory()
            version_address = dictionary + client.DICT_VERSION_OFFSET
            read_i32 = memory.read_i32
            reads = []

            def read(address):
                if address == version_address:
                    reads.append(address)
                    return 2 if len(reads) == 1 else 3
                return read_i32(address)

            if kind == 'missing_occupied':
                memory.ints[0x5000 + client.DICT_ENTRY_START_OFFSET + client.DICT_ENTRY_HASH_CODE_OFFSET] = -1
            with patch.object(client, 'get_run_stat_values', return_value={'powerupsUsed': 3}), \
                 patch.object(memory, 'read_i32', side_effect=read if kind == 'version_changed' else read_i32):
                self.assertEqual(client.get_powerup_pickup_sources(owner), (None, None))


class PickupSourceRefreshTests(unittest.TestCase):
    def test_recording_enrichment_preserves_live_snapshot_and_optional_failure_keeps_time(self):
        raw = PowerupTrackingSnapshot(1, 1, 1, 0, 600, 1, '1x')
        for evidence in ((2, 5), MemoryReadError('unavailable')):
            source = Mock(side_effect=evidence) if isinstance(evidence, Exception) else Mock(return_value=evidence)
            captured, tracked = [], []
            client = SimpleNamespace(resolve_owner_stats=lambda: 123,
                get_powerup_tracking_snapshot=lambda _: raw, get_powerup_pickup_sources=source)
            service, world = build_refresh_tasks(stats_client=client,
                vod_recorder=SimpleNamespace(is_recording=True),
                capture=SimpleNamespace(observe_powerups=lambda snapshot, run: captured.append(snapshot)))
            world.tracker.update_powerups = lambda snapshot: tracked.append(snapshot)
            self.assertTrue(service._refresh_powerups_task(RefreshTickContext(1, 0, clock=lambda: 0)))
            source.assert_called_once_with(123)
            self.assertIs(tracked[0], raw)
            self.assertEqual(captured[0].my_time_seconds, 1)
            self.assertEqual(captured[0].za_warudo_count, None if isinstance(evidence, Exception) else 2)

    def test_does_not_read_pickup_sources_when_not_recording(self):
        source = Mock(side_effect=AssertionError('extra live read'))
        raw = PowerupTrackingSnapshot(1, 1, 1, 0, 600, 1, '1x')
        client = SimpleNamespace(resolve_owner_stats=lambda: 123,
            get_powerup_tracking_snapshot=lambda _: raw, get_powerup_pickup_sources=source)
        service, _ = build_refresh_tasks(stats_client=client,
            vod_recorder=SimpleNamespace(is_recording=False))
        self.assertTrue(service._refresh_powerups_task(RefreshTickContext(1, 0, clock=lambda: 0)))
        source.assert_not_called()
