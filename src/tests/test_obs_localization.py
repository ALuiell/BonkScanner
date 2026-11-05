"""Exercise the real browser renderer with all seven shipped catalogs."""
import json
from itertools import product
from pathlib import Path
import shutil
import subprocess

import pytest
import src
from core.localization import SUPPORTED_LANGUAGES
from infra.localization_catalogs import create_translator
from projections.obs_localization import browser_localization


def test_browser_catalogs_and_language_switch_keep_held_data_and_escape_text(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for browser-renderer validation")
    translator = create_translator()
    catalogs = []
    for language, game_language in product(SUPPORTED_LANGUAGES, repeat=2):
        translator.set_languages(language, game_language)
        catalog = browser_localization(translator)
        assert catalog["language"] == language
        assert catalog["game_language"] == game_language
        assert catalog["game"]["weapons"]["Fire Staff"] == translator.game_name("weapons", "Fire Staff")
        assert catalog["game"]["stats"]["DMG"] == (
            "DMG" if game_language == "en" else translator.game_name("stats", "Damage"))
        assert "{level}" in catalog["messages"]["Lv.{level}"]
        catalogs.append(catalog)
    fixture = tmp_path / "browser-catalogs.json"
    fixture.write_text(json.dumps(catalogs, ensure_ascii=False), encoding="utf-8")
    harness = Path(__file__).parent / "support" / "overlay_js_check.mjs"
    result = subprocess.run([node, str(harness), str(fixture)], capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
