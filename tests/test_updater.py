import unittest

import updater


class FakeNotes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def setHtml(self, value: str) -> None:
        self.calls.append(("html", value))

    def setMarkdown(self, value: str) -> None:
        self.calls.append(("markdown", value))

    def setPlainText(self, value: str) -> None:
        self.calls.append(("plain", value))


class UpdaterTests(unittest.TestCase):
    def test_set_release_notes_content_prefers_html_for_html_input(self) -> None:
        notes = FakeNotes()

        updater._set_release_notes_content(notes, "<p><b>IMPORTANT:</b></p>")

        self.assertEqual(len(notes.calls), 1)
        self.assertEqual(notes.calls[0][0], "html")
        self.assertIn("<b>IMPORTANT:</b>", notes.calls[0][1])
        self.assertIn("font-family:'Segoe UI',sans-serif", notes.calls[0][1])

    def test_set_release_notes_content_uses_markdown_for_plain_markdown_input(self) -> None:
        notes = FakeNotes()

        updater._set_release_notes_content(notes, "## What's New")

        self.assertEqual(notes.calls, [("markdown", "## What's New")])

    def test_looks_like_html_detects_tags(self) -> None:
        self.assertTrue(updater._looks_like_html("<hr><p>Hello</p>"))
        self.assertFalse(updater._looks_like_html("## Hello"))

    def test_format_release_notes_html_adds_consistent_styling(self) -> None:
        rendered = updater._format_release_notes_html(
            "<h2>What's New 2.0.4</h2><h3>ENG</h3><ul><li>Improved <code>Live Stats</code>.</li></ul>"
        )

        self.assertIn("background-color:#f8fafc", rendered)
        self.assertIn("<h2 style=", rendered)
        self.assertIn("<h3 style=", rendered)
        self.assertIn("<code style=", rendered)


if __name__ == "__main__":
    unittest.main()
