from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.run_verifier import VerificationStatus, float32_bits
from infra.run_verifier import verify_vod
from infra.vod_storage import load_vod
from tests.support.recording_corpus import (
    MECHANICS_SCENARIOS,
    MechanicsScenario,
    MechanicsScenarioStep,
    RecordedRunFixture,
    RecordingDocument,
    TargetStatSources,
    audit_snapshot_alignment,
    build_mechanics_corpus,
    build_mechanics_timeline,
    build_reference_corpus,
    inspect_recording,
    modded_environment_snapshot,
    scan_recording_libraries,
    summarize_inventory,
)
from tests.support.recording_corpus_cli import main as corpus_cli_main


class RecordedRunFixtureTests(unittest.TestCase):
    def _finished_fixture(
        self,
        directory: Path,
        *,
        modded: bool = False,
    ) -> RecordedRunFixture:
        fixture = RecordedRunFixture(
            directory,
            environment_snapshot=(
                modded_environment_snapshot() if modded else None
            ),
        )
        try:
            fixture.advance(2.0)
            fixture.capture_state(
                TargetStatSources(
                    shrines={39: 0.08},
                    dice={40: 0.06},
                    chaos={41: 0.05},
                    old_mask=2,
                ),
                player_level=10,
                mob_kills=100,
            )
            fixture.advance(1.0)
            self.assertEqual(fixture.finish(), "kept")
        except Exception:
            fixture.close()
            raise
        return fixture

    def test_fixture_uses_real_serializers_and_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self._finished_fixture(Path(temp_dir))

            loaded = load_vod(fixture.path)
            report = verify_vod(fixture.path)
            document = fixture.document()

            self.assertEqual(len(loaded.snapshots), 1)
            self.assertEqual(report.status, VerificationStatus.CONSISTENT)
            self.assertEqual(document.record_types[0], "metadata")
            self.assertEqual(document.record_types[-1], "summary")
            self.assertIn("snapshot", document.record_types)
            self.assertIn("verification_checkpoint", document.record_types)

    def test_multiple_source_rolls_are_serialized_as_distinct_modifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RecordedRunFixture(Path(temp_dir))
            fixture.advance(2.0)
            fixture.capture_state(
                TargetStatSources(
                    shrines={41: 0.18},
                    shrine_rolls={41: 3},
                    dice={40: 0.10},
                    dice_rolls={40: 2},
                    chaos={39: 0.30},
                    chaos_rolls={39: 2},
                )
            )
            fixture.finish()

            report = verify_vod(fixture.path)
            checkpoint = fixture.document().records_of_type(
                "verification_checkpoint"
            )[0]

            self.assertEqual(report.status, VerificationStatus.CONSISTENT)
            self.assertEqual(checkpoint["modifier_summary"]["41"]["count"], 3)
            self.assertEqual(checkpoint["sources"]["shrines"]["selected"], 3)
            self.assertEqual(checkpoint["sources"]["dice"]["level"], 2)
            self.assertEqual(checkpoint["sources"]["chaos"]["level"], 2)

    def test_context_manager_finalizes_a_successful_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with RecordedRunFixture(Path(temp_dir)) as fixture:
                fixture.advance(1.0)
                fixture.capture_state(TargetStatSources())
            self.assertEqual(
                fixture.document().record_types[-1],
                "summary",
            )

    def test_context_manager_does_not_fake_completion_after_an_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = None
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with RecordedRunFixture(Path(temp_dir)) as fixture:
                    fixture.advance(1.0)
                    fixture.capture_state(TargetStatSources())
                    raise RuntimeError("synthetic failure")
            self.assertIsNotNone(fixture)
            self.assertNotIn("summary", fixture.document().record_types)

    def test_legal_source_builder_rejects_impossible_inputs(self) -> None:
        invalid = (
            lambda: TargetStatSources(shrines={41: -0.1}),
            lambda: TargetStatSources(chaos={40: float("nan")}),
            lambda: TargetStatSources(chaos={40: 1e100}),
            lambda: TargetStatSources(chaos={40: True}),
            lambda: TargetStatSources(chaos={40: "0.1"}),
            lambda: TargetStatSources(dice={12: 0.1}),
            lambda: TargetStatSources(shrines={"41": 0.1}),
            lambda: TargetStatSources(shrine_rolls={"41": 1}),
            lambda: TargetStatSources(shrines={41: 0.1}, shrine_rolls={41: 0}),
            lambda: TargetStatSources(shrines={41: 0.1}, shrine_rolls={41: 1.0}),
            lambda: TargetStatSources(chaos_rolls={40: 1}),
            lambda: TargetStatSources(old_mask=True),
            lambda: TargetStatSources(old_mask=1.0),
            lambda: TargetStatSources(old_mask=1.5),
            lambda: TargetStatSources(shrine_charged=-1),
            lambda: TargetStatSources(dice_level=True),
            lambda: TargetStatSources(chaos_level=1.0),
            lambda: TargetStatSources(shrines={41: 0.1}, shrine_charged=0),
            lambda: TargetStatSources(
                dice={39: 0.1},
                dice_rolls={39: 2},
                dice_level=1,
            ),
        )
        for build in invalid:
            with self.subTest(build=build):
                with self.assertRaises(ValueError):
                    build()

    def test_partial_source_availability_keeps_unspecified_sources_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RecordedRunFixture(Path(temp_dir))
            fixture.advance(1.0)
            fixture.capture_state(
                TargetStatSources(),
                source_availability={"shrines": False},
            )
            fixture.finish()

            checkpoint = fixture.document().records_of_type(
                "verification_checkpoint"
            )[0]

            self.assertFalse(checkpoint["coverage"]["shrines_complete"])
            self.assertTrue(checkpoint["coverage"]["dice_complete"])
            self.assertTrue(checkpoint["coverage"]["chaos_complete"])

    def test_source_availability_rejects_typos_and_non_boolean_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for availability in (
                {"shrine": False},
                {"shrines": 0},
            ):
                with self.subTest(availability=availability):
                    fixture = RecordedRunFixture(Path(temp_dir))
                    try:
                        fixture.advance(1.0)
                        with self.assertRaises(ValueError):
                            fixture.capture_state(
                                TargetStatSources(),
                                source_availability=availability,
                            )
                    finally:
                        fixture.close()

    def test_capture_state_cannot_silently_replace_a_target_stat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = RecordedRunFixture(Path(temp_dir))
            with self.assertRaises(ValueError):
                fixture.capture_state(
                    TargetStatSources(),
                    extra_stats={"Powerup Multiplier": 99.0},
                )
            fixture.close()
            self.assertEqual(
                fixture.document().records_of_type("verification_checkpoint"),
                (),
            )

    def test_modded_environment_is_a_review_signal_not_an_inconsistency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self._finished_fixture(Path(temp_dir), modded=True)

            report = verify_vod(fixture.path)

            self.assertEqual(report.status, VerificationStatus.REVIEW_REQUIRED)
            self.assertEqual(report.inconsistency_count, 0)
            self.assertTrue(
                any(
                    finding.category == "Process environment"
                    and "mod-loader" in finding.title.lower()
                    for finding in report.findings
                )
            )


