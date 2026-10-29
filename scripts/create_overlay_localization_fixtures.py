"""Create deterministic data for verify_overlay_localization.mjs."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core.localization import SUPPORTED_LANGUAGES
from infra.localization_catalogs import create_translator
from projections.obs_localization import browser_localization


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Pass an output JSON path.")
    base = json.loads((ROOT / "src/tests/support/overlay_browser_state.json").read_text(encoding="utf-8"))
    fixtures = []
    for language in SUPPORTED_LANGUAGES:
        for game_language in dict.fromkeys(("en", language)):
            state = deepcopy(base)
            state["localization"] = browser_localization(create_translator(
                language=language, game_language=game_language))
            fixtures.append(state)
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixtures, ensure_ascii=False), encoding="utf-8")
    print(f"Created {len(fixtures)} UI/game-language fixtures: {output}")


if __name__ == "__main__":
    main()
