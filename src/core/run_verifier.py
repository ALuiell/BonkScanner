"""Pure models and consistency checks for verifier telemetry.

The verifier deliberately answers a narrower question than an anti-cheat:
does the recorded state agree with the mechanics profile and with itself?
Storage and Qt live in higher layers; this module accepts plain JSON records
so its equations can be exercised with small fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
import math
import struct
from typing import Any, Iterable, Mapping


VERIFIER_SCHEMA_VERSION = 1
ENVIRONMENT_SCHEMA_VERSION = 2
ENVIRONMENT_CAPTURE_INTERVAL_SECONDS = 10.0
GAME_TIME_BACKWARD_TOLERANCE_SECONDS = 3.0
MECHANICS_PROFILE_ID = "bonkscanner-target-stats-2026-08-30"
MECHANICS_PROFILE_DISPLAY_NAMES = {
    MECHANICS_PROFILE_ID: (
        "Powerup Multiplier, Powerup Drop Chance, and Elite Spawn Increase "
        "(2026-08-30 ruleset)"
    ),
}
SUPPORTED_GAME_BUILD_IDS = frozenset({"pe-6980d323-036fa000"})
TARGET_STAT_LABELS = {
    39: "Elite Spawn Increase",
    40: "Powerup Multiplier",
    41: "Powerup Drop Chance",
}
TARGET_STAT_IDS = tuple(TARGET_STAT_LABELS)

ENVIRONMENT_MODULE_FIELDS = (
    "id",
    "name",
    "location",
    "size",
    "sha256",
    "classification",
)
ENVIRONMENT_ARTIFACT_FIELDS = ("id", "path", "kind", "size", "sha256")
ENVIRONMENT_REGION_FIELDS = (
    "id",
    "size",
    "protection",
    "writable",
    "guarded",
)
STOCK_GAME_MODULE_NAMES = frozenset(
    {
        "megabonk.exe",
        "gameassembly.dll",
        "unityplayer.dll",
        "steam_api64.dll",
        "baselib.dll",
        "discord_game_sdk.dll",
        "rewired_windowsgaminginput.dll",
        "unitycrashhandler64.exe",
    }
)
STOCK_EXTERNAL_PLATFORM_MODULE_NAMES = frozenset(
    {
        "steamclient64.dll",
        "tier0_s64.dll",
        "vstdlib_s64.dll",
    }
)
STOCK_EXTERNAL_SYSTEM_MODULE_NAMES = frozenset({"mpoav.dll"})
STOCK_OVERLAY_MODULE_TOKENS = (
    "gameoverlayrenderer",
    "discordhook",
    "graphics-hook",
    "rtsshooks",
    "owclient",
    "owexplorer",
    "owutils",
)


def known_environment_module_classification(name: str, location: str) -> str | None:
    """Classify narrow stock modules without weakening game-directory proxies."""
    folded = str(name).casefold()
    if location == "game":
        return "game" if folded in STOCK_GAME_MODULE_NAMES else None
    if folded in STOCK_EXTERNAL_SYSTEM_MODULE_NAMES:
        return "system"
    if folded in STOCK_EXTERNAL_PLATFORM_MODULE_NAMES:
        return "known_overlay"
    if any(token in folded for token in STOCK_OVERLAY_MODULE_TOKENS):
        return "known_overlay"
    return None


def environment_digest(
    modules: Iterable[Mapping[str, Any]],
    artifacts: Iterable[Mapping[str, Any]],
    private_executable_regions: Iterable[Mapping[str, Any]] = (),
) -> str:
    """Hash the portable module/artifact inventory, excluding private paths."""
    module_rows = [
        {field: module.get(field) for field in ENVIRONMENT_MODULE_FIELDS}
        for module in modules
    ]
    artifact_rows = [
        {field: artifact.get(field) for field in ENVIRONMENT_ARTIFACT_FIELDS}
        for artifact in artifacts
    ]
    region_rows = [
        {field: region.get(field) for field in ENVIRONMENT_REGION_FIELDS}
        for region in private_executable_regions
    ]
    module_rows.sort(key=lambda row: str(row.get("id") or ""))
    artifact_rows.sort(key=lambda row: str(row.get("id") or ""))
    region_rows.sort(key=lambda row: str(row.get("id") or ""))
    payload = json.dumps(
        {
            "modules": module_rows,
            "artifacts": artifact_rows,
            "private_executable_regions": region_rows,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def mechanics_profile_display_name(profile: str | None) -> str:
    """Return a user-facing name for a versioned verifier ruleset."""
    if not profile:
        return "Not recorded"
    return MECHANICS_PROFILE_DISPLAY_NAMES.get(profile, "Unknown ruleset")


def float32(value: float) -> float:
    """Round a number exactly as a game ``float`` write does."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def float32_bits(value: float) -> str:
    return struct.pack("<f", float(value)).hex()


def reconstruct_stat(base: float, additive: float, multiplicative: float) -> float:
    return float32(float32(float32(base) * float32(additive)) * float32(multiplicative))


def close_float32(observed: float, expected: float, *, source_sum: bool = False) -> bool:
    if not math.isfinite(observed) or not math.isfinite(expected):
        return False
    scale = max(abs(observed), abs(expected), 1.0)
    tolerance = max(2e-6 if source_sum else 5e-7, scale * (2e-6 if source_sum else 5e-7))
    return abs(observed - expected) <= tolerance


@dataclass(frozen=True)
class VerifierStatComponents:
    stat_id: int
    final_value: float
    raw_value: float
    has_modifications: bool
    base_value: float
    additive_value: float
    multiplicative_value: float


@dataclass(frozen=True)
class VerifierStatFrame:
    stats: tuple[VerifierStatComponents, ...]
    stable: bool = True


class VerificationStatus(str, Enum):
    CONSISTENT = "Consistent"
    INCONSISTENT = "Inconsistent"
    REVIEW_REQUIRED = "Review required"
    PARTIAL = "Partial"
    LATE_START = "Late start"
    INTERRUPTED = "Interrupted"
    UNSUPPORTED_BUILD = "Unsupported build"


class FindingSeverity(str, Enum):
    MATCH = "match"
    INCONSISTENCY = "inconsistency"
    WARNING = "warning"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class VerificationFinding:
    category: str
    severity: FindingSeverity
    title: str
    detail: str
    elapsed_seconds: float | None = None
    stat_id: int | None = None
    occurrence_count: int = 1
    last_elapsed_seconds: float | None = None
    latest_detail: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    status: VerificationStatus
    recording_name: str
    created_at: str
    game_build_id: str | None
    scanner_version: str | None
    mechanics_profile: str | None
    checkpoint_count: int
    event_count: int
    match_count: int
    inconsistency_count: int
    warning_count: int
    unavailable_count: int
    findings: tuple[VerificationFinding, ...]
    coverage_text: str
    environment_text: str = "Not recorded"

    @property
    def is_consistent(self) -> bool:
        return self.status is VerificationStatus.CONSISTENT

    def to_text(self, *, include_guide: bool = True) -> str:
        profile_name = mechanics_profile_display_name(self.mechanics_profile)
        lines = [
            "BonkScanner Run Verification",
            f"Recording: {self.recording_name}",
            f"Created: {self.created_at or 'Unknown'}",
            f"Result: {self.status.value}",
            f"Game build: {self.game_build_id or 'Not recorded'}",
            f"BonkScanner version: {self.scanner_version or 'Not recorded'}",
            f"Verification rules: {profile_name}",
        ]
        if self.mechanics_profile:
            lines.append(f"Technical rules ID: {self.mechanics_profile}")
        lines.extend([
            f"Data coverage: {self.coverage_text}",
            f"Process environment: {self.environment_text}",
            (
                "Checks: "
                f"{self.match_count} matched, "
                f"{self.inconsistency_count} inconsistent, "
                f"{self.warning_count} warnings, "
                f"{self.unavailable_count} unavailable"
            ),
        ])
        if include_guide:
            lines.extend(
                [
                    "",
                    (
                        "Field guide: Game build is the game version; BonkScanner "
                        "version is the app version that created the recording; "
                        "Verification rules are the versioned formulas and memory "
                        "layout used for this check. Not recorded means the recording "
                        "file does not contain that value."
                    ),
                    (
                        "Check guide: matched checks passed; inconsistent checks found "
                        "conflicting values; warnings indicate incomplete or unusual "
                        "data; unavailable checks did not have enough recorded "
                        "information."
                    ),
                ]
            )
        lines.extend(
            [
                "",
                "This is a consistency analysis, not proof that a run is legitimate.",
            ]
        )
        if self.findings:
            lines.extend(("", "Findings:"))
            for finding in self.findings:
                first_elapsed = finding.elapsed_seconds
                last_elapsed = finding.last_elapsed_seconds
                if (
                    first_elapsed is not None
                    and last_elapsed is not None
                    and last_elapsed > first_elapsed + 0.05
                ):
                    at = f" at {first_elapsed:.1f}s-{last_elapsed:.1f}s"
                elif first_elapsed is not None:
                    at = f" at {first_elapsed:.1f}s"
                else:
                    at = ""
                occurrences = (
                    f" ({finding.occurrence_count} occurrences)"
                    if finding.occurrence_count > 1
                    else ""
                )
                detail = finding.detail
                if finding.latest_detail and finding.latest_detail != detail:
                    detail = f"{detail} Latest sample: {finding.latest_detail}"
                lines.append(
                    f"- [{finding.severity.value.upper()}] "
                    f"{finding.category}: {finding.title}{at}{occurrences} — {detail}"
                )
        return "\n".join(lines)


