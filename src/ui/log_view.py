"""The Logs panel: a filterable, timestamped view over a bounded buffer.

What was here before was a bare ``QTextEdit`` that ``Scanner._append_log``
appended HTML into. Three things were wrong with it, and only one of them was
about appearance.

**Severity was dead code.** ``_append_log`` resolved a tag with
``COLOR_MAP.get(tag.upper(), COLOR_MAP["DEFAULT"])``, and ``COLOR_MAP`` is a
*palette* -- ``WHITE``, ``GREEN``, ``YELLOW``, ``RED`` and friends. It has no
``WARNING``, ``SUCCESS`` or ``ERROR`` key, so all 55 tagged call sites fell
through to ``DEFAULT`` and rendered in the same grey. The warnings looked amber
only because two of them carry a literal U+26A0 in the message text.

The tag parameter had grown two vocabularies. A *scalar* tag is a severity
(``warning``/``success``/``error``); a *list* tag is one palette colour per
message part, which is what ``_log_colored_names`` uses for template and tier
names. `parse_log_entry` keeps both and stops them colliding.

**There were no timestamps.** For a tool that runs for hours and whose log is
the only record of a session, "when did this happen" was unanswerable.

**The document grew without bound.** ``insertHtml`` appended and nothing ever
trimmed, so a long session's log was limited by memory rather than by anything
deliberate. `LOG_BUFFER_LIMIT` is that limit now, and the footer says so.

Why the view owns records rather than text
==========================================

Filtering and search have to be able to re-render lines that were appended long
ago, so the buffer holds `LogRecord`s and the document is derived from it. That
also makes "copy" mean the visible lines rather than whatever markup the widget
happens to hold, and lets identical consecutive lines collapse into one with a
counter instead of scrolling the useful history away.

Re-rendering is coalesced through `UiUpdateThrottle` for the same reason the
timelines are: a reroll loop can log several lines a second, and each one would
otherwise rebuild the whole document synchronously on the UI thread.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import html
import time
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.template_colors import template_color_hex_or_none
from ui.throttle import UiUpdateThrottle

#: How many records the panel keeps. Old ones fall off the front.
LOG_BUFFER_LIMIT = 2000

#: The severities a scalar tag may name, in the order the filter shows them.
SEVERITIES = ("info", "success", "warning", "error")

#: Text colour per severity. These are in Python rather than the stylesheet
#: because the document is HTML that this module builds -- QSS cannot reach
#: inside a `QTextEdit`'s rich text. They are the redesign's tokens lightened
#: for a dark reading surface; the dot beside them is the token itself.
SEVERITY_TEXT = {
    "info": "#C6CDD8",
    "success": "#BBF7D0",
    "warning": "#FDE68A",
    "error": "#FCA5A5",
}
SEVERITY_DOT = {
    "info": "#60A5FA",
    "success": "#22C55E",
    "warning": "#FACC15",
    "error": "#F87171",
}

#: The ASCII severity markers the messages carry today. They are read *off* the
#: text and then removed: the dot says the same thing in one glyph, and these
#: four spellings were competing with each other at the start of every line.
#: Reading them also recovers a severity for the many lines that pass no tag.
PREFIX_SEVERITY = {
    "[-]": "error",
    "[+]": "success",
    "[WAIT]": "warning",
    "[*]": "info",
}

TIMESTAMP_COLOR = "#5C6675"
REPEAT_COLOR = "#5C6675"
MAP_STATS_PREFIXES = ("Stats: ", "Map Stats: ")


@dataclass
class LogRecord:
    """One line. Mutable only in `count`, which repeats bump."""

    timestamp: str
    severity: str
    #: `(text, colour)` pairs. The colour is an explicit palette hex from a
    #: list tag, or `None` to take the severity's.
    segments: tuple[tuple[str, str | None], ...]
    count: int = 1
    text: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.text:
            self.text = "".join(part for part, _colour in self.segments)


def parse_log_entry(message, tag=None, *, timestamp: str = "") -> LogRecord:
    """Turn a `Scanner.log` call into a record.

    Module-level and pure so the two tag vocabularies can be tested without a
    widget -- which is what the old resolution needed and never had.
    """
    if isinstance(tag, (list, tuple)):
        parts = list(message) if isinstance(message, (list, tuple)) else [str(message)]
        tags = list(tag)
        segments = tuple(
            (
                str(part),
                template_color_hex_or_none(part_tag),
            )
            for part, part_tag in zip(parts, tags)
        )
        severity = ""
    else:
        segments = ((str(message), None),)
        severity = str(tag).lower().strip() if tag else ""

    prefix_severity, segments = _strip_prefix(segments)
    if severity not in SEVERITIES:
        # An unknown scalar tag is not a severity, and silently keeping it
        # would put us back where `COLOR_MAP.get(...)` was. The prefix is the
        # better guess, and `info` is the floor.
        severity = prefix_severity or "info"
    return LogRecord(
        timestamp=timestamp or time.strftime("%H:%M:%S"),
        severity=severity,
        segments=segments,
    )


def _strip_prefix(segments):
    """Take a leading `[*]`/`[+]`/`[-]`/`[WAIT]` off the first segment."""
    if not segments:
        return "", segments
    head, colour = segments[0]
    stripped = head.lstrip()
    for prefix, severity in PREFIX_SEVERITY.items():
        if stripped.startswith(prefix):
            return severity, ((stripped[len(prefix):].lstrip(), colour),) + tuple(segments[1:])
    return "", segments


def record_matches(record: LogRecord, *, severities, search: str) -> bool:
    """Does `record` survive the level filter and the search box?

    Pure, and separate from the widget, because "which lines are visible" is
    also the answer Copy needs and the footer counts.
    """
    if severities and record.severity not in severities:
        return False
    if search and search.casefold() not in record.text.casefold():
        return False
    return True


def show_repeat_count(record: LogRecord) -> bool:
    """Whether a collapsed line should expose its repeat counter.

    Scanner map summaries can be delivered twice by the restart approval path.
    Keeping them collapsed avoids duplicate rows, but the counter reads like a
    map or score multiplier and adds no useful information to the scan history.
    Other repeated diagnostics keep their counter.
    """
    return record.count > 1 and not record.text.startswith(MAP_STATS_PREFIXES)


def render_record_html(record: LogRecord) -> str:
    """One line of the document."""
    dot = SEVERITY_DOT.get(record.severity, SEVERITY_DOT["info"])
    default_text = SEVERITY_TEXT.get(record.severity, SEVERITY_TEXT["info"])
    body = "".join(
        f'<span style="color:{colour or default_text}">{html.escape(part)}</span>'
        for part, colour in record.segments
    )
    repeat = (
        f' <span style="color:{REPEAT_COLOR}">&#215;{record.count}</span>'
        if show_repeat_count(record)
        else ""
    )
    return (
        f'<span style="color:{TIMESTAMP_COLOR}">{html.escape(record.timestamp)}</span>&nbsp;'
        f'<span style="color:{dot}">&#9679;</span>&nbsp;{body}{repeat}'
    )


class LogView(QWidget):
    """The Logs tab: filter bar, document and footer over one buffer."""

    def __init__(self, parent=None, *, throttle=None) -> None:
        super().__init__(parent)
        self.setObjectName("logPanel")
        self._records: deque[LogRecord] = deque(maxlen=LOG_BUFFER_LIMIT)
        self._severities: set[str] = set()
        self._search = ""
        self._render_throttle = throttle or UiUpdateThrottle()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(self._build_filter_bar())

        self._document = QTextEdit()
        self._document.setObjectName("logView")
        self._document.setReadOnly(True)
        self._document.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self._document, 1)

        self._footer = QLabel("")
        self._footer.setObjectName("logFooter")
        layout.addWidget(self._footer)

        self._render()

    # -- construction ---------------------------------------------------------

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        chips = QWidget()
        chips.setObjectName("logChips")
        chips_layout = QHBoxLayout(chips)
        chips_layout.setContentsMargins(3, 3, 3, 3)
        chips_layout.setSpacing(3)
        self._chips: dict[str, QPushButton] = {}
        for key, caption in (
            ("", "All"),
            ("info", "Info"),
            ("success", "Success"),
            ("warning", "Warnings"),
            ("error", "Errors"),
        ):
            chip = QPushButton(caption)
            chip.setObjectName("logChip")
            chip.setProperty("severity", key or "all")
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, k=key: self._on_chip(k))
            chips_layout.addWidget(chip)
            self._chips[key] = chip
        self._chips[""].setChecked(True)
        bar.addWidget(chips)

        self._search_entry = QLineEdit()
        self._search_entry.setObjectName("logSearch")
        self._search_entry.setPlaceholderText("Filter log…")
        self._search_entry.setClearButtonEnabled(True)
        self._search_entry.textChanged.connect(self._on_search)
        self._search_entry.setMaximumWidth(240)
        bar.addWidget(self._search_entry)

        bar.addStretch(1)

        self._autoscroll = QCheckBox("Auto-scroll")
        self._autoscroll.setChecked(True)
        bar.addWidget(self._autoscroll)

        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("ghost")
        copy_btn.clicked.connect(self.copy_visible)
        bar.addWidget(copy_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ghost")
        clear_btn.clicked.connect(self.clear)
        bar.addWidget(clear_btn)
        return bar

    # -- the scanner's port ---------------------------------------------------

    def append_log(self, message, tag=None) -> None:
        """Add a line. What `Scanner._append_log` calls.

        The unfiltered case appends one block to the document and trims the
        front, rather than rebuilding it. That is not a micro-optimisation:
        rebuilding is O(buffer) per line, so at the 2000-line limit a session
        that logs steadily does 2000 line renders and a full `setHtml` reparse
        *per message*. The bounded-buffer test found it by timing out.

        The two paths that cannot be incremental -- a repeat, which rewrites
        the line above, and any active filter, where document and buffer no
        longer line up -- fall back to the coalesced rebuild. Both are rare or
        user-driven; neither is the live logging path.
        """
        record = parse_log_entry(message, tag)
        last = self._records[-1] if self._records else None
        if (
            last is not None
            and last.severity == record.severity
            and last.text == record.text
        ):
            # Identical to the line above it: count it rather than repeat it.
            # The timestamp becomes the *latest* occurrence, which is the one
            # worth knowing when reading back.
            last.count += 1
            last.timestamp = record.timestamp
            self._request_render()
            return

        evicted = len(self._records) == LOG_BUFFER_LIMIT
        self._records.append(record)
        if self._is_filtered():
            self._request_render()
            return
        self._append_line(record, evicted=evicted)
        self._update_footer()

    # -- commands -------------------------------------------------------------

    def clear(self) -> None:
        self._records.clear()
        self._render()

    def copy_visible(self) -> None:
        """Put the visible lines on the clipboard, as plain text.

        The visible ones, not the whole buffer: with a filter on, what the user
        is looking at is what they mean to paste into a bug report.
        """
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(self.visible_text())

    def visible_text(self) -> str:
        return "\n".join(
            f"{record.timestamp}  [{record.severity}]  {record.text}"
            + (f"  x{record.count}" if show_repeat_count(record) else "")
            for record in self._visible_records()
        )

    def _on_chip(self, key: str) -> None:
        if key == "":
            self._severities = set()
        else:
            self._severities = {key}
        for chip_key, chip in self._chips.items():
            chip.setChecked(chip_key == key)
        self._render()

    def _on_search(self, text: str) -> None:
        self._search = str(text)
        self._render()

    # -- rendering ------------------------------------------------------------

    def _visible_records(self) -> list[LogRecord]:
        return [
            record
            for record in self._records
            if record_matches(record, severities=self._severities, search=self._search)
        ]

    def _is_filtered(self) -> bool:
        return bool(self._severities or self._search)

    def _request_render(self) -> None:
        self._render_throttle.request(self._render)

    def _render(self) -> None:
        """Rebuild the document from the buffer. The slow, complete path."""
        visible = self._visible_records()
        if not visible:
            self._document.setHtml(self._empty_html())
        else:
            self._document.setHtml(
                "<br>".join(render_record_html(record) for record in visible)
            )
            self._scroll_to_end()
        self._footer.setText(self._footer_text(len(visible)))

    def _append_line(self, record: LogRecord, *, evicted: bool) -> None:
        """Add one block, and drop the oldest if the buffer just did.

        `QTextEdit.append` inserts a block without reparsing what is already
        there, which is what makes this O(1) against `setHtml`'s O(buffer).
        """
        if len(self._records) == 1:
            # The first real line replaces the empty-state placeholder, which
            # `append` would otherwise leave sitting above it.
            self._document.setHtml(render_record_html(record))
        else:
            self._document.append(render_record_html(record))
        if evicted:
            self._drop_first_block()
        self._scroll_to_end()

    def _drop_first_block(self) -> None:
        document = self._document.document()
        if document.blockCount() <= 1:
            return
        cursor = QTextCursor(document.firstBlock())
        cursor.select(QTextCursor.BlockUnderCursor)
        cursor.removeSelectedText()
        # `BlockUnderCursor` leaves the separator behind on the first block,
        # which would accumulate as a blank line per eviction.
        cursor.deleteChar()

    def _scroll_to_end(self) -> None:
        if self._autoscroll.isChecked():
            self._document.moveCursor(QTextCursor.End)

    def _update_footer(self) -> None:
        self._footer.setText(self._footer_text(len(self._visible_records())))

    def _empty_html(self) -> str:
        if self._records:
            return (
                f'<span style="color:{TIMESTAMP_COLOR}">'
                "No lines match the current filter.</span>"
            )
        return (
            f'<span style="color:{TIMESTAMP_COLOR}">'
            "The log is empty. Press Start to begin a session.</span>"
        )

    def _footer_text(self, visible_count: int) -> str:
        total = len(self._records)
        if visible_count != total:
            return f"{visible_count} of {total} lines · buffer limit {LOG_BUFFER_LIMIT}"
        return f"{total} lines · buffer limit {LOG_BUFFER_LIMIT}"

    # -- inspection, for tests ------------------------------------------------

    @property
    def records(self) -> Sequence[LogRecord]:
        return tuple(self._records)

    def document_html(self) -> str:
        return self._document.toHtml()
