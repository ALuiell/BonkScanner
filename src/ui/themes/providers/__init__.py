"""Explicit built-in provider registration; descriptors never import executable code.

A new effect family registers one factory and one option validator here. Keep
factories lazy and use literal imports so frozen-build analysis can discover them.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING
import re

if TYPE_CHECKING:
    from ui.themes.contracts import AppearanceProvider, ThemeHost
    from ui.themes.package import ThemePackage


@dataclass(frozen=True)
class ProviderDefinition:
    factory: Callable[[ThemeHost, ThemePackage], AppearanceProvider]
    validate: Callable[[dict], Mapping]


def _palette_provider(host, package):
    from ui.themes.contracts import AppearanceProvider
    return AppearanceProvider(host, package)


def _palette_options(preset):
    if preset.get("parameters"):
        raise ValueError("Palette-only appearances have no effect parameters")
    return {}


def _halloween_provider(host, package):
    from ui.themes.providers.halloween import HalloweenProvider
    return HalloweenProvider(host, package)


def _halloween_options(preset):
    from ui.themes.providers.halloween_effects.options import validate
    return validate(preset)


_PROVIDERS: dict[str, ProviderDefinition] = {
    "none": ProviderDefinition(_palette_provider, _palette_options),
    "halloween": ProviderDefinition(_halloween_provider, _halloween_options),
}


def register_provider(name: str, definition: ProviderDefinition) -> None:
    """Register trusted application code, not an entry from a theme descriptor."""
    if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) is None:
        raise ValueError("Invalid appearance provider ID")
    if name in _PROVIDERS:
        raise ValueError(f"Appearance provider is already registered: {name}")
    if not isinstance(definition, ProviderDefinition) or not callable(definition.factory) or not callable(definition.validate):
        raise TypeError("Appearance provider needs a factory and an option validator")
    _PROVIDERS[name] = definition


def provider_definition(name: str) -> ProviderDefinition:
    if not isinstance(name, str) or name not in _PROVIDERS:
        raise ValueError(f"Unknown appearance provider: {name}")
    return _PROVIDERS[name]


def registered_providers() -> Mapping[str, ProviderDefinition]:
    return MappingProxyType(_PROVIDERS)
