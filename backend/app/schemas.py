from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
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


class TransactionCreate(BaseModel):
    posted_on: date
    description: str = Field(min_length=1, max_length=512)
    merchant_name: str | None = Field(default=None, max_length=255)
    amount_cents: int
    category: str = Field(
        default="Uncategorized",
        min_length=1,
        max_length=64,
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        stripped = value.strip()

        if not stripped:
            raise ValueError("description cannot be empty")

        return stripped

    @field_validator("merchant_name")
    @classmethod
    def validate_merchant_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        return stripped or None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        stripped = value.strip()

        if not stripped:
            raise ValueError("category cannot be empty")

        return stripped

    @field_validator("amount_cents")
    @classmethod
    def validate_amount_cents(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount cannot be zero")

        return value


class TransactionUpdate(BaseModel):
    posted_on: date | None = None
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )
    merchant_name: str | None = Field(default=None, max_length=255)
    amount_cents: int | None = None
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None

        stripped = value.strip()

        if not stripped:
            raise ValueError("description cannot be empty")

        return stripped

    @field_validator("merchant_name")
    @classmethod
    def validate_merchant_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        return stripped or None

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return None

        stripped = value.strip()

        if not stripped:
            raise ValueError("category cannot be empty")

        return stripped

    @field_validator("amount_cents")
    @classmethod
    def validate_amount_cents(cls, value: int | None) -> int | None:
        if value == 0:
            raise ValueError("amount cannot be zero")

        return value

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> "TransactionUpdate":
        if not self.model_fields_set:
            raise ValueError(
                "at least one field must be provided"
            )

        return self


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


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(
        min_length=1,
        max_length=4096,
    )


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
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


class ForecastConfidenceFactorOut(BaseModel):
    key: str
    label: str
    weight: float
    score: float
    impact: Literal["positive", "neutral", "negative"]
    detail: str


class MonthlyForecastConfidenceOut(BaseModel):
    month: str
    score: float
    transaction_count: int


class ForecastConfidenceDriverOut(BaseModel):
    code: str
    direction: Literal["positive", "negative"]
    message: str


class ForecastDataQualityOut(BaseModel):
    history_days: int
    transaction_count: int
    recognized_recurring_items: int
    uncategorized_share: float


class ForecastConfidenceOut(BaseModel):
    score: float
    level: Literal["high", "medium", "low"]
    factors: list[ForecastConfidenceFactorOut]
    recommendations: list[str]
    monthly_confidence: list[MonthlyForecastConfidenceOut]
    # Concise, top-weighted subset of `factors` (3-5 entries) using the
    # same code/direction/message shape as Safe-to-Spend's confidence
    # drivers, for an at-a-glance "why" instead of the full factor
    # table.
    drivers: list[ForecastConfidenceDriverOut] = Field(default_factory=list)
    data_quality: ForecastDataQualityOut


class CashFlowHorizonOut(BaseModel):
    horizon_days: int
    through_date: date
    expected_income_cents: int
    known_obligations_cents: int
    projected_balance_cents: int
    shortfall_cents: int
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
    confidence: ForecastConfidenceOut
    # 30/60/90-day outlook, composed from safe_to_spend_service's
    # existing horizon-bound obligation logic rather than a new
    # formula -- see cash_flow_forecast()'s docstring for methodology.
    horizon_outlook: list[CashFlowHorizonOut] = Field(default_factory=list)

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
    # Both default False so every existing caller (Buy Now vs Wait,
    # Major Purchase, Scenario Comparison, Financial Stress Test,
    # Copilot, Recommendations) keeps its exact current numeric
    # behavior. Only a caller that explicitly opts in gets income and
    # goal commitments folded into the calculation -- avoids silently
    # changing the result those already-tested features depend on.
    include_projected_income: bool = Field(default=False)
    include_goal_reserve: bool = Field(default=False)


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
    projected_income_cents: int
    upcoming_obligations_cents: int
    essential_spending_cents: int
    goal_reserve_cents: int
    safety_reserve_cents: int


class SafeToSpendConfidenceDriverOut(BaseModel):
    code: str
    direction: Literal["positive", "negative"]
    message: str


class SafeToSpendExplanationOut(BaseModel):
    code: str
    amount_cents: int | None
    message: str


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
    confidence_level: Literal["high", "medium", "low"]
    confidence_drivers: list[SafeToSpendConfidenceDriverOut]
    breakdown: SafeToSpendBreakdownOut
    obligations: list[SafeToSpendObligationOut]
    explanation: list[SafeToSpendExplanationOut]
    warnings: list[str] = Field(default_factory=list)


class FinancialResilienceRequest(BaseModel):
    # None means "derive it from Discero data"; an explicit value
    # (including a legitimate $0) is always used as-is and labeled
    # user-provided rather than estimated.
    essential_spending_cents: int | None = Field(default=None, ge=0)


class ResilienceHorizonOut(BaseModel):
    horizon_days: int
    required_essential_cents: int
    remaining_liquid_cents: int
    shortfall_cents: int
    coverage_percent: float


class FinancialResilienceOut(BaseModel):
    as_of: date
    liquid_balance_cents: int
    liquid_account_count: int
    monthly_essential_cents: int
    essential_spending_source: Literal["user_provided", "derived"]
    # Authoritative display label for `monthly_essential_cents`, so
    # every consumer (Forecast UI, Copilot, Recommendations) shows the
    # exact same wording rather than each re-deriving it: "Monthly
    # essential spending" only when the user actually said so, else
    # "Monthly spending baseline" -- never presented as if Discero
    # knows which transactions are essential.
    spending_basis_label: str
    months_of_spending_data: int
    runway_months: float | None
    runway_days: int | None
    resilience_status: Literal[
        "critical",
        "weak",
        "fair",
        "strong",
        "very_strong",
    ]
    horizons: list[ResilienceHorizonOut]
    confidence_score: float
    data_quality_note: str | None
    headline: str
    why: str
    what_this_means: str
    suggested_actions: list[str]
    warnings: list[str] = Field(default_factory=list)


class GoalImpactOut(BaseModel):
    goal_id: int
    goal_name: str
    target_date: date | None
    target_amount_cents: int
    saved_amount_cents: int
    remaining_amount_cents: int
    current_required_monthly_contribution_cents: int
    baseline_monthly_allocation_cents: int
    adjusted_monthly_allocation_cents: int
    monthly_allocation_change_cents: int
    baseline_estimated_completion_date: date | None
    adjusted_estimated_completion_date: date | None
    delay_months: int
    funding_shortfall_cents: int
    status: Literal[
        "unaffected",
        "reduced",
        "delayed",
        "at_risk",
        "impossible",
    ]
    explanation: str


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
    goal_monthly_savings_required_cents: int
    goal_impact_months: float
    confidence_score: float
    explanation: str
    alternatives: list[MajorPurchaseAlternativeOut]
    safe_to_spend: SafeToSpendOut
    goal_impacts: list[GoalImpactOut] = Field(default_factory=list)


class BuyNowVsWaitRequest(BaseModel):
    purchase_name: str = Field(min_length=1, max_length=120)
    purchase_amount_cents: int = Field(gt=0)
    buy_now_date: date
    wait_until_date: date
    safety_reserve_cents: int = Field(default=0, ge=0)
    essential_spending_cents: int = Field(default=0, ge=0)
    horizon_days: int = Field(default=30, ge=1, le=90)

    @model_validator(mode="after")
    def validate_dates(self) -> "BuyNowVsWaitRequest":
        if self.wait_until_date <= self.buy_now_date:
            raise ValueError(
                "wait_until_date must be after buy_now_date"
            )
        return self


class BuyNowVsWaitOptionOut(BaseModel):
    label: Literal["now", "wait"]
    evaluated_date: date
    simulation: MajorPurchaseSimulationOut


class BuyNowVsWaitOut(BaseModel):
    purchase_name: str
    purchase_amount_cents: int
    buy_now_date: date
    wait_until_date: date
    now: BuyNowVsWaitOptionOut
    wait: BuyNowVsWaitOptionOut
    recommended_timing: Literal["buy_now", "wait", "either", "neither"]
    reason: str
    key_driver: Literal[
        "affordability",
        "buffer",
        "goal_impact",
        "confidence",
        "equivalent",
    ]
    buffer_difference_cents: int
    goal_impact_note: str | None
    confidence_difference: float
    assumption: str
    caveat: str | None


class ScenarioComparisonRequest(BaseModel):
    option_a: MajorPurchaseSimulationRequest
    option_b: MajorPurchaseSimulationRequest


class ScenarioComparisonOptionOut(BaseModel):
    option_key: Literal["option_a", "option_b"]
    simulation: MajorPurchaseSimulationOut
    affordability_rank: int


class ScenarioComparisonScoreCriterionOut(BaseModel):
    key: str
    label: str
    weight: float
    winner: Literal["option_a", "option_b", "tie"]


class ScenarioComparisonScorecardOut(BaseModel):
    option_a_score: float
    option_b_score: float
    max_score: float
    criteria: list[ScenarioComparisonScoreCriterionOut]


class ScenarioComparisonOut(BaseModel):
    recommended_option: Literal["option_a", "option_b", "tie"]
    recommendation: str
    reasons: list[str]
    scorecard: ScenarioComparisonScorecardOut
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
        "income_reduction",
        "one_time_expense",
        "recurring_expense_increase",
        "combined",
    ]
    scenario_name: str = Field(
        min_length=1,
        max_length=120,
    )
    stress_amount_cents: int | None = Field(
        default=None,
        ge=0,
    )
    income_reduction_percent: float | None = Field(
        default=None,
        gt=0,
        le=100,
    )
    recurring_expense_increase_percent: float | None = Field(
        default=None,
        gt=0,
        le=500,
    )
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


