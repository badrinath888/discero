from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    posted_on: date
    description: str
    merchant_name: str | None
    amount_cents: int
    category: str
    source: str
    pending: bool
    financial_account_id: int | None
    account_name: str | None
    institution_name: str | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    total_income_cents: int
    total_spending_cents: int
    net_cents: int


class TransactionUpdate(BaseModel):
    category: str = Field(min_length=1, max_length=64)


class BulkTransactionIds(BaseModel):
    transaction_ids: list[int]

    @field_validator("transaction_ids")
    @classmethod
    def validate_transaction_ids(
        cls,
        value: list[int],
    ) -> list[int]:
        unique_ids = list(dict.fromkeys(value))

        if not unique_ids:
            raise ValueError(
                "at least one transaction ID is required"
            )

        if any(
            transaction_id <= 0
            for transaction_id in unique_ids
        ):
            raise ValueError(
                "transaction IDs must be positive"
            )

        if len(unique_ids) > 100:
            raise ValueError(
                "no more than 100 transaction IDs are allowed"
            )

        return unique_ids


class BulkTransactionCategoryUpdate(BulkTransactionIds):
    category: str = Field(min_length=1, max_length=64)


class TransactionCategoryUpdate(BaseModel):
    transaction_id: int
    category: str = Field(min_length=1, max_length=64)

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(
        cls,
        value: int,
    ) -> int:
        if value <= 0:
            raise ValueError(
                "transaction IDs must be positive"
            )

        return value

    @field_validator("category")
    @classmethod
    def validate_category(
        cls,
        value: str,
    ) -> str:
        category = value.strip()

        if not category:
            raise ValueError(
                "category cannot be empty"
            )

        return category


class BulkTransactionCategoriesUpdate(BaseModel):
    updates: list[TransactionCategoryUpdate]

    @field_validator("updates")
    @classmethod
    def validate_updates(
        cls,
        value: list[TransactionCategoryUpdate],
    ) -> list[TransactionCategoryUpdate]:
        if not value:
            raise ValueError(
                "at least one transaction update is required"
            )

        transaction_ids = [
            update.transaction_id
            for update in value
        ]

        if len(set(transaction_ids)) != len(transaction_ids):
            raise ValueError(
                "transaction IDs must be unique"
            )

        if len(transaction_ids) > 100:
            raise ValueError(
                "no more than 100 transaction updates are allowed"
            )

        return value


class BulkTransactionDelete(BulkTransactionIds):
    pass


class BulkTransactionDeleteResult(BaseModel):
    deleted: int


class UploadSummary(BaseModel):
    imported: int
    rejected: int
    duplicates: int = 0
    errors: list[str] = Field(default_factory=list)


class CategoryTotal(BaseModel):
    category: str
    total_cents: int
    count: int


class Overview(BaseModel):
    total_income_cents: int
    total_spending_cents: int
    net_cents: int
    transaction_count: int


class MonthTotal(BaseModel):
    month: str
    income_cents: int
    spending_cents: int
    net_cents: int


class RecurringPaymentOut(BaseModel):
    merchant: str
    amount_cents: int
    frequency: str
    last_payment: date
    next_payment: date
    days_until_due: int
    occurrences: int
    confidence_score: float
    price_change_percent: float
    price_change_warning: bool


class RecurringItemCreate(BaseModel):
    merchant: str = Field(
        min_length=1,
        max_length=255,
    )
    normalized_merchant: str = Field(
        min_length=1,
        max_length=255,
    )
    category: str | None = Field(
        default=None,
        max_length=64,
    )
    amount_cents: int = Field(gt=0)
    frequency: Literal[
        "Weekly",
        "Biweekly",
        "Monthly",
    ]
    last_payment: date
    next_payment: date
    status: Literal[
        "suggested",
        "active",
        "dismissed",
    ] = "suggested"
    confidence_score: float = Field(
        ge=0,
        le=100,
    )
    price_change_percent: float = 0.0
    price_change_warning: bool = False


class RecurringItemUpdate(BaseModel):
    category: str | None = Field(
        default=None,
        max_length=64,
    )
    amount_cents: int | None = Field(
        default=None,
        gt=0,
    )
    frequency: Literal[
        "Weekly",
        "Biweekly",
        "Monthly",
    ] | None = None
    next_payment: date | None = None
    status: Literal[
        "suggested",
        "active",
        "paused",
        "cancelled",
        "dismissed",
    ] | None = None


class RecurringItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant: str
    normalized_merchant: str
    category: str | None
    amount_cents: int
    frequency: str
    last_payment: date
    next_payment: date
    status: str
    confidence_score: float
    price_change_percent: float
    price_change_warning: bool
    created_at: datetime
    updated_at: datetime


class BudgetCreate(BaseModel):
    category: str = Field(
        min_length=1,
        max_length=64,
    )
    month: str = Field(
        min_length=7,
        max_length=7,
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    )
    limit_cents: int = Field(gt=0)


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    month: str
    limit_cents: int


