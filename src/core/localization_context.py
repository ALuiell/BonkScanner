"""Scoped translation for pure display projections; defaults preserve their API.

Only UI callers enter this context. Recording data, sorting, export models and
user-authored Twitch templates retain their canonical identifiers.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256

_translator = ContextVar("display_translator", default=None)


def message_key(source):
    return "app." + sha256(source.encode("utf-8")).hexdigest()[:16]


class DisplayText(str):
    """Text provenance carried through structured UI projection results."""
    def __new__(cls, source, values, translator):
        instance = str.__new__(cls, translator.text(message_key(source), **values))
        instance.source, instance.values = source, values
        return instance


class GameDisplayText(str):
    def __new__(cls, category, source, suffix, translator):
        instance = str.__new__(cls, translator.game_name(category, source) + suffix)
        instance.category, instance.name, instance.suffix = category, source, suffix
        return instance


def text(source, **values):
    translator = _translator.get()
    return source.format(**values) if translator is None else DisplayText(source, values, translator)


def game_name(category, source, *, suffix=""):
    translator = _translator.get()
    return source + suffix if translator is None else GameDisplayText(category, source, suffix, translator)


def term(source):
    if isinstance(source, (DisplayText, GameDisplayText)):
        return source
    translator = _translator.get()
    if translator is None:
        return source
    escaped = source.replace("{", "{{").replace("}", "}}")
    try:
        return DisplayText(escaped, {}, translator)
    except KeyError:
        return source


def stat_label(source):
    translator = _translator.get()
    if translator is None or isinstance(source, (DisplayText, GameDisplayText)):
        return source
    from core.stat_labels import STAT_LABEL_ABBREVIATIONS
    canonical = next((key for key, value in STAT_LABEL_ABBREVIATIONS.items() if value == source), source)
    return game_name("stats", canonical) if translator.has_game_name("stats", canonical) else term(source)


@contextmanager
def using_translator(translator):
    token = _translator.set(translator)
    try:
        yield
    finally:
        _translator.reset(token)
