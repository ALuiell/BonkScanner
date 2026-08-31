from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from core.character_passives import CharacterPassiveStatus
from core.run_verifier import (
    ENVIRONMENT_SCHEMA_VERSION,
    FindingSeverity,
    VerificationStatus,
    VerifierStatComponents,
    VerifierStatFrame,
    analyze_records,
    environment_digest,
    reconstruct_stat,
    _Analysis,
)
from infra.run_verifier import VerifierTelemetryWriter, verify_vod
from infra.vod_storage import VOD_FORMAT_VERSION, VodRecorder, load_vod


SUPPORTED_BUILD = "pe-6980d323-036fa000"
SOURCE_AVAILABILITY = {
    "shrines": True,
    "chaos_tome": True,
    "character_passive": True,
}


def _zero_chaos_snapshot():
    return SimpleNamespace(level=0, ambiguous_rolls=0, stats=())


def _clean_environment_snapshot():
    modules = [
        {
            "id": "a" * 24,
            "name": "Megabonk.exe",
            "location": "game",
            "size": 1234,
            "sha256": None,
            "classification": "game",
        }
    ]
    artifacts = []
    private_executable_regions = []
    return {
        "schema": ENVIRONMENT_SCHEMA_VERSION,
        "modules": modules,
        "artifacts": artifacts,
        "private_executable_regions": private_executable_regions,
        "digest": environment_digest(
            modules,
            artifacts,
            private_executable_regions,
        ),
    }


def _stat(stat_id: int, base: float, addition: float) -> VerifierStatComponents:
    additive = 1.0 + addition
    final = reconstruct_stat(base, additive, 1.0)
    return VerifierStatComponents(
        stat_id=stat_id,
        final_value=final,
        raw_value=final,
        has_modifications=False,
        base_value=base,
        additive_value=additive,
        multiplicative_value=1.0,
    )


def _source_fixture(writer: VerifierTelemetryWriter):
    additions = {39: 0.25, 40: 0.20, 41: 0.06}
    frame = VerifierStatFrame(
        stats=tuple(
            _stat(stat_id, 1.30 if stat_id == 39 else 1.0, addition)
            for stat_id, addition in additions.items()
        )
    )
    modifiers = {
        stat_id: (
            SimpleNamespace(
                object_ptr=0xABC000 + stat_id,
                stat_id=stat_id,
                modify_type=0,
                value=value,
            ),
        )
        for stat_id, value in additions.items()
    }
    shrine = SimpleNamespace(
        charged=3,
        selected=3,
        pending=0,
        ambiguous_matches=0,
        stats=tuple(
            SimpleNamespace(stat_id=stat_id, value=value, rolls=1)
            for stat_id, value in additions.items()
        ),
    )
    passive = SimpleNamespace(
        passive_name="Not Gamba",
        status=CharacterPassiveStatus.SUPPORTED,
        coverage="complete",
        ambiguous=0,
        pending=0,
        effects=(),
    )
    records = writer.records_for_checkpoint(
        frame,
        elapsed_seconds=2.0,
        game_time_seconds=2.0,
        permanent_modifiers=modifiers,
        shrine_snapshot=shrine,
        chaos_snapshot=_zero_chaos_snapshot(),
        character_passive_snapshot=passive,
        dice_level=None,
        held_items=("Old Mask x2",),
        source_availability=SOURCE_AVAILABILITY,
    )
    return frame, modifiers, shrine, passive, records


def _complete_records(
    writer: VerifierTelemetryWriter,
    environment_snapshot=None,
):
    _frame, _modifiers, _shrine, _passive, checkpoint_records = _source_fixture(writer)
    environment_record = writer.environment_record(
        environment_snapshot or _clean_environment_snapshot(),
        elapsed_seconds=0.0,
    )
    return [
        {
            "type": "metadata",
            "version": VOD_FORMAT_VERSION,
            "name": "Verifier fixture",
            "created_at": "2026-08-30T12:00:00",
            "verification": writer.metadata(
                scanner_version="3.0.1",
                game_build_id=SUPPORTED_BUILD,
                run_start_time_seconds=0.5,
            ),
        },
        environment_record,
        *checkpoint_records,
        writer.coverage_record(elapsed_seconds=3.0),
        {
            "type": "summary",
            "name": "Verifier fixture",
            "duration_seconds": 3,
            "snapshot_count": 0,
        },
    ]


def _append_checkpoint(records, *, mutate_first=None, mutate_second=None):
    first = next(
        record for record in records if record["type"] == "verification_checkpoint"
    )
    second = deepcopy(first)
    second["sequence"] = 1
    second["elapsed_seconds"] = 4.0
    second["game_time_seconds"] = 4.0
    if mutate_first is not None:
        mutate_first(first)
    if mutate_second is not None:
        mutate_second(second)
    coverage = next(
        record for record in records if record["type"] == "verification_coverage"
    )
    coverage["checkpoint_count"] = 2
    coverage["duration_seconds"] = 5.0
    records[-1]["duration_seconds"] = 5
    records.insert(records.index(coverage), second)
    return first, second