class RecordingDocumentMutationTests(unittest.TestCase):
    def _document(self, directory: Path) -> RecordingDocument:
        fixture = RecordedRunFixture(directory)
        fixture.advance(2.0)
        fixture.capture_state(TargetStatSources(shrines={41: 0.1}))
        fixture.advance(1.0)
        fixture.finish()
        return fixture.document()

    def test_field_mutation_is_isolated_and_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = self._document(root)
            changed = original.with_field(
                "verification_checkpoint",
                ("stats", "41", "final"),
                999.0,
            )
            original_path = original.write(root / "original.jsonl")
            changed_path = changed.write(root / "changed.jsonl")

            self.assertEqual(
                verify_vod(original_path).status,
                VerificationStatus.CONSISTENT,
            )
            self.assertEqual(
                verify_vod(changed_path).status,
                VerificationStatus.INCONSISTENT,
            )
            self.assertNotEqual(
                changed.records_of_type("verification_checkpoint")[0]["stats"]["41"]["final"],
                original.records_of_type("verification_checkpoint")[0]["stats"]["41"]["final"],
            )

    def test_missing_coverage_and_duplicate_metadata_have_distinct_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = self._document(root)
            missing = document.without("verification_coverage").write(
                root / "missing.jsonl"
            )
            duplicate = document.duplicated("metadata").write(
                root / "duplicate.jsonl"
            )

            self.assertNotEqual(
                verify_vod(missing).status,
                VerificationStatus.CONSISTENT,
            )
            self.assertEqual(
                verify_vod(duplicate).status,
                VerificationStatus.INCONSISTENT,
            )

    def test_summary_snapshot_count_detects_removed_duplicated_and_invalid_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = self._document(root)
            variants = {
                "removed": original.without("snapshot"),
                "duplicated": original.duplicated("snapshot"),
                "invalid": original.with_field(
                    "summary",
                    ("snapshot_count",),
                    True,
                ),
            }

            for name, document in variants.items():
                with self.subTest(name=name):
                    report = verify_vod(document.write(root / f"{name}.jsonl"))
                    self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
                    self.assertTrue(
                        any(
                            "snapshot count" in finding.title.lower()
                            for finding in report.findings
                        )
                    )

    def test_normal_snapshot_after_final_coverage_is_inconsistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            original = self._document(root)
            snapshot_index = original.record_types.index("snapshot")
            coverage_index = original.record_types.index("verification_coverage")
            changed = original.swapped(snapshot_index, coverage_index)

            report = verify_vod(changed.write(root / "late-snapshot.jsonl"))

            self.assertEqual(report.status, VerificationStatus.INCONSISTENT)
            self.assertTrue(
                any(
                    finding.title == "Snapshot follows final coverage"
                    for finding in report.findings
                )
            )

    def test_incomplete_process_exit_tail_is_tolerated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = self._document(root).with_trailing_fragment('{"type":"snap')
            path = document.write(root / "truncated.jsonl")

            loaded = RecordingDocument.load(path)

            self.assertEqual(loaded.trailing_fragment, b'{"type":"snap')
            self.assertEqual(
                verify_vod(path).status,
                VerificationStatus.CONSISTENT,
            )

    def test_complete_malformed_tail_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = self._document(root).with_trailing_fragment("{broken}\n")
            path = document.write(root / "malformed.jsonl")

            with self.assertRaises(Exception):
                RecordingDocument.load(path)
            with self.assertRaises(Exception):
                verify_vod(path)

    def test_snapshot_alignment_diagnostic_catches_playback_only_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = self._document(root)
            clean_path = document.write(root / "clean.jsonl")
            tampered_path = document.with_field(
                "snapshot",
                ("stats", "Powerup Drop Chance", "value"),
                77.0,
            ).write(root / "playback-tampered.jsonl")

            clean = audit_snapshot_alignment(clean_path)
            tampered = audit_snapshot_alignment(tampered_path)

            self.assertEqual(clean.compared_value_count, 3)
            self.assertEqual(clean.issues, ())
            self.assertEqual(len(tampered.issues), 1)
            self.assertEqual(tampered.issues[0].stat_id, 41)
            self.assertFalse(tampered.issues[0].transitioning_neighborhood)

    def test_snapshot_alignment_ignores_numbers_outside_float32_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            document = self._document(root).with_field(
                "verification_checkpoint",
                ("stats", "39", "final"),
                1e100,
            )

            report = audit_snapshot_alignment(
                document.write(root / "oversized-float.jsonl")
            )

            self.assertEqual(report.compared_value_count, 2)
            self.assertEqual(report.issues, ())


