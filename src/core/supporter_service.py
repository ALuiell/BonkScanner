"""Trusted locations and protocol limits for BonkScanner supporter access."""

from __future__ import annotations

import os
import sys


PRODUCTION_BASE_URL = "https://aluiel3.pythonanywhere.com"
DEVELOPMENT_URL_ENV = "BONKSCANNER_SUPPORTER_SERVICE_URL"
ACCESS_CHECK_PATH = "/api/v1/access/validate"
PUBLIC_SUPPORTERS_PATH = "/api/v1/supporters"
ACCESS_KEY_PATTERN = r"^BSK_(?:[A-Z2-9]{8}_){3}[A-Z2-9]{8}$"


def supporter_service_base_url() -> str:
    """Return the fixed production host, with a source-build-only override."""
    if not getattr(sys, "frozen", False):
        override = os.environ.get(DEVELOPMENT_URL_ENV, "").strip()
        if override:
            return override.rstrip("/")
    return PRODUCTION_BASE_URL


def supporter_service_url(path: str) -> str:
    return supporter_service_base_url().rstrip("/") + "/" + path.lstrip("/")
