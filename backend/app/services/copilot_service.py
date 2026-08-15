"""Discero AI Copilot orchestration.

Design principle: the LLM never invents a financial number. Each user turn
runs at most two Anthropic calls, both via tool-use (structured JSON, not
free text):

1. DECIDE -- Claude picks exactly one of: a real deterministic financial
   tool (mirroring an existing service, e.g. `simulate_major_purchase`),
   `request_clarification` (missing/ambiguous required parameter), or
   `decline_out_of_scope` (non-financial or unsupported question).
2. NARRATE -- only if a financial tool was used. Claude is shown that
   tool's REAL result JSON and must call `present_financial_answer` to
   produce prose. The numeric "key numbers" chips shown to the user are
   built directly from the real result by plain Python in this module,
   never parsed out of Claude's prose -- so a hallucinated number in the
   narration step can never reach a metric chip.

Conversation memory is just the full message history resent each turn
(Claude's native multi-turn context), so follow-ups like "what about
$3,000?" resolve for free with no bespoke intent/slot-filling code.
"""

from __future__ import annotations

import time
from datetime import date

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PlaidItem, SavingsGoal, User
from app.schemas import (
    BuyNowVsWaitRequest,
    CopilotConfidenceOut,
    CopilotMessageIn,
    CopilotMetricOut,
    CopilotResponseOut,
    FinancialStressTestRequest,
    GoalConflictDetectionRequest,
    MajorPurchaseSimulationRequest,
    SafeToSpendRequest,
    ScenarioComparisonRequest,
    WhatIfSimulationRequest,
)
from app.services.buy_now_vs_wait_service import evaluate_buy_now_vs_wait
from app.services.financial_resilience_service import (
    evaluate_financial_resilience,
)
from app.services.financial_stress_test_service import (
    run_financial_stress_test,
)
from app.services.goal_conflict_detection_service import (
    detect_goal_conflicts,
)
from app.services.goal_intelligence_service import evaluate_goal_intelligence
from app.services.major_purchase_service import (
    _average_monthly_income_cents,
    simulate_major_purchase,
)
from app.services import copilot_audit, copilot_free_mode
from app.services.recommendation_service import evaluate_recommendations
from app.services.recurring_intelligence_service import (
    evaluate_recurring_intelligence,
)
from app.services.safe_to_spend_service import calculate_safe_to_spend
from app.services.scenario_comparison_service import (
    compare_major_purchase_scenarios,
)
from app.services.spending_anomaly_service import detect_spending_anomalies
from app.services.what_if_service import simulate_what_if

_MAX_HISTORY_MESSAGES = 20
_UNAVAILABLE_ANSWER = (
    "The Copilot needs an AI provider key configured "
    "(ANTHROPIC_API_KEY) before it can answer questions."
)
_FALLBACK_ANSWER = (
    "I couldn't complete that just now. Please try rephrasing your "
    "question."
)
_SCOPE_FALLBACK = (
    "I can only help with questions about your Discero finances."
)

_STATUS_TONE = {
    "safe": "positive",
    "limited": "warning",
    "negative": "danger",
    "affordable": "positive",
    "caution": "warning",
    "not_affordable": "danger",
    "resilient": "positive",
    "strained": "warning",
    "critical": "danger",
    "no_conflict": "positive",
    "conflict": "danger",
    "unaffected": "positive",
    "on_track": "positive",
    "reduced": "warning",
    "delayed": "warning",
    "at_risk": "warning",
    "unfunded": "danger",
    "impossible": "danger",
    "completed": "positive",
    "no_deadline": "neutral",
    "high": "positive",
    "medium": "warning",
    "low": "danger",
    "buy_now": "positive",
    "wait": "positive",
    "either": "neutral",
    "neither": "danger",
    "weak": "warning",
    "fair": "warning",
    "strong": "positive",
    "very_strong": "positive",
}


def _tone(status: str) -> str:
    return _STATUS_TONE.get(status, "neutral")


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


def _chip(
    label: str,
    value_display: str,
    *,
    kind: str = "currency",
    tone: str = "neutral",
) -> CopilotMetricOut:
    return CopilotMetricOut(
        label=label,
        value_display=value_display,
        kind=kind,
        tone=tone,
    )