class _Analysis:
    def __init__(self) -> None:
        self.matches = 0
        self.inconsistencies = 0
        self.warnings = 0
        self.unavailable = 0
        self.interrupted = False
        self.review_required = False
        self.findings: list[VerificationFinding] = []
        self._finding_indices: dict[
            tuple[FindingSeverity, str, str, int | None], int
        ] = {}
        self._pending_reconciliations: dict[
            tuple[str, Any], tuple[int, str, str, float, int | None]
        ] = {}
        self._pending_unavailable: dict[
            tuple[str, Any], VerificationFinding
        ] = {}
        self._source_counter_high_water: dict[str, int] = {}

    def add(
        self,
        severity: FindingSeverity,
        category: str,
        title: str,
        detail: str,
        *,
        elapsed: float | None = None,
        stat_id: int | None = None,
        retain: bool = True,
    ) -> None:
        if severity is FindingSeverity.MATCH:
            self.matches += 1
        elif severity is FindingSeverity.INCONSISTENCY:
            self.inconsistencies += 1
        elif severity is FindingSeverity.WARNING:
            self.warnings += 1
        else:
            self.unavailable += 1
        if not retain:
            return
        key = (severity, category, title, stat_id)
        existing_index = self._finding_indices.get(key)
        if existing_index is not None:
            existing = self.findings[existing_index]
            last_elapsed = (
                elapsed
                if elapsed is not None
                else existing.last_elapsed_seconds
            )
            self.findings[existing_index] = replace(
                existing,
                occurrence_count=existing.occurrence_count + 1,
                last_elapsed_seconds=last_elapsed,
                latest_detail=detail,
            )
            return
        self._finding_indices[key] = len(self.findings)
        self.findings.append(
            VerificationFinding(
                category=category,
                severity=severity,
                title=title,
                detail=detail,
                elapsed_seconds=elapsed,
                stat_id=stat_id,
                last_elapsed_seconds=elapsed,
                latest_detail=detail,
            )
        )

    def reconcile_failure(
        self,
        key: tuple[str, Any],
        title: str,
        detail: str,
        *,
        elapsed: float,
        stat_id: int | None,
    ) -> None:
        """Require two adjacent stable samples for cross-source accusations.

        Component values and source trackers are read sequentially. A pickup or
        roll can legitimately land between those reads, so one mismatch is
        held until the next stable checkpoint instead of becoming a false
        inconsistency immediately.
        """
        previous = self._pending_reconciliations.get(key)
        count = (previous[0] if previous is not None else 0) + 1
        self._pending_reconciliations[key] = (
            count,
            title,
            detail,
            elapsed,
            stat_id,
        )
        if count >= 2:
            self.add(
                FindingSeverity.INCONSISTENCY,
                "Source reconciliation",
                title,
                detail,
                elapsed=elapsed,
                stat_id=stat_id,
            )

    def reconcile_success(self, key: tuple[str, Any]) -> None:
        self._pending_reconciliations.pop(key, None)

    def defer_unavailable(
        self,
        key: tuple[str, Any],
        category: str,
        title: str,
        detail: str,
        *,
        elapsed: float | None = None,
        stat_id: int | None = None,
    ) -> None:
        """Hold recoverable coverage loss until the recording ends.

        Source trackers and component reads are sampled independently. A
        checkpoint can therefore land while a cumulative source is catching up
        even though a later checkpoint reconstructs the complete state. Keeping
        only the currently open episode prevents recovered gaps from becoming
        permanent report noise while preserving a gap that is still open at the
        end of the run.
        """
        previous = self._pending_unavailable.get(key)
        if previous is None:
            self._pending_unavailable[key] = VerificationFinding(
                category=category,
                severity=FindingSeverity.UNAVAILABLE,
                title=title,
                detail=detail,
                elapsed_seconds=elapsed,
                stat_id=stat_id,
                last_elapsed_seconds=elapsed,
                latest_detail=detail,
            )
            return
        self._pending_unavailable[key] = replace(
            previous,
            occurrence_count=previous.occurrence_count + 1,
            last_elapsed_seconds=(
                elapsed if elapsed is not None else previous.last_elapsed_seconds
            ),
            latest_detail=detail,
        )

    def resolve_unavailable(self, key: tuple[str, Any]) -> None:
        self._pending_unavailable.pop(key, None)

    def finalize_reconciliations(self) -> None:
        for count, title, detail, elapsed, stat_id in self._pending_reconciliations.values():
            if count != 1:
                continue
            self.add(
                FindingSeverity.UNAVAILABLE,
                "Coverage and limitations",
                f"{title} was not confirmed",
                f"Only the final stable checkpoint disagreed. {detail}",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        for finding in self._pending_unavailable.values():
            self.add(
                FindingSeverity.UNAVAILABLE,
                finding.category,
                finding.title,
                finding.detail,
                elapsed=finding.elapsed_seconds,
                stat_id=finding.stat_id,
            )
            for _ in range(1, finding.occurrence_count):
                self.add(
                    FindingSeverity.UNAVAILABLE,
                    finding.category,
                    finding.title,
                    finding.latest_detail or finding.detail,
                    elapsed=finding.last_elapsed_seconds,
                    stat_id=finding.stat_id,
                )
        self._pending_unavailable.clear()


def _number(value: Any) -> float | None:
    # Verifier JSON is a typed evidence format. Accepting strings or bools
    # here would let e.g. ``"false"``/``True`` silently become numeric data.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    try:
        # Every recorded value represents a game float. A finite Python float
        # may still be too large for float32 and used to crash float32_bits().
        struct.pack("<f", result)
    except (OverflowError, struct.error):
        return None
    return result


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    result = int(value)
    # All integer fields in schema 1 originate from C#/game int values or
    # bounded recorder counters. Reject arbitrary-precision JSON integers so
    # later source arithmetic cannot overflow while analyzing hostile files.
    if not -(2**31) <= result <= (2**31 - 1):
        return None
    return result


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _stat_entry(checkpoint: dict[str, Any], stat_id: int) -> dict[str, Any] | None:
    stats = checkpoint.get("stats")
    if not isinstance(stats, dict):
        return None
    entry = stats.get(str(stat_id), stats.get(stat_id))
    return entry if isinstance(entry, dict) else None


def _source_total(checkpoint: dict[str, Any], source: str, stat_id: int) -> float | None:
    sources = checkpoint.get("sources")
    if not isinstance(sources, dict):
        return None
    source_record = sources.get(source)
    if not isinstance(source_record, dict):
        return None
    totals = source_record.get("totals")
    if not isinstance(totals, dict):
        return None
    return _number(totals.get(str(stat_id), totals.get(stat_id)))


def _effective_source_coverage(
    checkpoint: dict[str, Any], source: str
) -> bool | None:
    """Return a coverage flag with the schema-1 Dice pending bug normalized."""
    coverage = checkpoint.get("coverage")
    if not isinstance(coverage, dict):
        return None
    declared = _boolean(coverage.get(f"{source}_complete"))
    if source != "dice" or declared is not False:
        return declared

    sources = checkpoint.get("sources")
    dice = sources.get("dice") if isinstance(sources, dict) else None
    if not isinstance(dice, dict):
        return declared
    level = _integer(dice.get("level"))
    ambiguous = _integer(dice.get("ambiguous"))
    pending = _integer(dice.get("pending"))
    if (
        str(dice.get("coverage", "")) == "complete"
        and level is not None
        and level >= 0
        and ambiguous == 0
        and pending is not None
        and pending > 0
    ):
        # Early schema-1 writers treated every unmatched permanent modifier as
        # an unresolved Dice roll.  The tracker already distinguishes the two:
        # coverage="complete" and ambiguous=0 prove the full Dice roll budget
        # was solved, while pending is only the leftover non-Dice candidate pool.
        return True
    return declared


def _effective_source_attribution_complete(
    checkpoint: dict[str, Any], declared: bool | None
) -> bool | None:
    if declared is not False:
        return declared
    if all(
        _effective_source_coverage(checkpoint, source) is True
        for source in ("shrines", "dice", "chaos")
    ):
        return True
    return declared


def _check_bits(
    analysis: _Analysis,
    entry: dict[str, Any],
    field: str,
    *,
    elapsed: float,
    stat_id: int,
) -> float | None:
    value = _number(entry.get(field))
    bits = entry.get(f"{field}_bits")
    label = TARGET_STAT_LABELS[stat_id]
    if field not in entry or f"{field}_bits" not in entry:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Stat reconstruction",
            f"{label} {field} is missing",
            "The checkpoint does not contain both the finite value and its float32 bits.",
            elapsed=elapsed,
            stat_id=stat_id,
        )
        return None
    if value is None or not isinstance(bits, str):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            f"{label} {field} is invalid",
            "The recorded value must be a finite float32 and its bits must be text.",
            elapsed=elapsed,
            stat_id=stat_id,
        )
        return None
    if float32_bits(value) != bits.lower():
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            f"{label} float bits disagree",
            f"{field}={value!r}, encoded bits={bits!r}.",
            elapsed=elapsed,
            stat_id=stat_id,
        )
    else:
        analysis.add(
            FindingSeverity.MATCH,
            "Recording integrity",
            f"{label} float bits",
            "The decimal value matches the recorded float32 bits.",
            retain=False,
        )
    return value