class StressResilienceFactorOut(BaseModel):
    key: str
    label: str
    weight: float
    score: float


class StressAffectedGoalOut(BaseModel):
    goal_id: int
    name: str
    status_before: str
    status_after: str
    monthly_shortfall_before_cents: int
    monthly_shortfall_after_cents: int
    estimated_delay_months: int | None


class StressRecoveryRecommendationOut(BaseModel):
    type: Literal[
        "replace_lost_income",
        "reduce_stress_expense",
        "preserve_cash_buffer",
        "no_action_required",
    ]
    message: str
    adjustment_cents: int | None
    # True only when this exact adjustment was re-run through the same
    # deterministic formula the stress test itself uses and confirmed
    # to resolve the shortfall/runway gap -- not a guess.
    verified: bool


class FinancialStressTestOut(BaseModel):
    scenario_type: Literal[
        "emergency_expense",
        "temporary_income_loss",
        "delayed_paycheck",
        "recurring_bill_increase",
        "income_reduction",
        "one_time_expense",
        "recurring_expense_increase",
        "combined",
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
    severity: Literal[
        "low",
        "moderate",
        "high",
        "critical",
    ]
    safe_to_spend_before_stress_cents: int
    safe_to_spend_after_stress_cents: int
    total_financial_impact_cents: int
    shortfall_cents: int
    baseline_projected_balance_cents: int
    stressed_projected_balance_cents: int
    balance_change_cents: int
    balance_change_percent: float
    cash_flow_positive: bool
    resilience_score: float
    resilience_factors: list[StressResilienceFactorOut]
    affected_goals: list[StressAffectedGoalOut]
    confidence_score: float
    estimated_recovery_days: int | None
    explanation: str
    recommendations: list[str]
    data_disclaimer: str
    safe_to_spend: SafeToSpendOut
    goal_impacts: list[GoalImpactOut] = Field(default_factory=list)
    # Days of stressed liquid runway; null when the stressed monthly
    # cash flow is non-negative (unbounded/not applicable).
    runway_days: int | None = None
    first_shortfall_date: date | None = None
    key_driver: Literal[
        "income_loss",
        "recurring_expense_increase",
        "emergency_expense",
        "baseline_shortfall",
    ] = "baseline_shortfall"
    # Reuses Confidence-Aware Forecasting 2.0 as context; not a
    # stress-specific score.
    forecast_confidence: ForecastConfidenceOut | None = None
    recovery_recommendation: StressRecoveryRecommendationOut | None = None
    explanations: list[str] = Field(default_factory=list)


WhatIfScenarioType = Literal[
    "one_time_expense",
    "monthly_expense_change",
    "monthly_income_change",
    "monthly_savings_change",
    "temporary_income_loss",
]


def _validate_what_if_scenario_fields(
    *,
    scenario_type: str,
    amount_cents: int | None,
    effective_date: date | None,
    monthly_amount_change_cents: int | None,
    monthly_income_loss_cents: int | None,
    duration_months: int | None,
) -> None:
    """Shared by `WhatIfSimulationRequest` and
    `WhatIfComparisonScenarioRequest` so both single and compared
    scenarios enforce the exact same required-field rules per type.
    """
    if scenario_type == "one_time_expense":
        if amount_cents is None:
            raise ValueError(
                "amount_cents is required for a one-time "
                "expense scenario"
            )
        if effective_date is None:
            raise ValueError(
                "effective_date is required for a one-time "
                "expense scenario"
            )
    elif scenario_type in (
        "monthly_expense_change",
        "monthly_income_change",
        "monthly_savings_change",
    ):
        if monthly_amount_change_cents is None:
            raise ValueError(
                "monthly_amount_change_cents is required for "
                f"the {scenario_type} scenario"
            )
    elif scenario_type == "temporary_income_loss":
        if monthly_income_loss_cents is None:
            raise ValueError(
                "monthly_income_loss_cents is required for a "
                "temporary income loss scenario"
            )
        if duration_months is None:
            raise ValueError(
                "duration_months is required for a temporary "
                "income loss scenario"
            )


class WhatIfSimulationRequest(BaseModel):
    scenario_type: WhatIfScenarioType
    scenario_name: str = Field(min_length=1, max_length=120)

    # one_time_expense
    amount_cents: int | None = Field(default=None, gt=0)
    effective_date: date | None = Field(default=None)

    # monthly_expense_change / monthly_income_change /
    # monthly_savings_change -- positive is an increase, negative is
    # a decrease. Never zero: a no-op scenario isn't a hypothetical.
    monthly_amount_change_cents: int | None = Field(default=None)

    # temporary_income_loss
    monthly_income_loss_cents: int | None = Field(default=None, gt=0)
    duration_months: int | None = Field(default=None, ge=1, le=24)

    safety_reserve_cents: int = Field(default=0, ge=0)
    essential_spending_cents: int = Field(default=0, ge=0)
    horizon_days: int = Field(default=30, ge=1, le=90)

    @field_validator("scenario_name")
    @classmethod
    def validate_scenario_name(cls, value: str) -> str:
        scenario_name = value.strip()

        if not scenario_name:
            raise ValueError("scenario_name cannot be blank")

        return scenario_name

    @field_validator("monthly_amount_change_cents")
    @classmethod
    def validate_monthly_amount_change(
        cls, value: int | None
    ) -> int | None:
        if value == 0:
            raise ValueError(
                "monthly_amount_change_cents cannot be zero"
            )

        return value

    @model_validator(mode="after")
    def validate_scenario_fields(self) -> "WhatIfSimulationRequest":
        _validate_what_if_scenario_fields(
            scenario_type=self.scenario_type,
            amount_cents=self.amount_cents,
            effective_date=self.effective_date,
            monthly_amount_change_cents=self.monthly_amount_change_cents,
            monthly_income_loss_cents=self.monthly_income_loss_cents,
            duration_months=self.duration_months,
        )
        return self


class WhatIfOutcomeOut(BaseModel):
    safe_to_spend_cents: int
    shortfall_cents: int
    confidence_score: float
    confidence_level: Literal["high", "medium", "low"]


class WhatIfImpactOut(BaseModel):
    safe_to_spend_delta_cents: int
    shortfall_delta_cents: int
    confidence_delta: float
    level: Literal["positive", "neutral", "caution", "negative"]


class WhatIfSimulationOut(BaseModel):
    scenario_type: WhatIfScenarioType
    scenario_name: str
    as_of: date
    through_date: date
    horizon_days: int
    baseline: WhatIfOutcomeOut
    scenario: WhatIfOutcomeOut
    impact: WhatIfImpactOut
    explanation: list[SafeToSpendExplanationOut]
    goal_impacts: list[GoalImpactOut] = Field(default_factory=list)
    safe_to_spend: SafeToSpendOut


class WhatIfComparisonScenarioRequest(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    scenario_type: WhatIfScenarioType

    # one_time_expense
    amount_cents: int | None = Field(default=None, gt=0)
    effective_date: date | None = Field(default=None)

    # monthly_expense_change / monthly_income_change /
    # monthly_savings_change
    monthly_amount_change_cents: int | None = Field(default=None)

    # temporary_income_loss
    monthly_income_loss_cents: int | None = Field(default=None, gt=0)
    duration_months: int | None = Field(default=None, ge=1, le=24)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = value.strip()

        if not label:
            raise ValueError("label cannot be blank")

        return label

    @field_validator("monthly_amount_change_cents")
    @classmethod
    def validate_monthly_amount_change(
        cls, value: int | None
    ) -> int | None:
        if value == 0:
            raise ValueError(
                "monthly_amount_change_cents cannot be zero"
            )

        return value

    @model_validator(mode="after")
    def validate_scenario_fields(
        self,
    ) -> "WhatIfComparisonScenarioRequest":
        _validate_what_if_scenario_fields(
            scenario_type=self.scenario_type,
            amount_cents=self.amount_cents,
            effective_date=self.effective_date,
            monthly_amount_change_cents=self.monthly_amount_change_cents,
            monthly_income_loss_cents=self.monthly_income_loss_cents,
            duration_months=self.duration_months,
        )
        return self


class WhatIfComparisonRequest(BaseModel):
    horizon_days: int = Field(default=30, ge=1, le=90)
    safety_reserve_cents: int = Field(default=0, ge=0)
    essential_spending_cents: int = Field(default=0, ge=0)
    scenarios: list[WhatIfComparisonScenarioRequest] = Field(
        min_length=2,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_unique_labels(self) -> "WhatIfComparisonRequest":
        labels = [
            scenario.label.strip().lower()
            for scenario in self.scenarios
        ]

        if len(labels) != len(set(labels)):
            raise ValueError(
                "scenario labels must be unique"
            )

        return self


class WhatIfComparisonScenarioOut(BaseModel):
    label: str
    scenario_type: WhatIfScenarioType
    safe_to_spend_cents: int
    shortfall_cents: int
    safe_to_spend_delta_cents: int
    shortfall_delta_cents: int
    confidence_score: float
    confidence_level: Literal["high", "medium", "low"]
    impact_level: Literal["positive", "neutral", "caution", "negative"]
    goal_impacts: list[GoalImpactOut] = Field(default_factory=list)
    explanation: list[SafeToSpendExplanationOut]


class WhatIfComparisonOut(BaseModel):
    as_of: date
    through_date: date
    horizon_days: int
    baseline: WhatIfOutcomeOut
    scenarios: list[WhatIfComparisonScenarioOut]
    recommended_label: str | None
    recommendation_reason: str
    key_driver: Literal[
        "shortfall",
        "safe_to_spend",
        "goal_impact",
        "tie",
    ]
    key_tradeoff: str | None
    ranking: list[str]
    is_tie: bool


class GoalConflictDetectionRequest(BaseModel):
    monthly_savings_capacity_cents: int | None = Field(
        default=None,
        ge=0,
    )


class GoalConflictGoalOut(BaseModel):
    goal_id: int
    name: str
    target_cents: int
    saved_cents: int
    remaining_cents: int
    target_date: date | None
    created_at: date
    months_remaining: int | None
    required_monthly_cents: int
    allocated_monthly_cents: int
    monthly_shortfall_cents: int
    status: Literal[
        "on_track",
        "at_risk",
        "unfunded",
        "no_deadline",
        "completed",
    ]


class GoalConflictRecommendationOut(BaseModel):
    type: Literal[
        "increase_monthly_capacity",
        "increase_goal_allocation",
        "reduce_goal_contribution",
        "extend_target_date",
        "reprioritize_goal",
        "no_change_needed",
    ]
    message: str
    goal_id: int | None = None
    amount_cents: int | None = None
    extension_months: int | None = None
    resulting_monthly_gap_cents: int


class GoalConflictDetectionOut(BaseModel):
    as_of: date
    conflict_status: Literal[
        "no_conflict",
        "strained",
        "conflict",
    ]
    monthly_savings_capacity_cents: int
    total_required_monthly_cents: int
    monthly_shortfall_cents: int
    monthly_headroom_cents: int
    key_driver: Literal[
        "no_goals",
        "no_conflict",
        "insufficient_capacity",
        "largest_required_goal",
    ]
    confidence_score: float
    goals: list[GoalConflictGoalOut]
    explanation: str
    recommendations: list[str]
    recommendation: GoalConflictRecommendationOut
    recommendation_alternatives: list[GoalConflictRecommendationOut] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class GoalIntelligenceGoalOut(BaseModel):
    goal_id: int
    name: str
    target_amount_cents: int
    saved_amount_cents: int
    remaining_amount_cents: int
    target_date: date | None
    months_remaining: int | None
    required_monthly_cents: int
    allocated_monthly_cents: int
    monthly_gap_cents: int
    status: Literal[
        "on_track",
        "ahead",
        "at_risk",
        "conflict",
        "not_feasible",
        "completed",
        "no_deadline",
    ]
    projected_completion_date: date | None
    suggested_feasible_target_date: date | None
    projected_delay_months: int | None
    urgency_rank: int | None
    confidence_score: float
    explanation: str
    key_driver: Literal[
        "goal_already_completed",
        "no_target_date_set",
        "ahead_of_schedule",
        "on_track",
        "target_date_passed",
        "competing_goal_priority",
        "insufficient_monthly_capacity",
        "completion_after_target_date",
    ]
    recommended_action: GoalConflictRecommendationOut
    alternative_actions: list[GoalConflictRecommendationOut] = Field(
        default_factory=list
    )


class GoalIntelligenceOut(BaseModel):
    as_of: date
    conflict_status: Literal[
        "no_conflict",
        "strained",
        "conflict",
    ]
    total_capacity_cents: int
    total_required_cents: int
    total_shortfall_cents: int
    monthly_headroom_cents: int
    key_driver: Literal[
        "no_goals",
        "no_conflict",
        "insufficient_capacity",
        "largest_required_goal",
    ]
    largest_pressure_goal_id: int | None
    confidence_score: float
    explanation: str
    suggestions: list[str]
    recommendation: GoalConflictRecommendationOut
    recommendation_alternatives: list[GoalConflictRecommendationOut] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
    goals: list[GoalIntelligenceGoalOut]


class CopilotMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class CopilotChatRequest(BaseModel):
    messages: list[CopilotMessageIn] = Field(
        min_length=1,
        max_length=40,
    )


class CopilotMetricOut(BaseModel):
    label: str
    value_display: str
    kind: Literal["currency", "percent", "score", "text"]
    tone: Literal["positive", "neutral", "warning", "danger"]


class CopilotConfidenceOut(BaseModel):
    score: float
    level: Literal["high", "medium", "low"]


class CopilotResponseOut(BaseModel):
    kind: Literal[
        "answer",
        "clarifying_question",
        "out_of_scope",
        "unavailable",
    ]
    answer: str | None = None
    why: str | None = None
    what_this_means: str | None = None
    key_numbers: list[CopilotMetricOut] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    clarifying_question: str | None = None
    clarifying_options: list[str] | None = None
    tool_used: str | None = None
    confidence: CopilotConfidenceOut | None = None
    low_data_warning: str | None = None
    provenance: Literal["deterministic", "ai_enhanced"] = "deterministic"


class RecommendationSourceSignalOut(BaseModel):
    label: str
    value_display: str


class RecommendationOut(BaseModel):
    id: str
    category: Literal[
        "liquidity",
        "budget",
        "goals",
        "spending",
        "recurring",
        "forecast",
        "savings",
        "data_quality",
        "positive_progress",
        "resilience",
    ]
    severity: Literal[
        "critical",
        "warning",
        "opportunity",
        "positive",
        "informational",
    ]
    priority: int
    title: str
    summary: str
    why: str
    recommended_action: str
    impact: str | None = None
    confidence: float | None = None
    source_signals: list[RecommendationSourceSignalOut] = Field(
        default_factory=list
    )
    deep_link: str | None = None
    evaluated_at: date


class RecommendationsOut(BaseModel):
    as_of: date
    recommendations: list[RecommendationOut]


DecisionType = Literal[
    "major_purchase",
    "scenario_comparison",
    "stress_test",
    "buy_now_vs_wait",
    "what_if",
    "what_if_comparison",
]


class SaveDecisionRequest(BaseModel):
    decision_type: DecisionType
    title: str = Field(min_length=1, max_length=120)
    # Raw dict matching the request schema for `decision_type` (the
    # same payload already sent to the individual simulate/compare/
    # stress-test endpoints). Re-validated and re-run server-side --
    # never trusted as-is -- so the persisted result is always a real
    # deterministic calculation, never client-supplied data.
    input: dict

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        title = value.strip()

        if not title:
            raise ValueError("title cannot be blank")

        return title


DecisionLifecycleStatus = Literal["saved", "acted_on", "dismissed"]


class SavedDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_type: DecisionType
    title: str
    input_snapshot: dict
    result_snapshot: dict
    status: DecisionLifecycleStatus
    acted_on_at: datetime | None
    created_at: datetime
    outcome_count: int = 0
    latest_outcome_at: datetime | None = None


class DecisionRerunOut(BaseModel):
    decision_id: int
    decision_type: DecisionType
    evaluated_at: date
    result_snapshot: dict


class UpdateDecisionLifecycleRequest(BaseModel):
    status: DecisionLifecycleStatus


class DecisionOutcomeComparisonMetric(BaseModel):
    path: str
    before: int | float | bool | str
    current: int | float | bool | str
    delta: int | float | None = None
    change_type: Literal["numeric", "boolean", "text", "date"]


class DecisionOutcomeComparisonSummary(BaseModel):
    metrics_compared: int
    metrics_changed: int


class DecisionOutcomeComparisonOut(BaseModel):
    changed: bool
    metrics: list[DecisionOutcomeComparisonMetric]
    summary: DecisionOutcomeComparisonSummary


class DecisionOutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    decision_id: int
    evaluated_at: datetime
    current_result_snapshot: dict
    comparison_snapshot: DecisionOutcomeComparisonOut
    created_at: datetime


# --- Recurring-payment intelligence ----------------------------------


class RecurringUpcomingObligationOut(BaseModel):
    recurring_item_id: int
    merchant: str
    category: str | None
    amount_cents: int
    frequency: str
    next_payment: date
    days_until_due: int


class RecurringAmountChangeOut(BaseModel):
    recurring_item_id: int
    merchant: str
    category: str | None
    status: Literal["increased", "decreased"]
    current_amount_cents: int
    baseline_amount_cents: int
    change_cents: int
    change_percent: float
    occurrences_considered: int
    last_payment: date


class NewRecurringPaymentOut(BaseModel):
    recurring_item_id: int
    merchant: str
    category: str | None
    amount_cents: int
    frequency: str
    occurrences_seen: int
    last_payment: date


class MissingRecurringPaymentOut(BaseModel):
    recurring_item_id: int
    merchant: str
    category: str | None
    amount_cents: int
    frequency: str
    expected_date: date
    days_overdue: int
    message: str


class DuplicateRecurringPairOut(BaseModel):
    recurring_item_id_a: int
    recurring_item_id_b: int
    merchant_a: str
    merchant_b: str
    amount_a_cents: int
    amount_b_cents: int
    frequency: str
    reason: str


class RecurringBurdenOut(BaseModel):
    monthly_recurring_cents: int
    active_recurring_count: int
    percent_of_income: float | None
    percent_of_spending: float | None
    next_30_days_cents: int
    next_60_days_cents: int
    next_90_days_cents: int


class RecurringIntelligenceOut(BaseModel):
    as_of: date
    burden: RecurringBurdenOut
    upcoming: list[RecurringUpcomingObligationOut]
    amount_changes: list[RecurringAmountChangeOut]
    new_recurring: list[NewRecurringPaymentOut]
    possibly_missing: list[MissingRecurringPaymentOut]
    possible_duplicates: list[DuplicateRecurringPairOut]
    data_quality_note: str | None


# --- Spending anomaly detection ----------------------------------------


class SpendingAnomalyOut(BaseModel):
    id: str
    type: Literal[
        "merchant_unusual_spend",
        "category_spike",
        "large_transaction",
        "repeated_charge",
    ]
    severity: Literal["info", "warning", "high"]
    title: str
    merchant: str | None
    category: str | None
    transaction_id: int | None
    transaction_ids: list[int] | None = None
    occurrence_count: int | None = None
    date: date
    current_amount_cents: int
    baseline_amount_cents: int | None
    difference_cents: int | None
    percent_difference: float | None
    reason: str
    confidence: Literal["low", "medium", "high"]


class SpendingAnomaliesOut(BaseModel):
    as_of: date
    lookback_months: int
    anomalies: list[SpendingAnomalyOut]
    data_quality_note: str | None
