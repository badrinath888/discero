from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, settings


class TokenEncryptionError(RuntimeError):
    pass


def _get_fernet(
    app_settings: Settings = settings,
) -> Fernet:
    key = app_settings.token_encryption_key

    if not key:
        raise TokenEncryptionError(
            "Token encryption key is not configured"
        )

    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise TokenEncryptionError(
            "Token encryption key is invalid"
        ) from exc


def encrypt_token(
    token: str,
    app_settings: Settings = settings,
) -> str:
    if not token:
        raise TokenEncryptionError(
            "Token cannot be empty"
        )

    fernet = _get_fernet(app_settings)

    return fernet.encrypt(
        token.encode("utf-8")
    ).decode("utf-8")


def decrypt_token(
    ciphertext: str,
    app_settings: Settings = settings,
) -> str:
    if not ciphertext:
        raise TokenEncryptionError(
            "Encrypted token cannot be empty"
        )

    fernet = _get_fernet(app_settings)

    try:
        return fernet.decrypt(
            ciphertext.encode("utf-8")
        ).decode("utf-8")
    except InvalidToken as exc:
        raise TokenEncryptionError(
            "Encrypted token is invalid"
        ) from exc