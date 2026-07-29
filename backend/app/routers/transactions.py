from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingestion import parse_csv
from app.models import Transaction, User
from app.schemas import CategoryTotal, TransactionOut, UploadSummary

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
) -> UploadSummary:
    """Upload a CSV of transactions for a user. Good rows are saved; bad rows
    are reported back rather than failing the whole upload."""
    _get_user_or_404(user_id, db)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="please upload a .csv file")

    raw = await file.read()
    result = parse_csv(raw)

    for t in result.transactions:
        db.add(
            Transaction(
                user_id=user_id,
                posted_on=t.posted_on,
                description=t.description,
                amount_cents=t.amount_cents,
                category=t.category,
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