class RunVerifierAnalysisTests(unittest.TestCase):
    def test_repeated_findings_are_retained_as_one_time_range(self):
        analysis = _Analysis()
        for elapsed, detail in (
            (72.2, "modifier sum 0.16"),
            (74.2, "modifier sum 0.16"),
            (366.3, "modifier sum 0.67"),
        ):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Source reconciliation",
                "Powerup Multiplier modifiers disagree",
                detail,
                elapsed=elapsed,
                stat_id=40,
            )

        self.assertEqual(analysis.inconsistencies, 3)
        self.assertEqual(len(analysis.findings), 1)
        finding = analysis.findings[0]
        self.assertEqual(finding.occurrence_count, 3)
        self.assertEqual(finding.elapsed_seconds, 72.2)
        self.assertEqual(finding.last_elapsed_seconds, 366.3)
        self.assertEqual(finding.latest_detail, "modifier sum 0.67")

    def test_known_good_equations_are_consistent(self):
        report = analyze_records(_complete_records(VerifierTelemetryWriter()))

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertEqual(report.unavailable_count, 0)
        self.assertGreater(report.match_count, 10)

    def test_tampered_final_value_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["stats"]["40"]["final"] = 9.0
        checkpoint["stats"]["40"]["final_bits"] = "00001041"

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("final and raw" in finding.title for finding in report.findings)
        )

    def test_missing_modifier_delta_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        records[:] = [
            record
            for record in records
            if not (
                record.get("type") == "verification_event"
                and record.get("modifier_changes")
            )
        ]
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["event_count"] = 0

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("modifier delta history" in finding.title for finding in report.findings)
        )

    def test_legacy_recording_is_partial(self):
        report = analyze_records(
            [
                {"type": "metadata", "name": "Old run", "created_at": "2026-01-01"},
                {"type": "summary", "name": "Old run", "snapshot_count": 0},
            ]
        )

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        report_text = report.to_text()
        self.assertIn("Legacy recording", report_text)
        self.assertIn("Game build: Not recorded", report_text)
        self.assertIn("BonkScanner version: Not recorded", report_text)
        self.assertIn("Verification rules: Not recorded", report_text)
        self.assertNotIn("Mechanics profile", report_text)

    def test_report_explains_the_current_verification_rules(self):
        report = analyze_records(_complete_records(VerifierTelemetryWriter()))

        report_text = report.to_text()

        self.assertIn(
            "Verification rules: Powerup Multiplier, Powerup Drop Chance, and "
            "Elite Spawn Increase (2026-08-30 ruleset)",
            report_text,
        )
        self.assertIn(
            "Technical rules ID: bonkscanner-target-stats-2026-08-30",
            report_text,
        )
        self.assertIn("Field guide: Game build is the game version", report_text)
        self.assertIn("Check guide: matched checks passed", report_text)
        compact_text = report.to_text(include_guide=False)
        self.assertNotIn("Field guide:", compact_text)
        self.assertNotIn("Check guide:", compact_text)
        self.assertIn("Verification rules: Powerup Multiplier", compact_text)

    def test_unknown_build_is_not_checked_with_current_formulas(self):
        records = _complete_records(VerifierTelemetryWriter())
        records[0]["verification"]["game_build_id"] = "pe-deadbeef-00000001"

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.UNSUPPORTED_BUILD)
        self.assertEqual(report.inconsistency_count, 0)

    def test_recorded_gap_makes_result_interrupted(self):
        writer = VerifierTelemetryWriter()
        metadata = {
            "type": "metadata",
            "name": "Gap run",
            "created_at": "2026-08-30",
            "verification": writer.metadata(
                scanner_version="3.0.1",
                game_build_id=SUPPORTED_BUILD,
                run_start_time_seconds=0.0,
            ),
        }
        gap = writer.note_failure(0.5, "transient read")
        _frame, _modifiers, _shrine, _passive, checkpoint_records = _source_fixture(writer)
        environment_record = writer.environment_record(
            _clean_environment_snapshot(),
            elapsed_seconds=0.0,
        )
        records = [
            metadata,
            environment_record,
            gap,
            *checkpoint_records,
            writer.coverage_record(elapsed_seconds=3.0),
            {
                "type": "summary",
                "name": "Gap run",
                "duration_seconds": 3,
                "snapshot_count": 0,
            },
        ]

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INTERRUPTED)
        self.assertEqual(report.warning_count, 1)

    def test_float_larger_than_float32_is_reported_instead_of_crashing(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["stats"]["40"]["final"] = 1e300

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("final is invalid" in item.title for item in report.findings))

    def test_typed_boolean_fields_do_not_accept_truthy_strings(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["stable"] = "false"
        checkpoint["coverage"]["source_attribution_complete"] = "true"

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("stability flag" in item.title for item in report.findings))

    def test_source_coverage_flag_requires_a_json_boolean(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["coverage"]["source_attribution_complete"] = "true"

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("Source coverage flag" in item.title for item in report.findings))

    def test_fractional_sequence_is_not_silently_truncated(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sequence"] = 0.5

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("sequence is discontinuous" in item.title for item in report.findings))

    def test_unstable_checkpoint_cannot_produce_consistent_result(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["stable"] = False

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertEqual(report.coverage_text, "0/1 stable checkpoints")

    def test_unstable_counter_sample_cannot_accuse_next_stable_sample(self):
        records = _complete_records(VerifierTelemetryWriter())
        first = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        unstable = deepcopy(first)
        unstable["sequence"] = 1
        unstable["elapsed_seconds"] = 4.0
        unstable["game_time_seconds"] = 4.0
        unstable["stable"] = False
        unstable["sources"]["dice"]["level"] = 999
        recovered = deepcopy(first)
        recovered["sequence"] = 2
        recovered["elapsed_seconds"] = 6.0
        recovered["game_time_seconds"] = 6.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        insert_at = records.index(coverage)
        records[insert_at:insert_at] = [unstable, recovered]

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.coverage_text, "2/3 stable checkpoints")
        self.assertEqual(report.unavailable_count, 0)
        self.assertFalse(any("Unsettled memory sample" == item.title for item in report.findings))
        self.assertFalse(any("counter regressed" in item.title for item in report.findings))

    def test_unavailable_source_counter_is_not_treated_as_a_regression(self):
        records = _complete_records(VerifierTelemetryWriter())

        def first_counter(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 5

        def unavailable_counter(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 0
            checkpoint["coverage"]["dice_complete"] = False
            checkpoint["coverage"]["source_attribution_complete"] = False

        _append_checkpoint(
            records,
            mutate_first=first_counter,
            mutate_second=unavailable_counter,
        )

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertFalse(any("counter regressed" in item.title for item in report.findings))

    def test_single_source_counter_regression_that_recovers_is_not_an_accusation(self):
        records = _complete_records(VerifierTelemetryWriter())

        def high_counter(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 5

        def transient_low(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 0

        _first, second = _append_checkpoint(
            records,
            mutate_first=high_counter,
            mutate_second=transient_low,
        )
        recovered = deepcopy(second)
        recovered["sequence"] = 2
        recovered["elapsed_seconds"] = 6.0
        recovered["game_time_seconds"] = 6.0
        recovered["sources"]["dice"]["level"] = 5
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), recovered)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertFalse(any("counter regressed" in item.title for item in report.findings))

    def test_persistent_source_counter_regression_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())

        def high_counter(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 5

        def low_counter(checkpoint):
            checkpoint["sources"]["dice"]["level"] = 0

        _first, second = _append_checkpoint(
            records,
            mutate_first=high_counter,
            mutate_second=low_counter,
        )
        repeated_low = deepcopy(second)
        repeated_low["sequence"] = 2
        repeated_low["elapsed_seconds"] = 6.0
        repeated_low["game_time_seconds"] = 6.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), repeated_low)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("counter regressed" in item.title for item in report.findings))

    def test_negative_old_mask_amount_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sources"]["items"]["old_mask"] = -2

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("Old Mask amount" in item.title for item in report.findings))

    def test_arbitrary_precision_integer_cannot_overflow_source_math(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sources"]["items"]["old_mask"] = 10**1000

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("Old Mask amount" in item.title for item in report.findings))

    def test_unreported_game_time_gap_is_interrupted(self):
        records = _complete_records(VerifierTelemetryWriter())
        first = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        second = deepcopy(first)
        second["sequence"] = 1
        second["elapsed_seconds"] = 10.0
        second["game_time_seconds"] = 10.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 2
        coverage["duration_seconds"] = 11.0
        summary = records[-1]
        summary["duration_seconds"] = 11
        records.insert(records.index(coverage), second)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INTERRUPTED)
        self.assertTrue(any("Unreported checkpoint gap" == item.title for item in report.findings))

    def test_game_time_correction_up_to_three_seconds_is_tolerated(self):
        records = _complete_records(VerifierTelemetryWriter())

        def first_time(checkpoint):
            checkpoint["game_time_seconds"] = 10.0

        def corrected_time(checkpoint):
            checkpoint["game_time_seconds"] = 7.0

        _append_checkpoint(
            records,
            mutate_first=first_time,
            mutate_second=corrected_time,
        )

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertFalse(
            any("Game time moved backwards" == item.title for item in report.findings)
        )

    def test_game_time_regression_beyond_three_seconds_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())

        def first_time(checkpoint):
            checkpoint["game_time_seconds"] = 10.0

        def regressed_time(checkpoint):
            checkpoint["game_time_seconds"] = 6.9

        _first, second = _append_checkpoint(
            records,
            mutate_first=first_time,
            mutate_second=regressed_time,
        )
        repeated = deepcopy(second)
        repeated["sequence"] = 2
        repeated["elapsed_seconds"] = 6.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), repeated)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("Game time moved backwards" == item.title for item in report.findings)
        )

    def test_small_repeated_regressions_are_measured_from_high_water_mark(self):
        records = _complete_records(VerifierTelemetryWriter())

        def first_time(checkpoint):
            checkpoint["game_time_seconds"] = 10.0

        def second_time(checkpoint):
            checkpoint["game_time_seconds"] = 8.0

        _first, second = _append_checkpoint(
            records,
            mutate_first=first_time,
            mutate_second=second_time,
        )
        third = deepcopy(second)
        third["sequence"] = 2
        third["elapsed_seconds"] = 6.0
        third["game_time_seconds"] = 6.0
        fourth = deepcopy(third)
        fourth["sequence"] = 3
        fourth["elapsed_seconds"] = 8.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 4
        coverage["duration_seconds"] = 9.0
        records[-1]["duration_seconds"] = 9
        insert_at = records.index(coverage)
        records[insert_at:insert_at] = [third, fourth]

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        finding = next(
            item for item in report.findings if item.title == "Game time moved backwards"
        )
        self.assertIn("Highest observed 10.000s", finding.detail)

    def test_single_large_game_time_regression_that_recovers_is_not_an_accusation(self):
        records = _complete_records(VerifierTelemetryWriter())

        def first_time(checkpoint):
            checkpoint["game_time_seconds"] = 10.0

        def transient_time(checkpoint):
            checkpoint["game_time_seconds"] = 6.0

        _first, second = _append_checkpoint(
            records,
            mutate_first=first_time,
            mutate_second=transient_time,
        )
        recovered = deepcopy(second)
        recovered["sequence"] = 2
        recovered["elapsed_seconds"] = 6.0
        recovered["game_time_seconds"] = 12.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), recovered)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertFalse(
            any("Game time moved backwards" == item.title for item in report.findings)
        )

    def test_recovered_missing_game_time_does_not_become_report_noise(self):
        records = _complete_records(VerifierTelemetryWriter())

        def missing_time(checkpoint):
            checkpoint["game_time_seconds"] = None

        _first, second = _append_checkpoint(records, mutate_second=missing_time)
        recovered = deepcopy(second)
        recovered["sequence"] = 2
        recovered["elapsed_seconds"] = 6.0
        recovered["game_time_seconds"] = 6.0
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), recovered)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.unavailable_count, 0)
        self.assertFalse(
            any("game time is unavailable" in item.title for item in report.findings)
        )

    def test_single_cross_source_transition_that_settles_is_not_a_false_positive(self):
        records = _complete_records(VerifierTelemetryWriter())

        def mismatch(checkpoint):
            checkpoint["sources"]["shrines"]["totals"]["40"] = 0.0

        _append_checkpoint(records, mutate_first=mismatch)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertEqual(report.unavailable_count, 0)

    def test_cross_source_mismatch_must_repeat_before_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())

        def mismatch(checkpoint):
            checkpoint["sources"]["shrines"]["totals"]["40"] = 0.0

        _append_checkpoint(
            records,
            mutate_first=mismatch,
            mutate_second=mismatch,
        )

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("legal sources do not match" in item.title for item in report.findings))

    def test_source_mismatches_separated_by_unavailable_coverage_do_not_combine(self):
        records = _complete_records(VerifierTelemetryWriter())

        def mismatch(checkpoint):
            checkpoint["sources"]["shrines"]["totals"]["40"] = 0.0

        def unavailable(checkpoint):
            checkpoint["coverage"]["shrines_complete"] = False
            checkpoint["coverage"]["source_attribution_complete"] = False

        _first, second = _append_checkpoint(
            records,
            mutate_first=mismatch,
            mutate_second=unavailable,
        )
        third = deepcopy(second)
        third["sequence"] = 2
        third["elapsed_seconds"] = 6.0
        third["game_time_seconds"] = 6.0
        third["coverage"]["shrines_complete"] = True
        third["coverage"]["source_attribution_complete"] = True
        mismatch(third)
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 3
        coverage["duration_seconds"] = 7.0
        records[-1]["duration_seconds"] = 7
        records.insert(records.index(coverage), third)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertTrue(any("was not confirmed" in item.title for item in report.findings))

    def test_unconfirmed_final_cross_source_mismatch_is_partial(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sources"]["shrines"]["totals"]["40"] = 0.0

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertTrue(any("was not confirmed" in item.title for item in report.findings))

    def test_schema1_dice_pending_bug_is_normalized_during_analysis(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sources"]["dice"].update(
            level=0,
            coverage="complete",
            ambiguous=0,
            pending=29,
        )
        checkpoint["coverage"]["dice_complete"] = False
        checkpoint["coverage"]["source_attribution_complete"] = False

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.unavailable_count, 0)

    def test_schema1_genuinely_partial_dice_is_not_normalized(self):
        records = _complete_records(VerifierTelemetryWriter())
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoint["sources"]["dice"].update(
            level=1,
            coverage="partial",
            ambiguous=1,
            pending=0,
        )
        checkpoint["coverage"]["dice_complete"] = False
        checkpoint["coverage"]["source_attribution_complete"] = False

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertTrue(
            any(
                "source attribution is incomplete" in item.title
                for item in report.findings
            )
        )

    def test_recovered_shrine_pending_episodes_do_not_become_report_noise(self):
        records = _complete_records(VerifierTelemetryWriter())
        template = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )
        checkpoints = []
        for sequence, elapsed, charged, selected in (
            (1, 4.0, 4, 3),
            (2, 6.0, 4, 4),
            (3, 8.0, 5, 4),
            (4, 10.0, 5, 5),
        ):
            checkpoint = deepcopy(template)
            checkpoint["sequence"] = sequence
            checkpoint["elapsed_seconds"] = elapsed
            checkpoint["game_time_seconds"] = elapsed
            shrine = checkpoint["sources"]["shrines"]
            shrine.update(
                charged=charged,
                selected=selected,
                pending=charged - selected,
            )
            if charged != selected:
                checkpoint["coverage"]["shrines_complete"] = False
                checkpoint["coverage"]["source_attribution_complete"] = False
            checkpoints.append(checkpoint)
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["checkpoint_count"] = 5
        coverage["duration_seconds"] = 11.0
        records[-1]["duration_seconds"] = 11
        records[records.index(coverage):records.index(coverage)] = checkpoints

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.unavailable_count, 0)
        self.assertFalse(
            any("source attribution is incomplete" in item.title for item in report.findings)
        )

    def test_unresolved_final_shrine_pending_remains_partial(self):
        records = _complete_records(VerifierTelemetryWriter())

        def pending_shrine(checkpoint):
            checkpoint["sources"]["shrines"].update(
                charged=4,
                selected=3,
                pending=1,
            )
            checkpoint["coverage"]["shrines_complete"] = False
            checkpoint["coverage"]["source_attribution_complete"] = False

        _append_checkpoint(records, mutate_second=pending_shrine)

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        findings = [
            item
            for item in report.findings
            if "source attribution is incomplete" in item.title
        ]
        self.assertEqual(len(findings), 3)
        self.assertTrue(all(item.occurrence_count == 1 for item in findings))
        self.assertTrue(all(item.elapsed_seconds == 4.0 for item in findings))

    def test_unavailable_source_is_not_treated_as_zero_bonus(self):
        writer = VerifierTelemetryWriter()
        frame, modifiers, shrine, passive, _records = _source_fixture(writer)

        records = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=None,
            character_passive_snapshot=passive,
            dice_level=None,
            held_items=("Old Mask x2",),
            source_availability={**SOURCE_AVAILABILITY, "chaos_tome": False},
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertFalse(checkpoint["coverage"]["chaos_complete"])
        self.assertFalse(checkpoint["coverage"]["source_attribution_complete"])

    def test_unmatched_non_dice_candidates_do_not_disable_complete_gamba(self):
        frame, modifiers, shrine, _passive, _records = _source_fixture(
            VerifierTelemetryWriter()
        )
        passive = SimpleNamespace(
            passive_name="Gamba",
            status=CharacterPassiveStatus.SUPPORTED,
            coverage="complete",
            ambiguous=0,
            # This is possible at level zero: these are unassigned non-Dice
            # modifiers, not Dice rolls waiting to be reconstructed.
            pending=29,
            effects=(),
        )

        records = VerifierTelemetryWriter().records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=_zero_chaos_snapshot(),
            character_passive_snapshot=passive,
            dice_level=0,
            held_items=("Old Mask x2",),
            source_availability=SOURCE_AVAILABILITY,
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertEqual(checkpoint["sources"]["dice"]["pending"], 29)
        self.assertTrue(checkpoint["coverage"]["dice_complete"])
        self.assertTrue(checkpoint["coverage"]["source_attribution_complete"])

    def test_unresolved_gamba_coverage_still_disables_source_attribution(self):
        frame, modifiers, shrine, _passive, _records = _source_fixture(
            VerifierTelemetryWriter()
        )
        passive = SimpleNamespace(
            passive_name="Gamba",
            status=CharacterPassiveStatus.SUPPORTED,
            coverage="partial",
            ambiguous=1,
            pending=0,
            effects=(),
        )

        records = VerifierTelemetryWriter().records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=_zero_chaos_snapshot(),
            character_passive_snapshot=passive,
            dice_level=1,
            held_items=("Old Mask x2",),
            source_availability=SOURCE_AVAILABILITY,
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertFalse(checkpoint["coverage"]["dice_complete"])
        self.assertFalse(checkpoint["coverage"]["source_attribution_complete"])

    def test_fresh_missing_chaos_entry_means_tome_is_not_held(self):
        writer = VerifierTelemetryWriter()
        frame, modifiers, shrine, passive, _records = _source_fixture(writer)

        records = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=None,
            character_passive_snapshot=passive,
            dice_level=None,
            held_items=("Old Mask x2",),
            source_availability=SOURCE_AVAILABILITY,
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertTrue(checkpoint["coverage"]["chaos_complete"])
        self.assertTrue(checkpoint["coverage"]["source_attribution_complete"])

    def test_missing_target_source_value_makes_attribution_incomplete(self):
        writer = VerifierTelemetryWriter()
        frame, modifiers, shrine, passive, _records = _source_fixture(writer)
        chaos = SimpleNamespace(
            level=1,
            ambiguous_rolls=0,
            stats=(SimpleNamespace(stat_id=40, value=None, rolls=1),),
        )

        records = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=chaos,
            character_passive_snapshot=passive,
            dice_level=None,
            held_items=("Old Mask x2",),
            source_availability=SOURCE_AVAILABILITY,
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertFalse(checkpoint["coverage"]["chaos_complete"])
        self.assertFalse(checkpoint["coverage"]["source_attribution_complete"])

    def test_missing_character_identity_does_not_prove_run_is_not_dice(self):
        writer = VerifierTelemetryWriter()
        frame, modifiers, shrine, _passive, _records = _source_fixture(writer)

        records = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=4.0,
            game_time_seconds=4.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=_zero_chaos_snapshot(),
            character_passive_snapshot=None,
            dice_level=None,
            held_items=("Old Mask x2",),
            source_availability={
                **SOURCE_AVAILABILITY,
                "character_passive": False,
            },
        )
        checkpoint = next(
            record for record in records if record["type"] == "verification_checkpoint"
        )

        self.assertFalse(checkpoint["coverage"]["dice_complete"])
        self.assertFalse(checkpoint["coverage"]["source_attribution_complete"])

    def test_duplicate_metadata_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        records.insert(1, deepcopy(records[0]))

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(any("Duplicate metadata" in item.title for item in report.findings))

    def test_legacy_unknown_labels_for_stock_modules_do_not_require_review(self):
        writer = VerifierTelemetryWriter()
        records = _complete_records(writer)
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        environment["modules"].extend(
            (
                {
                    "id": "b" * 24,
                    "name": "discord_game_sdk.dll",
                    "location": "game",
                    "size": 4321,
                    "sha256": "c" * 64,
                    "classification": "unknown",
                },
                {
                    "id": "d" * 24,
                    "name": "steamclient64.dll",
                    "location": "other",
                    "size": 8765,
                    "sha256": "e" * 64,
                    "classification": "unknown",
                },
            )
        )
        environment["module_count"] = 3
        environment["digest"] = environment_digest(
            environment["modules"],
            environment["artifacts"],
            environment["private_executable_regions"],
        )
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["environment"]["initial_digest"] = environment["digest"]
        coverage["environment"]["final_digest"] = environment["digest"]
        coverage["environment"]["final_module_count"] = 3

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertFalse(
            any("mod-loader modules" in finding.title for finding in report.findings)
        )

    def test_mod_loader_indicator_requires_manual_review(self):
        writer = VerifierTelemetryWriter()
        records = _complete_records(writer)
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        environment["modules"].append(
            {
                "id": "b" * 24,
                "name": "winhttp.dll",
                "location": "game",
                "size": 4321,
                "sha256": "c" * 64,
                "classification": "mod_loader",
            }
        )
        environment["module_count"] = 2
        environment["digest"] = environment_digest(
            environment["modules"],
            environment["artifacts"],
            environment["private_executable_regions"],
        )
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["environment"]["initial_digest"] = environment["digest"]
        coverage["environment"]["final_digest"] = environment["digest"]
        coverage["environment"]["final_module_count"] = 2

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertTrue(
            any("mod-loader modules" in finding.title for finding in report.findings)
        )

    def test_environment_delta_requires_manual_review(self):
        writer = VerifierTelemetryWriter()
        records = _complete_records(writer)
        changed_snapshot = deepcopy(_clean_environment_snapshot())
        changed_snapshot["modules"].append(
            {
                "id": "d" * 24,
                "name": "GameAssembly.dll",
                "location": "game",
                "size": 5678,
                "sha256": None,
                "classification": "game",
            }
        )
        changed_snapshot["digest"] = environment_digest(
            changed_snapshot["modules"],
            changed_snapshot["artifacts"],
            changed_snapshot["private_executable_regions"],
        )
        checkpoint = writer.environment_record(changed_snapshot, elapsed_seconds=10.0)
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        records.insert(records.index(coverage), checkpoint)
        records[records.index(coverage)] = writer.coverage_record(elapsed_seconds=11.0)
        records[-1]["duration_seconds"] = 11

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
        self.assertTrue(
            any("changed during the run" in finding.title for finding in report.findings)
        )

    def test_unrecognized_third_party_module_requires_manual_review(self):
        records = _complete_records(VerifierTelemetryWriter())
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        module = environment["modules"][0]
        module.update(
            name="CustomOverlay.dll",
            location="program_files",
            classification="third_party",
            sha256="e" * 64,
        )
        environment["digest"] = environment_digest(
            environment["modules"],
            environment["artifacts"],
            environment["private_executable_regions"],
        )
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["environment"]["initial_digest"] = environment["digest"]
        coverage["environment"]["final_digest"] = environment["digest"]

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
        self.assertEqual(report.inconsistency_count, 0)

    def test_initial_private_executable_memory_is_a_neutral_baseline(self):
        snapshot = _clean_environment_snapshot()
        snapshot["private_executable_regions"].append(
            {
                "id": "f" * 24,
                "size": 0x3000,
                "protection": 0x40,
                "writable": True,
                "guarded": False,
            }
        )
        snapshot["digest"] = environment_digest(
            snapshot["modules"],
            snapshot["artifacts"],
            snapshot["private_executable_regions"],
        )

        report = analyze_records(
            _complete_records(VerifierTelemetryWriter(), snapshot)
        )

        self.assertEqual(report.status, VerificationStatus.CONSISTENT)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertIn("1 private executable", report.environment_text)
        self.assertTrue(
            any(
                finding.title == "Private executable memory baseline captured"
                for finding in report.findings
            )
        )

    def test_private_executable_memory_delta_requires_manual_review(self):
        writer = VerifierTelemetryWriter()
        records = _complete_records(writer)
        changed_snapshot = _clean_environment_snapshot()
        changed_snapshot["private_executable_regions"].append(
            {
                "id": "9" * 24,
                "size": 0x1000,
                "protection": 0x20,
                "writable": False,
                "guarded": False,
            }
        )
        changed_snapshot["digest"] = environment_digest(
            changed_snapshot["modules"],
            changed_snapshot["artifacts"],
            changed_snapshot["private_executable_regions"],
        )
        checkpoint = writer.environment_record(
            changed_snapshot,
            elapsed_seconds=10.0,
        )
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        records.insert(records.index(coverage), checkpoint)
        records[records.index(coverage)] = writer.coverage_record(elapsed_seconds=11.0)
        records[-1]["duration_seconds"] = 11

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertTrue(
            any(
                finding.title
                == "New private executable memory appeared during the run"
                for finding in report.findings
            )
        )
        self.assertTrue(
            any("changed during the run" in finding.title for finding in report.findings)
        )

    def test_tampered_private_executable_memory_flags_are_inconsistent(self):
        snapshot = _clean_environment_snapshot()
        snapshot["private_executable_regions"].append(
            {
                "id": "8" * 24,
                "size": 0x2000,
                "protection": 0x40,
                "writable": True,
                "guarded": False,
            }
        )
        snapshot["digest"] = environment_digest(
            snapshot["modules"],
            snapshot["artifacts"],
            snapshot["private_executable_regions"],
        )
        records = _complete_records(VerifierTelemetryWriter(), snapshot)
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        environment["private_executable_regions"][0]["writable"] = False

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("memory entry is invalid" in finding.title for finding in report.findings)
        )

    def test_tampered_environment_digest_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        environment["digest"] = "0" * 64

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("inventory digest disagrees" in finding.title for finding in report.findings)
        )

    def test_environment_scan_after_final_duration_is_inconsistent(self):
        records = _complete_records(VerifierTelemetryWriter())
        environment = next(
            record for record in records if record["type"] == "verification_environment"
        )
        environment["elapsed_seconds"] = 30.0

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
        self.assertTrue(
            any("exceeds final duration" in finding.title for finding in report.findings)
        )

    def test_missing_periodic_environment_scans_require_manual_review(self):
        records = _complete_records(VerifierTelemetryWriter())
        coverage = next(
            record for record in records if record["type"] == "verification_coverage"
        )
        coverage["duration_seconds"] = 40.0
        records[-1]["duration_seconds"] = 40

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertTrue(
            any("coverage has large gaps" in finding.title for finding in report.findings)
        )

    def test_failed_initial_environment_scan_is_partial_not_inconsistent(self):
        writer = VerifierTelemetryWriter()
        _frame, _modifiers, _shrine, _passive, checkpoint_records = _source_fixture(writer)
        records = [
            {
                "type": "metadata",
                "version": VOD_FORMAT_VERSION,
                "name": "Environment failure",
                "created_at": "2026-08-30T12:00:00",
                "verification": writer.metadata(
                    scanner_version="3.0.1",
                    game_build_id=SUPPORTED_BUILD,
                    run_start_time_seconds=0.0,
                ),
            },
            writer.environment_failure_record("module scan unavailable", elapsed_seconds=0.0),
            *checkpoint_records,
            writer.coverage_record(elapsed_seconds=3.0),
            {
                "type": "summary",
                "name": "Environment failure",
                "duration_seconds": 3,
                "snapshot_count": 0,
            },
        ]

        report = analyze_records(records)

        self.assertEqual(report.status, VerificationStatus.PARTIAL)
        self.assertEqual(report.inconsistency_count, 0)
        self.assertEqual(report.environment_text, "Scan unavailable")