class BudgetCopyResult(BaseModel):
    source_month: str
    target_month: str
    copied: int
    updated: int
    skipped: int
    budgets: list[BudgetOut]


class BudgetCopyRequest(BaseModel):
    source_month: str = Field(
        min_length=7,
        max_length=7,
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    )
    target_month: str = Field(
        min_length=7,
        max_length=7,
        pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$",
    )
    overwrite: bool = False


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
    )


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(
        min_length=1,
        max_length=128,
    )


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(
        min_length=1,
        max_length=128,
    )
    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


class EmailChangeRequest(BaseModel):
    new_email: EmailStr
    current_password: str = Field(
        min_length=1,
        max_length=128,
    )


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(
        min_length=1,
        max_length=512,
    )


class PasswordResetRequest(TokenRequest):
    new_password: str = Field(
        min_length=8,
        max_length=128,
    )


class PublicMessage(BaseModel):
    message: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    email_verified: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class PlaidLinkTokenOut(BaseModel):
    link_token: str


class PlaidExchangeRequest(BaseModel):
    public_token: str = Field(
        min_length=1,
        max_length=2048,
    )
    institution_id: str | None = Field(
        default=None,
        max_length=255,
    )
    institution_name: str | None = Field(
        default=None,
        max_length=255,
    )


class FinancialAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    official_name: str | None
    account_type: str
    account_subtype: str | None
    mask: str | None
    current_balance_cents: int | None
    available_balance_cents: int | None
    currency: str


class PlaidConnectionOut(BaseModel):
    item_id: int
    institution_name: str | None
    status: str
    accounts: list[FinancialAccountOut]


class PlaidItemOut(BaseModel):
    id: int
    institution_name: str | None
    status: str
    sync_status: str
    sync_error: str | None
    last_sync_attempted_at: datetime | None
    last_synced_at: datetime | None


class ConnectedAccountOut(BaseModel):
    id: int
    plaid_item_id: int
    institution_name: str | None
    name: str
    official_name: str | None
    account_type: str
    account_subtype: str | None
    mask: str | None
    current_balance_cents: int | None
    available_balance_cents: int | None
    currency: str
    connection_status: str
    sync_status: str
    sync_error: str | None
    last_sync_attempted_at: datetime | None
    last_synced_at: datetime | None


class PlaidSyncOut(BaseModel):
    added: int
    modified: int
    removed: int
    items_synced: int
    synced_at: datetime


class PlaidSyncStatusOut(BaseModel):
    items: list[PlaidItemOut]


class BudgetProgressOut(BaseModel):
    category: str
    month: str
    limit_cents: int
    spent_cents: int
    remaining_cents: int
    percent_used: float
    over_budget_cents: int
    overspent: bool


class SavingsGoalCreate(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
    )
    target_cents: int = Field(gt=0)
    saved_cents: int = Field(
        default=0,
        ge=0,
    )
    target_date: date | None = None


class SavingsGoalUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
    )
    target_cents: int | None = Field(
        default=None,
        gt=0,
    )
    target_date: date | None = None


class SavingsGoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_cents: int
    saved_cents: int
    remaining_cents: int
    progress_percent: float
    target_date: date | None
    status: str
    created_at: datetime
    updated_at: datetime


class GoalContributionCreate(BaseModel):
    amount_cents: int = Field(gt=0)
    contribution_type: Literal[
        "deposit",
        "withdrawal",
    ] = "deposit"
    contributed_on: date = Field(
        default_factory=date.today,
    )
    note: str | None = Field(
        default=None,
        max_length=255,
    )


class GoalContributionUpdate(BaseModel):
    amount_cents: int | None = Field(
        default=None,
        gt=0,
    )
    contribution_type: Literal[
        "deposit",
        "withdrawal",
    ] | None = None
    contributed_on: date | None = None
    note: str | None = Field(
        default=None,
        max_length=255,
    )


class GoalContributionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal_id: int
    amount_cents: int
    contribution_type: Literal[
        "deposit",
        "withdrawal",
    ]
    contributed_on: date
    note: str | None
    created_at: datetime
    updated_at: datetime


class FinancialInsightOut(BaseModel):
    kind: str
    title: str
    description: str
    severity: str
    category: str | None = None
    amount_cents: int | None = None
    percentage: float | None = None


class MonthlyInsightsOut(BaseModel):
    month: str
    previous_month: str
    income_cents: int
    spending_cents: int
    net_cents: int
    savings_rate_percent: float
    spending_change_cents: int
    spending_change_percent: float | None
    insights: list[FinancialInsightOut]


class UpcomingCashFlowOut(BaseModel):
    merchant: str
    amount_cents: int
    expected_date: date
    kind: str
    confidence_score: float


class CashFlowForecastOut(BaseModel):
    as_of: date
    month_end: date
    days_remaining: int
    liquid_balance_cents: int
    income_received_cents: int
    expected_income_cents: int
    upcoming_bills_cents: int
    projected_end_balance_cents: int
    low_balance_risk: bool
    upcoming_cash_flows: list[UpcomingCashFlowOut]

