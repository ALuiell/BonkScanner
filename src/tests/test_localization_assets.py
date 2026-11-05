"""Check the shipped copy, markup contracts, help mirrors and Qt resources."""
from collections import Counter
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
from string import Formatter
import subprocess
import sys

import src
from core.localization import SUPPORTED_LANGUAGES, Translator
from infra.localization_catalogs import localization_directory

ROOT = Path(src.__file__).resolve().parent.parent


def read_catalog(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, (path, key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


class Markup(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.events = []
        self.feed(value)
    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, tuple(attrs)))
    def handle_endtag(self, tag):
        self.events.append(("end", tag))
    def handle_startendtag(self, tag, attrs):
        self.events.append(("empty", tag, tuple(attrs)))


def test_all_catalogs_keep_placeholder_multiplicity_formats_markup_and_control_characters():
    root = localization_directory() / "ui"
    english = read_catalog(root / "en.json")
    def fields(value):
        return Counter((field, spec, conversion) for _, field, spec, conversion
                       in Formatter().parse(value) if field is not None)
    for code in SUPPORTED_LANGUAGES:
        catalog = read_catalog(root / f"{code}.json")
        assert set(catalog) == set(english), code
        for key, value in catalog.items():
            assert value.strip(), (code, key)
            assert not any(ord(char) < 32 and char not in "\n\t" for char in value), (code, key)
            assert fields(value) == fields(english[key]), (code, key)
            assert Markup(value).events == Markup(english[key]).events, (code, key)


def test_bad_repeated_fields_or_format_specifiers_fall_back_before_rendering():
    catalogs = {"en": {"repeat": "{value} + {value}", "number": "{value:.2f}"},
                "uk": {"repeat": "{value}", "number": "{value:.1f}"}}
    translator = Translator(catalogs.__getitem__, lambda _: {}, {}, language="uk")
    assert translator.text("repeat", value=3) == "3 + 3"
    assert translator.text("number", value=1.25) == "1.25"


def test_extraction_covers_every_explicit_display_message():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/extract_ui_messages.py"), "--check"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_seven_help_files_ship_and_match_the_canonical_sources():
    for suffix in ("eng", "ukr", "ru", "fr", "es", "de", "pt"):
        mirror = ROOT / f"src/media/help/help_{suffix}.txt"
        assert len(mirror.read_text(encoding="utf-8")) > 5000
        canonical = ROOT / f"docs/help/help_{suffix}.txt"
        if canonical.is_file():
            assert mirror.read_bytes() == canonical.read_bytes(), suffix


def test_build_hook_collects_existing_standard_qt_dialog_translations():
    path = ROOT / "scripts/pyinstaller_hooks/hook-ui.localization.py"
    spec = importlib.util.spec_from_file_location("localization_build_hook", path)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert len(hook.datas) == 6
    assert all(Path(source).is_file() and destination == "PySide6/translations"
               for source, destination in hook.datas)


def test_decimal_input_accepts_both_conventions_without_changing_storage_format():
    from ui.shared import _safe_float
    assert _safe_float("1,25") == _safe_float("1.25") == 1.25
    assert _safe_float("1,2.3", 7.0) == 7.0
