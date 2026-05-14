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

        self.assertEqual(notes.calls, [("html", "<p><b>IMPORTANT:</b></p>")])

    def test_set_release_notes_content_uses_markdown_for_plain_markdown_input(self) -> None:
        notes = FakeNotes()

        updater._set_release_notes_content(notes, "## What's New")

        self.assertEqual(notes.calls, [("markdown", "## What's New")])

    def test_looks_like_html_detects_tags(self) -> None:
        self.assertTrue(updater._looks_like_html("<hr><p>Hello</p>"))
        self.assertFalse(updater._looks_like_html("## Hello"))


if __name__ == "__main__":
    unittest.main()