class SafeToSpendRequest(BaseModel):
    safety_reserve_cents: int = Field(
        default=0,
        ge=0,
    )
    essential_spending_cents: int = Field(
        default=0,
        ge=0,
    )
    horizon_days: int = Field(
        default=30,
        ge=1,
        le=90,
    )


class SafeToSpendObligationOut(BaseModel):
    name: str
    amount_cents: int
    expected_date: date
    category: str | None
    confidence_score: float
    source: Literal[
        "recurring",
        "budget",
        "manual",
    ]


class SafeToSpendBreakdownOut(BaseModel):
    liquid_balance_cents: int
    upcoming_obligations_cents: int
    essential_spending_cents: int
    safety_reserve_cents: int


class SafeToSpendOut(BaseModel):
    as_of: date
    through_date: date
    horizon_days: int
    safe_to_spend_cents: int
    shortfall_cents: int
    status: Literal[
        "safe",
        "limited",
        "negative",
    ]
    confidence_score: float
    breakdown: SafeToSpendBreakdownOut
    obligations: list[SafeToSpendObligationOut]
    warnings: list[str] = Field(default_factory=list)

class MajorPurchaseSimulationRequest(BaseModel):
    purchase_name: str = Field(
        min_length=1,
        max_length=120,
    )
    purchase_amount_cents: int = Field(
        gt=0,
    )
    purchase_date: date
    safety_reserve_cents: int = Field(
        default=0,
        ge=0,
    )
    essential_spending_cents: int = Field(
        default=0,
        ge=0,
    )
    horizon_days: int = Field(
        default=30,
        ge=1,
        le=90,
    )


class MajorPurchaseAlternativeOut(BaseModel):
    label: str
    purchase_amount_cents: int
    remaining_safe_to_spend_cents: int
    description: str


class MajorPurchaseSimulationOut(BaseModel):
    purchase_name: str
    purchase_amount_cents: int
    purchase_date: date
    as_of: date
    through_date: date
    affordability_status: Literal[
        "affordable",
        "caution",
        "not_affordable",
    ]
    safe_to_spend_before_purchase_cents: int
    safe_to_spend_after_purchase_cents: int
    shortfall_after_purchase_cents: int
    recommended_max_purchase_cents: int
    purchase_impact_percent: float
    confidence_score: float
    explanation: str
    alternatives: list[MajorPurchaseAlternativeOut]
    safe_to_spend: SafeToSpendOut


class ScenarioComparisonRequest(BaseModel):
    option_a: MajorPurchaseSimulationRequest
    option_b: MajorPurchaseSimulationRequest


class ScenarioComparisonOptionOut(BaseModel):
    option_key: Literal["option_a", "option_b"]
    simulation: MajorPurchaseSimulationOut
    affordability_rank: int


class ScenarioComparisonOut(BaseModel):
    recommended_option: Literal["option_a", "option_b", "tie"]
    recommendation: str
    safe_to_spend_difference_cents: int
    purchase_cost_difference_cents: int
    impact_difference_percent: float
    option_a: ScenarioComparisonOptionOut
    option_b: ScenarioComparisonOptionOut


class FinancialStressTestRequest(BaseModel):
    scenario_type: Literal[
        "emergency_expense",
        "temporary_income_loss",
        "delayed_paycheck",
        "recurring_bill_increase",
    ]
    scenario_name: str = Field(
        min_length=1,
        max_length=120,
    )
    stress_amount_cents: int = Field(gt=0)
    event_date: date
    duration_days: int | None = Field(
        default=None,
        gt=0,
        le=365,
    )
    safety_reserve_cents: int = Field(
        default=0,
        ge=0,
    )
    essential_spending_cents: int = Field(
        default=0,
        ge=0,
    )
    horizon_days: int = Field(
        default=30,
        ge=1,
        le=90,
    )

    @field_validator("scenario_name")
    @classmethod
    def validate_scenario_name(cls, value: str) -> str:
        scenario_name = value.strip()

        if not scenario_name:
            raise ValueError(
                "scenario_name cannot be blank"
            )

        return scenario_name


class FinancialStressTestOut(BaseModel):
    scenario_type: Literal[
        "emergency_expense",
        "temporary_income_loss",
        "delayed_paycheck",
        "recurring_bill_increase",
    ]
    scenario_name: str
    event_date: date
    duration_days: int | None
    as_of: date
    through_date: date
    risk_level: Literal[
        "resilient",
        "strained",
        "critical",
    ]
    safe_to_spend_before_stress_cents: int
    safe_to_spend_after_stress_cents: int
    total_financial_impact_cents: int
    shortfall_cents: int
    confidence_score: float
    estimated_recovery_days: int | None
    explanation: str
    recommendations: list[str]
    safe_to_spend: SafeToSpendOut
