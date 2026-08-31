"""Developer CLI for generated fixtures and read-only recording-library audits.

Run from the repository root with both the root and ``src`` on ``PYTHONPATH``::

    python -m tests.support.recording_corpus_cli build .tmp/recording-fixtures
    python -m tests.support.recording_corpus_cli inventory stats_recordings
    python -m tests.support.recording_corpus_cli audit stats_recordings
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import time
from typing import Iterable, Sequence

from infra.run_verifier import verify_vod
from tests.support.recording_corpus import (
    audit_snapshot_alignment,
    build_reference_corpus,
    scan_recording_libraries,
    summarize_inventory,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _recording_paths(inputs: Iterable[str]) -> tuple[Path, ...]:
    discovered: dict[Path, Path] = {}
    for raw in inputs:
        candidate = Path(raw)
        if not candidate.exists():
            raise ValueError(f"Recording input does not exist: {candidate}")
        if candidate.is_file() and candidate.suffix.casefold() == ".jsonl":
            discovered.setdefault(candidate.resolve(), candidate)
        elif candidate.is_dir():
            for path in candidate.glob("*.jsonl"):
                discovered.setdefault(path.resolve(), path)
        else:
            raise ValueError(
                f"Recording input must be a .jsonl file or directory: {candidate}"
            )
    if not discovered:
        raise ValueError("No .jsonl recordings were found in the supplied inputs")
    return tuple(discovered[key] for key in sorted(discovered, key=str))


def _build(output: str) -> int:
    recordings = build_reference_corpus(Path(output))
    print(
        _json(
            {
                "file_count": len(recordings),
                "recordings": [
                    {
                        "file": recording.path.name,
                        "key": recording.key,
                        "expected_status": (
                            recording.expected_status.value
                            if recording.expected_status is not None
                            else None
                        ),
                        "expected_exception": (
                            recording.expected_exception.__name__
                            if recording.expected_exception is not None
                            else None
                        ),
                        "description": recording.description,
                    }
                    for recording in recordings
                ],
            }
        )
    )
    return 0


def _inventory(inputs: Sequence[str]) -> int:
    roots = tuple(Path(value) for value in inputs)
    for root in roots:
        if not root.exists():
            raise ValueError(f"Recording input does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"Recording inventory input must be a directory: {root}")
    entries = scan_recording_libraries(roots)
    print(_json(summarize_inventory(entries)))
    return 0


def _audit(inputs: Sequence[str], *, details: bool, alignment: bool) -> int:
    paths = _recording_paths(inputs)
    statuses: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    alignment_error_types: Counter[str] = Counter()
    durations_ms: list[float] = []
    detail_rows = []
    alignment_counts: Counter[str] = Counter()
    started = time.perf_counter()
    for path in paths:
        file_started = time.perf_counter()
        try:
            report = verify_vod(path)
        except Exception as exc:
            error_types[type(exc).__name__] += 1
            if details:
                detail_rows.append(
                    {
                        "file": path.name,
                        "error": type(exc).__name__,
                    }
                )
        else:
            statuses[report.status.value] += 1
            alignment_report = None
            alignment_error = None
            if alignment:
                try:
                    alignment_report = audit_snapshot_alignment(path)
                except Exception as exc:
                    alignment_error = type(exc).__name__
                    alignment_error_types[alignment_error] += 1
                else:
                    if alignment_report.checkpoint_count == 0:
                        alignment_counts["files_without_checkpoints"] += 1
                        alignment_counts["legacy_snapshots_not_compared"] += (
                            alignment_report.snapshot_count
                        )
                    else:
                        alignment_counts["compared_values"] += (
                            alignment_report.compared_value_count
                        )
                        alignment_counts["issues"] += len(alignment_report.issues)
                        alignment_counts["transitioning_issues"] += sum(
                            issue.transitioning_neighborhood
                            for issue in alignment_report.issues
                        )
                        alignment_counts[
                            "snapshots_without_nearby_checkpoint"
                        ] += alignment_report.snapshots_without_nearby_checkpoint
            if details:
                detail = {
                    "file": path.name,
                    "status": report.status.value,
                    "checkpoints": report.checkpoint_count,
                    "inconsistencies": report.inconsistency_count,
                    "warnings": report.warning_count,
                    "unavailable": report.unavailable_count,
                    "finding_titles": [
                        finding.title
                        for finding in report.findings
                        if finding.severity.value != "match"
                    ],
                }
                if alignment_error is not None:
                    detail["alignment_error"] = alignment_error
                elif alignment_report is not None:
                    detail["alignment"] = {
                        "compared_values": alignment_report.compared_value_count,
                        "issues": len(alignment_report.issues),
                        "transitioning_issues": sum(
                            issue.transitioning_neighborhood
                            for issue in alignment_report.issues
                        ),
                        "snapshots_without_nearby_checkpoint": (
                            alignment_report.snapshots_without_nearby_checkpoint
                        ),
                    }
                detail_rows.append(detail)
        durations_ms.append((time.perf_counter() - file_started) * 1000.0)

    sorted_durations = sorted(durations_ms)
    p95_index = max(0, math.ceil(len(sorted_durations) * 0.95) - 1)
    result = {
        "file_count": len(paths),
        "statuses": dict(sorted(statuses.items())),
        "errors": dict(sorted(error_types.items())),
        "wall_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "mean_ms": (
            round(sum(durations_ms) / len(durations_ms), 2)
            if durations_ms
            else 0.0
        ),
        "p95_ms": (
            round(sorted_durations[p95_index], 2) if sorted_durations else 0.0
        ),
        "max_ms": round(max(durations_ms), 2) if durations_ms else 0.0,
    }
    if details:
        result["recordings"] = detail_rows
    if alignment:
        result["snapshot_alignment"] = dict(sorted(alignment_counts.items()))
        result["alignment_errors"] = dict(sorted(alignment_error_types.items()))
    print(_json(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or inspect reusable BonkScanner recording fixtures."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="generate the clean/modded/adversarial reference corpus",
    )
    build.add_argument("output")

    inventory = subparsers.add_parser(
        "inventory",
        help="print a privacy-safe schema inventory without changing recordings",
    )
    inventory.add_argument("inputs", nargs="+")

    audit = subparsers.add_parser(
        "audit",
        help="run the verifier over files and print aggregate outcomes/timing",
    )
    audit.add_argument("inputs", nargs="+")
    audit.add_argument(
        "--details",
        action="store_true",
        help="include filenames and non-match finding titles",
    )
    audit.add_argument(
        "--alignment",
        action="store_true",
        help="also compare playback stats with nearby stable checkpoints",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        return _build(args.output)
    try:
        if args.command == "inventory":
            return _inventory(args.inputs)
        if args.command == "audit":
            return _audit(
                args.inputs,
                details=bool(args.details),
                alignment=bool(args.alignment),
            )
    except ValueError as exc:
        parser.error(str(exc))
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
