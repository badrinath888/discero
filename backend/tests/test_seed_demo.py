from datetime import date

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings as app_settings
from app.database import Base
from app.models import (
    Budget,
    FinancialAccount,
    GoalContribution,
    PlaidItem,
    RecurringItem,
    SavedDecision,
    SavingsGoal,
    Transaction,
    User,
)
from app.schemas import BuyNowVsWaitOut, UserCreate
from app.security import verify_password
from app.token_encryption import TokenEncryptionError, decrypt_token
from scripts.seed_demo import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    DEMO_PLAID_TOKEN_PLACEHOLDER,
    _LEGACY_DEMO_EMAIL,
    seed_demo_user,
)

AS_OF = date(2026, 8, 9)

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine
)


@pytest.fixture
def db() -> Session:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _other_user(db: Session) -> User:
    other = User(
        email="real-user@example.com",
        password_hash="not-a-real-hash",
        email_verified=True,
    )
    db.add(other)
    db.flush()
    db.add(
        Transaction(
            user_id=other.id,
            posted_on=AS_OF,
            description="Real user's own transaction",
            amount_cents=-500,
            category="Dining",
        )
    )
    db.commit()
    return other


def _legacy_demo_user(db: Session) -> User:
    legacy = User(
        email=_LEGACY_DEMO_EMAIL,
        password_hash="old-demo-hash",
        email_verified=True,
    )
    db.add(legacy)
    db.flush()
    db.add(
        Budget(
            user_id=legacy.id,
            category="Groceries",
            month="2026-01",
            limit_cents=10_000,
        )
    )
    db.commit()
    return legacy


def test_new_demo_email_passes_registration_validation() -> None:
    # Exercises the exact schema login/registration use (EmailStr),
    # not a hand-rolled regex, so this fails if the app's real
    # validation would ever reject the seeded email.
    validated = UserCreate(email=DEMO_EMAIL, password=DEMO_PASSWORD)
    assert validated.email == DEMO_EMAIL


def test_legacy_demo_user_is_purged_without_touching_others(
    db: Session,
) -> None:
    # Captured before the seed's commit expires these ORM instances --
    # the legacy user's row is genuinely gone afterward, so holding
    # onto plain ids (not the mapped objects) is what we actually want
    # to assert against.
    legacy_id = _legacy_demo_user(db).id
    other_id = _other_user(db).id

    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    assert (
        db.scalar(select(User).where(User.email == _LEGACY_DEMO_EMAIL))
        is None
    )
    assert (
        db.scalar(select(Budget).where(Budget.user_id == legacy_id)) is None
    )

    still_other = db.scalar(select(User).where(User.id == other_id))
    assert still_other is not None
    assert still_other.email == "real-user@example.com"

    new_demo_user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    assert new_demo_user is not None


def test_legacy_purge_is_a_idempotent_no_op_on_rerun(db: Session) -> None:
    _legacy_demo_user(db)

    seed_demo_user(db, as_of=AS_OF)
    db.commit()
    # Second run: no legacy row left to find/delete -- must not error.
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    assert (
        db.scalar(select(User).where(User.email == _LEGACY_DEMO_EMAIL))
        is None
    )
    demo_users = db.scalars(
        select(User).where(User.email == DEMO_EMAIL)
    ).all()
    assert len(demo_users) == 1


def test_seed_only_affects_demo_user(db: Session) -> None:
    other = _other_user(db)

    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    other_txns = db.scalars(
        select(Transaction).where(Transaction.user_id == other.id)
    ).all()
    assert len(other_txns) == 1
    assert other_txns[0].description == "Real user's own transaction"

    demo_user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    assert demo_user is not None
    assert demo_user.id != other.id


def test_seed_creates_realistic_record_counts(db: Session) -> None:
    summary = seed_demo_user(db, as_of=AS_OF)
    db.commit()

    assert summary["transactions"] > 100
    assert summary["recurring_items"] == 5
    assert summary["budgets"] == 6
    assert summary["goals"] == 2
    assert summary["goal_contributions"] == 12
    assert summary["saved_decisions"] == 2
    assert summary["financial_accounts"] == 3


