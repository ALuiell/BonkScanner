"""Use the Scanner's language service in the Quick Guide."""
from ui import i18n as l10n
from ui.localization import localization

from .guide_messages import MESSAGES


def message(key: str, **values: object) -> str:
    return MESSAGES[localization().translator.language][key].format(**values)


def ui(label: str) -> str:
    return str(l10n.term(label))


def game(table: str, key: str) -> str:
    return localization().translator.game_text(table, key)


def bind(widget, text, *, method: str = "setText"):
    l10n.RefreshBinding(widget, lambda: getattr(widget, method)(text()))
    return widget