def _check_checkpoint(
    analysis: _Analysis,
    checkpoint: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    capture_interval: float | None,
    game_time_high_water: float | None,
) -> None:
    elapsed = _number(checkpoint.get("elapsed_seconds"))
    if elapsed is None:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Checkpoint time is invalid",
            "A verifier checkpoint has no finite elapsed time.",
        )
        elapsed = 0.0

    stable = _boolean(checkpoint.get("stable"))
    if stable is None:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Checkpoint stability flag is invalid",
            "stable must be a JSON boolean.",
            elapsed=elapsed,
        )
        return
    stability_key = ("coverage", "stable_checkpoint")
    if not stable:
        analysis.defer_unavailable(
            stability_key,
            "Coverage and limitations",
            "Unsettled memory sample",
            "Two consecutive component reads did not agree; this checkpoint is not used for strong equations.",
            elapsed=elapsed,
        )
        return
    analysis.resolve_unavailable(stability_key)

    current_game_time = _number(checkpoint.get("game_time_seconds"))
    game_time_coverage_key = ("coverage", "game_time")
    if current_game_time is None or current_game_time < 0:
        analysis.defer_unavailable(
            game_time_coverage_key,
            "Coverage and limitations",
            "Checkpoint game time is unavailable",
            "The checkpoint does not contain a valid non-negative game time.",
            elapsed=elapsed,
        )
        current_game_time = None
    else:
        analysis.resolve_unavailable(game_time_coverage_key)

    sources = checkpoint.get("sources")
    items = sources.get("items") if isinstance(sources, dict) else None
    old_mask = _integer(items.get("old_mask")) if isinstance(items, dict) else None
    if old_mask is None or old_mask < 0:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Old Mask amount is invalid",
            "The checkpoint must contain a non-negative integer Old Mask amount.",
            elapsed=elapsed,
        )
        old_mask = 0

    for source, counter_name in (
        ("shrines", "charged"),
        ("dice", "level"),
        ("chaos", "level"),
    ):
        source_record = sources.get(source) if isinstance(sources, dict) else None
        counter = (
            _integer(source_record.get(counter_name))
            if isinstance(source_record, dict)
            else None
        )
        if counter is None or counter < 0:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                f"{source.title()} counter is invalid",
                f"{counter_name} must be a non-negative integer.",
                elapsed=elapsed,
            )

    for stat_id in TARGET_STAT_IDS:
        label = TARGET_STAT_LABELS[stat_id]
        entry = _stat_entry(checkpoint, stat_id)
        if entry is None:
            analysis.add(
                FindingSeverity.UNAVAILABLE,
                "Stat reconstruction",
                f"{label} is missing",
                "No component record exists for this target stat.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
            continue

        values = {
            field: _check_bits(
                analysis,
                entry,
                field,
                elapsed=elapsed,
                stat_id=stat_id,
            )
            for field in ("final", "raw", "base", "additive", "multiplicative")
        }
        if any(value is None for value in values.values()):
            continue
        final = values["final"]
        raw = values["raw"]
        base = values["base"]
        additive = values["additive"]
        multiplicative = values["multiplicative"]
        assert final is not None and raw is not None and base is not None
        assert additive is not None and multiplicative is not None

        try:
            reconstructed = reconstruct_stat(base, additive, multiplicative)
        except (OverflowError, struct.error):
            reconstructed = None
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Stat reconstruction",
                f"{label} component equation overflows float32",
                "The recorded components cannot produce a finite game float.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        if reconstructed is not None and float32_bits(raw) != float32_bits(reconstructed):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Stat reconstruction",
                f"{label} components do not reconstruct raw value",
                f"Observed {raw:.9g}; component result {reconstructed:.9g}.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        elif reconstructed is not None:
            analysis.add(
                FindingSeverity.MATCH,
                "Stat reconstruction",
                f"{label} component equation",
                "base × additive × multiplicative matches raw float32 exactly.",
                retain=False,
            )
        if float32_bits(final) != float32_bits(raw):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Stat reconstruction",
                f"{label} final and raw values differ",
                f"Observed final {final:.9g}; raw {raw:.9g}.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        else:
            analysis.add(
                FindingSeverity.MATCH,
                "Stat reconstruction",
                f"{label} final/raw equation",
                "No unsupported final-value clamp was observed.",
                retain=False,
            )

        expected_base = 1.0 + (0.15 * old_mask if stat_id == 39 else 0.0)
        base_key = ("base", stat_id)
        if not close_float32(base, expected_base, source_sum=True):
            analysis.reconcile_failure(
                base_key,
                f"{label} base has no legal source",
                f"Observed {base:.9g}; expected {expected_base:.9g} from Old Mask amount {old_mask}.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        else:
            analysis.reconcile_success(base_key)
            analysis.add(
                FindingSeverity.MATCH,
                "Source reconciliation",
                f"{label} base source",
                "The base agrees with the built-in value and Old Mask stacks.",
                retain=False,
            )
        if not close_float32(multiplicative, 1.0):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Source reconciliation",
                f"{label} has an unsupported multiplier",
                f"Observed multiplicative component {multiplicative:.9g}; this profile permits 1.0 only.",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        else:
            analysis.add(
                FindingSeverity.MATCH,
                "Source reconciliation",
                f"{label} multiplicative source",
                "No unsupported multiplier is present.",
                retain=False,
            )

        modifier_summary = checkpoint.get("modifier_summary")
        summary_entry = (
            modifier_summary.get(str(stat_id), modifier_summary.get(stat_id))
            if isinstance(modifier_summary, dict)
            else None
        )
        modifier_sum = None
        unsupported_count = None
        if isinstance(summary_entry, dict):
            modifier_sum = _number(summary_entry.get("addition_sum"))
            unsupported_count = _integer(summary_entry.get("unsupported_count"))
            modifier_bits = summary_entry.get("addition_sum_bits")
            if modifier_sum is None or not isinstance(modifier_bits, str):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    f"{label} modifier summary is invalid",
                    "The compact Addition total or its float32 bits are missing.",
                    elapsed=elapsed,
                    stat_id=stat_id,
                )
            elif float32_bits(modifier_sum) != modifier_bits.lower():
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    f"{label} modifier-summary bits disagree",
                    "The compact Addition total does not match its recorded float32 bits.",
                    elapsed=elapsed,
                    stat_id=stat_id,
                )
            replayed = checkpoint.get("_replayed_modifiers")
            if isinstance(replayed, tuple):
                replayed_for_stat = [
                    modifier
                    for modifier in replayed
                    if _integer(modifier.get("stat_id")) == stat_id
                ]
                replayed_sum = math.fsum(
                    _number(modifier.get("value")) or 0.0
                    for modifier in replayed_for_stat
                    if _integer(modifier.get("modify_type")) == 0
                )
                replayed_unsupported = sum(
                    _integer(modifier.get("modify_type")) != 0
                    for modifier in replayed_for_stat
                )
                if (
                    _integer(summary_entry.get("count")) != len(replayed_for_stat)
                    or unsupported_count != replayed_unsupported
                    or modifier_sum is None
                    or not close_float32(
                        modifier_sum, replayed_sum, source_sum=True
                    )
                ):
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        f"{label} modifier delta history disagrees",
                        "Replayed modifier events do not match the compact checkpoint summary.",
                        elapsed=elapsed,
                        stat_id=stat_id,
                    )
        else:
            # Schema-development compatibility for the first local fixtures.
            modifiers = checkpoint.get("modifiers")
            if not isinstance(modifiers, list):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    f"{label} modifier summary is missing",
                    "Neither the schema-1 compact summary nor a development modifier list exists.",
                    elapsed=elapsed,
                    stat_id=stat_id,
                )
                modifiers = []
            target_modifiers = [
                modifier
                for modifier in modifiers if isinstance(modifier, dict)
                and _integer(modifier.get("stat_id")) == stat_id
            ] if isinstance(modifiers, list) else []
            values = [_number(modifier.get("value")) for modifier in target_modifiers]
            if all(value is not None for value in values):
                modifier_sum = math.fsum(value for value in values if value is not None)
            unsupported_count = sum(
                _integer(modifier.get("modify_type")) != 0
                for modifier in target_modifiers
            )
        if unsupported_count:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Source reconciliation",
                f"{label} has an unsupported permanent modifier type",
                f"Found {unsupported_count} non-Addition target modifier(s).",
                elapsed=elapsed,
                stat_id=stat_id,
            )
        modifier_key = ("modifier", stat_id)
        if modifier_sum is not None:
            if not close_float32(additive - 1.0, modifier_sum, source_sum=True):
                analysis.reconcile_failure(
                    modifier_key,
                    f"{label} permanent modifiers do not match additive component",
                    f"Component delta {additive - 1.0:.9g}; modifier sum {modifier_sum:.9g}.",
                    elapsed=elapsed,
                    stat_id=stat_id,
                )
            else:
                analysis.reconcile_success(modifier_key)
                analysis.add(
                    FindingSeverity.MATCH,
                    "Source reconciliation",
                    f"{label} modifier sum",
                    "Permanent Addition modifiers match the additive component.",
                    retain=False,
                )
        else:
            # An unavailable compact total breaks adjacency; a mismatch on the
            # next usable frame must earn its own confirmation.
            analysis.reconcile_success(modifier_key)

        source_values = [
            _source_total(checkpoint, source, stat_id)
            for source in ("shrines", "dice", "chaos")
        ]
        checkpoint_coverage = checkpoint.get("coverage")
        declared_source_complete = (
            _boolean(checkpoint_coverage.get("source_attribution_complete"))
            if isinstance(checkpoint_coverage, dict)
            else None
        )
        if declared_source_complete is None:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Source coverage flag is invalid",
                "source_attribution_complete must be a JSON boolean.",
                elapsed=elapsed,
            )
        source_complete = _effective_source_attribution_complete(
            checkpoint, declared_source_complete
        )
        source_key = ("sources", stat_id)
        source_coverage_key = ("source_coverage", stat_id)
        if source_complete and all(value is not None for value in source_values):
            analysis.resolve_unavailable(source_coverage_key)
            source_sum = math.fsum(value for value in source_values if value is not None)
            if not close_float32(additive - 1.0, source_sum, source_sum=True):
                analysis.reconcile_failure(
                    source_key,
                    f"{label} legal sources do not match additive component",
                    f"Component delta {additive - 1.0:.9g}; Shrine + Dice + Chaos {source_sum:.9g}.",
                    elapsed=elapsed,
                    stat_id=stat_id,
                )
            else:
                analysis.reconcile_success(source_key)
                analysis.add(
                    FindingSeverity.MATCH,
                    "Source reconciliation",
                    f"{label} legal source equation",
                    "Shrine + Dice + Chaos agrees with the additive component.",
                    retain=False,
                )
        else:
            # Coverage for these sources is cumulative. If a later stable frame
            # catches up, it validates the full total and this episode is not a
            # limitation of the finished run. Keep only an episode that remains
            # unresolved at the final checkpoint.
            analysis.reconcile_success(source_key)
            analysis.defer_unavailable(
                source_coverage_key,
                "Coverage and limitations",
                f"{label} source attribution is incomplete",
                "The component equation is still checked, but the exact source equation is unavailable.",
                elapsed=elapsed,
                stat_id=stat_id,
            )

    checkpoint_coverage = checkpoint.get("coverage")
    for source, counter_name in (
        ("shrines", "charged"),
        ("dice", "level"),
        ("chaos", "level"),
    ):
        source_record = sources.get(source) if isinstance(sources, dict) else None
        current_value = (
            _integer(source_record.get(counter_name))
            if isinstance(source_record, dict)
            else None
        )
        source_complete = _effective_source_coverage(checkpoint, source)
        counter_key = ("counter", source)
        if current_value is None or source_complete is not True:
            # Do not combine regressions across an interval in which the source
            # counter itself was not trustworthy.
            analysis.reconcile_success(counter_key)
            continue
        high_water = analysis._source_counter_high_water.get(source)
        if high_water is not None and current_value < high_water:
            analysis.reconcile_failure(
                counter_key,
                f"{source.title()} counter regressed",
                f"Highest observed {high_water}; current {counter_name}={current_value}.",
                elapsed=elapsed,
                stat_id=None,
            )
        else:
            analysis.reconcile_success(counter_key)
        analysis._source_counter_high_water[source] = (
            current_value if high_water is None else max(high_water, current_value)
        )

    game_time_regressed = bool(
        current_game_time is not None
        and game_time_high_water is not None
        and game_time_high_water - current_game_time
        > GAME_TIME_BACKWARD_TOLERANCE_SECONDS
    )
    if game_time_regressed:
        assert current_game_time is not None and game_time_high_water is not None
        analysis.reconcile_failure(
            ("game_time", 0),
            "Game time moved backwards",
            (
                f"Highest observed {game_time_high_water:.3f}s; current "
                f"{current_game_time:.3f}s; tolerance "
                f"{GAME_TIME_BACKWARD_TOLERANCE_SECONDS:.1f}s."
            ),
            elapsed=elapsed,
            stat_id=None,
        )
    elif current_game_time is not None:
        analysis.reconcile_success(("game_time", 0))
    else:
        # Missing time breaks the sequence of comparable samples just like an
        # unavailable source counter does above.
        analysis.reconcile_success(("game_time", 0))

    # A torn component frame is useful as a coverage fact, but none of its
    # clocks is authoritative. Compare clocks only across adjacent stable
    # checkpoints so a transient value cannot accuse the next good sample.
    if previous is not None and _boolean(previous.get("stable")) is True:
        previous_elapsed = _number(previous.get("elapsed_seconds"))
        if previous_elapsed is not None and elapsed < previous_elapsed:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Timeline checks",
                "Checkpoint time moved backwards",
                f"Previous {previous_elapsed:.3f}s; current {elapsed:.3f}s.",
                elapsed=elapsed,
            )
        previous_game_time = _number(previous.get("game_time_seconds"))
        previous_game_time_was_regressed = bool(
            previous_game_time is not None
            and game_time_high_water is not None
            and game_time_high_water - previous_game_time
            > GAME_TIME_BACKWARD_TOLERANCE_SECONDS
        )
        if (
            not game_time_regressed
            and not previous_game_time_was_regressed
            and current_game_time is not None
            and previous_game_time is not None
            and capture_interval is not None
        ):
            game_delta = current_game_time - previous_game_time
            gap_limit = max(capture_interval * 2.5, capture_interval + 1.0)
            if game_delta > gap_limit:
                analysis.interrupted = True
                analysis.add(
                    FindingSeverity.WARNING,
                    "Coverage and limitations",
                    "Unreported checkpoint gap",
                    (
                        f"Game time advanced {game_delta:.3f}s between adjacent "
                        f"checkpoints; expected about {capture_interval:.3f}s."
                    ),
                    elapsed=elapsed,
                )


