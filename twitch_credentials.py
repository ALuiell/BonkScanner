import sys


CREDENTIAL_TARGET = "BonkScanner/TwitchOAuthToken"
CREDENTIAL_USERNAME = "twitch_oauth_token"


def get_twitch_oauth_token() -> str:
    token = _get_windows_credential()
    if token:
        return token
    return _get_keyring_credential()


def set_twitch_oauth_token(token: str) -> None:
    if _set_windows_credential(token):
        return
    if _set_keyring_credential(token):
        return
    raise RuntimeError("No secure credential storage backend is available.")


def delete_twitch_oauth_token() -> None:
    if _delete_windows_credential():
        return
    _delete_keyring_credential()


def _get_windows_credential() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import win32cred

        cred = win32cred.CredRead(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob", b"")
        if isinstance(blob, bytes):
            return blob.decode("utf-8")
        return str(blob or "")
    except Exception:
        return ""


def _set_windows_credential(token: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": CREDENTIAL_TARGET,
                "UserName": CREDENTIAL_USERNAME,
                "CredentialBlob": token.encode("utf-8"),
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

        win32cred.CredDelete(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        return True
    except Exception:
        return False


def _get_keyring_credential() -> str:
    try:
        import keyring

        return keyring.get_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME) or ""
    except Exception:
        return ""


def _set_keyring_credential(token: str) -> bool:
    try:
        import keyring

        keyring.set_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME, token)
        return True
    except Exception:
        return False


def _delete_keyring_credential() -> None:
    try:
        import keyring

        keyring.delete_password(CREDENTIAL_TARGET, CREDENTIAL_USERNAME)
    except Exception:
        pass