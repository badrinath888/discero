from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_categorizer
from app.ingestion import parse_csv
from app.llm_categorization import LLMCategorizer
from app.models import Transaction, User
from app.schemas import (
    CategoryTotal,
    MonthTotal,
    Overview,
    TransactionOut,
    UploadSummary,
)

router = APIRouter(prefix="/users/{user_id}", tags=["transactions"])


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return user


@router.post("/transactions/upload", response_model=UploadSummary)
async def upload_transactions(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    categorizer: LLMCategorizer = Depends(get_categorizer),
) -> UploadSummary:
    """Upload a CSV of transactions for a user. Good rows are saved; bad rows
    are reported back rather than failing the whole upload.

    Categorization runs in one batched pass over all the descriptions (LLM when
    a key is configured, deterministic rules otherwise)."""
    _get_user_or_404(user_id, db)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="please upload a .csv file")

    raw = await file.read()
    result = parse_csv(raw)

    categories = categorizer.categorize_batch(
        [t.description for t in result.transactions]
    )

    for t, category in zip(result.transactions, categories):
        db.add(
            Transaction(
                user_id=user_id,
                posted_on=t.posted_on,
                description=t.description,
                amount_cents=t.amount_cents,
                category=category,
            )
        )
    db.commit()

    return UploadSummary(
        imported=result.ok_count,
        rejected=result.error_count,
        errors=[f"row {e.row_number}: {e.message}" for e in result.errors],
    )


@router.get("/transactions", response_model=list[TransactionOut])
def list_transactions(user_id: int, db: Session = Depends(get_db)) -> list[Transaction]:
    _get_user_or_404(user_id, db)
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.posted_on.desc())
    )
    return list(db.scalars(stmt).all())


@router.get("/summary/by-category", response_model=list[CategoryTotal])
def summary_by_category(user_id: int, db: Session = Depends(get_db)) -> list[CategoryTotal]:
    """Total spend/income grouped by category, for the dashboard in Phase 3."""
    _get_user_or_404(user_id, db)
    stmt = (
        select(
            Transaction.category,
            func.sum(Transaction.amount_cents),
            func.count(Transaction.id),
        )
        .where(Transaction.user_id == user_id)
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount_cents))
    )
    return [
        CategoryTotal(category=cat, total_cents=int(total or 0), count=cnt)
        for cat, total, cnt in db.execute(stmt).all()
    ]


def _user_transactions(user_id: int, db: Session) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == user_id)
    return list(db.scalars(stmt).all())


@router.get("/summary/overview", response_model=Overview)
def summary_overview(user_id: int, db: Session = Depends(get_db)) -> Overview:
    """Income, spending, and net across all of a user's transactions."""
    _get_user_or_404(user_id, db)
    txns = _user_transactions(user_id, db)

    income = sum(t.amount_cents for t in txns if t.amount_cents > 0)
    spending = sum(-t.amount_cents for t in txns if t.amount_cents < 0)
    return Overview(
        total_income_cents=income,
        total_spending_cents=spending,
        net_cents=income - spending,
        transaction_count=len(txns),
    )


@router.get("/summary/by-month", response_model=list[MonthTotal])
def summary_by_month(user_id: int, db: Session = Depends(get_db)) -> list[MonthTotal]:
    """Income/spending/net per calendar month, oldest first.

    Aggregated in Python rather than with dialect-specific date SQL so the
    behavior is identical on SQLite (tests) and Postgres (production).
    """
    _get_user_or_404(user_id, db)
    txns = _user_transactions(user_id, db)

    income: dict[str, int] = defaultdict(int)
    spending: dict[str, int] = defaultdict(int)
    for t in txns:
        month = t.posted_on.strftime("%Y-%m")
        if t.amount_cents > 0:
            income[month] += t.amount_cents
        else:
            spending[month] += -t.amount_cents

    months = sorted(set(income) | set(spending))
    return [
        MonthTotal(
            month=m,
            income_cents=income[m],
            spending_cents=spending[m],
            net_cents=income[m] - spending[m],
        )
        for m in months
    ]