_ENVIRONMENT_LOCATIONS = frozenset({"game", "system", "program_files", "other"})
_ENVIRONMENT_CLASSIFICATIONS = frozenset(
    {"game", "system", "third_party", "known_overlay", "mod_loader", "unknown"}
)
_ENVIRONMENT_ARTIFACT_KINDS = frozenset(
    {"mod_loader_file", "mod_loader_directory", "proxy_loader", "plugin"}
)
_ENVIRONMENT_REGION_PROTECTIONS = frozenset({0x10, 0x20, 0x40, 0x80})


def _hex_text(value: Any, *, lengths: frozenset[int]) -> str | None:
    if not isinstance(value, str):
        return None
    folded = value.strip().lower()
    if len(folded) not in lengths or any(character not in "0123456789abcdef" for character in folded):
        return None
    return folded


def _environment_module_entry(
    analysis: _Analysis,
    raw: Any,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Process module entry is invalid",
            "Every process-environment module must be an object.",
        )
        return None
    token = _hex_text(raw.get("id"), lengths=frozenset(range(16, 65)))
    name = raw.get("name")
    location = raw.get("location")
    size = _integer(raw.get("size"))
    sha256 = raw.get("sha256")
    classification = raw.get("classification")
    valid_sha = sha256 is None or _hex_text(sha256, lengths=frozenset({64})) is not None
    if (
        token is None
        or not isinstance(name, str)
        or not name.strip()
        or len(name) > 260
        or "/" in name
        or "\\" in name
        or location not in _ENVIRONMENT_LOCATIONS
        or size is None
        or size < 0
        or size > (1 << 44)
        or not valid_sha
        or classification not in _ENVIRONMENT_CLASSIFICATIONS
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Process module entry is invalid",
            f"Invalid module metadata for {str(name or '<unnamed>')[:80]!r}.",
        )
        return None
    return {
        "id": token,
        "name": name.strip(),
        "location": location,
        "size": size,
        "sha256": None if sha256 is None else str(sha256).lower(),
        "classification": classification,
    }


