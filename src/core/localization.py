"""Language-independent message and game-term lookup; no Qt or config writes."""
from __future__ import annotations

from collections.abc import Callable
from string import Formatter


DEFAULT_LANGUAGE = "en"
LANGUAGE_CONFIG_KEY = "UI_LANGUAGE"
SUPPORTED_LANGUAGES = {
    "en": "English",
    "uk": "Українська",
    "ru": "Русский",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "pt": "Português",
}


def normalize_language(value: object) -> str:
    return value if isinstance(value, str) and value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


class Translator:
    """One language selection with separately keyed UI and original game text.

    Loaders are injected so native widgets and browser-state producers can use
    the same service. Catalogs are cached per language, never read on paint.
    """

    def __init__(self, load_ui: Callable, load_game: Callable, aliases: dict, *, language="en"):
        self._load_ui = load_ui
        self._load_game = load_game
        self._aliases = aliases
        self._ui: dict = {}
        self._game: dict = {}
        self.language = normalize_language(language)

    def set_language(self, language: str) -> bool:
        normalized = normalize_language(language)
        if normalized == self.language:
            return False
        # Load before publishing the selection: a broken asset cannot leave
        # some bound widgets in the old language and others in the new one.
        self._ui_catalog(normalized)
        self.language = normalized
        return True

    def _ui_catalog(self, language: str) -> dict:
        if language not in self._ui:
            self._ui[language] = self._load_ui(language)
        return self._ui[language]

    def _game_catalog(self, language: str) -> dict:
        if language not in self._game:
            self._game[language] = self._load_game(language)["tables"]
        return self._game[language]

    def text(self, key: str, **values) -> str:
        """Translate a complete UI message, falling back to its English text."""
        english = self._ui_catalog(DEFAULT_LANGUAGE)[key]
        translated = self._ui_catalog(self.language).get(key) or english
        try:
            fields = lambda message: {field for _, field, _, _ in Formatter().parse(message) if field is not None}
            if fields(translated) != fields(english):
                translated = english
            return translated.format(**values)
        except (KeyError, ValueError, IndexError):
            # Bad translated placeholders must not break a visible control.
            # Missing parameters in the caller still raise from the English text.
            return english.format(**values)

    def game_text(self, table: str, key: str, *, default: str | None = None) -> str:
        """Return original game text, including its unexpanded SmartFormat tags."""
        for language in dict.fromkeys((self.language, DEFAULT_LANGUAGE)):
            entry = self._game_catalog(language).get(table, {}).get("entries", {}).get(key)
            if entry and entry["text"]:
                return entry["text"]
        return key if default is None else default

    def game_name(self, category: str, scanner_name: str) -> str:
        """Resolve a reviewed legacy scanner alias without changing its identity."""
        reference = self._aliases.get(category, {}).get(scanner_name)
        if reference is None:
            return scanner_name
        return self.game_text(reference["table"], reference["key"], default=scanner_name)
