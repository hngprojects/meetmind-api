from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from sdk.config import get_sdk_settings

ENCRYPTED_PREFIX = "fernet:"


class SDKTokenEncryptionError(RuntimeError):
    pass


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    cipher = _token_cipher()
    return ENCRYPTED_PREFIX + cipher.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    cipher = _token_cipher()
    encrypted_value = value.removeprefix(ENCRYPTED_PREFIX)
    try:
        return cipher.decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SDKTokenEncryptionError("Could not decrypt stored SDK token.") from exc


def _token_cipher() -> Fernet:
    key = get_sdk_settings().sdk_token_encryption_key
    if not key:
        raise SDKTokenEncryptionError(
            "SDK_TOKEN_ENCRYPTION_KEY is required to store encrypted OAuth tokens."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except ValueError as exc:
        raise SDKTokenEncryptionError(
            "SDK_TOKEN_ENCRYPTION_KEY must be a valid Fernet key."
        ) from exc