def _environment_artifact_entry(
    analysis: _Analysis,
    raw: Any,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Process artifact entry is invalid",
            "Every process-environment artifact must be an object.",
        )
        return None
    token = _hex_text(raw.get("id"), lengths=frozenset(range(16, 65)))
    path = raw.get("path")
    kind = raw.get("kind")
    size = _integer(raw.get("size"))
    sha256 = raw.get("sha256")
    normalized_path = str(path or "").replace("\\", "/")
    unsafe_path = (
        not normalized_path
        or normalized_path.startswith("/")
        or ":" in normalized_path
        or ".." in normalized_path.split("/")
        or len(normalized_path) > 320
    )
    if (
        token is None
        or unsafe_path
        or kind not in _ENVIRONMENT_ARTIFACT_KINDS
        or size is None
        or size < 0
        or size > (1 << 44)
        or not (
            sha256 is None
            or _hex_text(sha256, lengths=frozenset({64})) is not None
        )
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Process artifact entry is invalid",
            f"Invalid artifact metadata for {normalized_path[:80]!r}.",
        )
        return None
    return {
        "id": token,
        "path": normalized_path,
        "kind": kind,
        "size": size,
        "sha256": None if sha256 is None else str(sha256).lower(),
    }


def _environment_region_entry(
    analysis: _Analysis,
    raw: Any,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Private executable memory entry is invalid",
            "Every private executable memory region must be an object.",
        )
        return None
    token = _hex_text(raw.get("id"), lengths=frozenset(range(16, 65)))
    size = _integer(raw.get("size"))
    protection = _integer(raw.get("protection"))
    writable = _boolean(raw.get("writable"))
    guarded = _boolean(raw.get("guarded"))
    expected_writable = protection in {0x40, 0x80}
    if (
        token is None
        or size is None
        or size <= 0
        or size > (1 << 44)
        or protection not in _ENVIRONMENT_REGION_PROTECTIONS
        or writable is None
        or guarded is None
        or writable != expected_writable
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Private executable memory entry is invalid",
            "Region size, executable protection, and flags must agree.",
        )
        return None
    return {
        "id": token,
        "size": size,
        "protection": protection,
        "writable": writable,
        "guarded": guarded,
    }


def _environment_entries(
    analysis: _Analysis,
    raw_values: Any,
    parser,
    *,
    title: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_values, list):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            title,
            "The environment entry collection must be a list.",
        )
        return {}
    if len(raw_values) > 4096:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            title,
            "The environment entry collection exceeds the safety limit.",
        )
        raw_values = raw_values[:4096]
    parsed: dict[str, dict[str, Any]] = {}
    for raw in raw_values:
        entry = parser(analysis, raw)
        if entry is None:
            continue
        token = entry["id"]
        if token in parsed:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                title,
                f"Environment ID {token!r} appears more than once.",
            )
            continue
        parsed[token] = entry
    return parsed


