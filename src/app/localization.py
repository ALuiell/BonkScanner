"""Compose shared localization with the saved application preference."""
from app import config
from core.localization import (LANGUAGE_CONFIG_KEY, GAME_LANGUAGE_CONFIG_KEY,
                               normalize_language, normalize_game_language)
from infra.localization_catalogs import create_translator


def selected_language() -> str:
    return selected_languages()[0]


def selected_game_language() -> str:
    return selected_languages()[1]


def selected_languages() -> tuple[str, str]:
    with config.config_lock:
        return (normalize_language(config.user_config.get(LANGUAGE_CONFIG_KEY)),
                normalize_game_language(config.user_config.get(GAME_LANGUAGE_CONFIG_KEY)))


def create_localization_translator():
    language, game_language = selected_languages()
    return create_translator(language=language, game_language=game_language)
