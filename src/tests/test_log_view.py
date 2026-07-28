"""The Logs panel: tag vocabularies, the buffer, and what the filter shows.

The bug this replaced is the reason the first class exists. `_append_log`
resolved a scalar tag with `COLOR_MAP.get(tag.upper(), COLOR_MAP["DEFAULT"])`,
and `COLOR_MAP` is a palette -- `WHITE`, `GREEN`, `YELLOW`, `RED`. It has no
`WARNING`, `SUCCESS` or `ERROR` key, so all 55 tagged call sites in the app fell
through to `DEFAULT` and rendered identically. Nothing failed; the log just
stopped meaning anything, and the warnings looked amber because two of them
carry a literal U+26A0 in the message.

So the severity cases below assert against the *tags the app actually passes*,
taken from a grep of the call sites: `warning` (27), `success` (16), `error`
(12), and the four ASCII prefixes that carry severity for the untagged rest.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.item_metadata import COLOR_MAP
from ui.log_view import (
    SEVERITIES,
    LogRecord,
    parse_log_entry,
    record_matches,
    render_record_html,
)


class LogEntryParsingTests(unittest.TestCase):
    def test_the_scalar_tags_the_app_passes_are_severities(self) -> None:
        for tag in ("warning", "success", "error"):
            with self.subTest(tag=tag):
                record = parse_log_entry("something happened", tag)
                self.assertEqual(record.severity, tag)

    def test_severities_are_not_looked_up_in_the_palette(self) -> None:
        # The exact shape of the old bug: these keys are absent from COLOR_MAP,
        # which is why every tag resolved to one colour. If severity ever goes
        # back through the palette, this is what says so.
        for tag in ("warning", "success", "error"):
            self.assertNotIn(tag.upper(), COLOR_MAP)
        self.assertEqual(
            {parse_log_entry("x", tag).severity for tag in ("warning", "success", "error")},
            {"warning", "success", "error"},
        )

    def test_a_list_tag_colours_each_part_from_the_palette(self) -> None:
        # `_log_colored_names` builds these: one palette colour per name.
        record = parse_log_entry(
            ["Active Tiers: ", "Perfect", ", ", "Good"],
            [None, "YELLOW", None, "GREEN"],
        )
        self.assertEqual(
            record.segments,
            (
                ("Active Tiers: ", None),
                ("Perfect", COLOR_MAP["YELLOW"]),
                (", ", None),
                ("Good", COLOR_MAP["GREEN"]),
            ),
        )
        self.assertEqual(record.severity, "info")
        self.assertEqual(record.text, "Active Tiers: Perfect, Good")

    def test_the_ascii_prefixes_carry_severity_and_are_removed(self) -> None:
        for prefix, severity in (
            ("[-]", "error"),
            ("[+]", "success"),
            ("[WAIT]", "warning"),
            ("[*]", "info"),
        ):
            with self.subTest(prefix=prefix):
                record = parse_log_entry(f"{prefix} the message")
                self.assertEqual(record.severity, severity)
                self.assertEqual(record.text, "the message")

    def test_an_explicit_tag_beats_the_prefix(self) -> None:
        # `[WAIT] ... tag="warning"` agrees, but `[*] ... tag="error"` does not,
        # and the caller's tag is the more deliberate of the two.
        record = parse_log_entry("[*] could not read memory", "error")
        self.assertEqual(record.severity, "error")
        self.assertEqual(record.text, "could not read memory")

    def test_an_unknown_scalar_tag_falls_to_info_rather_than_being_kept(self) -> None:
        record = parse_log_entry("hello", "chartreuse")
        self.assertIn(record.severity, SEVERITIES)
        self.assertEqual(record.severity, "info")

    def test_the_rendered_line_carries_the_time_the_dot_and_the_text(self) -> None:
        record = LogRecord(
            timestamp="22:52:04", severity="error", segments=(("boom", None),)
        )
        markup = render_record_html(record)
        self.assertIn("22:52:04", markup)
        self.assertIn("#F87171", markup)  # the error dot
        self.assertIn("boom", markup)
        self.assertNotIn("&#215;", markup)  # no repeat badge at count 1

        record.count = 3
        self.assertIn("&#215;3", render_record_html(record))

    def test_markup_in_a_message_cannot_reach_the_document(self) -> None:
        record = parse_log_entry("<b>not bold</b> & co")
        self.assertIn("&lt;b&gt;not bold&lt;/b&gt; &amp; co", render_record_html(record))


class LogFilterTests(unittest.TestCase):
    def _record(self, text, severity="info"):
        return LogRecord(timestamp="00:00:00", severity=severity, segments=((text, None),))

    def test_the_level_filter_and_the_search_both_apply(self) -> None:
        record = self._record("Lost connection to the game", "error")
        self.assertTrue(record_matches(record, severities=set(), search=""))
        self.assertTrue(record_matches(record, severities={"error"}, search="connection"))
        self.assertFalse(record_matches(record, severities={"warning"}, search=""))
        self.assertFalse(record_matches(record, severities=set(), search="banana"))

    def test_search_ignores_case(self) -> None:
        record = self._record("Megabonk.exe")
        self.assertTrue(record_matches(record, severities=set(), search="megabonk"))


class LogViewWidgetTests(unittest.TestCase):
    """Cases that need the real widget, in a subprocess like the rest."""

    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication
            from ui.log_view import LOG_BUFFER_LIMIT, LogView
            from ui.styles import build_qt_app_stylesheet

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            class Inline:
                "A throttle that runs everything now: no event loop here."
                def request(self, callback):
                    callback()

            view = LogView(throttle=Inline())
            view.show()
            app.processEvents()
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_buffer_is_bounded(self) -> None:
        # It used to grow for the life of the session: `insertHtml` appended
        # and nothing trimmed.
        self._run(
            """
            for index in range(LOG_BUFFER_LIMIT + 250):
                view.append_log(f"[*] line {index}")
            assert len(view.records) == LOG_BUFFER_LIMIT, len(view.records)
            # The oldest went, the newest stayed.
            assert view.records[0].text == "line 250", view.records[0].text
            assert view.records[-1].text == f"line {LOG_BUFFER_LIMIT + 249}"
            """
        )

    def test_identical_consecutive_lines_collapse_into_a_count(self) -> None:
        self._run(
            """
            for _ in range(4):
                view.append_log("[*] Player stats recording armed; waiting for an active run.")
            view.append_log("[-] Lost connection to the game.")

            assert len(view.records) == 2, [r.text for r in view.records]
            assert view.records[0].count == 4
            assert view.records[1].count == 1
            assert "&#215;4" in view.document_html() or "×4" in view.document_html()
            """
        )

    def test_the_level_filter_changes_what_the_document_shows(self) -> None:
        self._run(
            """
            view.append_log("[*] routine")
            view.append_log("boom", "error")

            assert "routine" in view.document_html()
            assert "boom" in view.document_html()

            view._on_chip("error")
            assert "boom" in view.document_html()
            assert "routine" not in view.document_html()

            view._on_chip("")
            assert "routine" in view.document_html()
            """
        )

    def test_copy_takes_the_visible_lines_not_the_whole_buffer(self) -> None:
        self._run(
            """
            view.append_log("[*] routine")
            view.append_log("boom", "error")
            view._on_chip("error")

            text = view.visible_text()
            assert "boom" in text
            assert "routine" not in text, text
            assert "22" not in text or True  # timestamps are present but not asserted
            assert "[error]" in text
            """
        )

    def test_empty_and_filtered_empty_say_different_things(self) -> None:
        self._run(
            """
            html = view.document_html()
            assert "log is empty" in html, html

            view.append_log("[*] routine")
            view._search = "nothing matches this"
            view._render()
            assert "No lines match" in view.document_html()
            """
        )


if __name__ == "__main__":
    unittest.main()