def _analyze_process_environment(
    analysis: _Analysis,
    verification: dict[str, Any],
    coverage: dict[str, Any] | None,
    records: list[dict[str, Any]],
) -> str:
    declared_schema = _integer(verification.get("environment_schema"))
    if declared_schema is None:
        if records:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment records are undeclared",
                "Process-environment records exist without metadata declaring their schema.",
            )
        else:
            analysis.add(
                FindingSeverity.UNAVAILABLE,
                "Process environment",
                "Process environment was not recorded",
                "This recording predates native module and mod-loader telemetry.",
            )
        return "Not recorded"
    if declared_schema != ENVIRONMENT_SCHEMA_VERSION:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Environment schema is unsupported",
            f"Expected {ENVIRONMENT_SCHEMA_VERSION}; observed {declared_schema!r}.",
        )
        return "Unsupported telemetry"
    environment_interval = _number(
        verification.get("environment_capture_interval_seconds")
    )
    if (
        environment_interval is None
        or not close_float32(
            environment_interval,
            ENVIRONMENT_CAPTURE_INTERVAL_SECONDS,
        )
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Environment capture interval is invalid",
            (
                f"Expected the schema-{ENVIRONMENT_SCHEMA_VERSION} interval "
                f"{ENVIRONMENT_CAPTURE_INTERVAL_SECONDS:.1f}s."
            ),
        )

    modules: dict[str, dict[str, Any]] | None = None
    artifacts: dict[str, dict[str, Any]] | None = None
    regions: dict[str, dict[str, Any]] | None = None
    initial_digest: str | None = None
    final_digest: str | None = None
    failures = 0
    changes = 0
    previous_elapsed: float | None = None
    scan_times: list[float] = []
    flagged_modules: dict[str, str] = {}
    flagged_artifacts: dict[str, str] = {}
    flagged_regions: dict[str, dict[str, Any]] = {}

    for expected_sequence, record in enumerate(records):
        if _integer(record.get("sequence")) != expected_sequence:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment scan sequence is discontinuous",
                f"Expected {expected_sequence}; observed {record.get('sequence')!r}.",
            )
        elapsed = _number(record.get("elapsed_seconds"))
        if elapsed is None or elapsed < 0:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment scan time is invalid",
                "Every process-environment record needs a non-negative finite time.",
            )
        elif previous_elapsed is not None and elapsed < previous_elapsed:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment scan time moved backwards",
                f"Previous {previous_elapsed:.3f}s; current {elapsed:.3f}s.",
            )
        if elapsed is not None:
            previous_elapsed = elapsed
            scan_times.append(elapsed)

        kind = record.get("kind")
        if kind == "failure":
            failures += 1
            reason = record.get("reason")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment failure record is invalid",
                    "A bounded failure reason is required.",
                )
            continue
        if kind == "initial":
            if modules is not None or artifacts is not None or regions is not None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment inventory was initialized twice",
                    "Only the first successful environment scan may contain a full inventory.",
                )
            modules = _environment_entries(
                analysis,
                record.get("modules"),
                _environment_module_entry,
                title="Initial process module inventory is invalid",
            )
            artifacts = _environment_entries(
                analysis,
                record.get("artifacts"),
                _environment_artifact_entry,
                title="Initial process artifact inventory is invalid",
            )
            regions = _environment_entries(
                analysis,
                record.get("private_executable_regions"),
                _environment_region_entry,
                title="Initial private executable memory inventory is invalid",
            )
            if not modules:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Initial process module inventory is empty",
                    "A successful native-module scan must include the game process.",
                )
        elif kind == "checkpoint":
            if modules is None or artifacts is None or regions is None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment checkpoint precedes initial inventory",
                    "A delta cannot be applied before the first successful full scan.",
                )
                continue
            added_modules = _environment_entries(
                analysis,
                record.get("modules_added"),
                _environment_module_entry,
                title="Added process module list is invalid",
            )
            added_artifacts = _environment_entries(
                analysis,
                record.get("artifacts_added"),
                _environment_artifact_entry,
                title="Added process artifact list is invalid",
            )
            added_regions = _environment_entries(
                analysis,
                record.get("regions_added"),
                _environment_region_entry,
                title="Added private executable memory list is invalid",
            )
            # A process can legitimately begin with executable private pages
            # created by graphics drivers, overlays, or runtime components.
            # The MVP records that baseline but only elevates regions that
            # appear or materially change after recording has started.
            flagged_regions.update(added_regions)
            removed_modules = record.get("modules_removed")
            removed_artifacts = record.get("artifacts_removed")
            removed_regions = record.get("regions_removed")
            if (
                not isinstance(removed_modules, list)
                or not isinstance(removed_artifacts, list)
                or not isinstance(removed_regions, list)
            ):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment removal lists are invalid",
                    "Module, artifact, and memory-region removals must be lists.",
                )
                removed_modules = []
                removed_artifacts = []
                removed_regions = []
            changed = bool(
                added_modules
                or added_artifacts
                or added_regions
                or removed_modules
                or removed_artifacts
                or removed_regions
            )
            if changed:
                changes += 1
            for token in removed_modules:
                token = str(token or "").lower()
                if token not in modules:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Unknown process module was removed",
                        f"Environment module ID {token or '<missing>'!r} was not active.",
                    )
                modules.pop(token, None)
            for token in removed_artifacts:
                token = str(token or "").lower()
                if token not in artifacts:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Unknown process artifact was removed",
                        f"Environment artifact ID {token or '<missing>'!r} was not active.",
                    )
                artifacts.pop(token, None)
            for token in removed_regions:
                token = str(token or "").lower()
                if token not in regions:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Unknown private executable memory region was removed",
                        f"Environment region ID {token or '<missing>'!r} was not active.",
                    )
                regions.pop(token, None)
            for token, entry in added_modules.items():
                if token in modules:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Process module was added twice",
                        f"Environment module ID {token!r} was already active.",
                    )
                modules[token] = entry
            for token, entry in added_artifacts.items():
                if token in artifacts:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Process artifact was added twice",
                        f"Environment artifact ID {token!r} was already active.",
                    )
                artifacts[token] = entry
            for token, entry in added_regions.items():
                if token in regions:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Private executable memory region was added twice",
                        f"Environment region ID {token!r} was already active.",
                    )
                regions[token] = entry
        else:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment record kind is invalid",
                f"Unsupported kind={kind!r}.",
            )
            continue

        assert modules is not None and artifacts is not None and regions is not None
        calculated_digest = environment_digest(
            modules.values(),
            artifacts.values(),
            regions.values(),
        )
        reported_digest = _hex_text(record.get("digest"), lengths=frozenset({64}))
        if reported_digest != calculated_digest:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment inventory digest disagrees",
                "The recorded module/artifact/memory-region state does not match its digest.",
            )
        if _integer(record.get("module_count")) != len(modules):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment module count disagrees",
                f"Replayed {len(modules)} active module(s).",
            )
        if _integer(record.get("artifact_count")) != len(artifacts):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment artifact count disagrees",
                f"Replayed {len(artifacts)} active artifact(s).",
            )
        if _integer(record.get("private_executable_region_count")) != len(regions):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Environment private executable memory count disagrees",
                f"Replayed {len(regions)} active private executable region(s).",
            )
        if initial_digest is None:
            initial_digest = calculated_digest
        final_digest = calculated_digest
        for entry in modules.values():
            effective_classification = (
                known_environment_module_classification(
                    entry["name"], entry["location"]
                )
                or entry["classification"]
            )
            if effective_classification in {"mod_loader", "third_party", "unknown"}:
                flagged_modules[entry["id"]] = entry["name"]
        for entry in artifacts.values():
            flagged_artifacts[entry["id"]] = entry["path"]

    environment_coverage = coverage.get("environment") if coverage is not None else None
    coverage_duration = (
        _number(coverage.get("duration_seconds")) if coverage is not None else None
    )
    if (
        previous_elapsed is not None
        and coverage_duration is not None
        and previous_elapsed > coverage_duration + 0.01
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Environment scan exceeds final duration",
            (
                f"Last environment scan={previous_elapsed:.3f}s; "
                f"coverage={coverage_duration:.3f}s."
            ),
        )
    coverage_gaps = 0
    if environment_interval is not None and scan_times:
        gap_limit = max(
            environment_interval * 2.5,
            environment_interval + 2.0,
        )
        timeline = [0.0, *scan_times]
        if coverage_duration is not None:
            timeline.append(coverage_duration)
        coverage_gaps = sum(
            1
            for left, right in zip(timeline, timeline[1:])
            if right - left > gap_limit
        )
        if coverage_gaps:
            analysis.review_required = True
            analysis.add(
                FindingSeverity.WARNING,
                "Process environment",
                "Process-environment coverage has large gaps",
                (
                    f"Found {coverage_gaps} interval(s) longer than "
                    f"{gap_limit:.1f}s between module-scan records."
                ),
            )
    if not isinstance(environment_coverage, dict):
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Process environment",
            "Final process-environment coverage is missing",
            "The recorder did not publish its final module-scan digest and counts.",
        )
    else:
        expected_values = {
            "schema": ENVIRONMENT_SCHEMA_VERSION,
            "scan_count": len(records),
            "failure_count": failures,
            "change_count": changes,
            "initial_digest": initial_digest,
            "final_digest": final_digest,
            "final_module_count": None if modules is None else len(modules),
            "final_artifact_count": None if artifacts is None else len(artifacts),
            "final_private_executable_region_count": (
                None if regions is None else len(regions)
            ),
        }
        for key, expected in expected_values.items():
            observed = environment_coverage.get(key)
            if observed != expected:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Final process-environment coverage disagrees",
                    f"{key} expected {expected!r}; observed {observed!r}.",
                )

    if modules is None or artifacts is None or regions is None:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Process environment",
            "Process module inventory is unavailable",
            f"All {failures or len(records)} environment scan attempt(s) failed.",
        )
        return "Scan unavailable"

    analysis.add(
        FindingSeverity.MATCH,
        "Process environment",
        "Process module inventory captured",
        f"The final snapshot contains {len(modules)} native module(s).",
    )
    analysis.add(
        FindingSeverity.MATCH,
        "Process environment",
        "Private executable memory baseline captured",
        f"The final snapshot contains {len(regions)} private executable region(s).",
    )
    if flagged_modules:
        analysis.review_required = True
        names = sorted(set(flagged_modules.values()), key=str.casefold)
        suffix = "" if len(names) <= 8 else f" (+{len(names) - 8} more)"
        analysis.add(
            FindingSeverity.WARNING,
            "Process environment",
            "Unrecognized third-party or mod-loader modules were recorded",
            f"Flagged modules: {', '.join(names[:8])}{suffix}.",
        )
    if flagged_artifacts:
        analysis.review_required = True
        paths = sorted(set(flagged_artifacts.values()), key=str.casefold)
        suffix = "" if len(paths) <= 8 else f" (+{len(paths) - 8} more)"
        analysis.add(
            FindingSeverity.WARNING,
            "Process environment",
            "Mod-loader artifacts were found in the game directory",
            f"Flagged artifacts: {', '.join(paths[:8])}{suffix}.",
        )
    if flagged_regions:
        analysis.review_required = True
        total_size = sum(entry["size"] for entry in flagged_regions.values())
        writable_count = sum(
            1 for entry in flagged_regions.values() if entry["writable"]
        )
        analysis.add(
            FindingSeverity.WARNING,
            "Process environment",
            "New private executable memory appeared during the run",
            (
                f"Observed {len(flagged_regions)} new or changed anonymous/private "
                f"executable region(s), {total_size} byte(s) total; "
                f"{writable_count} were writable. "
                "This can be created by injected or dynamically generated code, but "
                "it is not an automatic cheating verdict."
            ),
        )
    if changes:
        analysis.review_required = True
        analysis.add(
            FindingSeverity.WARNING,
            "Process environment",
            "Process environment changed during the run",
            f"Module, artifact, or memory-region deltas appeared in {changes} scan(s).",
        )
    if failures:
        analysis.review_required = True
        analysis.add(
            FindingSeverity.WARNING,
            "Process environment",
            "Some process-environment scans failed",
            f"{failures} of {len(records)} scan attempt(s) were unavailable.",
        )
    if (
        not flagged_modules
        and not flagged_artifacts
        and not flagged_regions
        and not changes
        and not failures
        and not coverage_gaps
    ):
        analysis.add(
            FindingSeverity.MATCH,
            "Process environment",
            "No flagged process-environment indicators",
            "The pilot classifier found no unrecognized third-party modules, "
            "mod-loader artifacts, private executable memory, or mid-run changes.",
        )
    flagged_count = (
        len(flagged_modules) + len(flagged_artifacts) + len(flagged_regions)
    )
    detail = (
        f"{len(modules)} modules · {len(regions)} private executable · "
        f"{len(records)} scans"
    )
    if flagged_count or changes or failures or coverage_gaps:
        detail += (
            f" · {flagged_count} flagged · {changes} changed · "
            f"{failures} failed · {coverage_gaps} coverage gaps"
        )
    else:
        detail += " · no flagged indicators"
    return detail


