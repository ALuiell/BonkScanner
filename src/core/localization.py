"""Language-independent message and game-term lookup; no Qt or config writes."""
from __future__ import annotations

from collections.abc import Callable
from collections import Counter
from string import Formatter


DEFAULT_LANGUAGE = "en"
LANGUAGE_CONFIG_KEY = "UI_LANGUAGE"
GAME_LANGUAGE_CONFIG_KEY = "GAME_LANGUAGE"
FOLLOW_INTERFACE_LANGUAGE = "interface"
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


def normalize_game_language(value: object) -> str:
    if isinstance(value, str) and (value in SUPPORTED_LANGUAGES or value == FOLLOW_INTERFACE_LANGUAGE):
        return value
    return DEFAULT_LANGUAGE


class Translator:
    """Independent UI and game-name languages with shared cached catalogs.

    Loaders are injected so native widgets and browser-state producers can use
    the same service. Catalogs are cached per language, never read on paint.
    """

    def __init__(self, load_ui: Callable, load_game: Callable, aliases: dict, *, language="en", game_language=FOLLOW_INTERFACE_LANGUAGE):
        self._load_ui = load_ui
        self._load_game = load_game
        self._aliases = aliases
        self._ui: dict = {}
        self._game: dict = {}
        self.language = normalize_language(language)
        self._game_language = normalize_game_language(game_language)

    @property
    def game_language(self) -> str:
        return self.language if self._game_language == FOLLOW_INTERFACE_LANGUAGE else self._game_language

    @property
    def cache_key(self) -> tuple[str, str]:
        return self.language, self.game_language

    def set_language(self, language: str) -> bool:
        return self.set_languages(language, self._game_language)

    def set_game_language(self, game_language: str) -> bool:
        return self.set_languages(self.language, game_language)

    def set_languages(self, language: str, game_language: str) -> bool:
        normalized = normalize_language(language)
        game_preference = normalize_game_language(game_language)
        if (normalized, game_preference) == (self.language, self._game_language):
            return False
        # Load before publishing the selection: a broken asset cannot leave
        # some bound widgets in the old language and others in the new one.
        self._ui_catalog(normalized)
        effective_game = normalized if game_preference == FOLLOW_INTERFACE_LANGUAGE else game_preference
        if self._game and effective_game != self.game_language:
            self._game_catalog(effective_game)
        self.language = normalized
        self._game_language = game_preference
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
        translated = self.message_template(key)
        try:
            return translated.format(**values)
        except (KeyError, ValueError, IndexError):
            # Bad translated placeholders must not break a visible control.
            # Missing parameters in the caller still raise from the English text.
            return english.format(**values)

    def has_text(self, key: str) -> bool:
        return key in self._ui_catalog(DEFAULT_LANGUAGE)

    def message_template(self, key: str) -> str:
        """Validated named-field template for another presentation renderer."""
        english = self._ui_catalog(DEFAULT_LANGUAGE)[key]
        translated = self._ui_catalog(self.language).get(key) or english
        try:
            fields = lambda value: Counter((field, spec, conversion) for _, field, spec, conversion
                                          in Formatter().parse(value) if field is not None)
            return translated if fields(translated) == fields(english) else english
        except ValueError:
            return english

    def game_text(self, table: str, key: str, *, default: str | None = None) -> str:
        """Return original game text, including its unexpanded SmartFormat tags."""
        for language in dict.fromkeys((self.game_language, DEFAULT_LANGUAGE)):
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

    def has_game_name(self, category: str, scanner_name: str) -> bool:
        return scanner_name in self._aliases.get(category, {})

    def game_names(self, category: str) -> dict[str, str]:
        """Presentation lookup keyed by stable scanner identities."""
        return {name: self.game_name(category, name)
                for name in self._aliases.get(category, {})}
