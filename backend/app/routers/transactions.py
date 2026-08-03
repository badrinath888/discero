from calendar import monthrange
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.deps import get_categorizer
from app.ingestion import parse_csv
from app.llm_categorization import LLMCategorizer
from app.models import FinancialAccount, PlaidItem, Transaction, User
from app.recurring import detect_recurring
from app.schemas import (
    CategoryTotal,
    CashFlowForecastOut,
    FinancialInsightOut,
    MonthTotal,
    MonthlyInsightsOut,
    Overview,
    RecurringPaymentOut,
    TransactionOut,
    TransactionPage,
    UpcomingCashFlowOut,
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


@router.get(
    "/transactions/search",
    response_model=TransactionPage,
)
def search_transactions(
    user_id: int,
    search: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=64),
    source: str | None = Query(default=None, max_length=16),
    account_id: int | None = Query(default=None, gt=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    pending: bool | None = Query(default=None),
    duplicates_only: bool | None = Query(default=None),
    transaction_type: str | None = Query(
        default=None,
        pattern="^(income|spending)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TransactionPage:
    _authorize_user(user_id, current_user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date cannot be after end_date",
        )

    filters = [Transaction.user_id == user_id]

    if search and (normalized := search.strip().lower()):
        pattern = f"%{normalized}%"
        filters.append(
            or_(
                func.lower(Transaction.description).like(pattern),
                func.lower(
                    func.coalesce(Transaction.merchant_name, "")
                ).like(pattern),
                func.lower(Transaction.category).like(pattern),
                func.lower(
                    func.coalesce(FinancialAccount.name, "")
                ).like(pattern),
                func.lower(
                    func.coalesce(PlaidItem.institution_name, "")
                ).like(pattern),
            )
        )

    if category:
        filters.append(Transaction.category == category)

    if source:
        filters.append(Transaction.source == source.lower())

    if account_id is not None:
        filters.append(Transaction.financial_account_id == account_id)

    if start_date is not None:
        filters.append(Transaction.posted_on >= start_date)

    if end_date is not None:
        filters.append(Transaction.posted_on <= end_date)

    if pending is not None:
        filters.append(Transaction.pending == pending)

    if duplicates_only:
        duplicate = aliased(Transaction)
        transaction_identity = func.lower(
            func.trim(
                func.coalesce(
                    func.nullif(func.trim(Transaction.merchant_name), ""),
                    Transaction.description,
                )
            )
        )
        duplicate_identity = func.lower(
            func.trim(
                func.coalesce(
                    func.nullif(func.trim(duplicate.merchant_name), ""),
                    duplicate.description,
                )
            )
        )
        filters.append(
            select(1)
            .select_from(duplicate)
            .where(
                duplicate.user_id == Transaction.user_id,
                duplicate.id != Transaction.id,
                duplicate.posted_on == Transaction.posted_on,
                duplicate.amount_cents == Transaction.amount_cents,
                duplicate_identity == transaction_identity,
            )
            .exists()
        )

    if transaction_type == "income":
        filters.append(Transaction.amount_cents > 0)
    elif transaction_type == "spending":
        filters.append(Transaction.amount_cents < 0)

    def base_select(*entities):
        return (
            select(*entities)
            .select_from(Transaction)
            .outerjoin(
                FinancialAccount,
                Transaction.financial_account_id == FinancialAccount.id,
            )
            .outerjoin(
                PlaidItem,
                FinancialAccount.plaid_item_id == PlaidItem.id,
            )
            .where(*filters)
        )

    total = int(
        db.scalar(base_select(func.count(Transaction.id))) or 0
    )

    total_income_cents = int(
        db.scalar(
            base_select(
                func.coalesce(func.sum(Transaction.amount_cents), 0)
            ).where(Transaction.amount_cents > 0)
        )
        or 0
    )

    negative_total = int(
        db.scalar(
            base_select(
                func.coalesce(func.sum(Transaction.amount_cents), 0)
            ).where(Transaction.amount_cents < 0)
        )
        or 0
    )
    total_spending_cents = abs(negative_total)

    statement = (
        base_select(Transaction)
        .options(
            joinedload(Transaction.financial_account).joinedload(
                FinancialAccount.plaid_item
            )
        )
        .order_by(
            Transaction.posted_on.desc(),
            Transaction.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    items = list(db.scalars(statement).all())
    total_pages = (total + page_size - 1) // page_size

    return TransactionPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        total_income_cents=total_income_cents,
        total_spending_cents=total_spending_cents,
        net_cents=total_income_cents - total_spending_cents,
    )


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

@router.get(
    "/summary/insights",
    response_model=MonthlyInsightsOut,
)
def monthly_insights(
    user_id: int,
    month: str = Query(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MonthlyInsightsOut:
    _authorize_user(user_id, current_user)

    previous_month = _shift_month(month, -1)

    transactions = _user_transactions(user_id, db)

    current = [
        transaction
        for transaction in transactions
        if transaction.posted_on.strftime("%Y-%m") == month
    ]

    previous = [
        transaction
        for transaction in transactions
        if transaction.posted_on.strftime("%Y-%m")
        == previous_month
    ]

    current_income = sum(
        transaction.amount_cents
        for transaction in current
        if transaction.amount_cents > 0
    )

    current_spending = sum(
        -transaction.amount_cents
        for transaction in current
        if transaction.amount_cents < 0
    )

    previous_spending = sum(
        -transaction.amount_cents
        for transaction in previous
        if transaction.amount_cents < 0
    )

    spending_change = current_spending - previous_spending

    spending_change_percent = (
        round(
            spending_change / previous_spending * 100,
            1,
        )
        if previous_spending > 0
        else None
    )

    savings_rate = (
        round(
            (current_income - current_spending)
            / current_income
            * 100,
            1,
        )
        if current_income > 0
        else 0.0
    )

    category_spending: dict[str, int] = defaultdict(int)
    previous_category_spending: dict[str, int] = defaultdict(int)

    for transaction in current:
        if transaction.amount_cents < 0:
            category_spending[transaction.category] += (
                -transaction.amount_cents
            )

    for transaction in previous:
        if transaction.amount_cents < 0:
            previous_category_spending[transaction.category] += (
                -transaction.amount_cents
            )

    insights: list[FinancialInsightOut] = []

    if category_spending:
        highest_category, highest_amount = max(
            category_spending.items(),
            key=lambda item: item[1],
        )

        insights.append(
            FinancialInsightOut(
                kind="highest_category",
                title="Highest spending category",
                description=(
                    f"{highest_category} was your largest "
                    f"expense category this month."
                ),
                severity="info",
                category=highest_category,
                amount_cents=highest_amount,
            )
        )

    if spending_change_percent is not None:
        direction = (
            "increased"
            if spending_change > 0
            else "decreased"
        )

        insights.append(
            FinancialInsightOut(
                kind="monthly_spending_change",
                title=f"Spending {direction}",
                description=(
                    f"Your spending {direction} by "
                    f"{abs(spending_change_percent)}% "
                    f"compared with {previous_month}."
                ),
                severity=(
                    "warning"
                    if spending_change > 0
                    else "positive"
                ),
                amount_cents=abs(spending_change),
                percentage=spending_change_percent,
            )
        )

    for category, amount in category_spending.items():
        previous_amount = previous_category_spending.get(
            category,
            0,
        )

        if previous_amount <= 0:
            continue

        change_percent = round(
            (amount - previous_amount)
            / previous_amount
            * 100,
            1,
        )

        if change_percent >= 20:
            insights.append(
                FinancialInsightOut(
                    kind="category_increase",
                    title=f"{category} spending increased",
                    description=(
                        f"{category} spending increased by "
                        f"{change_percent}% from last month."
                    ),
                    severity="warning",
                    category=category,
                    amount_cents=amount - previous_amount,
                    percentage=change_percent,
                )
            )

    if savings_rate >= 20:
        insights.append(
            FinancialInsightOut(
                kind="savings_rate",
                title="Strong savings rate",
                description=(
                    f"You saved approximately "
                    f"{savings_rate}% of your income."
                ),
                severity="positive",
                percentage=savings_rate,
            )
        )
    elif current_income > 0 and savings_rate < 10:
        insights.append(
            FinancialInsightOut(
                kind="savings_rate",
                title="Low savings rate",
                description=(
                    f"You saved approximately "
                    f"{savings_rate}% of your income."
                ),
                severity="warning",
                percentage=savings_rate,
            )
        )

    if not insights:
        insights.append(
            FinancialInsightOut(
                kind="insufficient_data",
                title="More data needed",
                description=(
                    "Add more transactions to generate "
                    "meaningful monthly insights."
                ),
                severity="info",
            )
        )

    return MonthlyInsightsOut(
        month=month,
        previous_month=previous_month,
        income_cents=current_income,
        spending_cents=current_spending,
        net_cents=current_income - current_spending,
        savings_rate_percent=savings_rate,
        spending_change_cents=spending_change,
        spending_change_percent=spending_change_percent,
        insights=insights,
    )


def _shift_month(month: str, offset: int) -> str:
    year, month_number = map(int, month.split("-"))
    absolute_month = year * 12 + month_number - 1 + offset

    next_year, next_month = divmod(absolute_month, 12)

    return f"{next_year}-{next_month + 1:02d}"


@router.get(
    "/summary/cash-flow-forecast",
    response_model=CashFlowForecastOut,
)
def cash_flow_forecast(
    user_id: int,
    as_of: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CashFlowForecastOut:
    _authorize_user(user_id, current_user)

    month_start = as_of.replace(day=1)
    month_end = as_of.replace(
        day=monthrange(as_of.year, as_of.month)[1]
    )

    days_elapsed = as_of.day
    days_remaining = max(
        (month_end - as_of).days,
        0,
    )

    transactions = _user_transactions(user_id, db)

    month_transactions = [
        transaction
        for transaction in transactions
        if month_start
        <= transaction.posted_on
        <= as_of
    ]

    income_received = sum(
        transaction.amount_cents
        for transaction in month_transactions
        if transaction.amount_cents > 0
    )

    expected_income = (
        round(
            income_received
            / days_elapsed
            * days_remaining
        )
        if days_elapsed > 0
        else 0
    )

    account_rows = db.execute(
        select(FinancialAccount)
        .join(
            PlaidItem,
            FinancialAccount.plaid_item_id
            == PlaidItem.id,
        )
        .where(
            PlaidItem.user_id == user_id,
            FinancialAccount.account_type
            == "depository",
        )
    ).scalars()

    liquid_balance = sum(
        (
            account.available_balance_cents
            if account.available_balance_cents is not None
            else account.current_balance_cents
        )
        or 0
        for account in account_rows
    )

    recurring = detect_recurring(
        transactions,
        as_of=as_of,
    )

    upcoming_cash_flows: list[UpcomingCashFlowOut] = []

    for payment in recurring:
        next_payment = payment["next_payment"]
        confidence = float(payment["confidence_score"])

        if (
            not isinstance(next_payment, date)
            or next_payment < as_of
            or next_payment > month_end
            or confidence < 60
        ):
            continue

        upcoming_cash_flows.append(
            UpcomingCashFlowOut(
                merchant=str(payment["merchant"]),
                amount_cents=int(payment["amount_cents"]),
                expected_date=next_payment,
                kind="expense",
                confidence_score=confidence,
            )
        )

    upcoming_bills = sum(
        item.amount_cents
        for item in upcoming_cash_flows
        if item.kind == "expense"
    )

    projected_end_balance = (
        liquid_balance
        + expected_income
        - upcoming_bills
    )

    return CashFlowForecastOut(
        as_of=as_of,
        month_end=month_end,
        days_remaining=days_remaining,
        liquid_balance_cents=liquid_balance,
        income_received_cents=income_received,
        expected_income_cents=expected_income,
        upcoming_bills_cents=upcoming_bills,
        projected_end_balance_cents=projected_end_balance,
        low_balance_risk=projected_end_balance < 0,
        upcoming_cash_flows=sorted(
            upcoming_cash_flows,
            key=lambda item: item.expected_date,
        ),
    )