class RunVerifierStorageTests(unittest.TestCase):
    def test_environment_failure_record_does_not_leak_an_absolute_path(self):
        writer = VerifierTelemetryWriter()
        record = writer.environment_failure_record(
            OSError(r"C:\Users\PrivateName\Megabonk\winhttp.dll could not be read"),
            elapsed_seconds=1.0,
        )

        payload = json.dumps(record)
        self.assertNotIn("PrivateName", payload)
        self.assertNotIn("winhttp.dll", payload)
        self.assertIn("OSError", payload)

    def test_writer_uses_opaque_modifier_ids(self):
        writer = VerifierTelemetryWriter()
        _frame, _modifiers, _shrine, _passive, records = _source_fixture(writer)
        payload = json.dumps(records)

        self.assertIn('"id": "m1"', payload)
        self.assertNotIn("object_ptr", payload)
        self.assertNotIn("0xABC", payload)

    def test_unchanged_large_modifier_set_is_not_repeated_in_checkpoint(self):
        writer = VerifierTelemetryWriter()
        frame = VerifierStatFrame(stats=(_stat(39, 1.0, 5.0),))
        modifiers = {
            39: tuple(
                SimpleNamespace(
                    object_ptr=0x100000 + index,
                    stat_id=39,
                    modify_type=0,
                    value=0.01,
                )
                for index in range(500)
            )
        }
        shrine = SimpleNamespace(
            charged=0,
            selected=0,
            pending=0,
            ambiguous_matches=0,
            stats=(),
        )
        passive = SimpleNamespace(passive_name="Not Gamba", effects=())
        first = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=0.0,
            game_time_seconds=0.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=None,
            character_passive_snapshot=passive,
            dice_level=None,
            held_items=(),
            source_availability={
                "shrines": True,
                "chaos_tome": False,
                "character_passive": False,
            },
        )
        second = writer.records_for_checkpoint(
            frame,
            elapsed_seconds=2.0,
            game_time_seconds=2.0,
            permanent_modifiers=modifiers,
            shrine_snapshot=shrine,
            chaos_snapshot=None,
            character_passive_snapshot=passive,
            dice_level=None,
            held_items=(),
            source_availability={
                "shrines": True,
                "chaos_tome": False,
                "character_passive": False,
            },
        )

        self.assertEqual([record["type"] for record in second], ["verification_checkpoint"])
        self.assertLess(len(json.dumps(second)), 2500)
        self.assertGreater(len(json.dumps(first)), len(json.dumps(second)) * 10)

    def test_vod_keeps_summary_last_and_playback_ignores_verifier_records(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = SimpleNamespace(value=0.0)
            recorder = VodRecorder(
                vods_dir=Path(directory),
                interval_seconds=30,
                clock=lambda: clock.value,
            )
            recorder.prepare_verification_context(
                scanner_version="3.0.1",
                game_build_id=SUPPORTED_BUILD,
                run_start_time_seconds=0.0,
                environment_snapshot=_clean_environment_snapshot(),
            )
            path = recorder.start(name="Storage fixture")
            writer = VerifierTelemetryWriter()
            frame, modifiers, shrine, passive, _records = _source_fixture(writer)
            clock.value = 2.0
            recorder.capture_verification(
                frame,
                game_time_seconds=2.0,
                permanent_modifiers=modifiers,
                shrine_snapshot=shrine,
                chaos_snapshot=_zero_chaos_snapshot(),
                character_passive_snapshot=passive,
                dice_level=None,
                held_items=("Old Mask x2",),
                source_availability=SOURCE_AVAILABILITY,
            )
            with patch("infra.vod_storage.minimum_snapshot_count", return_value=0):
                recorder.stop()

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[-2]["type"], "verification_coverage")
            self.assertEqual(records[-1]["type"], "summary")
            loaded = load_vod(path)
            self.assertEqual(loaded.metadata.name, "Storage fixture")
            self.assertEqual(loaded.snapshots, ())
            self.assertEqual(verify_vod(path).status, VerificationStatus.CONSISTENT)