def _confidence_level(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _confidence(score: float) -> CopilotConfidenceOut:
    return CopilotConfidenceOut(
        score=score, level=_confidence_level(score)
    )


def _low_data_warning(
    score: float, warnings: list[str] | None = None
) -> str | None:
    if score < 45:
        return (
            "This is based on limited transaction/account history, "
            "so treat it as a rough estimate."
        )
    if warnings:
        return warnings[0]
    return None


class CopilotClient:
    """Thin Anthropic wrapper. Network call isolated for testability."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "claude-sonnet-4-6",
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        # Bounds how long a single DECIDE/NARRATE call can hang -- a
        # synchronous request endpoint must never wait on the SDK's
        # much longer default. max_retries=1 caps the SDK's own
        # transient-error retry (its default is 2) so a flaky
        # provider can't silently double a turn's latency/cost.
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def call(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
    ):
        import anthropic

        client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=1,
        )

        return client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice or {"type": "auto"},
        )


def _tool_schema(model: type[BaseModel]) -> dict:
    return model.model_json_schema()


_TOOLS = [
    {
        "name": "get_safe_to_spend",
        "description": (
            "Calculate how much the user can safely spend right now "
            "without endangering upcoming obligations, essential "
            "spending, and their safety reserve. Use for questions "
            "about current spending room or discretionary spending."
        ),
        "input_schema": _tool_schema(SafeToSpendRequest),
    },
    {
        "name": "simulate_major_purchase",
        "description": (
            "Simulate the effect of ONE specific one-time purchase "
            "(amount, date) on safe-to-spend and savings-goal "
            "funding. Use whenever the user asks whether they can "
            "afford something, or 'what if I buy X'. All *_cents "
            "fields must be in CENTS (dollars x 100)."
        ),
        "input_schema": _tool_schema(MajorPurchaseSimulationRequest),
    },
    {
        "name": "run_what_if",
        "description": (
            "Simulate a SUSTAINED monthly change -- a recurring "
            "expense going up or down (rent, a bill, a subscription), "
            "a recurring income change, a change in how much the "
            "user saves per month, or a temporary income loss over "
            "several months -- and its effect on safe-to-spend and "
            "savings goals. Use for 'what happens if my rent/bill "
            "goes up by $X', 'what if I made $X more/less per month', "
            "or 'what if I saved $X more per month' questions. Do NOT "
            "use this for a single one-time purchase (use "
            "simulate_major_purchase instead). All *_cents fields "
            "must be in CENTS. For monthly_expense_change, "
            "monthly_income_change, and monthly_savings_change, a "
            "positive monthly_amount_change_cents is an increase and "
            "negative is a decrease -- never zero."
        ),
        "input_schema": _tool_schema(WhatIfSimulationRequest),
    },
    {
        "name": "compare_purchase_scenarios",
        "description": (
            "Compare TWO alternative one-time purchases side by "
            "side and recommend the better option. Use when the "
            "user is deciding between two specific purchase "
            "options. All *_cents fields must be in CENTS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "option_a": _tool_schema(
                    MajorPurchaseSimulationRequest
                ),
                "option_b": _tool_schema(
                    MajorPurchaseSimulationRequest
                ),
            },
            "required": ["option_a", "option_b"],
        },
    },
    {
        "name": "run_stress_test",
        "description": (
            "Model a downside financial scenario (job loss, "
            "emergency expense, bill increase, delayed paycheck, "
            "etc.) and return a resilience score plus affected "
            "goals. Use for risk questions about income loss, "
            "emergencies, or financial shocks. All *_cents fields "
            "must be in CENTS."
        ),
        "input_schema": _tool_schema(FinancialStressTestRequest),
    },
    {
        "name": "check_goal_conflicts",
        "description": (
            "Check whether the user's current savings goals "
            "collectively conflict given their monthly savings "
            "capacity -- which goals are on track, at risk, or "
            "unfunded. Use for 'which goal is at risk' or 'can I "
            "fund all my goals' questions. Omit "
            "monthly_savings_capacity_cents if not stated by the "
            "user; it will be estimated from real income history."
        ),
        "input_schema": _tool_schema(GoalConflictDetectionRequest),
    },
    {
        "name": "get_goal_intelligence",
        "description": (
            "Get detailed per-goal intelligence: which goal is most "
            "urgent, which goal is causing a savings shortfall, each "
            "goal's required monthly contribution, on-track/at-risk "
            "status, and a realistic projected completion date. Use "
            "for 'which goal is most urgent', 'which goal is causing "
            "my shortfall', 'how much should I save for this goal', "
            "'when can I realistically finish this goal', or 'what "
            "if I move this goal's target date' questions. Omit "
            "monthly_capacity_cents if not stated by the user; it "
            "will be estimated from real income history -- if you "
            "omit it, explicitly tell the user the capacity figure "
            "was estimated from their financial data and that they "
            "can state a specific monthly amount instead. If the "
            "user did state an amount and you passed it through, "
            "never call it estimated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "monthly_capacity_cents": {
                    "type": ["integer", "null"],
                    "description": (
                        "Monthly savings capacity in cents, if "
                        "stated by the user."
                    ),
                }
            },
        },
    },
    {
        "name": "buy_now_vs_wait",
        "description": (
            "Compare buying a specific purchase NOW versus WAITING "
            "until a later date: affordability, safe-to-spend, goal "
            "impact, and confidence for both timings, with a "
            "deterministic recommendation. Use for 'should I buy "
            "this now or wait until X', 'what if I wait a month', or "
            "'when is the safest time to buy this' questions. All "
            "*_cents fields must be in CENTS. The WAIT figures "
            "project today's known balances and obligations forward "
            "to that date -- they are NOT a forecast of actual "
            "future income or spending. Always relay the result's "
            "`assumption` field to the user; never describe the WAIT "
            "result as a real future forecast."
        ),
        "input_schema": _tool_schema(BuyNowVsWaitRequest),
    },
    {
        "name": "get_financial_resilience",
        "description": (
            "Get the user's financial resilience / emergency runway: "
            "how many months their liquid cash would cover, a "
            "resilience status (critical/weak/fair/strong/"
            "very_strong), and a 30/60/90-day outlook if income "
            "stopped. Use for 'how many months could I survive "
            "without income', 'how long would my savings last if I "
            "lost my job', 'how financially resilient am I', 'what "
            "is my emergency runway', 'what happens if my income "
            "stops for N months', 'can I cover 90 days without "
            "income', or 'what if my essential spending is $X/month' "
            "questions. Omit essential_spending_cents if not stated "
            "by the user; it will then be a SPENDING BASELINE "
            "estimated from their recent total spending, NOT a true "
            "essential-expense figure (Discero does not yet classify "
            "essential vs. discretionary transactions) -- if you "
            "omit it, call the result 'your recent spending pace' or "
            "a 'spending baseline', never 'essential expenses', and "
            "tell the user they can state a specific essential-"
            "spending amount instead. Only call it essential spending "
            "when the user explicitly provided the amount. Never "
            "describe the runway or 30/60/90-day figures as a "
            "guaranteed forecast of future income or spending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "essential_spending_cents": {
                    "type": ["integer", "null"],
                    "description": (
                        "Monthly essential spending in cents, if "
                        "stated by the user."
                    ),
                }
            },
        },
    },
    {
        "name": "get_cash_flow_forecast",
        "description": (
            "Get the projected month-end balance, expected income, "
            "upcoming bills, forecast confidence, and a 30/60/90-day "
            "outlook. Use for 'monthly cash flow' or 'forecast "
            "confidence' questions. All expected-income figures "
            "(including horizon_outlook) are a PACE-BASED estimate "
            "(recent income divided evenly across days), not a "
            "guaranteed or precise income forecast -- it does not "
            "model irregular or seasonal income. Never describe "
            "these figures as guaranteed; if confidence is low, say "
            "so explicitly rather than stating the numbers plainly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "as_of": {
                    "type": "string",
                    "format": "date",
                    "description": "Defaults to today if omitted.",
                }
            },
        },
    },
    {
        "name": "get_monthly_insights",
        "description": (
            "Get income, spending, net cash flow, and savings rate "
            "for a specific month compared to the prior month. Use "
            "for 'how much did I save this month' or spending-trend "
            "questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "string",
                    "description": (
                        "YYYY-MM. Defaults to the current month if "
                        "omitted."
                    ),
                }
            },
        },
    },
    {
        "name": "get_recommendations",
        "description": (
            "Get the user's ranked proactive financial "
            "recommendations/priorities. Use for 'what should I do "
            "next', 'what needs my attention', 'what are my top "
            "priorities', 'how can I improve my finances', 'what's "
            "going well', or 'what are my biggest financial risks' "
            "questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recurring_intelligence",
        "description": (
            "Get deterministic intelligence about the user's ACTIVE "
            "recurring bills/subscriptions: upcoming payments with due "
            "dates, meaningful amount changes (increased/decreased) "
            "detected from real transaction history, newly established "
            "recurring payments, payments Discero expected but has not "
            "seen yet (never call these 'cancelled' -- only say "
            "Discero hasn't seen the payment), possible duplicate "
            "subscriptions, and the total monthly recurring burden "
            "(with 30/60/90-day known obligations). Use for questions "
            "like 'what changed in my recurring bills', 'did any "
            "subscription increase', 'do I have duplicate "
            "subscriptions', 'what recurring payments are coming up', "
            "or 'how much do recurring bills cost me per month'. Never "
            "report a change, duplicate, or missing payment that isn't "
            "in this tool's result."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_spending_anomalies",
        "description": (
            "Get deterministic spending anomalies detected from the "
            "user's real transaction history: unusually large charges "
            "at a specific merchant relative to that merchant's own "
            "history, category-level spending spikes this month versus "
            "recent months, unusually large individual transactions, "
            "and repeated near-identical charges from the same merchant "
            "close together in time (a possible duplicate/double "
            "charge). Use for 'did I spend unusually this month', "
            "'what spending looks unusual', 'did I get charged twice', "
            "or 'why was my spending higher this month' questions. If "
            "the result has no anomalies, say so plainly -- never "
            "invent a reason for a spending change that isn't in the "
            "result."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "request_clarification",
        "description": (
            "Use when a required financial parameter (amount, "
            "date, which goal, etc.) is missing from the "
            "conversation and cannot be safely inferred. Never "
            "guess a dollar amount or date -- ask instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional short quick-reply choices, at "
                        "most 4."
                    ),
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "decline_out_of_scope",
        "description": (
            "Use for questions unrelated to the user's Discero "
            "finances (non-financial), or financial questions "
            "Discero has no data/capability to analyze. Never "
            "fabricate an answer instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": [
                        "non_financial",
                        "unsupported_financial",
                    ],
                },
            },
            "required": ["reason", "category"],
        },
    },
]

_NARRATION_TOOL = {
    "name": "present_financial_answer",
    "description": (
        "Present the final answer to the user using ONLY the real "
        "numbers you were just shown in the tool result. Never "
        "invent or alter a number. Prefer grounding `why` in the "
        "tool result's own `explanation`/`recommendation` field "
        "when present, rather than inventing new reasoning."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "1-3 sentence direct answer.",
            },
            "why": {
                "type": "string",
                "description": (
                    "The strongest factor driving this result, if "
                    "relevant. Omit if not useful."
                ),
            },
            "what_this_means": {
                "type": "string",
                "description": (
                    "Practical implication for the user. Omit if "
                    "not useful."
                ),
            },
            "suggested_actions": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 2,
                "description": (
                    "0-2 short, concrete next steps phrased as "
                    "things the user could ask next."
                ),
            },
        },
        "required": ["answer"],
    },
}

_TOOL_LABELS = {
    "get_safe_to_spend": "Safe-to-Spend",
    "simulate_major_purchase": "Major Purchase Simulator",
    "run_what_if": "What-If Simulator",
    "compare_purchase_scenarios": "Scenario Comparison",
    "run_stress_test": "Financial Stress Test",
    "check_goal_conflicts": "Goal Conflict Check",
    "get_goal_intelligence": "Goal Intelligence",
    "buy_now_vs_wait": "Buy Now vs Wait",
    "get_financial_resilience": "Financial Resilience",
    "get_cash_flow_forecast": "Cash-Flow Forecast",
    "get_monthly_insights": "Monthly Insights",
    "get_recommendations": "Recommendations",
    "get_recurring_intelligence": "Recurring Intelligence",
    "get_spending_anomalies": "Spending Anomalies",
}

_RECOMMENDATION_SEVERITY_TONE = {
    "critical": "danger",
    "warning": "warning",
    "opportunity": "neutral",
    "positive": "positive",
    "informational": "neutral",
}


def _handle_safe_to_spend(db, user_id, tool_input, as_of, current_user):
    payload = SafeToSpendRequest(**tool_input)
    result = calculate_safe_to_spend(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Safe to spend",
            _currency(result.safe_to_spend_cents),
            tone=_tone(result.status),
        ),
        _chip(
            "Shortfall",
            _currency(result.shortfall_cents),
            tone="danger" if result.shortfall_cents else "positive",
        ),
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        ),
    ]

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        _low_data_warning(result.confidence_score, result.warnings),
    )


def _handle_major_purchase(db, user_id, tool_input, as_of, current_user):
    payload = MajorPurchaseSimulationRequest(**tool_input)
    result = simulate_major_purchase(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Affordability",
            result.affordability_status.replace("_", " ").title(),
            kind="text",
            tone=_tone(result.affordability_status),
        ),
        _chip(
            "Safe to spend after",
            _currency(result.safe_to_spend_after_purchase_cents),
            tone=(
                "danger"
                if result.shortfall_after_purchase_cents
                else "positive"
            ),
        ),
        _chip(
            "Purchase impact",
            _percent(result.purchase_impact_percent),
            kind="percent",
            tone="neutral",
        ),
        _chip(
            "Shortfall",
            _currency(result.shortfall_after_purchase_cents),
            tone=(
                "danger"
                if result.shortfall_after_purchase_cents
                else "positive"
            ),
        ),
    ]

    if result.goal_impacts:
        worst = min(
            result.goal_impacts,
            key=lambda g: _GOAL_STATUS_RANK.get(g.status, 0),
        )
        chips.append(
            _chip(
                "Goal impact",
                f"{worst.goal_name}: {worst.status.replace('_', ' ')}",
                kind="text",
                tone=_tone(worst.status),
            )
        )

    chips.append(
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        )
    )

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        _low_data_warning(result.confidence_score),
    )


_GOAL_STATUS_RANK = {
    "unaffected": 4,
    "reduced": 3,
    "delayed": 2,
    "at_risk": 1,
    "impossible": 0,
}


def _handle_what_if(db, user_id, tool_input, as_of, current_user):
    payload = WhatIfSimulationRequest(**tool_input)
    result = simulate_what_if(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Safe to spend before",
            _currency(result.baseline.safe_to_spend_cents),
        ),
        _chip(
            "Safe to spend after",
            _currency(result.scenario.safe_to_spend_cents),
            tone="danger" if result.scenario.shortfall_cents else "positive",
        ),
        _chip(
            "Impact",
            _currency(result.impact.safe_to_spend_delta_cents),
            tone=(
                "positive"
                if result.impact.safe_to_spend_delta_cents >= 0
                else "danger"
            ),
        ),
        _chip(
            "Shortfall",
            _currency(result.scenario.shortfall_cents),
            tone="danger" if result.scenario.shortfall_cents else "positive",
        ),
    ]

    if result.goal_impacts:
        worst = min(
            result.goal_impacts,
            key=lambda g: _GOAL_STATUS_RANK.get(g.status, 0),
        )
        chips.append(
            _chip(
                "Goal impact",
                f"{worst.goal_name}: {worst.status.replace('_', ' ')}",
                kind="text",
                tone=_tone(worst.status),
            )
        )

    chips.append(
        _chip(
            "Confidence",
            f"{round(result.scenario.confidence_score)}%",
            kind="score",
            tone=_tone(result.scenario.confidence_level),
        )
    )

    return (
        result,
        chips,
        _confidence(result.scenario.confidence_score),
        _low_data_warning(result.scenario.confidence_score),
    )


def _handle_compare_scenarios(
    db, user_id, tool_input, as_of, current_user
):
    payload = ScenarioComparisonRequest(**tool_input)
    result = compare_major_purchase_scenarios(
        db, user_id, payload, as_of=as_of
    )

    recommended_label = {
        "option_a": "Option A",
        "option_b": "Option B",
        "tie": "Tie",
    }[result.recommended_option]

    chips = [
        _chip("Recommended", recommended_label, kind="text", tone="positive"),
        _chip(
            "Option A safe-to-spend after",
            _currency(
                result.option_a.simulation
                .safe_to_spend_after_purchase_cents
            ),
        ),
        _chip(
            "Option B safe-to-spend after",
            _currency(
                result.option_b.simulation
                .safe_to_spend_after_purchase_cents
            ),
        ),
        _chip(
            "Impact difference",
            _percent(abs(result.impact_difference_percent)),
            kind="percent",
        ),
    ]

    confidence_score = min(
        result.option_a.simulation.confidence_score,
        result.option_b.simulation.confidence_score,
    )

    return (
        result,
        chips,
        _confidence(confidence_score),
        _low_data_warning(confidence_score),
    )


_KEY_DRIVER_LABELS = {
    "income_loss": "Lost or reduced income",
    "recurring_expense_increase": "Recurring expense increase",
    "emergency_expense": "One-time emergency expense",
    "baseline_shortfall": "Existing shortfall before this scenario",
}


def _handle_stress_test(db, user_id, tool_input, as_of, current_user):
    payload = FinancialStressTestRequest(**tool_input)
    result = run_financial_stress_test(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Risk level",
            result.risk_level.title(),
            kind="text",
            tone=_tone(result.risk_level),
        ),
        _chip(
            "Resilience score",
            f"{round(result.resilience_score)}",
            kind="score",
            tone=_tone(result.risk_level),
        ),
        _chip(
            "Safe to spend after",
            _currency(result.safe_to_spend_after_stress_cents),
        ),
        _chip(
            "Shortfall",
            _currency(result.shortfall_cents),
            tone="danger" if result.shortfall_cents else "positive",
        ),
        _chip(
            "Runway",
            (
                f"{result.runway_days} day(s)"
                if result.runway_days is not None
                else "Not exhausted"
            ),
            kind="text",
            tone="danger" if result.runway_days is not None else "positive",
        ),
        _chip(
            "Biggest pressure",
            _KEY_DRIVER_LABELS.get(result.key_driver, result.key_driver),
            kind="text",
            tone="neutral",
        ),
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        ),
    ]

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        _low_data_warning(result.confidence_score),
    )


def _handle_goal_conflicts(db, user_id, tool_input, as_of, current_user):
    tool_input = dict(tool_input)

    # Only fall back to an auto-derived capacity when the caller
    # genuinely didn't supply one -- an explicit value (including a
    # legitimate $0) must never be silently overridden.
    if tool_input.get("monthly_savings_capacity_cents") is None:
        tool_input["monthly_savings_capacity_cents"] = (
            _average_monthly_income_cents(db, user_id, as_of)
        )

    payload = GoalConflictDetectionRequest(**tool_input)
    result = detect_goal_conflicts(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Status",
            result.conflict_status.replace("_", " ").title(),
            kind="text",
            tone=_tone(result.conflict_status),
        ),
        _chip(
            "Monthly capacity",
            _currency(result.monthly_savings_capacity_cents),
            tone="neutral",
        ),
        _chip(
            "Required monthly",
            _currency(result.total_required_monthly_cents),
            tone="neutral",
        ),
        _chip(
            "Monthly shortfall",
            _currency(result.monthly_shortfall_cents),
            tone="danger" if result.monthly_shortfall_cents else "positive",
        ),
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        ),
    ]

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        _low_data_warning(result.confidence_score, result.warnings),
    )


_CAPACITY_ESTIMATED_NOTE = (
    "Monthly capacity ({capacity}) was estimated from your recent "
    "financial data. Tell me a specific monthly amount and I'll use "
    "that instead."
)


def _handle_goal_intelligence(db, user_id, tool_input, as_of, current_user):
    tool_input = dict(tool_input)

    # Same fallback convention as _handle_goal_conflicts: a genuinely
    # unstated capacity is estimated from real income history rather
    # than silently defaulting to zero. Recorded as `capacity_source`
    # so the response can be transparent about which one happened --
    # an estimated figure must never be presented as if the user said
    # it, and vice versa.
    explicit_capacity = tool_input.get("monthly_capacity_cents") is not None
    capacity_source = "explicit" if explicit_capacity else "estimated"

    if not explicit_capacity:
        tool_input["monthly_capacity_cents"] = (
            _average_monthly_income_cents(db, user_id, as_of)
        )

    result = evaluate_goal_intelligence(
        db,
        user_id,
        monthly_capacity_cents=tool_input["monthly_capacity_cents"],
        as_of=as_of,
    )

    chips = [
        _chip(
            "Status",
            result.conflict_status.replace("_", " ").title(),
            kind="text",
            tone=_tone(result.conflict_status),
        ),
        _chip(
            "Monthly capacity",
            _currency(result.total_capacity_cents),
            tone="neutral",
        ),
        _chip(
            "Capacity source",
            "Your stated amount"
            if capacity_source == "explicit"
            else "Estimated",
            kind="text",
            tone="neutral",
        ),
        _chip(
            "Required monthly",
            _currency(result.total_required_cents),
            tone="neutral",
        ),
        _chip(
            "Shortfall",
            _currency(result.total_shortfall_cents),
            tone="danger" if result.total_shortfall_cents else "positive",
        ),
    ]

    urgent = next((g for g in result.goals if g.urgency_rank == 1), None)
    if urgent:
        chips.append(
            _chip(
                "Most urgent",
                urgent.name,
                kind="text",
                tone=_tone(urgent.status),
            )
        )

    chips.append(
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        )
    )

    # Only the estimated path needs a disclosure -- an explicitly
    # stated capacity needs no caveat, per the product requirement to
    # never call a user-provided figure "estimated".
    low_data_warning = _low_data_warning(result.confidence_score)
    if capacity_source == "estimated":
        capacity_note = _CAPACITY_ESTIMATED_NOTE.format(
            capacity=_currency(result.total_capacity_cents)
        )
        low_data_warning = (
            f"{capacity_note} {low_data_warning}"
            if low_data_warning
            else capacity_note
        )

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        low_data_warning,
    )


def _handle_buy_now_vs_wait(db, user_id, tool_input, as_of, current_user):
    payload = BuyNowVsWaitRequest(**tool_input)
    result = evaluate_buy_now_vs_wait(db, user_id, payload, as_of=as_of)

    chips = [
        _chip(
            "Recommendation",
            result.recommended_timing.replace("_", " ").title(),
            kind="text",
            tone=_tone(result.recommended_timing),
        ),
        _chip(
            "Now: safe to spend after",
            _currency(
                result.now.simulation.safe_to_spend_after_purchase_cents
            ),
        ),
        _chip(
            "Wait: safe to spend after",
            _currency(
                result.wait.simulation.safe_to_spend_after_purchase_cents
            ),
        ),
        _chip(
            "Buffer difference",
            _currency(result.buffer_difference_cents),
            tone=(
                "positive"
                if result.buffer_difference_cents >= 0
                else "danger"
            ),
        ),
    ]

    confidence_score = min(
        result.now.simulation.confidence_score,
        result.wait.simulation.confidence_score,
    )

    return (
        result,
        chips,
        _confidence(confidence_score),
        result.caveat,
    )


_SPENDING_BASELINE_ESTIMATED_NOTE = (
    "Monthly spending baseline ({amount}) was estimated from your "
    "recent total spending because Discero does not yet classify "
    "essential vs. discretionary expenses. Tell me a specific "
    "essential-spending amount and I'll use that instead."
)


def _handle_financial_resilience(
    db, user_id, tool_input, as_of, current_user
):
    essential_override = tool_input.get("essential_spending_cents")
    result = evaluate_financial_resilience(
        db,
        user_id,
        essential_spending_cents=essential_override,
        as_of=as_of,
    )

    runway_display = (
        f"{result.runway_months} mo"
        if result.runway_months is not None
        else "N/A"
    )

    chips = [
        _chip(
            "Resilience status",
            result.resilience_status.replace("_", " ").title(),
            kind="text",
            tone=_tone(result.resilience_status),
        ),
        _chip("Runway", runway_display, kind="text", tone="neutral"),
        _chip(
            "Liquid cash",
            _currency(result.liquid_balance_cents),
            tone="neutral",
        ),
        _chip(
            result.spending_basis_label,
            _currency(result.monthly_essential_cents),
            tone="neutral",
        ),
        _chip(
            "Spending source",
            "Your stated amount"
            if result.essential_spending_source == "user_provided"
            else "Estimated",
            kind="text",
            tone="neutral",
        ),
    ]

    for horizon in result.horizons:
        chips.append(
            _chip(
                f"{horizon.horizon_days}-day coverage",
                f"{horizon.coverage_percent:.0f}%",
                kind="percent",
                tone="danger" if horizon.shortfall_cents else "positive",
            )
        )

    chips.append(
        _chip(
            "Confidence",
            f"{round(result.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(result.confidence_score)),
        )
    )

    # Only the derived path needs a disclosure -- a user-provided
    # figure needs no caveat, mirroring the savings-capacity
    # transparency convention.
    low_data_warning = result.data_quality_note
    if result.essential_spending_source == "derived":
        note = _SPENDING_BASELINE_ESTIMATED_NOTE.format(
            amount=_currency(result.monthly_essential_cents)
        )
        low_data_warning = (
            f"{note} {low_data_warning}" if low_data_warning else note
        )

    return (
        result,
        chips,
        _confidence(result.confidence_score),
        low_data_warning,
    )


def _handle_cash_flow_forecast(
    db, user_id, tool_input, as_of, current_user
):
    # Imported lazily: app.routers.transactions imports app.deps, and
    # app.deps imports CopilotClient from this module -- a module-level
    # import here would be circular.
    from app.routers.transactions import cash_flow_forecast

    as_of_param = tool_input.get("as_of")
    parsed_as_of = date.fromisoformat(as_of_param) if as_of_param else as_of

    result = cash_flow_forecast(
        user_id=user_id,
        as_of=parsed_as_of,
        db=db,
        current_user=current_user,
    )

    monthly_flow_cents = (
        result.expected_income_cents - result.upcoming_bills_cents
    )

    chips = [
        _chip(
            "Projected month-end balance",
            _currency(result.projected_end_balance_cents),
            tone="danger" if result.low_balance_risk else "positive",
        ),
        _chip(
            "Monthly cash flow",
            _currency(monthly_flow_cents),
            tone="positive" if monthly_flow_cents >= 0 else "danger",
        ),
        _chip(
            "Forecast confidence",
            f"{round(result.confidence.score)}%",
            kind="score",
            tone=_tone(result.confidence.level),
        ),
    ]

    return (
        result,
        chips,
        _confidence(result.confidence.score),
        _low_data_warning(result.confidence.score),
    )


def _handle_monthly_insights(
    db, user_id, tool_input, as_of, current_user
):
    from app.routers.transactions import monthly_insights

    month = tool_input.get("month") or as_of.strftime("%Y-%m")

    result = monthly_insights(
        user_id=user_id,
        month=month,
        db=db,
        current_user=current_user,
    )

    chips = [
        _chip(
            "Monthly cash flow",
            _currency(result.net_cents),
            tone="positive" if result.net_cents >= 0 else "danger",
        ),
        _chip(
            "Savings rate",
            _percent(result.savings_rate_percent),
            kind="percent",
            tone=(
                "positive"
                if result.savings_rate_percent >= 0
                else "danger"
            ),
        ),
    ]

    if result.spending_change_percent is not None:
        chips.append(
            _chip(
                "Spending change",
                _percent(result.spending_change_percent),
                kind="percent",
                tone=(
                    "warning"
                    if result.spending_change_percent > 0
                    else "positive"
                ),
            )
        )

    return (result, chips, None, None)


def _handle_recommendations(db, user_id, tool_input, as_of, current_user):
    result = evaluate_recommendations(db, user_id, current_user, as_of=as_of)

    chips = [
        _chip(
            rec.title,
            rec.impact or rec.severity.replace("_", " ").title(),
            kind="text",
            tone=_RECOMMENDATION_SEVERITY_TONE.get(rec.severity, "neutral"),
        )
        for rec in result.recommendations[:3]
    ]

    return (result, chips, None, None)


def _handle_recurring_intelligence(
    db, user_id, tool_input, as_of, current_user
):
    result = evaluate_recurring_intelligence(db, user_id, as_of=as_of)
    burden = result.burden

    chips = [
        _chip(
            "Monthly recurring",
            _currency(burden.monthly_recurring_cents),
        ),
        _chip(
            "Active recurring items",
            str(burden.active_recurring_count),
            kind="text",
        ),
        _chip(
            "Next 30 days",
            _currency(burden.next_30_days_cents),
        ),
    ]

    if result.amount_changes:
        top_change = max(
            result.amount_changes, key=lambda c: abs(c.change_percent)
        )
        chips.append(
            _chip(
                f"{top_change.merchant} {top_change.status}",
                _percent(top_change.change_percent),
                kind="percent",
                tone=(
                    "warning"
                    if top_change.status == "increased"
                    else "positive"
                ),
            )
        )

    if result.possible_duplicates:
        chips.append(
            _chip(
                "Possible duplicates",
                str(len(result.possible_duplicates)),
                kind="text",
                tone="warning",
            )
        )

    if result.possibly_missing:
        chips.append(
            _chip(
                "Possibly missing",
                str(len(result.possibly_missing)),
                kind="text",
                tone="warning",
            )
        )

    return (result, chips, None, result.data_quality_note)


def _handle_spending_anomalies(
    db, user_id, tool_input, as_of, current_user
):
    result = detect_spending_anomalies(db, user_id, as_of=as_of)

    chips = [
        _chip(
            "Anomalies found",
            str(len(result.anomalies)),
            kind="text",
            tone="warning" if result.anomalies else "positive",
        ),
    ]

    # Distinct anomalies (different transactions/dates) can share the
    # same title -- e.g. several separate near-daily "possible
    # duplicate charge" incidents for the same merchant. Each is a
    # real, distinct signal in `result.anomalies` (nothing here hides
    # or discards data), but showing more than one identically-titled
    # card adds no new information and looks like the same signal
    # repeated. Cap key cards to one per distinct title.
    seen_titles: set[str] = set()

    for anomaly in result.anomalies:
        if anomaly.title in seen_titles:
            continue

        seen_titles.add(anomaly.title)
        chips.append(
            _chip(
                anomaly.title,
                _currency(anomaly.current_amount_cents),
                tone="danger" if anomaly.severity == "high" else "warning",
            )
        )

        if len(seen_titles) >= 3:
            break

    return (result, chips, None, result.data_quality_note)


_TOOL_HANDLERS = {
    "get_safe_to_spend": _handle_safe_to_spend,
    "simulate_major_purchase": _handle_major_purchase,
    "run_what_if": _handle_what_if,
    "compare_purchase_scenarios": _handle_compare_scenarios,
    "run_stress_test": _handle_stress_test,
    "check_goal_conflicts": _handle_goal_conflicts,
    "get_goal_intelligence": _handle_goal_intelligence,
    "buy_now_vs_wait": _handle_buy_now_vs_wait,
    "get_financial_resilience": _handle_financial_resilience,
    "get_cash_flow_forecast": _handle_cash_flow_forecast,
    "get_monthly_insights": _handle_monthly_insights,
    "get_recommendations": _handle_recommendations,
    "get_recurring_intelligence": _handle_recurring_intelligence,
    "get_spending_anomalies": _handle_spending_anomalies,
}


def _build_system_prompt(db: Session, user_id: int, as_of: date) -> str:
    goals = list(
        db.scalars(
            select(SavingsGoal).where(SavingsGoal.user_id == user_id)
        ).all()
    )

    goal_lines = [
        (
            f"- {g.name}: saved {_currency(g.saved_cents)} of "
            f"{_currency(g.target_cents)}"
            + (
                f", target date {g.target_date.isoformat()}"
                if g.target_date
                else ", no target date"
            )
        )
        for g in goals
    ] or ["- (no savings goals yet)"]

    plaid_connected = (
        db.scalar(
            select(func.count())
            .select_from(PlaidItem)
            .where(
                PlaidItem.user_id == user_id,
                PlaidItem.status == "active",
            )
        )
        or 0
    )

    return (
        "You are Discero's financial copilot. You answer questions "
        "about the CURRENT user's real Discero data using the "
        "provided tools.\n\n"
        "Rules:\n"
        "- NEVER invent a dollar amount, date, percentage, or any "
        "financial figure. Every number in your final answer must "
        "come from a tool result you were shown, or from the facts "
        "below.\n"
        "- All request fields ending in _cents must be integer "
        "CENTS (multiply a dollar amount by 100).\n"
        "- If a required amount, date, or goal is missing and can't "
        "be inferred from the conversation, call "
        "request_clarification instead of guessing.\n"
        "- For questions unrelated to the user's finances, or "
        "financial questions Discero has no capability to "
        "analyze, call decline_out_of_scope.\n"
        "- Resolve follow-up questions (e.g. \"what about $3,000?\", "
        "\"why?\", \"which goal?\") against the immediately "
        "preceding tool call in this conversation when unambiguous.\n"
        "- When a result involves risk or a tradeoff, name the "
        "single strongest factor driving it.\n"
        "- If a tool's confidence score is low, or the facts below "
        "show little transaction/account history, say so "
        "explicitly.\n"
        "- Never invent a recurring-bill change, duplicate "
        "subscription, missing payment, or spending anomaly. Only "
        "report ones present in a tool result -- if a tool returns no "
        "anomalies, say clearly that nothing unusual was found.\n"
        "- Never call a recurring payment 'cancelled' -- if it's "
        "overdue, say Discero hasn't seen the expected payment yet.\n"
        "- Keep prose short: a few sentences per section, no "
        "filler.\n\n"
        f"Today's date: {as_of.isoformat()}\n"
        f"Bank accounts connected via Plaid: {plaid_connected}\n"
        "Active savings goals:\n" + "\n".join(goal_lines)
    )


def _first_tool_use(response):
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return block
    return None


def _extract_text(response) -> str:
    parts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text" and block.text
    ]
    return " ".join(p.strip() for p in parts).strip()


def _extract_intent(tool_input: dict) -> str | None:
    """Bounded, enum-constrained scenario label -- never free text."""
    value = tool_input.get("scenario_type")
    return value if isinstance(value, str) else None


def _timed_model_call(client: CopilotClient, **kwargs):
    """Runs a DECIDE/NARRATE call, timing it and classifying failure.

    Returns (response_or_None, latency_ms, error_code_or_None). Never
    raises -- any provider/network/timeout exception is caught and
    classified into a stable error code so callers can audit it
    without ever surfacing a stack trace to the user.
    """
    start = time.monotonic()

    try:
        response = client.call(**kwargs)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return None, latency_ms, copilot_audit.classify_provider_error(exc)

    latency_ms = int((time.monotonic() - start) * 1000)
    return response, latency_ms, None


def _narrate(
    client: CopilotClient,
    system: str,
    history: list[dict],
    decision,
    tool_use,
    result: BaseModel,
    *,
    db: Session,
    user_id: int,
    request_id: str,
) -> dict:
    followup_messages = history + [
        {"role": "assistant", "content": decision.content},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result.model_dump_json(),
                }
            ],
        },
    ]

    response, latency_ms, error_code = _timed_model_call(
        client,
        system=system,
        messages=followup_messages,
        tools=[_NARRATION_TOOL],
        tool_choice={
            "type": "tool",
            "name": "present_financial_answer",
        },
    )

    if response is None:
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="provider_failure",
            success=False,
            error_code=error_code,
            latency_ms=latency_ms,
            model=client.model,
            metadata={"stage": "narrate"},
        )
        return {}

    narrate_use = _first_tool_use(response)

    if narrate_use is None or narrate_use.name != "present_financial_answer":
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="provider_failure",
            success=False,
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            latency_ms=latency_ms,
            model=client.model,
            metadata={"stage": "narrate"},
        )
        return {}

    return narrate_use.input or {}


def _run_free_mode(
    db: Session,
    user_id: int,
    current_user: User,
    messages: list[CopilotMessageIn],
    as_of: date,
    *,
    request_id: str,
) -> CopilotResponseOut:
    """Deterministic, zero-cost fallback -- see copilot_free_mode."""
    resolution = copilot_free_mode.resolve_intent(messages, as_of)

    if resolution is None:
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="free",
            event_type="answer",
            success=True,
            tool_call_count=0,
            response_kind="out_of_scope",
            provenance="deterministic",
        )
        return CopilotResponseOut(
            kind="out_of_scope",
            answer=copilot_free_mode.CAPABILITY_EXPLANATION,
            provenance="deterministic",
        )

    if isinstance(resolution, copilot_free_mode.Clarify):
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="free",
            event_type="clarification",
            success=True,
            tool_call_count=0,
            response_kind="clarifying_question",
            provenance="deterministic",
        )
        return CopilotResponseOut(
            kind="clarifying_question",
            clarifying_question=resolution.question,
            clarifying_options=resolution.options,
            provenance="deterministic",
        )

    handler = _TOOL_HANDLERS.get(resolution.tool_name)

    if handler is None:
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="free",
            event_type="tool_failure",
            success=False,
            error_code=copilot_audit.TOOL_NOT_REGISTERED,
            tool_name=resolution.tool_name,
            tool_call_count=1,
            response_kind="answer",
            provenance="deterministic",
        )
        return CopilotResponseOut(
            kind="answer",
            answer=_FALLBACK_ANSWER,
            provenance="deterministic",
        )

    tool_start = time.monotonic()

    try:
        result, chips, confidence, low_data_warning = handler(
            db, user_id, resolution.tool_input, as_of, current_user
        )
    except (ValidationError, ValueError) as exc:
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="free",
            event_type="tool_failure",
            success=False,
            error_code=copilot_audit.TOOL_VALIDATION_FAILED,
            tool_name=resolution.tool_name,
            latency_ms=int((time.monotonic() - tool_start) * 1000),
            tool_call_count=1,
            response_kind="clarifying_question",
            provenance="deterministic",
            intent=_extract_intent(resolution.tool_input),
        )
        return CopilotResponseOut(
            kind="clarifying_question",
            clarifying_question=(
                "I need a bit more detail to run that precisely "
                f"({exc}). Could you clarify the amount or date?"
            ),
            provenance="deterministic",
        )

    tool_latency_ms = int((time.monotonic() - tool_start) * 1000)

    answer, why, what_this_means, actions = (
        copilot_free_mode.deterministic_narration(
            resolution.tool_name, result, resolution.emphasize
        )
    )

    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        mode="free",
        event_type="tool_success",
        success=True,
        tool_name=resolution.tool_name,
        latency_ms=tool_latency_ms,
        tool_call_count=1,
        response_kind="answer",
        provenance="deterministic",
        intent=_extract_intent(resolution.tool_input),
    )

    return CopilotResponseOut(
        kind="answer",
        answer=answer,
        why=why,
        what_this_means=what_this_means,
        key_numbers=chips,
        suggested_actions=actions[:2],
        tool_used=_TOOL_LABELS.get(resolution.tool_name, resolution.tool_name),
        confidence=confidence,
        low_data_warning=low_data_warning,
        provenance="deterministic",
    )


def run_copilot_turn(
    db: Session,
    user_id: int,
    current_user: User,
    messages: list[CopilotMessageIn],
    client: CopilotClient,
    *,
    as_of: date | None = None,
    request_id: str | None = None,
) -> CopilotResponseOut:
    calculation_date = as_of or date.today()
    request_id = request_id or copilot_audit.new_request_id()

    if not client.enabled:
        return _run_free_mode(
            db,
            user_id,
            current_user,
            messages,
            calculation_date,
            request_id=request_id,
        )

    history = [
        {"role": m.role, "content": m.content}
        for m in messages[-_MAX_HISTORY_MESSAGES:]
    ]

    system = _build_system_prompt(db, user_id, calculation_date)

    decision, decide_latency_ms, decide_error_code = _timed_model_call(
        client, system=system, messages=history, tools=_TOOLS
    )

    if decision is None:
        # Anthropic unreachable/timed out/rate-limited -- fall back to
        # the free deterministic pipeline instead of failing the
        # request. Never fabricates a financial answer either way.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="provider_failure",
            success=False,
            error_code=decide_error_code,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            metadata={"stage": "decide"},
        )
        return _run_free_mode(
            db,
            user_id,
            current_user,
            messages,
            calculation_date,
            request_id=request_id,
        )

    tool_use = _first_tool_use(decision)

    if tool_use is None:
        text = _extract_text(decision)
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="answer",
            success=True,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="answer",
            provenance="ai_enhanced",
        )
        return CopilotResponseOut(
            kind="answer",
            answer=text or _FALLBACK_ANSWER,
            provenance="ai_enhanced",
        )

    name = tool_use.name
    tool_input = tool_use.input or {}

    if name == "request_clarification":
        question = str(tool_input.get("question", "")).strip()
        raw_options = tool_input.get("options") or []
        options = [str(o) for o in raw_options][:4] or None

        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="clarification",
            success=True,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="clarifying_question",
            provenance="ai_enhanced",
        )
        return CopilotResponseOut(
            kind="clarifying_question",
            clarifying_question=question or "Could you clarify that?",
            clarifying_options=options,
            provenance="ai_enhanced",
        )

    if name == "decline_out_of_scope":
        reason = str(tool_input.get("reason", "")).strip()
        category = tool_input.get("category")

        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="answer",
            success=True,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="out_of_scope",
            provenance="ai_enhanced",
            intent=category if isinstance(category, str) else None,
        )
        return CopilotResponseOut(
            kind="out_of_scope",
            answer=reason or _SCOPE_FALLBACK,
            provenance="ai_enhanced",
        )

    handler = _TOOL_HANDLERS.get(name)

    if handler is None:
        # The model named a tool outside our registry -- never
        # executed, only ever answered from the fixed fallback text.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="safety_rejection",
            success=False,
            error_code=copilot_audit.TOOL_NOT_REGISTERED,
            tool_name=name,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=1,
            response_kind="answer",
            provenance="ai_enhanced",
        )
        return CopilotResponseOut(
            kind="answer",
            answer=_FALLBACK_ANSWER,
            provenance="ai_enhanced",
        )

    tool_start = time.monotonic()

    try:
        result, chips, confidence, low_data_warning = handler(
            db, user_id, tool_input, calculation_date, current_user
        )
    except (ValidationError, ValueError) as exc:
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode="anthropic",
            event_type="tool_failure",
            success=False,
            error_code=copilot_audit.TOOL_VALIDATION_FAILED,
            tool_name=name,
            latency_ms=int((time.monotonic() - tool_start) * 1000),
            model=client.model,
            tool_call_count=1,
            response_kind="clarifying_question",
            provenance="ai_enhanced",
            intent=_extract_intent(tool_input),
        )
        return CopilotResponseOut(
            kind="clarifying_question",
            clarifying_question=(
                "I need a bit more detail to run that precisely "
                f"({exc}). Could you clarify the amount or date?"
            ),
            provenance="ai_enhanced",
        )

    tool_latency_ms = int((time.monotonic() - tool_start) * 1000)

    narration = _narrate(
        client,
        system,
        history,
        decision,
        tool_use,
        result,
        db=db,
        user_id=user_id,
        request_id=request_id,
    )

    if narration:
        answer = narration.get("answer") or _FALLBACK_ANSWER
        why = narration.get("why")
        what_this_means = narration.get("what_this_means")
        actions = list(narration.get("suggested_actions") or [])[:2]
        provenance = "ai_enhanced"
    else:
        # Narration call failed -- we already have the REAL tool
        # result, so fall back to the same deterministic templates
        # free mode uses rather than failing the request.
        answer, why, what_this_means, actions = (
            copilot_free_mode.deterministic_narration(name, result)
        )
        provenance = "deterministic"

    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        mode="anthropic",
        event_type="tool_success",
        success=True,
        tool_name=name,
        latency_ms=tool_latency_ms,
        model=client.model,
        tool_call_count=1,
        response_kind="answer",
        provenance=provenance,
        intent=_extract_intent(tool_input),
    )

    return CopilotResponseOut(
        kind="answer",
        answer=answer,
        why=why,
        what_this_means=what_this_means,
        key_numbers=chips,
        suggested_actions=actions,
        tool_used=_TOOL_LABELS.get(name, name),
        confidence=confidence,
        low_data_warning=low_data_warning,
        provenance=provenance,
    )
