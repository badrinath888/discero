from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.deps import get_categorizer
from app.ingestion import parse_csv
from app.llm_categorization import LLMCategorizer
from app.models import FinancialAccount, Transaction, User
from app.recurring import detect_recurring
from app.schemas import (
    CategoryTotal,
    MonthTotal,
    Overview,
    RecurringPaymentOut,
    TransactionOut,
    TransactionUpdate,
    UploadSummary,
)

router = APIRouter(
    prefix="/users/{user_id}",
    tags=["transactions"],
)


def _authorize_user(
    user_id: int,
    current_user: User,
) -> None:
    if current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="you cannot access another user's data",
        )


def _get_transaction_or_404(
    user_id: int,
    transaction_id: int,
    db: Session,
) -> Transaction:
    transaction = db.scalar(
        select(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == user_id,
        )
    )

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="transaction not found",
        )

    return transaction


def _user_transactions(
    user_id: int,
    db: Session,
) -> list[Transaction]:
    statement = select(Transaction).where(
        Transaction.user_id == user_id
    )

    return list(db.scalars(statement).all())


@router.post(
    "/transactions/upload",
    response_model=UploadSummary,
)
async def upload_transactions(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    categorizer: LLMCategorizer = Depends(get_categorizer),
) -> UploadSummary:
    _authorize_user(user_id, current_user)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="please upload a .csv file",
        )

    result = parse_csv(await file.read())

    existing = {
        (
            posted_on,
            description.strip().lower(),
            amount_cents,
        )
        for posted_on, description, amount_cents in db.execute(
            select(
                Transaction.posted_on,
                Transaction.description,
                Transaction.amount_cents,
            ).where(Transaction.user_id == user_id)
        ).all()
    }

    unique_transactions = []
    duplicates = 0

    for transaction in result.transactions:
        signature = (
            transaction.posted_on,
            transaction.description.strip().lower(),
            transaction.amount_cents,
        )

        if signature in existing:
            duplicates += 1
            continue

        existing.add(signature)
        unique_transactions.append(transaction)

    categories = (
        categorizer.categorize_batch(
            [
                transaction.description
                for transaction in unique_transactions
            ]
        )
        if unique_transactions
        else []
    )

    for transaction, category in zip(
        unique_transactions,
        categories,
    ):
        db.add(
            Transaction(
                user_id=user_id,
                posted_on=transaction.posted_on,
                description=transaction.description,
                amount_cents=transaction.amount_cents,
                category=category,
            )
        )

    db.commit()

    return UploadSummary(
        imported=len(unique_transactions),
        rejected=result.error_count,
        duplicates=duplicates,
        errors=[
            f"row {error.row_number}: {error.message}"
            for error in result.errors
        ],
    )


@router.get(
    "/transactions",
    response_model=list[TransactionOut],
)
def list_transactions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Transaction]:
    _authorize_user(user_id, current_user)

    statement = (
        select(Transaction)
        .options(
            joinedload(Transaction.financial_account).joinedload(
                FinancialAccount.plaid_item
            )
        )
        .where(Transaction.user_id == user_id)
        .order_by(
            Transaction.posted_on.desc(),
            Transaction.id.desc(),
        )
    )

    return list(db.scalars(statement).all())


@router.patch(
    "/transactions/{transaction_id}",
    response_model=TransactionOut,
)
def update_transaction(
    user_id: int,
    transaction_id: int,
    payload: TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Transaction:
    _authorize_user(user_id, current_user)

    transaction = _get_transaction_or_404(
        user_id,
        transaction_id,
        db,
    )

    category = payload.category.strip()

    if not category:
        raise HTTPException(
            status_code=422,
            detail="category cannot be empty",
        )

    transaction.category = category
    transaction.category_locked = True

    db.commit()
    db.refresh(transaction)

    return transaction


@router.delete(
    "/transactions/{transaction_id}",
    status_code=204,
)
def delete_transaction(
    user_id: int,
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    _authorize_user(user_id, current_user)

    transaction = _get_transaction_or_404(
        user_id,
        transaction_id,
        db,
    )

    db.delete(transaction)
    db.commit()


@router.get(
    "/summary/by-category",
    response_model=list[CategoryTotal],
)
def summary_by_category(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CategoryTotal]:
    _authorize_user(user_id, current_user)

    statement = (
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
        CategoryTotal(
            category=category,
            total_cents=int(total or 0),
            count=count,
        )
        for category, total, count in db.execute(statement).all()
    ]


@router.get(
    "/summary/overview",
    response_model=Overview,
)
def summary_overview(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Overview:
    _authorize_user(user_id, current_user)

    transactions = _user_transactions(user_id, db)

    income = sum(
        transaction.amount_cents
        for transaction in transactions
        if transaction.amount_cents > 0
    )

    spending = sum(
        -transaction.amount_cents
        for transaction in transactions
        if transaction.amount_cents < 0
    )

    return Overview(
        total_income_cents=income,
        total_spending_cents=spending,
        net_cents=income - spending,
        transaction_count=len(transactions),
    )


@router.get(
    "/summary/by-month",
    response_model=list[MonthTotal],
)
def summary_by_month(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MonthTotal]:
    _authorize_user(user_id, current_user)

    transactions = _user_transactions(user_id, db)

    income: dict[str, int] = defaultdict(int)
    spending: dict[str, int] = defaultdict(int)

    for transaction in transactions:
        month = transaction.posted_on.strftime("%Y-%m")

        if transaction.amount_cents > 0:
            income[month] += transaction.amount_cents
        else:
            spending[month] += -transaction.amount_cents

    months = sorted(set(income) | set(spending))

    return [
        MonthTotal(
            month=month,
            income_cents=income[month],
            spending_cents=spending[month],
            net_cents=income[month] - spending[month],
        )
        for month in months
    ]


@router.get(
    "/summary/recurring",
    response_model=list[RecurringPaymentOut],
)
def summary_recurring(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RecurringPaymentOut]:
    _authorize_user(user_id, current_user)

    return [
        RecurringPaymentOut(**item)
        for item in detect_recurring(
            _user_transactions(user_id, db)
        )
    ]