class RecordingInventoryTests(unittest.TestCase):
    def test_inventory_is_schema_only_and_summary_finds_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = RecordedRunFixture(root)
            fixture.advance(1.0)
            fixture.capture_snapshot({"Luck": 1.0})
            fixture.capture_target_stats(TargetStatSources())
            fixture.finish()
            first = fixture.path
            second = root / "copy.jsonl"
            second.write_bytes(first.read_bytes())

            entries = scan_recording_libraries((root,))
            summary = summarize_inventory(entries)

            self.assertEqual(len(entries), 2)
            self.assertTrue(all(entry.finalized for entry in entries))
            self.assertTrue(all(entry.count("snapshot") == 1 for entry in entries))
            self.assertEqual(summary["unique_payloads"], 1)
            self.assertEqual(summary["duplicate_files"], 1)
            self.assertNotIn("name", summary)
            self.assertNotIn("path", summary)

    def test_inventory_marks_unfinalized_and_malformed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active = root / "active.jsonl"
            active.write_text('{"type":"metadata","version":10}\n', encoding="utf-8")
            malformed = root / "malformed.jsonl"
            malformed.write_text("{broken}\n", encoding="utf-8")

            active_inventory = inspect_recording(active)
            malformed_inventory = inspect_recording(malformed)

            self.assertFalse(active_inventory.finalized)
            self.assertEqual(active_inventory.last_record_type, "metadata")
            self.assertFalse(malformed_inventory.finalized)
            self.assertEqual(malformed_inventory.issues[0].kind, "malformed_json")


