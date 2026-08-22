"""Discero AI Copilot orchestration.

Design principle: the LLM never invents a financial number. Each user turn
runs at most two provider calls, both via tool-use (structured JSON, not
free text):

1. DECIDE -- the provider picks exactly one of: a real deterministic
   financial tool (mirroring an existing service, e.g.
   `simulate_major_purchase`), `request_clarification` (missing/ambiguous
   required parameter), or `decline_out_of_scope` (non-financial or
   unsupported question). tool_choice="any" forces this choice every
   turn -- the provider can never skip picking a tool and return bare
   prose instead, closing off "the model just talked" as a hidden fourth
   routing path.
2. NARRATE -- only if a financial tool was used. The provider is shown
   that tool's REAL result JSON and must call `present_financial_answer`
   to produce prose. The numeric "key numbers" chips shown to the user
   are built directly from the real result by plain Python in this
   module, never parsed out of the model's prose -- so a hallucinated
   number in the narration step can never reach a metric chip.

Every routing decision, whether from a provider's DECIDE call or from
`copilot_free_mode`'s deterministic router, resolves to one of the same
three outcomes: `copilot_free_mode.RouteKind` ("tool" / "clarification" /
"unsupported"). Whenever a provider is reachable but returns something
unusable for that vocabulary -- no tool call at all, or a tool name
outside the registry -- orchestration falls back to
`copilot_free_mode.resolve_intent` on the real message rather than
guessing or returning a static reply, the same deterministic router
free mode itself uses when no provider is configured.

Conversation memory is just the full message history resent each turn
(the provider's native multi-turn context), so follow-ups like "what
about $3,000?" resolve for free with no bespoke intent/slot-filling
code.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from typing import Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PlaidItem, SavingsGoal, User
from app.schemas import (
    BuyNowVsWaitRequest,
    CopilotConfidenceOut,
    CopilotDecisionCalibrationOut,
    CopilotDecisionReviewOut,
    CopilotMessageIn,
    CopilotMetricOut,
    CopilotRecentDecisionOut,
    CopilotRecentDecisionsOut,
    CopilotResponseOut,
    CopilotReviewItemOut,
    CopilotSafeToSpendRequest,
    FinancialStressTestRequest,
    GoalConflictDetectionRequest,
    MajorPurchaseSimulationRequest,
    ScenarioComparisonRequest,
    WhatIfComparisonRequest,
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
from app.services import (
    copilot_audit,
    copilot_free_mode,
    copilot_observability,
    decision_calibration_service,
    decision_data_freshness_service,
    decision_history_service,
    decision_memory_service,
    decision_review_service,
)
from app.services.recommendation_service import evaluate_recommendations
from app.services.recurring_intelligence_service import (
    evaluate_recurring_intelligence,
)
from app.services.safe_to_spend_service import (
    calculate_current_safe_to_spend,
)
from app.services.scenario_comparison_service import (
    compare_major_purchase_scenarios,
)
from app.services.spending_anomaly_service import detect_spending_anomalies
from app.services.what_if_comparison_service import compare_what_if_scenarios
from app.services.what_if_service import simulate_what_if

logger = logging.getLogger(__name__)

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

# Deliberately static and DB-free (no goal list, no Plaid lookup) --
# unlike _build_system_prompt (used only for DECIDE now), a NARRATE
# call already has everything it needs in the normalized tool result
# handed to it, so building this costs nothing per turn.
_NARRATE_SYSTEM_PROMPT = (
    "You narrate one already-computed Discero financial result for the "
    "user, using ONLY the fields you were shown. The tool result has "
    "already been normalized for display -- every dollar figure is a "
    "formatted string (e.g. \"$900.00\"), never raw cents. Use those "
    "figures exactly as given; never reconstruct, rescale, recalculate, "
    "or relabel a number yourself, and never append a unit word (like "
    "\"cents\") to a figure that already has one. Do not perform "
    "arithmetic on any figure you were shown (no adding, subtracting, "
    "or combining two numbers into a new one, e.g. a \"surplus\" or "
    "\"total\" not already present as its own field) -- if a figure "
    "you need isn't in the payload, don't state it. Never write a "
    "dollar amount that does not appear character-for-character "
    "somewhere in the payload you were shown. Never state a status "
    "(e.g. on track/at risk) stronger than the result's own status "
    "field, and never claim a date target is met unless the result's "
    "own fields say so. If the result has a `selected_goal`, your "
    "answer is about that goal specifically, using its own fields "
    "(status, target date, projected completion, required/allocated "
    "monthly, gap) -- a `portfolio` figure in the same payload (total "
    "monthly capacity, remaining headroom, total required, most "
    "urgent goal) is background context only, never a substitute or "
    "blend for the selected goal's own numbers, and 'capacity' and "
    "'headroom' are two different figures that must never be called "
    "each other. Ground any recommendation in the result's own "
    "`recommended_action`/`explanation` fields rather than inventing "
    "advice. If the result is about the user's decision history/"
    "calibration and its status/calibration_label is insufficient or "
    "empty, say so plainly -- never generalize from too little history "
    "(e.g. never say 'your decisions are usually accurate' from one "
    "tracked outcome). If the result has a `freshness_status`, never "
    "call the data current/up to date unless that field is literally "
    "'current' -- for 'stale' or 'unavailable', say so plainly. Keep "
    "it to a few short sentences, no filler."
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
    "ahead": "positive",
    "reduced": "warning",
    "delayed": "warning",
    "at_risk": "warning",
    "unfunded": "danger",
    "not_feasible": "danger",
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
    "current": "positive",
    "recent": "positive",
    "stale": "warning",
    "unavailable": "neutral",
}


def _tone(status: str) -> str:
    return _STATUS_TONE.get(status, "neutral")


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


class _TrustedFigures:
    """Accumulates the currency/percent strings _normalize_for_narration
    itself produced from real numeric fields during one payload build.

    This is the fix for a real gap: checking a narrated figure against
    `json.dumps(payload)` as one flat string cannot distinguish a
    number *_normalize_for_narration formatted from a real field* from
    the same-looking substring sitting inside an arbitrary, attacker-
    influenced text field the payload also carries (a goal name, a
    decision title) -- e.g. a goal named "Save 100% for retirement"
    would make a hallucinated "confidence is 100%" pass a naive
    substring/value check even though no real field says 100%. Tracked
    at formatting time, not by scanning the serialized payload
    afterward, so only genuinely real figures ever count as grounding
    evidence.
    """

    def __init__(self) -> None:
        self.amounts: set[str] = set()
        self.percents: set[float] = set()


def _normalize_for_narration(value, trusted: _TrustedFigures):
    """Recursively rewrites a deterministic tool result into a
    narration-safe payload, so the provider never has to convert a
    raw unit itself -- the exact class of bug that produced malformed
    output like "$90,000.00 cents" in production.

    Generic suffix rules only (no per-tool special-casing):
      *_cents   -> formatted currency string, key suffix dropped
                   (required_monthly_cents -> required_monthly)
      *_percent -> formatted percent string, key unchanged
      *_days    -> "N day(s)" string, key unchanged
      *_months  -> "N month(s)" string, key unchanged
    Anything else (dates, which are already ISO strings from
    model_dump(mode="json"), enums, ids, booleans, plain scores, and
    free text like names/titles) is passed through unchanged -- never
    invented, never guessed, and never treated as grounding evidence.
    """
    if isinstance(value, dict):
        normalized = {}
        for key, val in value.items():
            if key.endswith("_cents") and isinstance(val, (int, type(None))):
                formatted = _currency(val) if val is not None else None
                normalized[key[: -len("_cents")]] = formatted
                if formatted is not None:
                    trusted.amounts.add(formatted)
            elif key.endswith("_percent") and isinstance(val, (int, float)):
                formatted = _percent(val)
                normalized[key] = formatted
                trusted.percents.add(float(val))
            elif (
                key.endswith("_days") or key.endswith("_months")
            ) and isinstance(val, int):
                unit = "day" if key.endswith("_days") else "month"
                normalized[key] = f"{val} {unit}{'s' if val != 1 else ''}"
            else:
                normalized[key] = _normalize_for_narration(val, trusted)
        return normalized
    if isinstance(value, list):
        return [_normalize_for_narration(item, trusted) for item in value]
    return value


def _goal_intelligence_narration_payload(
    result: BaseModel, target_goal_name: str | None
) -> tuple[dict, _TrustedFigures]:
    """Scopes goal-intelligence narration so a portfolio-wide figure can
    never be mistaken for the specifically-named goal the user asked
    about (production symptom: goal-scoped "$900" vs. portfolio-scoped
    "$1,225" both narrated under one ambiguous "required monthly").
    """
    trusted = _TrustedFigures()
    dumped = result.model_dump(mode="json")
    goals = dumped.pop("goals", [])
    payload = {"portfolio": _normalize_for_narration(dumped, trusted)}

    selected = None
    if target_goal_name:
        selected = next(
            (g for g in goals if g.get("name") == target_goal_name), None
        )

    if selected is not None:
        payload["selected_goal"] = _normalize_for_narration(
            selected, trusted
        )
    else:
        payload["goals"] = [
            _normalize_for_narration(g, trusted) for g in goals
        ]

    return payload, trusted


def _cash_flow_forecast_narration_payload(
    result: BaseModel,
) -> tuple[dict, _TrustedFigures]:
    """Adds the same "monthly cash flow" figure the response's own
    chips already show (expected_income_cents - upcoming_bills_cents,
    computed in _handle_cash_flow_forecast) -- CashFlowForecastOut
    itself has no such field, so without this the provider is shown
    only income and bills separately and left to derive a "surplus"
    itself (production symptom: a narrated total that matched no real
    field). Giving it the real, correct figure removes the reason to
    compute one; _narration_is_grounded below still catches it even if
    it does anyway.
    """
    trusted = _TrustedFigures()
    dumped = result.model_dump(mode="json")
    monthly_flow_cents = (
        dumped["expected_income_cents"] - dumped["upcoming_bills_cents"]
    )
    payload = _normalize_for_narration(dumped, trusted)
    formatted_flow = _currency(monthly_flow_cents)
    payload["monthly_cash_flow"] = formatted_flow
    trusted.amounts.add(formatted_flow)
    return payload, trusted


def _narration_payload(
    tool_name: str, result: BaseModel, target_goal_name: str | None = None
) -> tuple[dict, _TrustedFigures]:
    """The ONLY data a NARRATE call ever sees for a tool result -- never
    the raw model_dump_json(), which put unconverted *_cents integers
    directly in front of the provider. Also returns the real figures
    formatted along the way, for _narration_is_grounded to check
    against (see _TrustedFigures).
    """
    if tool_name == "get_goal_intelligence":
        return _goal_intelligence_narration_payload(
            result, target_goal_name
        )
    if tool_name == "get_cash_flow_forecast":
        return _cash_flow_forecast_narration_payload(result)
    trusted = _TrustedFigures()
    payload = _normalize_for_narration(result.model_dump(mode="json"), trusted)
    return payload, trusted


_MONEY_IN_TEXT_RE = re.compile(r"\$-?\d[\d,]*(?:\.\d{1,2})?")
# Matched by numeric value, not verbatim substring (unlike
# _MONEY_IN_TEXT_RE) -- the payload always formats a percent with one
# decimal place (_percent() -> "94.0%"), but real, ungrounded narration
# rounding it to "94%" is not a hallucination and must not be treated
# as one. The sign is captured (and fed through float(), which parses
# a leading +/- itself) so "-2.3%" in the payload can never ground a
# narration that flips it to "+2.3%" -- comparing by magnitude alone
# would treat those as the same number. `(?<!\d)` keeps a hyphen
# inside a range like "3-5%" from being misread as a minus sign: it
# only allows a leading sign when the character before it isn't itself
# a digit.
_PERCENT_IN_TEXT_RE = re.compile(r"(?<!\d)([+-]?\d{1,3}(?:\.\d+)?)\s*%")


def _narration_is_grounded(
    narration: dict, trusted: _TrustedFigures
) -> bool:
    """Financial Authority Rule, enforced in code rather than trusted to
    prompt wording alone: every dollar figure and percentage the
    provider states must be traceable to a real numeric field in the
    deterministic payload it was shown -- never a number it computed,
    rounded to a different scale, invented itself (e.g. a hallucinated
    "100% confidence" when the real figure is lower), or laundered
    through an unrelated text field that happens to contain a similar-
    looking substring (e.g. a goal literally named "Save 100% of my
    bonus" -- see _TrustedFigures). Production symptom this catches: a
    cash-flow narration stating a "surplus" figure that matched no
    field in the tool result -- the provider had done its own
    arithmetic on the real numbers it saw. A smaller/faster model (this
    project also runs on Groq) is more likely to do this than a larger
    one, so this cannot be prompt-only.

    Checked against `trusted` -- the figures _normalize_for_narration
    itself formatted from real numeric fields while building this
    payload -- never against the payload's serialized text, which also
    contains arbitrary user-controlled strings (names, titles) that can
    coincidentally contain a dollar-or-percent-shaped substring.
    """
    narration_text = " ".join(
        str(narration.get(field) or "")
        for field in ("answer", "why", "what_this_means")
    )
    narration_text += " " + " ".join(
        str(a) for a in (narration.get("suggested_actions") or [])
    )

    amounts_grounded = all(
        amount in trusted.amounts
        for amount in _MONEY_IN_TEXT_RE.findall(narration_text)
    )

    percents_grounded = all(
        float(value) in trusted.percents
        for value in _PERCENT_IN_TEXT_RE.findall(narration_text)
    )

    return amounts_grounded and percents_grounded


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


class CopilotModelProvider(Protocol):
    """Structural contract DECIDE/NARRATE orchestration depends on.

    `CopilotClient` (Anthropic, below) and
    `app.services.copilot_groq_client.GroqCopilotClient` both satisfy
    this without inheriting from it -- orchestration only ever depends
    on this shape, never on a specific provider.
    """

    provider_name: str
    model: str

    @property
    def enabled(self) -> bool: ...

    def call(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
    ): ...


class CopilotClient:
    """Thin Anthropic wrapper. Network call isolated for testability."""

    provider_name = "anthropic"

    def __init__(
        self,
        api_key: str | None,
        model: str = "claude-sonnet-4-6",
        timeout: float = 20.0,
        max_retries: int = 1,
    ) -> None:
        self.api_key = api_key
        self.model = model
        # Bounds how long a single DECIDE/NARRATE call can hang -- a
        # synchronous request endpoint must never wait on the SDK's
        # much longer default. max_retries caps the SDK's own
        # transient-error retry (its default is 2) so a flaky
        # provider can't silently multiply a turn's latency/cost.
        self.timeout = timeout
        self.max_retries = max_retries

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
            max_retries=self.max_retries,
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
        "input_schema": _tool_schema(CopilotSafeToSpendRequest),
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
        "name": "compare_what_if_scenarios",
        "description": (
            "Compare TWO OR THREE alternative SUSTAINED monthly "
            "changes side by side -- e.g. a $100/month rent increase "
            "versus a $300/month rent increase, or two different "
            "recurring expense/income/savings changes -- and "
            "recommend the better outcome. Use whenever the user "
            "asks to 'compare' or asks 'X versus Y' about two or "
            "more recurring/monthly amounts. Each scenario needs its "
            "own short, distinct `label` (e.g. \"$100 increase\", "
            "\"$300 increase\") and its own scenario_type/amount, "
            "exactly like run_what_if's fields but one per scenario. "
            "Do NOT use run_what_if for a comparison question -- it "
            "only simulates ONE scenario and would silently drop the "
            "others. All *_cents fields must be in CENTS."
        ),
        "input_schema": _tool_schema(WhatIfComparisonRequest),
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
            "goal's required vs. currently affordable monthly "
            "contribution, on-track/ahead/at-risk/not-feasible status, "
            "a realistic projected completion date and delay, the "
            "deterministic key_driver for why a goal is at risk, and "
            "its recommended_action plus up to two alternative_actions "
            "(e.g. increase this goal's allocation by the exact gap, or "
            "move its target date). Use for 'which goal is most "
            "urgent', 'which goal is causing my shortfall', 'how much "
            "should I save for this goal', 'when can I realistically "
            "finish this goal', 'what is the smallest change that gets "
            "this goal back on track', or 'what if I move this goal's "
            "target date' questions. Always narrate recommended_action "
            "and key_driver from this result verbatim in meaning -- "
            "never invent a different dollar amount, date, or reason "
            "yourself. Omit monthly_capacity_cents if not stated by "
            "the user; it will be estimated from real income history "
            "-- if you omit it, explicitly tell the user the capacity "
            "figure was estimated from their financial data and that "
            "they can state a specific monthly amount instead. If the "
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
        "name": "get_decision_memory",
        "description": (
            "Get what Discero has learned from the user's own saved "
            "Decision Lab history: how many decisions they've saved, "
            "acted on, tracked outcomes for, recent usage patterns, and "
            "how many still need follow-up. Use for 'what decisions "
            "have I analyzed', 'what does Discero know from my "
            "decision history', or 'what have you learned from my "
            "decisions' questions. This is a summary of PAST saved "
            "decisions -- never invent a pattern or count not present "
            "in the result."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_decision_calibration",
        "description": (
            "Get whether the user has enough tracked outcome history "
            "for a reliable calibration pattern, and if so whether "
            "their decisions have run mostly conservative, mostly "
            "optimistic, or balanced relative to what actually "
            "happened. Use for 'do I have enough outcome history for "
            "calibration', 'how accurate have my decisions been', or "
            "'am I calibrated' questions. If the result's "
            "calibration_label is 'insufficient_data', say so plainly "
            "-- never generalize from a single observation or claim "
            "your decisions are 'usually' anything."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_decisions_needing_review",
        "description": (
            "Get which of the user's saved decisions are due for "
            "review -- saved but never marked acted-on/dismissed, "
            "acted on but never outcome-checked, or due for a "
            "recheck. Use for 'which decisions need follow-up', "
            "'what decisions need my attention', or 'what's overdue "
            "for review' questions. Never invent a reason a decision "
            "needs review beyond its own review_reason_text."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_decisions",
        "description": (
            "Get the user's most recently saved Decision Lab "
            "analyses (title, type, date, status). Use for 'what "
            "decisions have I analyzed recently', 'which decisions "
            "have I saved', or 'what have I looked at lately' "
            "questions."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_data_freshness",
        "description": (
            "Get how current the user's underlying transaction/account "
            "data is -- freshness status (current/recent/stale/"
            "unavailable), days since the latest transaction, and days "
            "since the last account sync. Use for 'how current is my "
            "data', 'how fresh is my data', or 'is my data up to date' "
            "questions. Never state or imply the data is current unless "
            "freshness_status is 'current' -- if it is 'stale' or "
            "'unavailable', say so plainly using the result's own "
            "notices."
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
                    "0-2 short, concrete next steps phrased as things "
                    "the user could ask next. Only reference a goal, "
                    "amount, or account that appears in the tool result "
                    "or the facts you were given -- never suggest a "
                    "goal the user doesn't have (e.g. 'retirement') or "
                    "a Discero capability that doesn't exist."
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
    "compare_what_if_scenarios": "What-If Comparison",
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
    "get_decision_memory": "Decision Memory",
    "get_decision_calibration": "Decision Calibration",
    "get_decisions_needing_review": "Decisions Needing Review",
    "get_recent_decisions": "Recent Decisions",
    "get_data_freshness": "Data Freshness",
}

_RECOMMENDATION_SEVERITY_TONE = {
    "critical": "danger",
    "warning": "warning",
    "opportunity": "neutral",
    "positive": "positive",
    "informational": "neutral",
}


def _handle_safe_to_spend(db, user_id, tool_input, as_of, current_user):
    # Uses the compact CopilotSafeToSpendRequest, not the full
    # SafeToSpendRequest -- the LLM can adjust reserve/essential/
    # horizon, but can never set include_projected_income or
    # include_goal_reserve. calculate_current_safe_to_spend always
    # enforces both True, so this can never diverge from the Overview
    # dashboard's CURRENT Safe-to-Spend figure.
    payload = CopilotSafeToSpendRequest(**tool_input)
    result = calculate_current_safe_to_spend(
        db,
        user_id,
        safety_reserve_cents=payload.safety_reserve_cents,
        essential_spending_cents=payload.essential_spending_cents,
        horizon_days=payload.horizon_days,
        as_of=as_of,
    )

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


def _handle_compare_what_if_scenarios(
    db, user_id, tool_input, as_of, current_user
):
    payload = WhatIfComparisonRequest(**tool_input)
    result = compare_what_if_scenarios(db, user_id, payload, as_of=as_of)

    recommended_label = (
        "Tie" if result.is_tie else (result.recommended_label or "Tie")
    )

    chips = [
        _chip(
            "Recommended", recommended_label, kind="text", tone="positive"
        ),
    ]

    for scenario in result.scenarios:
        chips.append(
            _chip(
                f"{scenario.label} safe-to-spend",
                _currency(scenario.safe_to_spend_cents),
                tone="danger" if scenario.shortfall_cents else "positive",
            )
        )
        chips.append(
            _chip(
                f"{scenario.label} shortfall",
                _currency(scenario.shortfall_cents),
                tone="danger" if scenario.shortfall_cents else "positive",
            )
        )

    confidence_score = min(
        scenario.confidence_score for scenario in result.scenarios
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


def _goal_intelligence_selected_chips(goal, result) -> list[CopilotMetricOut]:
    """Named-goal card: the selected goal's own fields lead. Portfolio
    figures are appended last as clearly-labeled secondary context,
    never the reverse -- this is the fix for the production symptom
    where a named "Emergency Fund" question surfaced a dominant
    portfolio-wide "Most urgent: New Laptop" chip instead of Emergency
    Fund's own status/dates/amounts.
    """
    chips = [
        _chip(
            "Status",
            goal.status.replace("_", " ").title(),
            kind="text",
            tone=_tone(goal.status),
        ),
    ]

    if goal.target_date:
        chips.append(
            _chip(
                "Target date",
                goal.target_date.isoformat(),
                kind="text",
                tone="neutral",
            )
        )

    if goal.status != "completed" and goal.projected_completion_date:
        on_time = (
            goal.target_date is None
            or goal.projected_completion_date <= goal.target_date
        )
        chips.append(
            _chip(
                "Projected completion",
                goal.projected_completion_date.isoformat(),
                kind="text",
                tone="positive" if on_time else "warning",
            )
        )

    chips.append(
        _chip(
            "Required monthly",
            _currency(goal.required_monthly_cents),
            tone="neutral",
        )
    )
    chips.append(
        _chip(
            "Allocated monthly",
            _currency(goal.allocated_monthly_cents),
            tone="neutral",
        )
    )
    chips.append(
        _chip(
            "Monthly gap",
            _currency(goal.monthly_gap_cents),
            tone="danger" if goal.monthly_gap_cents else "positive",
        )
    )

    # Secondary portfolio context -- distinctly labeled so it can never
    # be mistaken for a figure scoped to this goal (PHASE 12/13:
    # "capacity" and "headroom" are never the same number).
    chips.append(
        _chip(
            "Portfolio capacity",
            _currency(result.total_capacity_cents),
            tone="neutral",
        )
    )
    chips.append(
        _chip(
            "Remaining headroom",
            _currency(result.monthly_headroom_cents),
            tone="neutral",
        )
    )
    chips.append(
        _chip(
            "Confidence",
            f"{round(goal.confidence_score)}%",
            kind="score",
            tone=_tone(_confidence_level(goal.confidence_score)),
        )
    )

    return chips


def _goal_intelligence_portfolio_chips(
    result, capacity_source: str
) -> list[CopilotMetricOut]:
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
            "Remaining headroom",
            _currency(result.monthly_headroom_cents),
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

    return chips


def _handle_goal_intelligence(db, user_id, tool_input, as_of, current_user):
    tool_input = dict(tool_input)
    # Injected only by _resolve_deterministic (Path A) when the router
    # already resolved a specific named goal -- never part of the
    # public tool schema a provider DECIDE call can set, and always
    # popped before any request/service call sees this dict.
    target_goal_name = tool_input.pop("_target_goal_name", None)

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

    selected = None
    if target_goal_name:
        selected = next(
            (g for g in result.goals if g.name == target_goal_name), None
        )

    if selected is not None:
        chips = _goal_intelligence_selected_chips(selected, result)
        confidence_score = selected.confidence_score
    else:
        chips = _goal_intelligence_portfolio_chips(result, capacity_source)
        confidence_score = result.confidence_score

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
        _confidence(confidence_score),
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


# Compact copilot decision-intelligence tools -- all four call an
# existing deterministic decision service directly (never a second
# HTTP round-trip into Discero's own API) and return only bounded,
# already-persisted fields. No financial calculation happens here: the
# LLM only ever sees counts, labels, and short strings already computed
# by decision_memory_service/decision_calibration_service/
# decision_review_service/decision_history_service.

_COPILOT_RECENT_DECISIONS_LIMIT = 5
_COPILOT_REVIEW_ITEMS_LIMIT = 5


def _handle_decision_memory(db, user_id, tool_input, as_of, current_user):
    result = decision_memory_service.get_decision_memory(db, user_id)

    if result.status == "no_history":
        chips = [_chip("Decisions analyzed", "0", kind="text")]
        return (result, chips, None, None)

    chips = [
        _chip(
            "Decisions analyzed",
            str(result.summary.total_saved_decisions),
            kind="text",
        ),
        _chip(
            "Acted on", str(result.summary.acted_on_count), kind="text"
        ),
        _chip(
            "Outcomes tracked",
            str(result.outcomes.total_outcome_checks),
            kind="text",
        ),
    ]
    if result.needs_follow_up_count:
        chips.append(
            _chip(
                "Needs follow-up",
                str(result.needs_follow_up_count),
                kind="text",
                tone="warning",
            )
        )

    return (result, chips, None, None)


def _handle_decision_calibration(db, user_id, tool_input, as_of, current_user):
    calibration = decision_calibration_service.get_decision_calibration(
        db, user_id
    )
    # A deliberately compact projection -- never the full metric_groups/
    # decision_types breakdown, which is sized for the Decision History
    # page, not a chat payload.
    result = CopilotDecisionCalibrationOut(
        calibration_label=calibration.calibration_label,
        tracked_decisions=calibration.tracked_decisions,
        outcome_checks=calibration.outcome_checks,
        directional_observations=calibration.directional_metrics_compared,
        favorable_count=calibration.favorable_count,
        unfavorable_count=calibration.unfavorable_count,
        favorable_rate=calibration.favorable_rate,
    )

    chips = [
        _chip(
            "Calibration",
            result.calibration_label.replace("_", " ").title(),
            kind="text",
        ),
        _chip(
            "Tracked decisions", str(result.tracked_decisions), kind="text"
        ),
        _chip("Outcome checks", str(result.outcome_checks), kind="text"),
    ]
    if result.favorable_rate is not None:
        chips.append(
            _chip(
                "Favorable rate",
                _percent(result.favorable_rate * 100),
                kind="percent",
            )
        )

    return (result, chips, None, None)


def _handle_decisions_needing_review(
    db, user_id, tool_input, as_of, current_user
):
    queue = decision_review_service.build_review_queue(db, user_id)
    bounded = queue[:_COPILOT_REVIEW_ITEMS_LIMIT]

    result = CopilotDecisionReviewOut(
        items=[
            CopilotReviewItemOut(
                decision_id=item.decision_id,
                title=item.title,
                review_reason_text=item.review_reason_text,
                age_days=item.age_days,
            )
            for item in bounded
        ],
        total_count=len(queue),
    )

    chips = [
        _chip("Decisions needing review", str(result.total_count), kind="text")
    ]
    if result.items:
        chips.append(
            _chip(
                "Most urgent", result.items[0].title, kind="text",
                tone="warning",
            )
        )

    return (result, chips, None, None)


def _handle_recent_decisions(db, user_id, tool_input, as_of, current_user):
    decisions = decision_history_service.list_decisions(
        db, user_id, limit=_COPILOT_RECENT_DECISIONS_LIMIT
    )

    result = CopilotRecentDecisionsOut(
        decisions=[
            CopilotRecentDecisionOut(
                decision_id=decision.id,
                decision_type=decision.decision_type,
                title=decision.title,
                created_at=decision.created_at,
                status=decision.status,
            )
            for decision in decisions
        ],
        total_count=len(decisions),
    )

    chips = [
        _chip("Recent decisions", str(result.total_count), kind="text")
    ]
    if result.decisions:
        chips.append(
            _chip(
                "Most recent", result.decisions[0].title, kind="text"
            )
        )

    return (result, chips, None, None)


def _handle_data_freshness(db, user_id, tool_input, as_of, current_user):
    result = decision_data_freshness_service.get_data_freshness(
        db, user_id, as_of=as_of
    )

    chips = [
        _chip(
            "Data freshness",
            result.freshness_status.title(),
            kind="text",
            tone=_tone(result.freshness_status),
        ),
    ]
    if result.days_since_latest_transaction is not None:
        chips.append(
            _chip(
                "Last transaction",
                f"{result.days_since_latest_transaction} day(s) ago",
                kind="text",
            )
        )
    if result.days_since_account_update is not None:
        chips.append(
            _chip(
                "Last account sync",
                f"{result.days_since_account_update} day(s) ago",
                kind="text",
            )
        )

    return (result, chips, None, None)


_TOOL_HANDLERS = {
    "get_safe_to_spend": _handle_safe_to_spend,
    "simulate_major_purchase": _handle_major_purchase,
    "run_what_if": _handle_what_if,
    "compare_purchase_scenarios": _handle_compare_scenarios,
    "compare_what_if_scenarios": _handle_compare_what_if_scenarios,
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
    "get_decision_memory": _handle_decision_memory,
    "get_decision_calibration": _handle_decision_calibration,
    "get_decisions_needing_review": _handle_decisions_needing_review,
    "get_recent_decisions": _handle_recent_decisions,
    "get_data_freshness": _handle_data_freshness,
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


def _extract_intent(tool_input: dict) -> str | None:
    """Bounded, enum-constrained scenario label -- never free text."""
    value = tool_input.get("scenario_type")
    return value if isinstance(value, str) else None


def _timed_model_call(client: CopilotModelProvider, **kwargs):
    """Runs a DECIDE/NARRATE call, timing it and classifying failure.

    Returns (response_or_None, latency_ms, error_code_or_None,
    usage_or_None). Never raises -- any provider/network/timeout
    exception is caught and classified into a stable error code so
    callers can audit it without ever surfacing a stack trace to the
    user. `usage` is real provider-reported token counts (see
    copilot_observability.extract_token_usage) whenever the call
    succeeded and the provider supplied them -- never estimated.
    """
    start = time.monotonic()

    try:
        response = client.call(**kwargs)
    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return (
            None,
            latency_ms,
            copilot_audit.classify_provider_error(exc),
            None,
        )

    latency_ms = int((time.monotonic() - start) * 1000)
    usage = copilot_observability.extract_token_usage(response)
    return response, latency_ms, None, usage


def _usage_metadata(usage: copilot_observability.TokenUsage | None) -> dict:
    """Bounded metadata fields for a provider call's real token usage
    and, only when both cost rates are configured, its estimated
    dollar cost -- omitted entirely (never a fabricated 0/None-typed
    entry) when usage itself is unavailable.
    """
    if usage is None:
        return {}

    fields: dict = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }

    cost = copilot_observability.estimate_cost(
        usage,
        settings.copilot_input_cost_per_million_tokens,
        settings.copilot_output_cost_per_million_tokens,
    )
    if cost is not None:
        fields["estimated_cost"] = cost

    return fields


def _log_provider_failure(
    *,
    request_id: str,
    provider: str,
    phase: str,
    error_code: str | None,
    tool_name: str | None,
    latency_ms: int,
) -> None:
    """Production-safe structured warning -- request_id/provider/phase/
    error_code/tool/latency only, never a prompt, exception body, or
    financial payload (those could leak user data into Render logs).
    """
    logger.warning(
        "copilot_provider_failure request_id=%s provider=%s phase=%s "
        "error_code=%s tool=%s latency_ms=%d",
        request_id,
        provider,
        phase,
        error_code,
        tool_name or "-",
        latency_ms,
    )


def _narrate(
    client: CopilotModelProvider,
    tool_name: str,
    current_message: str,
    tool_input: dict,
    result: BaseModel,
    *,
    target_goal_name: str | None,
    db: Session,
    user_id: int,
    request_id: str,
) -> tuple[dict, int, copilot_observability.TokenUsage | None]:
    """The turn's one optional NARRATE call (Path A only -- see
    run_copilot_turn). Never a real follow-up on a live provider
    decision: the assistant/tool_use turn below is synthesized by us,
    since the tool was already picked deterministically and no DECIDE
    call happened this turn. Plain dicts (not SDK response objects) --
    both CopilotClient (native Anthropic tool_use param shape) and
    GroqCopilotClient (dict-aware, see copilot_groq_client.py) accept
    this construction.

    Returns (narration_dict_or_empty, latency_ms, usage_or_None). An
    empty dict means the caller must fall back to
    deterministic_narration -- the turn's successful tool result is
    never discarded because of this call. `usage` reflects the call
    that actually happened, so it can still be real even when the
    narration itself was discarded (e.g. an ungrounded amount) -- the
    provider was still called and still cost tokens.
    """
    tool_use_id = "toolu_deterministic_route"
    payload, trusted_figures = _narration_payload(
        tool_name, result, target_goal_name
    )

    followup_messages = [
        {"role": "user", "content": current_message},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(payload),
                }
            ],
        },
    ]

    response, latency_ms, error_code, usage = _timed_model_call(
        client,
        system=_NARRATE_SYSTEM_PROMPT,
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
            mode=client.provider_name,
            event_type="provider_failure",
            success=False,
            error_code=error_code,
            latency_ms=latency_ms,
            model=client.model,
            tool_name=tool_name,
            metadata={"stage": "narrate"},
        )
        _log_provider_failure(
            request_id=request_id,
            provider=client.provider_name,
            phase="narrate",
            error_code=error_code,
            tool_name=tool_name,
            latency_ms=latency_ms,
        )
        return {}, latency_ms, usage

    narrate_use = _first_tool_use(response)

    if (
        narrate_use is None
        or narrate_use.name != "present_financial_answer"
        or not (narrate_use.input or {}).get("answer")
    ):
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="provider_failure",
            success=False,
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            latency_ms=latency_ms,
            model=client.model,
            tool_name=tool_name,
            metadata={"stage": "narrate", **_usage_metadata(usage)},
        )
        _log_provider_failure(
            request_id=request_id,
            provider=client.provider_name,
            phase="narrate",
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            tool_name=tool_name,
            latency_ms=latency_ms,
        )
        return {}, latency_ms, usage

    narration = narrate_use.input or {}

    if not _narration_is_grounded(narration, trusted_figures):
        # Same treatment as any other narrate failure: discarded, never
        # shown, falls back to the deterministic template built from
        # this turn's already-successful REAL tool result -- never a
        # second provider call to re-ask.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="provider_failure",
            success=False,
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            latency_ms=latency_ms,
            model=client.model,
            tool_name=tool_name,
            metadata={
                "stage": "narrate",
                "reason": "ungrounded_amount",
                **_usage_metadata(usage),
            },
        )
        _log_provider_failure(
            request_id=request_id,
            provider=client.provider_name,
            phase="narrate",
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            tool_name=tool_name,
            latency_ms=latency_ms,
        )
        return {}, latency_ms, usage

    return narration, latency_ms, usage


def _load_goal_names(db: Session, user_id: int) -> list[str]:
    """Just the current user's real goal names, for named-goal routing.

    A single lightweight name-only column query (no balances, dates,
    or other goal fields) -- cheaper than the full goal objects
    `_build_system_prompt` already loads unconditionally on every
    AI-path turn, so doing the same here for the deterministic path
    is not a new class of query.
    """
    return list(
        db.scalars(
            select(SavingsGoal.name).where(SavingsGoal.user_id == user_id)
        ).all()
    )


def _turn_latency_ms(turn_start: float) -> int:
    return int((time.monotonic() - turn_start) * 1000)


def _unsupported_response(
    db: Session,
    user_id: int,
    request_id: str,
    *,
    route_source: str,
    provider_call_count: int,
    turn_start: float,
) -> CopilotResponseOut:
    """The terminal 'nothing can safely answer this' outcome -- reached
    only when BOTH the deterministic router and (if consulted) provider
    DECIDE have no safe resolution. Never the generic
    "I couldn't complete that" apology: that string is reserved for the
    true last-resort case where routing succeeded but something after
    it failed unrecoverably, which this function is not.
    """
    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        # Always "free": the returned text is always the deterministic
        # CAPABILITY_EXPLANATION, regardless of whether a provider was
        # consulted first -- `route_source` in metadata below is what
        # distinguishes a clean deterministic unsupported outcome from
        # one reached after a DECIDE failure/rejection.
        mode="free",
        event_type="answer",
        success=True,
        tool_call_count=0,
        response_kind="out_of_scope",
        provenance="deterministic",
        metadata={
            "route_kind": "unsupported",
            "route_source": route_source,
            "provider_call_count": provider_call_count,
            "provider_phase": "decide" if provider_call_count else "none",
            "total_latency_ms": _turn_latency_ms(turn_start),
        },
    )
    return CopilotResponseOut(
        kind="out_of_scope",
        answer=copilot_free_mode.CAPABILITY_EXPLANATION,
        provenance="deterministic",
    )


def _resolve_deterministic(
    db: Session,
    user_id: int,
    current_user: User,
    messages: list[CopilotMessageIn],
    as_of: date,
    client: CopilotModelProvider,
    *,
    request_id: str,
    turn_start: float,
) -> CopilotResponseOut | None:
    """PATH A/C -- Intent Router 2.0's deterministic semantic router runs
    BEFORE any provider call. Returns the final response for a tool
    match or a clarification (0 provider calls spent on ROUTING either
    way); returns None only when the router has no safe resolution, so
    the caller knows to spend this turn's one allowed provider call on
    DECIDE instead.

    A tool match may still spend that one provider call, but only on
    NARRATE (never routing) -- so this turn spends at most 1 call
    regardless of which branch below is taken.
    """
    resolution = copilot_free_mode.resolve_intent(
        messages, as_of, _load_goal_names(db, user_id)
    )

    if resolution is None:
        return None

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
            metadata={
                "route_kind": "clarification",
                "route_source": "deterministic",
                "provider_call_count": 0,
                "candidate_count": len(resolution.options or []),
                "total_latency_ms": _turn_latency_ms(turn_start),
            },
        )
        return CopilotResponseOut(
            kind="clarifying_question",
            clarifying_question=resolution.question,
            clarifying_options=resolution.options,
            provenance="deterministic",
        )

    handler = _TOOL_HANDLERS.get(resolution.tool_name)

    if handler is None:
        # Defensive only -- resolution.tool_name always comes from the
        # same registry _TOOL_HANDLERS is keyed by, so this never fires
        # in practice, but a response is still owed if it somehow did.
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
            metadata={
                "route_source": "deterministic",
                "provider_call_count": 0,
                "total_latency_ms": _turn_latency_ms(turn_start),
            },
        )
        return CopilotResponseOut(
            kind="answer",
            answer=_FALLBACK_ANSWER,
            provenance="deterministic",
        )

    tool_start = time.monotonic()

    tool_input = resolution.tool_input
    if (
        resolution.tool_name == "get_goal_intelligence"
        and resolution.target_goal_name
    ):
        # Threads the already-resolved named goal into the handler so
        # its structured chips can be scoped to that goal (PHASE 20) --
        # not just its narration payload/prose, which were already
        # scoped via `_narration_payload` above this call.
        tool_input = {
            **resolution.tool_input,
            "_target_goal_name": resolution.target_goal_name,
        }

    try:
        result, chips, confidence, low_data_warning = handler(
            db, user_id, tool_input, as_of, current_user
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
            metadata={
                "route_source": "deterministic",
                "provider_call_count": 0,
                "total_latency_ms": _turn_latency_ms(turn_start),
            },
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

    narration: dict = {}
    narrate_latency_ms: int | None = None
    narrate_usage: copilot_observability.TokenUsage | None = None

    if client.enabled:
        narration, narrate_latency_ms, narrate_usage = _narrate(
            client,
            resolution.tool_name,
            messages[-1].content,
            resolution.tool_input,
            result,
            target_goal_name=resolution.target_goal_name,
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
        # No provider configured, or its one narrate attempt failed --
        # either way the tool already succeeded, so the REAL result is
        # always shown via the same deterministic templates free mode
        # uses. A narrate failure can never turn a successful
        # calculation into the generic "couldn't complete that" error.
        answer, why, what_this_means, actions = (
            copilot_free_mode.deterministic_narration(
                resolution.tool_name,
                result,
                resolution.emphasize,
                resolution.target_goal_name,
            )
        )
        actions = actions[:2]
        provenance = "deterministic"

    total_latency_ms = _turn_latency_ms(turn_start)

    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        mode=client.provider_name if client.enabled else "free",
        event_type="tool_success",
        success=True,
        tool_name=resolution.tool_name,
        latency_ms=tool_latency_ms,
        model=client.model if client.enabled else None,
        tool_call_count=1,
        response_kind="answer",
        provenance=provenance,
        intent=_extract_intent(resolution.tool_input),
        metadata={
            "route_kind": "tool",
            "route_source": "deterministic",
            "provider_call_count": 1 if client.enabled else 0,
            "provider_phase": "narrate" if client.enabled else "none",
            "fallback_used": client.enabled and not narration,
            "total_latency_ms": total_latency_ms,
            **_usage_metadata(narrate_usage),
        },
    )

    copilot_observability.log_turn_completed(
        copilot_observability.CopilotTrace(
            request_id=request_id,
            tool=resolution.tool_name,
            tool_calls=1,
            tool_duration_ms=tool_latency_ms,
            provider_duration_ms=narrate_latency_ms,
            total_duration_ms=total_latency_ms,
            input_tokens=narrate_usage.input_tokens if narrate_usage else None,
            output_tokens=(
                narrate_usage.output_tokens if narrate_usage else None
            ),
            total_tokens=narrate_usage.total_tokens if narrate_usage else None,
            estimated_cost=copilot_observability.estimate_cost(
                narrate_usage,
                settings.copilot_input_cost_per_million_tokens,
                settings.copilot_output_cost_per_million_tokens,
            ),
            success=True,
        )
    )

    return CopilotResponseOut(
        kind="answer",
        answer=answer,
        why=why,
        what_this_means=what_this_means,
        key_numbers=chips,
        suggested_actions=actions,
        tool_used=_TOOL_LABELS.get(resolution.tool_name, resolution.tool_name),
        confidence=confidence,
        low_data_warning=low_data_warning,
        provenance=provenance,
    )


def unexpected_turn_failure_response(
    db: Session,
    user_id: int,
    request_id: str,
    exc: Exception,
) -> CopilotResponseOut:
    """Last-resort request-boundary responder for the Copilot router.

    Reached only when `run_copilot_turn` raises something none of its
    own handling caught -- a bug, not a classified provider/validation/
    tool failure -- so there is never an already-built deterministic
    response for this to discard; the crash necessarily happened before
    one could be returned.

    Logs only bounded, structured metadata: request_id, the exception's
    type name, and a stable error code. Never `str(exc)` or a
    traceback, since the exception may have originated inside a tool
    handler and its message could echo prompt text or financial values
    -- those must never reach logs or the audit trail.
    """
    db.rollback()
    error_code = copilot_audit.classify_provider_error(exc)

    logger.error(
        "copilot_unexpected_failure request_id=%s error_type=%s "
        "error_code=%s",
        request_id,
        type(exc).__name__,
        error_code,
    )

    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        mode="unknown",
        event_type="unexpected_failure",
        success=False,
        error_code=error_code,
        response_kind="answer",
        provenance="deterministic",
        metadata={"error_type": type(exc).__name__},
    )

    return CopilotResponseOut(
        kind="answer",
        answer=_FALLBACK_ANSWER,
        provenance="deterministic",
    )


def run_copilot_turn(
    db: Session,
    user_id: int,
    current_user: User,
    messages: list[CopilotMessageIn],
    client: CopilotModelProvider,
    *,
    as_of: date | None = None,
    request_id: str | None = None,
) -> CopilotResponseOut:
    """Orchestrates one Copilot turn under a hard invariant: at most ONE
    external provider call per turn, whether Anthropic or Groq.

    PATH A/C (deterministic router resolves or clarifies) -- checked
    FIRST, regardless of whether a provider is configured. A tool match
    may still spend the turn's one provider call, but only on NARRATE.
    PATH B (router has no safe resolution, provider configured) --
    spends the turn's one provider call on DECIDE (routing) instead;
    a tool it picks is narrated with the same deterministic templates
    Path A's narrate failure falls back to -- never a second provider
    call.
    PATH D (router has no safe resolution, no provider configured) --
    the same concise unsupported response Path B's own DECIDE failure
    falls back to, spending 0 calls.
    """
    calculation_date = as_of or date.today()
    request_id = request_id or copilot_audit.new_request_id()
    turn_start = time.monotonic()

    deterministic = _resolve_deterministic(
        db,
        user_id,
        current_user,
        messages,
        calculation_date,
        client,
        request_id=request_id,
        turn_start=turn_start,
    )
    if deterministic is not None:
        return deterministic

    # Confidently non-financial input (weather, "write Java code", a
    # "call <tool_name>" injection attempt) never reaches the provider
    # at all -- checked before the enabled/disabled branch below so it
    # costs 0 provider calls the same way whether or not a provider is
    # configured, unlike the router-exhausted case just above, which
    # still asks the provider to DECIDE when one is available.
    if copilot_free_mode.is_deterministically_unsupported(
        messages[-1].content
    ):
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source="deterministic",
            provider_call_count=0,
            turn_start=turn_start,
        )

    if not client.enabled:
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source="deterministic",
            provider_call_count=0,
            turn_start=turn_start,
        )

    # PATH B: the deterministic router above already found no safe
    # resolution -- ask the provider to DECIDE instead. This is the
    # turn's one and only provider call; whatever it produces (tool,
    # clarification, or decline), no second provider call follows.
    history = [
        {"role": m.role, "content": m.content}
        for m in messages[-_MAX_HISTORY_MESSAGES:]
    ]

    system = _build_system_prompt(db, user_id, calculation_date)

    # tool_choice="any" (not "auto"): DECIDE must always pick one of the
    # registered tools -- including request_clarification and
    # decline_out_of_scope, which are themselves tools -- so a supported
    # question can never come back as free-form, ungrounded prose. The
    # provider still fully expresses "ambiguous" (clarification) and
    # "out of scope" (decline) outcomes; it just can never skip picking
    # any tool at all.
    decision, decide_latency_ms, decide_error_code, decide_usage = (
        _timed_model_call(
            client,
            system=system,
            messages=history,
            tools=_TOOLS,
            tool_choice={"type": "any"},
        )
    )

    if decision is None:
        # Provider unreachable/timed out/rate-limited -- the turn's one
        # provider call is already spent; the deterministic router
        # already ruled out a safe resolution above, so there is
        # nothing further to try.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="provider_failure",
            success=False,
            error_code=decide_error_code,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            metadata={
                "stage": "decide",
                "route_source": client.provider_name,
                "provider_call_count": 1,
                "provider_phase": "decide",
            },
        )
        _log_provider_failure(
            request_id=request_id,
            provider=client.provider_name,
            phase="decide",
            error_code=decide_error_code,
            tool_name=None,
            latency_ms=decide_latency_ms,
        )
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source=client.provider_name,
            provider_call_count=1,
            turn_start=turn_start,
        )

    tool_use = _first_tool_use(decision)

    if tool_use is None:
        # The provider skipped every tool despite tool_choice="any" and
        # returned prose instead -- that prose is never grounded in a
        # real calculation, so it is never shown to the user.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="provider_failure",
            success=False,
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            metadata={
                "stage": "decide",
                "reason": "no_tool_call",
                "route_source": client.provider_name,
                "provider_call_count": 1,
            },
        )
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source=client.provider_name,
            provider_call_count=1,
            turn_start=turn_start,
        )

    name = tool_use.name
    tool_input = tool_use.input or {}

    if name in (
        "run_what_if",
        "simulate_major_purchase",
    ) and copilot_free_mode.is_multi_option_comparison_signal(
        messages[-1].content
    ):
        # The user's own message signaled a two-scenario comparison
        # (copilot_free_mode's own guard already refuses to silently
        # answer this deterministically, for the same reason) but the
        # provider picked a single-scenario tool anyway -- executing it
        # would silently answer only the first scenario and let
        # narration describe the comparison as if both were run. Never
        # executed: this turn's one provider call is already spent, so
        # this resolves the same way the deterministic guard does,
        # rather than a second provider call to re-ask.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="safety_rejection",
            success=False,
            error_code=copilot_audit.MODEL_INVALID_RESPONSE,
            tool_name=name,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="answer",
            provenance="ai_enhanced",
            metadata={
                "route_source": client.provider_name,
                "provider_call_count": 1,
                "reason": "single_scenario_for_comparison_question",
            },
        )
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source=client.provider_name,
            provider_call_count=1,
            turn_start=turn_start,
        )

    if name == "request_clarification":
        question = str(tool_input.get("question", "")).strip()
        raw_options = tool_input.get("options") or []
        options = [str(o) for o in raw_options][:4] or None

        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="clarification",
            success=True,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="clarifying_question",
            provenance="ai_enhanced",
            metadata={
                "route_kind": "clarification",
                "route_source": client.provider_name,
                "provider_call_count": 1,
                "provider_phase": "decide",
                "total_latency_ms": _turn_latency_ms(turn_start),
                **_usage_metadata(decide_usage),
            },
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
            mode=client.provider_name,
            event_type="answer",
            success=True,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=0,
            response_kind="out_of_scope",
            provenance="ai_enhanced",
            intent=category if isinstance(category, str) else None,
            metadata={
                "route_kind": "unsupported",
                "route_source": client.provider_name,
                "provider_call_count": 1,
                "provider_phase": "decide",
                "total_latency_ms": _turn_latency_ms(turn_start),
                **_usage_metadata(decide_usage),
            },
        )
        return CopilotResponseOut(
            kind="out_of_scope",
            answer=reason or _SCOPE_FALLBACK,
            provenance="ai_enhanced",
        )

    handler = _TOOL_HANDLERS.get(name)

    if handler is None:
        # The model named a tool outside our registry -- never executed
        # under any circumstances. The turn's one provider call is
        # already spent, so this resolves straight to the same
        # unsupported response a DECIDE failure falls back to, rather
        # than spending a second provider call on another attempt.
        copilot_audit.record_event(
            db,
            user_id=user_id,
            request_id=request_id,
            mode=client.provider_name,
            event_type="safety_rejection",
            success=False,
            error_code=copilot_audit.TOOL_NOT_REGISTERED,
            tool_name=name,
            latency_ms=decide_latency_ms,
            model=client.model,
            tool_call_count=1,
            response_kind="answer",
            provenance="ai_enhanced",
            metadata={
                "route_source": client.provider_name,
                "provider_call_count": 1,
            },
        )
        return _unsupported_response(
            db,
            user_id,
            request_id,
            route_source=client.provider_name,
            provider_call_count=1,
            turn_start=turn_start,
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
            mode=client.provider_name,
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
            metadata={
                "route_source": client.provider_name,
                "provider_call_count": 1,
            },
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

    # No second (NARRATE) provider call: this turn's one call was
    # already spent on DECIDE, so the result is always presented via
    # the same deterministic templates free mode and Path A's narrate
    # fallback use -- both correctly cents-normalized and, for
    # get_goal_intelligence, scoped to the named goal already resolved
    # in `resolution` upstream (Path A) or, here, unscoped since Path B
    # only runs when the deterministic router couldn't resolve a named
    # goal in the first place.
    answer, why, what_this_means, actions = (
        copilot_free_mode.deterministic_narration(name, result)
    )
    provenance = "deterministic"
    total_latency_ms = _turn_latency_ms(turn_start)

    copilot_audit.record_event(
        db,
        user_id=user_id,
        request_id=request_id,
        mode=client.provider_name,
        event_type="tool_success",
        success=True,
        tool_name=name,
        latency_ms=tool_latency_ms,
        model=client.model,
        tool_call_count=1,
        response_kind="answer",
        provenance=provenance,
        intent=_extract_intent(tool_input),
        metadata={
            "route_kind": "tool",
            "route_source": client.provider_name,
            "provider_call_count": 1,
            "provider_phase": "decide",
            "total_latency_ms": total_latency_ms,
            **_usage_metadata(decide_usage),
        },
    )

    copilot_observability.log_turn_completed(
        copilot_observability.CopilotTrace(
            request_id=request_id,
            tool=name,
            tool_calls=1,
            tool_duration_ms=tool_latency_ms,
            provider_duration_ms=decide_latency_ms,
            total_duration_ms=total_latency_ms,
            input_tokens=decide_usage.input_tokens if decide_usage else None,
            output_tokens=(
                decide_usage.output_tokens if decide_usage else None
            ),
            total_tokens=decide_usage.total_tokens if decide_usage else None,
            estimated_cost=copilot_observability.estimate_cost(
                decide_usage,
                settings.copilot_input_cost_per_million_tokens,
                settings.copilot_output_cost_per_million_tokens,
            ),
            success=True,
        )
    )

    return CopilotResponseOut(
        kind="answer",
        answer=answer,
        why=why,
        what_this_means=what_this_means,
        key_numbers=chips,
        suggested_actions=actions[:2],
        tool_used=_TOOL_LABELS.get(name, name),
        confidence=confidence,
        low_data_warning=low_data_warning,
        provenance=provenance,
    )
