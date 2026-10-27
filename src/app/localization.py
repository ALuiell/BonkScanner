"""Compose shared localization with the saved application preference."""
from app import config
from core.localization import LANGUAGE_CONFIG_KEY, normalize_language
from infra.localization_catalogs import create_translator


def selected_language() -> str:
    with config.config_lock:
        return normalize_language(config.user_config.get(LANGUAGE_CONFIG_KEY))


def create_localization_translator():
    return create_translator(language=selected_language())
