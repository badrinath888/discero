from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

from app.config import settings


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(password, hashed_password)


def create_one_time_token() -> tuple[str, str]:
    token = token_urlsafe(32)
    return token, hash_one_time_token(token)


def hash_one_time_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: int, token_version: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    return jwt.encode(
        {
            "sub": str(user_id),
            "ver": token_version,
            "type": "access",
            "exp": expires_at,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(user_id: int, token_version: int) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )

    return jwt.encode(
        {
            "sub": str(user_id),
            "ver": token_version,
            "type": "refresh",
            "exp": expires_at,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_refresh_token(token: str) -> tuple[int, int | None] | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != "refresh":
            return None

        subject = payload.get("sub")
        token_version = payload.get("ver")

        if not isinstance(subject, str):
            return None

        if type(token_version) is not int:
            token_version = None

        return int(subject), token_version
    except (
        InvalidTokenError,
        TypeError,
        ValueError,
    ):
        return None


def decode_access_token(token: str) -> tuple[int, int | None] | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )

        token_type = payload.get("type")
        if token_type is not None and token_type != "access":
            return None

        subject = payload.get("sub")
        token_version = payload.get("ver")

        if not isinstance(subject, str):
            return None

        if type(token_version) is not int:
            token_version = None

        return int(subject), token_version
    except (
        InvalidTokenError,
        TypeError,
        ValueError,
    ):
        return None