def analyze_records(records: Iterable[dict[str, Any]]) -> VerificationReport:
    """Analyze one already-decoded JSONL stream."""
    analysis = _Analysis()
    metadata: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    checkpoints: list[dict[str, Any]] = []
    environment_records: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    snapshot_count = 0
    event_count = 0
    last_type = None
    replayed_modifiers: dict[str, dict[str, Any]] = {}
    saw_coverage = False
    saw_gap_event = False
    open_gap_event = False
    gap_start_count = 0
    gap_recovery_count = 0

    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Non-object record",
                "Every JSONL line must decode to an object.",
            )
            continue
        record_type = record.get("type")
        last_type = record_type
        if record_type in {
            "verification_checkpoint",
            "verification_event",
            "verification_coverage",
        }:
            if _integer(record.get("schema")) != VERIFIER_SCHEMA_VERSION:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Verifier record schema is invalid",
                    f"{record_type} has schema={record.get('schema')!r}.",
                )
            if metadata is None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Verifier data precedes metadata",
                    f"{record_type} appeared before the recording metadata.",
                )
        if record_type == "verification_environment":
            if _integer(record.get("schema")) != ENVIRONMENT_SCHEMA_VERSION:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment record schema is invalid",
                    f"{record_type} has schema={record.get('schema')!r}.",
                )
            if metadata is None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment data precedes metadata",
                    "A process-environment record appeared before recording metadata.",
                )
        if record_type == "metadata":
            if metadata is not None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Duplicate metadata record",
                    "A recording must contain exactly one metadata record.",
                )
            else:
                metadata = record
                if record_index != 0:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Metadata is not the first record",
                        f"The metadata appeared at JSONL record {record_index + 1}.",
                    )
        elif record_type == "snapshot":
            snapshot_count += 1
            if saw_coverage:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Snapshot follows final coverage",
                    "Normal playback snapshots must precede final verifier coverage.",
                )
        elif record_type == "verification_checkpoint":
            if saw_coverage:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Checkpoint follows final coverage",
                    "Verifier checkpoints must precede the final coverage record.",
                )
            checkpoint = dict(record)
            checkpoint["_replayed_modifiers"] = tuple(
                dict(modifier) for modifier in replayed_modifiers.values()
            )
            checkpoints.append(checkpoint)
        elif record_type == "verification_event":
            if saw_coverage:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Verifier event follows final coverage",
                    "Verifier events must precede the final coverage record.",
                )
            event_count += 1
            event_name = record.get("event")
            if event_name == "telemetry_gap_started":
                saw_gap_event = True
                gap_start_count += 1
                if open_gap_event:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Telemetry gap started twice",
                        "A second gap-start event appeared before recovery.",
                    )
                open_gap_event = True
            elif event_name == "telemetry_gap_recovered":
                saw_gap_event = True
                gap_recovery_count += 1
                if not open_gap_event:
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Telemetry gap recovered without a start",
                        "A gap-recovery event has no matching open gap.",
                    )
                open_gap_event = False
            elif event_name != "target_state_changed":
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Unknown verifier event",
                    f"Unsupported event={event_name!r}.",
                )
            if _number(record.get("elapsed_seconds")) is None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Verifier event time is invalid",
                    f"{event_name!r} has no finite float32 elapsed time.",
                )
            changes = record.get("modifier_changes")
            if event_name == "target_state_changed" and not isinstance(changes, dict):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Modifier delta payload is missing",
                    "target_state_changed must contain modifier_changes.",
                )
            if isinstance(changes, dict):
                for change_kind in ("added", "changed"):
                    values = changes.get(change_kind, [])
                    if not isinstance(values, list):
                        analysis.add(
                            FindingSeverity.INCONSISTENCY,
                            "Recording integrity",
                            "Modifier delta payload is invalid",
                            f"{change_kind} must be a list.",
                        )
                        continue
                    for modifier in values:
                        if not isinstance(modifier, dict):
                            analysis.add(
                                FindingSeverity.INCONSISTENCY,
                                "Recording integrity",
                                "Modifier delta entry is invalid",
                                "A modifier change is not an object.",
                            )
                            continue
                        token = str(modifier.get("id") or "")
                        value = _number(modifier.get("value"))
                        bits = modifier.get("value_bits")
                        stat_id = _integer(modifier.get("stat_id"))
                        modify_type = _integer(modifier.get("modify_type"))
                        if (
                            not token.startswith("m")
                            or not token[1:].isdigit()
                            or stat_id not in TARGET_STAT_IDS
                            or modify_type is None
                            or value is None
                            or not isinstance(bits, str)
                            or float32_bits(value) != bits.lower()
                        ):
                            analysis.add(
                                FindingSeverity.INCONSISTENCY,
                                "Recording integrity",
                                "Modifier delta entry is invalid",
                                f"Invalid {change_kind} modifier {token or '<missing id>'}.",
                            )
                            continue
                        exists = token in replayed_modifiers
                        if change_kind == "added" and exists:
                            analysis.add(
                                FindingSeverity.INCONSISTENCY,
                                "Timeline checks",
                                "Modifier ID was added twice",
                                f"Opaque modifier {token} already exists.",
                            )
                        if change_kind == "changed" and not exists:
                            analysis.add(
                                FindingSeverity.INCONSISTENCY,
                                "Timeline checks",
                                "Unknown modifier ID was changed",
                                f"Opaque modifier {token} has no earlier add event.",
                            )
                        if change_kind == "changed" and exists:
                            old_modifier = replayed_modifiers[token]
                            if (
                                _integer(old_modifier.get("stat_id")) != stat_id
                                or _integer(old_modifier.get("modify_type"))
                                != modify_type
                            ):
                                analysis.add(
                                    FindingSeverity.INCONSISTENCY,
                                    "Timeline checks",
                                    "Modifier identity changed",
                                    f"Opaque modifier {token} changed stat or modifier type.",
                                )
                        replayed_modifiers[token] = dict(modifier)
                removed = changes.get("removed", [])
                if not isinstance(removed, list):
                    analysis.add(
                        FindingSeverity.INCONSISTENCY,
                        "Recording integrity",
                        "Modifier removal payload is invalid",
                        "removed must be a list.",
                    )
                else:
                    if removed:
                        analysis.add(
                            FindingSeverity.INCONSISTENCY,
                            "Timeline checks",
                            "Permanent modifier disappeared",
                            f"The event removes {len(removed)} target modifier ID(s).",
                            elapsed=_number(record.get("elapsed_seconds")),
                        )
                    for raw_token in removed:
                        token = str(raw_token or "")
                        if token not in replayed_modifiers:
                            analysis.add(
                                FindingSeverity.INCONSISTENCY,
                                "Timeline checks",
                                "Unknown modifier ID was removed",
                                f"Opaque modifier {token or '<missing id>'} has no live state.",
                            )
                            continue
                        replayed_modifiers.pop(token, None)
        elif record_type == "verification_environment":
            if saw_coverage:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Environment scan follows final coverage",
                    "Process-environment records must precede final coverage.",
                )
            environment_records.append(record)
        elif record_type == "verification_coverage":
            if coverage is not None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Duplicate verifier coverage",
                    "A recording must contain exactly one final coverage record.",
                )
            else:
                coverage = record
            saw_coverage = True
        elif record_type == "summary":
            if summary is not None:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Duplicate summary record",
                    "A recording must contain exactly one final summary.",
                )
            else:
                summary = record

    if summary is not None:
        declared_snapshot_count = _integer(summary.get("snapshot_count"))
        if declared_snapshot_count is None or declared_snapshot_count < 0:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Summary snapshot count is invalid",
                "The final summary must contain a non-negative integer snapshot count.",
            )
        elif declared_snapshot_count != snapshot_count:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Summary snapshot count disagrees",
                (
                    f"Summary={declared_snapshot_count}; replayed "
                    f"{snapshot_count} snapshot record(s)."
                ),
            )
        else:
            analysis.add(
                FindingSeverity.MATCH,
                "Recording integrity",
                "Snapshot count",
                f"The summary matches all {snapshot_count} snapshot record(s).",
            )

    metadata = metadata or {}
    verification = metadata.get("verification")
    verification = verification if isinstance(verification, dict) else None
    name = str((summary or {}).get("name") or metadata.get("name") or "Unknown recording")
    created_at = str(metadata.get("created_at") or "")
    if verification is None:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Coverage and limitations",
            "Legacy recording",
            "This recording predates verifier telemetry; playback data alone cannot prove source equations.",
        )
        return VerificationReport(
            status=(
                VerificationStatus.INCONSISTENT
                if analysis.inconsistencies
                else VerificationStatus.PARTIAL
            ),
            recording_name=name,
            created_at=created_at,
            game_build_id=None,
            scanner_version=None,
            mechanics_profile=None,
            checkpoint_count=0,
            event_count=0,
            match_count=analysis.matches,
            inconsistency_count=analysis.inconsistencies,
            warning_count=analysis.warnings,
            unavailable_count=analysis.unavailable,
            findings=tuple(analysis.findings),
            coverage_text="Legacy playback data only",
        )

    schema = _integer(verification.get("schema"))
    raw_game_build_id = verification.get("game_build_id")
    game_build_id = (
        raw_game_build_id.strip()
        if isinstance(raw_game_build_id, str) and raw_game_build_id.strip()
        else None
    )
    raw_scanner_version = verification.get("scanner_version")
    scanner_version = (
        raw_scanner_version.strip()
        if isinstance(raw_scanner_version, str) and raw_scanner_version.strip()
        else None
    )
    raw_profile = verification.get("mechanics_profile")
    profile = (
        raw_profile.strip()
        if isinstance(raw_profile, str) and raw_profile.strip()
        else None
    )
    capture_interval = _number(verification.get("capture_interval_seconds"))
    if capture_interval is None or capture_interval <= 0:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Capture interval is invalid",
            "Verifier metadata must contain a positive float32 capture interval.",
        )
        capture_interval = None
    target_stat_ids = verification.get("target_stat_ids")
    parsed_target_ids = (
        tuple(_integer(value) for value in target_stat_ids)
        if isinstance(target_stat_ids, list)
        else None
    )
    if parsed_target_ids != TARGET_STAT_IDS:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Target stat declaration is invalid",
            f"Expected {list(TARGET_STAT_IDS)!r}; observed {target_stat_ids!r}.",
        )
    if scanner_version is None:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Coverage and limitations",
            "BonkScanner version was not recorded",
            "The recording file does not identify the BonkScanner version that created it.",
        )
    unsupported = bool(
        schema != VERIFIER_SCHEMA_VERSION
        or profile != MECHANICS_PROFILE_ID
        or game_build_id not in SUPPORTED_GAME_BUILD_IDS
    )
    if unsupported:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Build compatibility",
            "Game build or verification rules are unsupported",
            (
                "BonkScanner has no validated formulas for this combination. "
                f"Technical details: schema={schema!r}, rules={profile!r}, "
                f"game_build={game_build_id!r}."
            ),
        )
    else:
        analysis.add(
            FindingSeverity.MATCH,
            "Build compatibility",
            "Supported verification rules",
            "The recording matches the currently validated memory layout and formulas.",
        )

    if summary is None or last_type != "summary":
        analysis.add(
            FindingSeverity.WARNING,
            "Recording integrity",
            "Recording is not cleanly finalized",
            "The final summary is missing or is not the final JSONL record.",
        )
    else:
        analysis.add(
            FindingSeverity.MATCH,
            "Recording integrity",
            "Final summary order",
            "The summary is the final record.",
        )

    if coverage is None:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Coverage and limitations",
            "Final verifier coverage is missing",
            "The recorder did not publish its final telemetry health record.",
        )
    if coverage is not None:
        reported_checkpoints = _integer(coverage.get("checkpoint_count"))
        if reported_checkpoints is None or reported_checkpoints < 0:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Checkpoint count is invalid",
                "Final coverage must contain a non-negative integer checkpoint count.",
            )
        elif reported_checkpoints != len(checkpoints):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Checkpoint count disagrees",
                f"Coverage reports {reported_checkpoints}; file contains {len(checkpoints)}.",
            )
        reported_events = _integer(coverage.get("event_count"))
        if reported_events is None or reported_events < 0:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Event count is invalid",
                "Final coverage must contain a non-negative integer event count.",
            )
        elif reported_events != event_count:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Event count disagrees",
                f"Coverage reports {reported_events}; file contains {event_count}.",
            )
    for expected_sequence, checkpoint in enumerate(checkpoints):
        if _integer(checkpoint.get("sequence")) != expected_sequence:
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Recording integrity",
                "Checkpoint sequence is discontinuous",
                f"Expected sequence {expected_sequence}; observed {checkpoint.get('sequence')!r}.",
                elapsed=_number(checkpoint.get("elapsed_seconds")),
            )
            break

    run_start = _number(verification.get("run_start_time_seconds"))
    recorded_late_start = _boolean(verification.get("late_start"))
    late_start = False
    if run_start is None:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Coverage and limitations",
            "Run start time is unavailable",
            "The verifier cannot determine whether recording began after the run started.",
        )
    elif run_start < 0:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Run start time is invalid",
            "run_start_time_seconds must not be negative.",
        )
    else:
        late_start = run_start > 5.0
    if recorded_late_start is None:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Late-start flag is invalid",
            "late_start must be a JSON boolean.",
        )
    elif run_start is not None and run_start >= 0 and recorded_late_start != late_start:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Late-start metadata disagrees",
            f"run_start_time_seconds={run_start:.3f} implies late_start={late_start}.",
        )

    raw_gaps = coverage.get("gaps", []) if coverage is not None else []
    gaps: list[dict[str, Any]] = []
    if not isinstance(raw_gaps, list):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Telemetry gap list is invalid",
            "Final coverage gaps must be a list.",
        )
    else:
        for raw_gap in raw_gaps:
            if not isinstance(raw_gap, dict):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Telemetry gap entry is invalid",
                    "Every coverage gap must be an object.",
                )
                continue
            start = _number(raw_gap.get("start_elapsed_seconds"))
            raw_end = raw_gap.get("end_elapsed_seconds")
            end = None if raw_end is None else _number(raw_end)
            if start is None or start < 0 or (raw_end is not None and end is None):
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Telemetry gap range is invalid",
                    f"Invalid gap range {raw_gap!r}.",
                )
                continue
            if end is not None and end < start:
                analysis.add(
                    FindingSeverity.INCONSISTENCY,
                    "Recording integrity",
                    "Telemetry gap range moved backwards",
                    f"Gap starts at {start:.3f}s and ends at {end:.3f}s.",
                )
                continue
            gaps.append(raw_gap)
    if coverage is not None and saw_gap_event and not gaps:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Gap events disagree with final coverage",
            "The event stream reports a telemetry gap, but final coverage does not.",
        )
    if coverage is not None and gaps and gap_start_count != len(gaps):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Gap event count disagrees",
            f"Coverage contains {len(gaps)} gap(s); events contain {gap_start_count} start(s).",
        )
    closed_gap_count = sum(gap.get("end_elapsed_seconds") is not None for gap in gaps)
    if coverage is not None and gaps and gap_recovery_count != closed_gap_count:
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Gap recovery count disagrees",
            f"Coverage contains {closed_gap_count} closed gap(s); events contain {gap_recovery_count} recovery event(s).",
        )

    coverage_duration = (
        _number(coverage.get("duration_seconds")) if coverage is not None else None
    )
    if coverage is not None and (coverage_duration is None or coverage_duration < 0):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Coverage duration is invalid",
            "Final coverage must contain a non-negative float32 duration.",
        )
        coverage_duration = None
    summary_duration = _number((summary or {}).get("duration_seconds"))
    if summary is not None and (summary_duration is None or summary_duration < 0):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Summary duration is invalid",
            "The final summary must contain a non-negative float32 duration.",
        )
    if (
        coverage_duration is not None
        and summary_duration is not None
        and abs(coverage_duration - summary_duration)
        > max(1.25, capture_interval or 0.0)
    ):
        analysis.add(
            FindingSeverity.INCONSISTENCY,
            "Recording integrity",
            "Final durations disagree",
            f"Coverage={coverage_duration:.3f}s; summary={summary_duration:.3f}s.",
        )
    if checkpoints and coverage_duration is not None:
        last_checkpoint_elapsed = _number(checkpoints[-1].get("elapsed_seconds"))
        if (
            last_checkpoint_elapsed is not None
            and last_checkpoint_elapsed > coverage_duration + 0.01
        ):
            analysis.add(
                FindingSeverity.INCONSISTENCY,
                "Timeline checks",
                "Checkpoint exceeds final duration",
                f"Last checkpoint={last_checkpoint_elapsed:.3f}s; coverage={coverage_duration:.3f}s.",
            )

    interrupted = (
        bool(gaps)
        or saw_gap_event
        or analysis.interrupted
        or summary is None
        or last_type != "summary"
    )
    if gaps:
        analysis.add(
            FindingSeverity.WARNING,
            "Coverage and limitations",
            "Telemetry gaps were recorded",
            f"The verifier reader reported {len(gaps)} gap range(s).",
        )

    if not unsupported:
        previous = None
        game_time_high_water: float | None = None
        for checkpoint in checkpoints:
            _check_checkpoint(
                analysis,
                checkpoint,
                previous,
                capture_interval=capture_interval,
                game_time_high_water=game_time_high_water,
            )
            current_game_time = _number(checkpoint.get("game_time_seconds"))
            if (
                _boolean(checkpoint.get("stable")) is True
                and current_game_time is not None
                and current_game_time >= 0
            ):
                game_time_high_water = (
                    current_game_time
                    if game_time_high_water is None
                    else max(game_time_high_water, current_game_time)
                )
            previous = checkpoint
        analysis.finalize_reconciliations()
    if not checkpoints:
        analysis.add(
            FindingSeverity.UNAVAILABLE,
            "Coverage and limitations",
            "No verifier checkpoints",
            "No component frames were available for analysis.",
        )

    environment_text = _analyze_process_environment(
        analysis,
        verification,
        coverage,
        environment_records,
    )

    if analysis.inconsistencies:
        status = VerificationStatus.INCONSISTENT
    elif unsupported:
        status = VerificationStatus.UNSUPPORTED_BUILD
    elif interrupted or analysis.interrupted:
        status = VerificationStatus.INTERRUPTED
    elif late_start:
        status = VerificationStatus.LATE_START
    elif analysis.unavailable:
        status = VerificationStatus.PARTIAL
    elif analysis.review_required:
        status = VerificationStatus.REVIEW_REQUIRED
    else:
        status = VerificationStatus.CONSISTENT

    healthy = sum(checkpoint.get("stable") is True for checkpoint in checkpoints)
    coverage_text = f"{healthy}/{len(checkpoints)} stable checkpoints"
    if gaps:
        coverage_text += f", {len(gaps)} telemetry gap(s)"
    return VerificationReport(
        status=status,
        recording_name=name,
        created_at=created_at,
        game_build_id=game_build_id,
        scanner_version=scanner_version,
        mechanics_profile=profile,
        checkpoint_count=len(checkpoints),
        event_count=event_count,
        match_count=analysis.matches,
        inconsistency_count=analysis.inconsistencies,
        warning_count=analysis.warnings,
        unavailable_count=analysis.unavailable,
        findings=tuple(analysis.findings),
        coverage_text=coverage_text,
        environment_text=environment_text,
    )
