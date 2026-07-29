from datetime import date

from pydantic import BaseModel, ConfigDict, EmailStr


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    posted_on: date
    description: str
    amount_cents: int
    category: str


class UploadSummary(BaseModel):
    """Returned after a CSV upload: what got saved and what got rejected."""

    imported: int
    rejected: int
    errors: list[str] = []


class CategoryTotal(BaseModel):
    category: str
    total_cents: int
    count: int


class Overview(BaseModel):
    """High-level money summary for a user."""

    total_income_cents: int
    total_spending_cents: int   # stored as a positive magnitude
    net_cents: int
    transaction_count: int


class MonthTotal(BaseModel):
    month: str                  # 'YYYY-MM'
    income_cents: int
    spending_cents: int         # positive magnitude
    net_cents: int


class UserCreate(BaseModel):
    email: EmailStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
