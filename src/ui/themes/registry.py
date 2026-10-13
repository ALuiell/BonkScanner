"""Small built-in theme catalog; release policy is separate from saved choice."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re

from ui.shared import resource_path


def valid_theme_id(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is not None


@dataclass(frozen=True)
class ThemeEntry:
    id: str
    name: str
    access: str = "public"

    def available(self, premium: bool) -> bool:
        return self.access == "public" or premium


@dataclass(frozen=True)
class ThemeCatalog:
    default_theme: str
    themes: tuple[ThemeEntry, ...]

    def get(self, theme: str) -> ThemeEntry | None:
        return next((entry for entry in self.themes if entry.id == theme), None)

    def resolve(self, requested: str, *, premium: bool) -> str:
        entry = self.get(requested)
        if entry is not None and entry.available(premium):
            return entry.id
        default = self.get(self.default_theme)
        if default is not None and default.available(premium):
            return default.id
        return "original"


@lru_cache(maxsize=1)
def theme_catalog() -> ThemeCatalog:
    """Read once per process; an incomplete installation keeps Default usable."""
    fallback = ThemeCatalog("original", (ThemeEntry("original", "Default"),))
    try:
        data = json.loads(Path(resource_path("media/themes/catalog.json")).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return fallback
        raw = data.get("themes")
        if not isinstance(raw, list) or not raw:
            return fallback
        entries = []
        ids = set()
        for item in raw:
            if not isinstance(item, dict) or not valid_theme_id(item.get("id")):
                return fallback
            entry = ThemeEntry(item["id"], item.get("name"), item.get("access", "public"))
            if (not isinstance(entry.name, str) or not entry.name.strip()
                    or entry.access not in ("public", "premium") or entry.id in ids):
                return fallback
            entries.append(entry)
            ids.add(entry.id)
        catalog = ThemeCatalog(data.get("default_theme"), tuple(entries))
        original = catalog.get("original")
        if original is None or original.access != "public" or catalog.default_theme not in ids:
            return fallback
        return catalog
    except (OSError, ValueError, TypeError):
        return fallback
