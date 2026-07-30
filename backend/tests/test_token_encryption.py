import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.token_encryption import (
    TokenEncryptionError,
    decrypt_token,
    encrypt_token,
)


def make_settings(
    encryption_key: str | None,
) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        jwt_secret="test-secret",
        token_encryption_key=encryption_key,
    )


def test_encrypt_and_decrypt_token() -> None:
    settings = make_settings(
        Fernet.generate_key().decode()
    )

    plaintext = "access-sandbox-test-token"

    ciphertext = encrypt_token(
        plaintext,
        settings,
    )

    assert ciphertext != plaintext
    assert decrypt_token(
        ciphertext,
        settings,
    ) == plaintext


def test_same_token_produces_different_ciphertext() -> None:
    settings = make_settings(
        Fernet.generate_key().decode()
    )

    first = encrypt_token(
        "access-token",
        settings,
    )
    second = encrypt_token(
        "access-token",
        settings,
    )

    assert first != second


def test_missing_encryption_key_is_rejected() -> None:
    settings = make_settings(None)

    with pytest.raises(
        TokenEncryptionError,
        match="Token encryption key is not configured",
    ):
        encrypt_token(
            "access-token",
            settings,
        )


def test_invalid_encryption_key_is_rejected() -> None:
    settings = make_settings("invalid-key")

    with pytest.raises(
        TokenEncryptionError,
        match="Token encryption key is invalid",
    ):
        encrypt_token(
            "access-token",
            settings,
        )


def test_empty_token_is_rejected() -> None:
    settings = make_settings(
        Fernet.generate_key().decode()
    )

    with pytest.raises(
        TokenEncryptionError,
        match="Token cannot be empty",
    ):
        encrypt_token(
            "",
            settings,
        )


def test_tampered_ciphertext_is_rejected() -> None:
    settings = make_settings(
        Fernet.generate_key().decode()
    )

    ciphertext = encrypt_token(
        "access-token",
        settings,
    )

    tampered = ciphertext[:-1] + (
        "A" if ciphertext[-1] != "A" else "B"
    )

    with pytest.raises(
        TokenEncryptionError,
        match="Encrypted token is invalid",
    ):
        decrypt_token(
            tampered,
            settings,
        )


def test_wrong_key_cannot_decrypt_token() -> None:
    first_settings = make_settings(
        Fernet.generate_key().decode()
    )
    second_settings = make_settings(
        Fernet.generate_key().decode()
    )

    ciphertext = encrypt_token(
        "access-token",
        first_settings,
    )

    with pytest.raises(
        TokenEncryptionError,
        match="Encrypted token is invalid",
    ):
        decrypt_token(
            ciphertext,
            second_settings,
        )