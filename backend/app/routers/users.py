import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import (
    EmailChangeRequest,
    EmailRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    PublicMessage,
    TokenOut,
    TokenRequest,
    UserCreate,
    UserLogin,
    UserOut,
)
from app.security import (
    create_access_token,
    create_one_time_token,
    hash_one_time_token,
    hash_password,
    verify_password,
)
from app.services import email_service

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)

PASSWORD_RESET_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)
VERIFICATION_MESSAGE = (
    "If the address needs verification, a verification link has been sent."
)
INVALID_RESET_TOKEN = "password reset link is invalid or expired"
INVALID_VERIFICATION_TOKEN = "email verification link is invalid or expired"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _send_verification(email: str, token: str) -> None:
    try:
        email_service.send_email_verification(email, token)
    except Exception:
        logger.exception("Unable to deliver verification email")


def _send_password_reset(email: str, token: str) -> None:
    try:
        email_service.send_password_reset(email, token)
    except Exception:
        logger.exception("Unable to deliver password reset email")


@router.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> User:
    email = payload.email.lower().strip()

    existing = db.scalar(
        select(User).where(
            func.lower(User.email) == email
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="email already registered",
        )

    verification_token, verification_hash = create_one_time_token()
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        email_verification_token_hash=verification_hash,
        email_verification_expires_at=_now()
        + timedelta(hours=settings.email_verification_expire_hours),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    background_tasks.add_task(
        _send_verification, user.email, verification_token
    )

    return user


@router.post("/login", response_model=TokenOut)
def login(
    payload: UserLogin,
    db: Session = Depends(get_db),
) -> TokenOut:
    email = payload.email.lower().strip()

    user = db.scalar(
        select(User).where(
            func.lower(User.email) == email
        )
    )

    if user is None or not verify_password(
        payload.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenOut(
        access_token=create_access_token(user.id, user.token_version),
        user=UserOut.model_validate(user),
    )


@router.post("/forgot-password", response_model=PublicMessage)
def forgot_password(
    payload: EmailRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PublicMessage:
    email = payload.email.lower().strip()
    user = db.scalar(
        select(User).where(func.lower(User.email) == email)
    )

    if user is not None:
        token, token_hash = create_one_time_token()
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = _now() + timedelta(
            minutes=settings.password_reset_expire_minutes
        )
        db.add(user)
        db.commit()
        background_tasks.add_task(_send_password_reset, user.email, token)

    return PublicMessage(message=PASSWORD_RESET_MESSAGE)


@router.post("/reset-password", response_model=PublicMessage)
def reset_password(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
) -> PublicMessage:
    token_hash = hash_one_time_token(payload.token)
    result = db.execute(
        update(User)
        .where(
            User.password_reset_token_hash == token_hash,
            User.password_reset_expires_at > _now(),
        )
        .values(
            password_hash=hash_password(payload.new_password),
            token_version=User.token_version + 1,
            password_reset_token_hash=None,
            password_reset_expires_at=None,
        )
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_RESET_TOKEN)

    db.commit()

    return PublicMessage(
        message="Password reset. Sign in with your new password."
    )


@router.post("/verify-email", response_model=PublicMessage)
def verify_email(
    payload: TokenRequest,
    db: Session = Depends(get_db),
) -> PublicMessage:
    token_hash = hash_one_time_token(payload.token)
    result = db.execute(
        update(User)
        .where(
            User.email_verification_token_hash == token_hash,
            User.email_verification_expires_at > _now(),
        )
        .values(
            email_verified=True,
            email_verification_token_hash=None,
            email_verification_expires_at=None,
        )
    )

    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail=INVALID_VERIFICATION_TOKEN)

    db.commit()

    return PublicMessage(message="Email verified successfully.")


@router.post("/resend-verification", response_model=PublicMessage)
def resend_verification(
    payload: EmailRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PublicMessage:
    email = payload.email.lower().strip()
    user = db.scalar(
        select(User).where(func.lower(User.email) == email)
    )

    if user is not None and not user.email_verified:
        token, token_hash = create_one_time_token()
        user.email_verification_token_hash = token_hash
        user.email_verification_expires_at = _now() + timedelta(
            hours=settings.email_verification_expire_hours
        )
        db.add(user)
        db.commit()
        background_tasks.add_task(_send_verification, user.email, token)

    return PublicMessage(message=VERIFICATION_MESSAGE)


@router.patch("/me/email", response_model=UserOut)
def change_email(
    payload: EmailChangeRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(
        payload.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=400,
            detail="current password is incorrect",
        )

    new_email = payload.new_email.lower().strip()

    if new_email == current_user.email.lower():
        raise HTTPException(
            status_code=400,
            detail="new email must be different",
        )

    existing = db.scalar(
        select(User).where(
            func.lower(User.email) == new_email
        )
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="email already registered",
        )

    verification_token, verification_hash = create_one_time_token()
    current_user.email = new_email
    current_user.email_verified = False
    current_user.email_verification_token_hash = verification_hash
    current_user.email_verification_expires_at = _now() + timedelta(
        hours=settings.email_verification_expire_hours
    )
    current_user.token_version += 1
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    background_tasks.add_task(
        _send_verification, current_user.email, verification_token
    )

    return current_user


@router.patch("/me/password", status_code=204)
def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(
        payload.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=400,
            detail="current password is incorrect",
        )

    if verify_password(
        payload.new_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=400,
            detail="new password must be different",
        )

    current_user.password_hash = hash_password(payload.new_password)
    current_user.token_version += 1
    db.add(current_user)
    db.commit()


@router.get("/me", response_model=UserOut)
def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="you cannot access another user's account",
        )

    return current_user