def test_buy_now_vs_wait_snapshot_matches_current_schema(db: Session) -> None:
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    decision = db.scalar(
        select(SavedDecision).where(
            SavedDecision.user_id == user.id,
            SavedDecision.decision_type == "buy_now_vs_wait",
        )
    )
    assert decision is not None

    snapshot = decision.result_snapshot

    # Every key actually used is a real BuyNowVsWaitOut field -- proves
    # nothing was invented, without requiring the (unpopulated) nested
    # now/wait sub-objects to be present too.
    assert set(snapshot.keys()) <= set(BuyNowVsWaitOut.model_fields.keys())

    # The 4 fields the history page's summary chips read.
    assert snapshot["recommended_timing"] in {
        "buy_now",
        "wait",
        "either",
        "neither",
    }
    assert isinstance(snapshot["buffer_difference_cents"], int)
    assert isinstance(snapshot["confidence_difference"], (int, float))
    assert isinstance(snapshot["assumption"], str)
    assert snapshot["assumption"]

    # Internally coherent with this specific seeded scenario: waiting
    # is recommended because it preserves materially more buffer, and
    # the driver/recommendation/reason all agree with each other and
    # with evaluate_buy_now_vs_wait's own decision rule.
    assert snapshot["key_driver"] == "buffer"
    assert snapshot["buffer_difference_cents"] > 0
    assert snapshot["recommended_timing"] == "wait"
    formatted_buffer = f"${snapshot['buffer_difference_cents'] / 100:,.2f}"
    assert formatted_buffer in snapshot["reason"]

    # The saved input_snapshot must still be a valid BuyNowVsWaitRequest
    # payload so "rerun" keeps working.
    input_snapshot = decision.input_snapshot
    assert input_snapshot["wait_until_date"] == snapshot["wait_until_date"]


def test_seed_is_idempotent(db: Session) -> None:
    first = seed_demo_user(db, as_of=AS_OF)
    db.commit()
    second = seed_demo_user(db, as_of=AS_OF)
    db.commit()

    assert first == second

    users = db.scalars(select(User).where(User.email == DEMO_EMAIL)).all()
    assert len(users) == 1

    txns = db.scalars(
        select(Transaction).where(Transaction.user_id == users[0].id)
    ).all()
    assert len(txns) == first["transactions"]


def test_uncategorized_share_within_target_range(db: Session) -> None:
    summary = seed_demo_user(db, as_of=AS_OF)
    db.commit()

    assert 0.05 <= summary["uncategorized_share"] <= 0.08


def test_recurring_price_increase_and_duplicate_charge_present(
    db: Session,
) -> None:
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))

    netflix = db.scalar(
        select(RecurringItem).where(
            RecurringItem.user_id == user.id,
            RecurringItem.merchant == "Netflix",
        )
    )
    assert netflix is not None
    assert netflix.price_change_warning is True
    assert netflix.price_change_percent > 0

    rei_charges = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.merchant_name == "REI",
        )
    ).all()
    assert len(rei_charges) == 2
    assert rei_charges[0].amount_cents == rei_charges[1].amount_cents
    assert abs((rei_charges[0].posted_on - rei_charges[1].posted_on).days) == 1


def test_demo_plaid_token_is_not_decryptable(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Configure a real, working encryption key -- proving the demo
    # token still can't be decrypted with a functioning key is a much
    # stronger guarantee than proving it fails when encryption is
    # merely unconfigured.
    monkeypatch.setattr(
        app_settings, "token_encryption_key", Fernet.generate_key().decode()
    )

    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    item = db.scalar(
        select(PlaidItem).where(PlaidItem.user_id == user.id)
    )

    assert item.access_token_ciphertext == DEMO_PLAID_TOKEN_PLACEHOLDER
    with pytest.raises(TokenEncryptionError):
        decrypt_token(item.access_token_ciphertext)


def test_demo_institution_naming_is_clearly_labeled(db: Session) -> None:
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    item = db.scalar(
        select(PlaidItem).where(PlaidItem.user_id == user.id)
    )
    assert item.institution_name == "Portfolio Demo Bank"
    assert "sandbox" not in item.institution_id.lower()


def test_demo_password_matches_documented_login(db: Session) -> None:
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    assert verify_password(DEMO_PASSWORD, user.password_hash)


def test_goal_saved_cents_matches_contributions(db: Session) -> None:
    seed_demo_user(db, as_of=AS_OF)
    db.commit()

    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    goals = db.scalars(
        select(SavingsGoal).where(SavingsGoal.user_id == user.id)
    ).all()

    for goal in goals:
        total = sum(
            c.amount_cents if c.contribution_type == "deposit" else -c.amount_cents
            for c in db.scalars(
                select(GoalContribution).where(
                    GoalContribution.goal_id == goal.id
                )
            )
        )
        assert goal.saved_cents == total
        assert goal.saved_cents <= goal.target_cents