class MechanicsCorpusTests(unittest.TestCase):
    def test_mechanics_corpus_matches_manifest_and_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            corpus = build_mechanics_corpus(Path(temp_dir))
            manifest = json.loads(corpus.manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(len(corpus.recordings), len(MECHANICS_SCENARIOS))
            self.assertEqual(manifest["schema"], 1)
            self.assertIn("0.15 * old_mask", manifest["source_equations"]["39"])
            self.assertEqual(len(manifest["scenarios"]), len(corpus.recordings))
            manifest_by_key = {
                scenario["key"]: scenario for scenario in manifest["scenarios"]
            }
            for recording in corpus.recordings:
                with self.subTest(scenario=recording.scenario.key):
                    payload = recording.path.read_bytes()
                    self.assertEqual(sha256(payload).hexdigest(), recording.sha256)
                    self.assertEqual(
                        manifest_by_key[recording.scenario.key]["sha256"],
                        recording.sha256,
                    )
                    self.assertEqual(
                        verify_vod(recording.path).status,
                        VerificationStatus.CONSISTENT,
                    )
                    timeline = build_mechanics_timeline(recording.path)
                    self.assertEqual(
                        timeline["checkpoint_count"],
                        len(recording.scenario.steps),
                    )
                    self.assertEqual(
                        timeline["event_count"],
                        len(recording.scenario.steps),
                    )
                    self.assertEqual(timeline["issue_event_count"], 0)
                    self.assertIsNone(timeline["first_issue"])

            stress = manifest_by_key["mixed_live_stress"]["steps"][-1]
            self.assertEqual(stress["sources"]["shrine_charged"], 13)
            self.assertEqual(stress["sources"]["dice_level"], 497)
            self.assertEqual(stress["sources"]["chaos_level"], 101)
            self.assertEqual(stress["sources"]["old_mask"], 5)
            self.assertEqual(stress["expected_stats"]["39"]["base"], 1.75)
            self.assertEqual(
                stress["expected_stats"]["39"]["additive"],
                2.6416709423065186,
            )
            source_additive = 1.0 + sum(
                stress["sources"][source].get("39", 0.0)
                for source in ("shrines", "dice", "chaos")
            )
            self.assertNotEqual(
                stress["expected_stats"]["39"]["additive"],
                source_additive,
            )
            stress_recording = next(
                recording
                for recording in corpus.recordings
                if recording.scenario.key == "mixed_live_stress"
            )
            checkpoint = RecordingDocument.load(
                stress_recording.path
            ).records_of_type("verification_checkpoint")[-1]
            self.assertEqual(checkpoint["sources"]["shrines"]["charged"], 13)
            self.assertEqual(checkpoint["sources"]["dice"]["level"], 497)
            self.assertEqual(checkpoint["sources"]["chaos"]["level"], 101)
            self.assertTrue(
                checkpoint["coverage"]["source_attribution_complete"]
            )

    def test_timeline_compresses_repeated_state_and_finds_first_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = RecordedRunFixture(root)
            for _ in range(2):
                fixture.advance(2.0)
                fixture.capture_state(TargetStatSources(shrine_charged=0))
            fixture.finish()
            clean_timeline = build_mechanics_timeline(fixture.path)
            tampered = fixture.document().with_field(
                "verification_checkpoint",
                ("stats", "41", "final"),
                99.0,
                occurrence=-1,
            )
            tampered_path = tampered.write(root / "tampered-timeline.jsonl")
            bad_timeline = build_mechanics_timeline(tampered_path)
            transient = fixture.document().with_field(
                "verification_checkpoint",
                ("sources", "shrines", "totals", "41"),
                0.5,
                occurrence=0,
            )
            transient_timeline = build_mechanics_timeline(
                transient.write(root / "transient-source.jsonl")
            )
            persistent = transient.with_field(
                "verification_checkpoint",
                ("sources", "shrines", "totals", "41"),
                0.5,
                occurrence=1,
            )
            persistent_timeline = build_mechanics_timeline(
                persistent.write(root / "persistent-source.jsonl")
            )
            def change_modifier_summary(record: dict) -> None:
                summary = record["modifier_summary"]["41"]
                summary["addition_sum"] = 0.5
                summary["addition_sum_bits"] = float32_bits(0.5)

            transient_modifier = fixture.document().mutate_record(
                "verification_checkpoint",
                change_modifier_summary,
                occurrence=0,
            )
            transient_modifier_timeline = build_mechanics_timeline(
                transient_modifier.write(root / "transient-modifier.jsonl")
            )
            persistent_modifier = transient_modifier.mutate_record(
                "verification_checkpoint",
                change_modifier_summary,
                occurrence=1,
            )
            persistent_modifier_timeline = build_mechanics_timeline(
                persistent_modifier.write(root / "persistent-modifier.jsonl")
            )
            unsupported_profile = fixture.document().with_field(
                "metadata",
                ("verification", "mechanics_profile"),
                "future-profile",
            )
            unsupported_timeline = build_mechanics_timeline(
                unsupported_profile.write(root / "unsupported-profile.jsonl")
            )

            self.assertEqual(clean_timeline["checkpoint_count"], 2)
            self.assertEqual(clean_timeline["event_count"], 1)
            self.assertIsNone(clean_timeline["first_issue"])
            self.assertEqual(bad_timeline["first_issue"]["checkpoint_index"], 1)
            self.assertIn(
                "stat_41_recorded_bits",
                bad_timeline["first_issue"]["issues"],
            )
            self.assertIsNone(transient_timeline["first_issue"])
            self.assertEqual(
                transient_timeline["pending_observation_checkpoint_count"],
                1,
            )
            self.assertEqual(
                persistent_timeline["first_issue"]["checkpoint_index"],
                1,
            )
            self.assertIn(
                "stat_41_source_sum",
                persistent_timeline["first_issue"]["issues"],
            )
            self.assertIsNone(transient_modifier_timeline["first_issue"])
            self.assertIn(
                "stat_41_modifier_sum",
                persistent_modifier_timeline["first_issue"]["issues"],
            )
            self.assertFalse(unsupported_timeline["available"])
            self.assertFalse(unsupported_timeline["profile_matches_analyzer"])
            self.assertEqual(unsupported_timeline["events"], [])

    def test_mechanics_corpus_never_overwrites_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            build_mechanics_corpus(root)
            before = {
                path.name: sha256(path.read_bytes()).hexdigest()
                for path in root.iterdir()
            }

            with self.assertRaises(FileExistsError):
                build_mechanics_corpus(root)

            self.assertEqual(
                {
                    path.name: sha256(path.read_bytes()).hexdigest()
                    for path in root.iterdir()
                },
                before,
            )

    def test_mechanics_corpus_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = build_mechanics_corpus(root / "first")
            second = build_mechanics_corpus(root / "second")

            self.assertEqual(
                [recording.sha256 for recording in first.recordings],
                [recording.sha256 for recording in second.recordings],
            )
            self.assertEqual(
                first.manifest_path.read_bytes(),
                second.manifest_path.read_bytes(),
            )

    def test_mechanics_corpus_rejects_path_like_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            scenario = MechanicsScenario(
                key="../outside",
                description="invalid",
                evidence="synthetic",
                steps=(
                    MechanicsScenarioStep(
                        key="baseline",
                        description="invalid",
                        sources=TargetStatSources(),
                        evidence="synthetic",
                    ),
                ),
            )

            with self.assertRaises(ValueError):
                build_mechanics_corpus(Path(temp_dir), (scenario,))

    def test_mechanics_cli_build_and_timeline_are_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            build_output = io.StringIO()
            with redirect_stdout(build_output):
                self.assertEqual(
                    corpus_cli_main(("build-mechanics", str(root))),
                    0,
                )
            build_payload = json.loads(build_output.getvalue())
            recording = root / build_payload["recordings"][0]["file"]
            timeline_output = io.StringIO()
            with redirect_stdout(timeline_output):
                self.assertEqual(
                    corpus_cli_main(("timeline", str(recording))),
                    0,
                )
            timeline_payload = json.loads(timeline_output.getvalue())

            self.assertEqual(build_payload["file_count"], len(MECHANICS_SCENARIOS))
            self.assertEqual(build_payload["manifest"], "mechanics_manifest.json")
            self.assertGreaterEqual(timeline_payload["event_count"], 2)
            self.assertIsNone(timeline_payload["first_issue"])


class ReferenceCorpusTests(unittest.TestCase):
    def test_reference_corpus_matches_its_expected_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recordings = build_reference_corpus(Path(temp_dir))

            self.assertEqual(len(recordings), 8)
            self.assertEqual(len({recording.key for recording in recordings}), 8)
            for recording in recordings:
                with self.subTest(recording=recording.key):
                    if recording.expected_exception is not None:
                        with self.assertRaises(recording.expected_exception):
                            verify_vod(recording.path)
                    else:
                        self.assertEqual(
                            verify_vod(recording.path).status,
                            recording.expected_status,
                        )

    def test_reference_corpus_never_overwrites_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            build_reference_corpus(root)
            before = tuple(sorted(path.name for path in root.iterdir()))
            with self.assertRaises(FileExistsError):
                build_reference_corpus(root)
            self.assertEqual(
                tuple(sorted(path.name for path in root.iterdir())),
                before,
            )

    def test_cli_build_and_audit_are_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            build_output = io.StringIO()
            with redirect_stdout(build_output):
                self.assertEqual(corpus_cli_main(("build", str(root))), 0)
            build_payload = json.loads(build_output.getvalue())

            audit_output = io.StringIO()
            with redirect_stdout(audit_output):
                self.assertEqual(
                    corpus_cli_main(("audit", str(root), "--alignment")),
                    0,
                )
            audit_payload = json.loads(audit_output.getvalue())

            self.assertEqual(build_payload["file_count"], 8)
            self.assertEqual(audit_payload["file_count"], 8)
            self.assertEqual(audit_payload["errors"], {"JSONDecodeError": 1})
            self.assertEqual(sum(audit_payload["statuses"].values()), 7)
            self.assertIn("compared_values", audit_payload["snapshot_alignment"])

    def test_cli_reports_alignment_failure_without_losing_verifier_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = RecordedRunFixture(root)
            fixture.advance(1.0)
            fixture.capture_state(TargetStatSources())
            fixture.finish()
            output = io.StringIO()

            with patch(
                "tests.support.recording_corpus_cli.audit_snapshot_alignment",
                side_effect=OverflowError("synthetic alignment failure"),
            ), redirect_stdout(output):
                self.assertEqual(
                    corpus_cli_main(
                        ("audit", str(fixture.path), "--alignment", "--details")
                    ),
                    0,
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["statuses"], {"Consistent": 1})
            self.assertEqual(payload["alignment_errors"], {"OverflowError": 1})
            self.assertEqual(
                payload["recordings"][0]["alignment_error"],
                "OverflowError",
            )

    def test_cli_rejects_missing_audit_and_inventory_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"
            for command in ("audit", "inventory"):
                error = io.StringIO()
                with self.subTest(command=command), redirect_stderr(error):
                    with self.assertRaises(SystemExit) as raised:
                        corpus_cli_main((command, str(missing)))

                self.assertEqual(raised.exception.code, 2)
                self.assertIn("Recording input does not exist", error.getvalue())

    def test_cli_rejects_an_empty_audit_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            error = io.StringIO()
            with redirect_stderr(error):
                with self.assertRaises(SystemExit) as raised:
                    corpus_cli_main(("audit", temp_dir))

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("No .jsonl recordings", error.getvalue())


if __name__ == "__main__":
    unittest.main()
