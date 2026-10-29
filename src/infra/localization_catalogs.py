"""Read bundled localization assets for source runs and PyInstaller builds."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from core.localization import Translator, FOLLOW_INTERFACE_LANGUAGE
from infra.paths import source_path


def localization_directory() -> Path:
    return Path(getattr(sys, "_MEIPASS", source_path())) / "media" / "localization"


def create_translator(*, language="en", game_language=FOLLOW_INTERFACE_LANGUAGE, directory: Path | None = None) -> Translator:
    root = directory if directory is not None else localization_directory()

    def read(relative: str):
        return json.loads((root / relative).read_text(encoding="utf-8"))

    return Translator(
        load_ui=lambda locale: read(f"ui/{locale}.json"),
        load_game=lambda locale: read(f"game/{locale}.json"),
        aliases=read("game_aliases.json"),
        language=language,
        game_language=game_language,
    )
