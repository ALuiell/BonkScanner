"""Secure storage for the personal supporter key."""

from __future__ import annotations

import sys


CREDENTIAL_TARGET = "BonkScanner/SupporterAccessKey"
CREDENTIAL_USERNAME = "supporter_access_key"


def get_supporter_access_key() -> str:
    value = _get_windows_credential()
    if value:
        return value
    return _get_keyring_credential()


def set_supporter_access_key(value: str) -> None:
    if _set_windows_credential(value):
        return
    if _set_keyring_credential(value):
        return
    raise RuntimeError("No secure credential storage backend is available.")


def delete_supporter_access_key() -> None:
    if _delete_windows_credential():
        return
    _delete_keyring_credential()


def _get_windows_credential() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import win32cred

        credential = win32cred.CredRead(
            CREDENTIAL_TARGET,
            win32cred.CRED_TYPE_GENERIC,
        )
        blob = credential.get("CredentialBlob", b"")
        if isinstance(blob, bytes):
            return blob.decode("utf-8", errors="ignore").replace("\x00", "")
        return str(blob or "")
    except Exception:
        return ""


def _set_windows_credential(value: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": CREDENTIAL_TARGET,
                "UserName": CREDENTIAL_USERNAME,
                "CredentialBlob": value,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )
        return True
    except Exception:
        return False


def _delete_windows_credential() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32cred

        win32cred.CredDelete(
            CREDENTIAL_TARGET,
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
        return True
    except Exception:
        return False


def _get_keyring_credential() -> str:
    try:
        import keyring

        return keyring.get_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME) or ""
    except Exception:
        return ""


def _set_keyring_credential(value: str) -> bool:
    try:
        import keyring

        keyring.set_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME, value)
        return True
    except Exception:
        return False


def _delete_keyring_credential() -> None:
    try:
        import keyring

        keyring.delete_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME)
    except Exception:
        pass
