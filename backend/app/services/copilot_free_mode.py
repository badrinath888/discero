"""Deterministic ("free mode") FinSight Copilot -- zero LLM cost.

Pipeline: user message -> regex/keyword intent classifier -> allowlisted
FinSight tool (the SAME dispatch table the Anthropic path uses) -> real
deterministic service result -> deterministic explanation template.

This module never sends user text anywhere and never executes anything
beyond a fixed, closed set of tool names -- there is no prompt for a
"prompt injection" to escape. A message either matches a known pattern
(running a real service call with safely-extracted parameters) or it
doesn't, in which case the user gets a canned capability explanation.
Every number shown comes straight from a real service call, never from
this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.schemas import CopilotMessageIn

CAPABILITY_EXPLANATION = (
    "I can help with questions FinSight can calculate directly from "
    "your real data: your safe-to-spend, whether you can afford a "
    "specific purchase, your monthly cash flow and savings insights, "
    "whether your savings goals are on track, cash-flow forecasts, and "
    "stress-testing an income drop. Try asking one of those."
)

_GOAL_STATUS_RANK = {
    "unaffected": 4,
    "reduced": 3,
    "delayed": 2,
    "at_risk": 1,
    "impossible": 0,
}


@dataclass
class Clarify:
    question: str
    options: list[str] | None = None


@dataclass
class Resolution:
    tool_name: str
    tool_input: dict
    emphasize: str | None = None


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


# --- Parameter extraction --------------------------------------------

_DOLLAR_SIGN_RE = re.compile(r"\$\s*([\d][\d,]*(?:\.\d{1,2})?)\s*([kK])?")
_WORD_DOLLAR_RE = re.compile(
    r"\b([\d][\d,]*(?:\.\d{1,2})?)\s*([kK])?\s*(?:dollars|bucks)\b",
    re.IGNORECASE,
)
_BARE_NUMBER_RE = re.compile(r"([\d][\d,]*(?:\.\d{1,2})?)\s*([kK])?")
_PERCENT_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", re.IGNORECASE
)


def _to_cents(number_str: str, suffix: str | None) -> int | None:
    try:
        value = float(number_str.replace(",", ""))
    except ValueError:
        return None

    if suffix:
        value *= 1000

    if value <= 0:
        return None

    return round(value * 100)


def extract_amount_cents(text: str) -> int | None:
    for pattern in (_DOLLAR_SIGN_RE, _WORD_DOLLAR_RE):
        match = pattern.search(text)
        if match:
            cents = _to_cents(match.group(1), match.group(2))
            if cents is not None:
                return cents
    return None


def _bare_number_cents(text: str) -> int | None:
    match = _BARE_NUMBER_RE.search(text)
    if not match:
        return None
    return _to_cents(match.group(1), match.group(2))


def extract_percent(text: str) -> float | None:
    match = _PERCENT_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if not (0 < value <= 100):
        return None
    return value


_MONTHLY_CADENCE_RE = re.compile(
    r"\b(per month|/\s*month|a month|each month|monthly)\b",
    re.IGNORECASE,
)
_CAPACITY_VERB_RE = re.compile(
    r"\b(save|capacity|available|put aside|set aside|contribute|spare)\b",
    re.IGNORECASE,
)


def extract_monthly_capacity_cents(text: str) -> tuple[bool, int | None]:
    """Detects an explicit monthly savings-capacity statement.

    Returns (stated, cents). `stated` is True whenever the text reads
    as a capacity statement (cadence + capacity wording present) even
    if no parseable amount was found -- callers must ask for
    clarification in that case rather than silently falling back to an
    auto-derived capacity, which would ignore what the user said.
    """
    stated = bool(
        _MONTHLY_CADENCE_RE.search(text) and _CAPACITY_VERB_RE.search(text)
    )
    if not stated:
        return False, None
    return True, extract_amount_cents(text)


# --- Intent classification --------------------------------------------

_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "run_stress_test",
        re.compile(
            r"\b(income (drop\w*|loss|reduc\w*|cut\w*)|lose my job|"
            r"job loss|laid off|pay cut)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "simulate_major_purchase",
        re.compile(
            r"\b(afford|can i (buy|get|purchase)|what if i (buy|spend|"
            r"purchase)|major purchase|thinking (of|about) buying)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "check_goal_conflicts",
        re.compile(
            # Deliberately excludes a bare "which goal?" -- that's
            # handled as a follow-up against the prior turn instead,
            # see _WHICH_GOAL_RE below.
            r"\bgoals?\b[^.?!]{0,40}\b(risk|conflict|on track|behind|"
            r"fund\w*)\b|\b(risk|conflict)\b[^.?!]{0,40}\bgoals?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_cash_flow_forecast",
        re.compile(
            r"\b(forecast|cash.?flow|projected balance|end.of.?month "
            r"balance|month.?end balance)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_safe_to_spend",
        re.compile(
            r"safe.to.spend|how much (can|could) i spend|spending room",
            re.IGNORECASE,
        ),
    ),
    (
        "get_recommendations",
        re.compile(
            r"\b(what should i (do next|focus on|work on)|what needs "
            r"my attention|pay attention|top (financial )?priorit\w*|"
            r"how can i improve|what('?s| is) going well|biggest "
            r"(financial )?risks?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_monthly_insights",
        re.compile(
            r"\b(this month|how am i doing|monthly summary|how much "
            r"did i save|spending trend)\b",
            re.IGNORECASE,
        ),
    ),
]


def classify_intent(text: str) -> str | None:
    for name, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return name
    return None


def build_tool_input(name: str, text: str, as_of: date) -> dict | Clarify:
    if name in (
        "get_safe_to_spend",
        "get_cash_flow_forecast",
        "get_monthly_insights",
        "get_recommendations",
    ):
        return {}

    if name == "check_goal_conflicts":
        stated, amount = extract_monthly_capacity_cents(text)
        if stated and amount is None:
            return Clarify(
                "What's your monthly savings capacity available for "
                'goals? (e.g. "$100 per month")'
            )
        if stated:
            return {"monthly_savings_capacity_cents": amount}
        return {}

    if name == "simulate_major_purchase":
        amount = extract_amount_cents(text)
        if amount is None:
            return Clarify("What amount are you considering?")
        return {
            "purchase_name": "This purchase",
            "purchase_amount_cents": amount,
            "purchase_date": as_of.isoformat(),
        }

    if name == "run_stress_test":
        percent = extract_percent(text)
        if percent is None:
            return Clarify(
                "What percentage income drop should I model?",
                ["10%", "20%", "30%"],
            )
        return {
            "scenario_type": "income_reduction",
            "scenario_name": "Income reduction scenario",
            "income_reduction_percent": percent,
            "event_date": as_of.isoformat(),
        }

    return Clarify("Could you rephrase that?")


# --- Follow-up resolution ----------------------------------------------

_WHY_RE = re.compile(r"^\s*why\b", re.IGNORECASE)
_WHICH_GOAL_RE = re.compile(r"\bwhich goal|what goal\b", re.IGNORECASE)
_FOLLOW_UP_AMOUNT_RE = re.compile(
    r"^(?:what about|how about|and|or)?\s*\$?\s*[\d][\d,]*(?:\.\d{1,2})?"
    r"\s*[kK]?\s*\??$",
    re.IGNORECASE,
)


def _find_prior_tool(
    history: list[CopilotMessageIn], as_of: date
) -> tuple[str, dict] | None:
    for message in reversed(history):
        if message.role != "user":
            continue

        name = classify_intent(message.content)
        if name is None:
            continue

        built = build_tool_input(name, message.content, as_of)
        if isinstance(built, Clarify):
            continue

        return name, built

    return None


def _find_prior_monthly_capacity(
    history: list[CopilotMessageIn],
) -> int | None:
    for message in reversed(history):
        if message.role != "user":
            continue

        stated, amount = extract_monthly_capacity_cents(message.content)
        if stated and amount is not None:
            return amount

    return None


def resolve_intent(
    messages: list[CopilotMessageIn], as_of: date
) -> Resolution | Clarify | None:
    """Returns a Resolution to run, a Clarify to ask, or None (unknown)."""
    current = messages[-1].content
    history = messages[:-1]

    name = classify_intent(current)

    if name is not None:
        built = build_tool_input(name, current, as_of)
        if isinstance(built, Clarify):
            return built

        if (
            name == "check_goal_conflicts"
            and "monthly_savings_capacity_cents" not in built
        ):
            # The current message didn't restate a capacity -- carry
            # forward an unambiguous one from earlier in this chat
            # rather than silently letting an auto-derived default
            # override what the user already told us.
            prior_capacity = _find_prior_monthly_capacity(history)
            if prior_capacity is not None:
                built = {
                    **built,
                    "monthly_savings_capacity_cents": prior_capacity,
                }

        return Resolution(name, built)

    stripped = current.strip()

    if _WHY_RE.search(stripped):
        prior = _find_prior_tool(history, as_of)
        if prior:
            return Resolution(prior[0], prior[1], "why")
        return None

    if _WHICH_GOAL_RE.search(stripped):
        prior = _find_prior_tool(history, as_of)
        if prior:
            return Resolution(prior[0], prior[1], "goals")
        return None

    if _FOLLOW_UP_AMOUNT_RE.match(stripped):
        amount = extract_amount_cents(stripped) or _bare_number_cents(
            stripped
        )
        if amount is not None:
            prior = _find_prior_tool(history, as_of)
            if prior and prior[0] == "simulate_major_purchase":
                new_input = dict(prior[1])
                new_input["purchase_amount_cents"] = amount
                return Resolution(prior[0], new_input)

    return None


# --- Deterministic explanation templates -------------------------------


def _safe_to_spend_why(result) -> str:
    breakdown = result.breakdown
    deductions = {
        "upcoming bills and obligations": (
            breakdown.upcoming_obligations_cents
        ),
        "your essential spending budget": (
            breakdown.essential_spending_cents
        ),
        "your safety reserve": breakdown.safety_reserve_cents,
    }
    nonzero = {label: cents for label, cents in deductions.items() if cents > 0}

    if not nonzero:
        # Never claim a zero-value component is "the driver" -- with
        # nothing being deducted, the liquid balance is what's left.
        return (
            "This is driven mainly by your available liquid balance "
            "-- you have no active recurring obligations, essential-"
            "spending budget, or safety reserve currently reducing it."
        )

    total_deductions = sum(deductions.values())

    if (
        breakdown.liquid_balance_cents > 0
        and total_deductions <= breakdown.liquid_balance_cents * 0.1
    ):
        return (
            "This is driven mainly by your liquid balance, which "
            "comfortably covers your current obligations and reserve."
        )

    largest_label = max(nonzero, key=lambda label: nonzero[label])
    return f"This is driven mainly by {largest_label}."


def _render_safe_to_spend(result, emphasize):
    answer = (
        f"You have {_currency(result.safe_to_spend_cents)} safe to "
        f"spend through {result.through_date.isoformat()}."
    )
    why = _safe_to_spend_why(result)
    what_this_means = {
        "safe": (
            "You're in a comfortable position to spend within this "
            "range."
        ),
        "limited": (
            "You have some room, but it's tighter than usual -- "
            "spend carefully."
        ),
        "negative": (
            "You're projected to come up short -- avoid new "
            "discretionary spending."
        ),
    }[result.status]
    actions = ["Check if a purchase fits", "See what's changed recently"]

    if emphasize == "why":
        answer, why = why, answer

    return answer, why, what_this_means, actions


def _render_major_purchase(result, emphasize):
    status_lead = {
        "affordable": "You can afford",
        "caution": "It's a stretch, but you can likely manage",
        "not_affordable": "You likely can't comfortably afford",
    }[result.affordability_status]
    answer = (
        f"{status_lead} a {_currency(result.purchase_amount_cents)} "
        "purchase."
    )
    why = result.explanation
    what_this_means = None

    if result.goal_impacts:
        worst = min(
            result.goal_impacts,
            key=lambda g: _GOAL_STATUS_RANK.get(g.status, 0),
        )
        if worst.status != "unaffected":
            what_this_means = (
                f"Your {worst.goal_name} goal would become "
                f"{worst.status.replace('_', ' ')} under this purchase."
            )

    actions = [
        "Compare with a different amount",
        "See how this affects your goals",
    ]

    if emphasize == "why":
        answer, why = why, answer
    elif emphasize == "goals" and result.goal_impacts:
        lines = [
            f"{g.goal_name}: {g.status.replace('_', ' ')}"
            for g in result.goal_impacts
        ]
        answer = "Goal impact -- " + "; ".join(lines)

    return answer, why, what_this_means, actions


def _render_compare_scenarios(result, emphasize):
    recommended = {
        "option_a": "Option A",
        "option_b": "Option B",
        "tie": "Both options",
    }[result.recommended_option]
    answer = f"{recommended} is the better choice."
    why = result.recommendation
    return answer, why, None, []


def _render_stress_test(result, emphasize):
    risk_lead = {
        "resilient": "Your finances would stay resilient",
        "strained": "Your finances would be strained",
        "critical": "Your finances would be at critical risk",
    }[result.risk_level]
    answer = (
        f"{risk_lead} under this scenario (resilience score "
        f"{round(result.resilience_score)}/100)."
    )
    why = result.explanation
    what_this_means = (
        f"Estimated recovery time: {result.estimated_recovery_days} "
        "days."
        if result.estimated_recovery_days
        else None
    )
    actions = ["Try a different percentage", "See which goals are affected"]

    if emphasize == "why":
        answer, why = why, answer
    elif emphasize == "goals" and result.affected_goals:
        lines = [
            f"{g.name}: {g.status_before} -> {g.status_after}"
            for g in result.affected_goals
        ]
        answer = "Goal impact -- " + "; ".join(lines)

    return answer, why, what_this_means, actions


def _render_goal_conflicts(result, emphasize):
    status_lead = {
        "no_conflict": "Your goals are fully fundable",
        "strained": "Your goals are fundable, but tight",
        "conflict": "Your goals currently conflict",
    }[result.conflict_status]
    answer = f"{status_lead} given your monthly savings capacity."
    why = result.explanation
    actions = ["Adjust a goal's target date", "See required monthly amounts"]

    if emphasize == "why":
        answer, why = why, answer
    elif emphasize == "goals" and result.goals:
        lines = [
            f"{g.name}: {g.status.replace('_', ' ')}" for g in result.goals
        ]
        answer = "Goal status -- " + "; ".join(lines)

    return answer, why, None, actions


def _render_cash_flow_forecast(result, emphasize):
    risk_note = (
        "which puts you at risk of a low balance"
        if result.low_balance_risk
        else "with a healthy buffer"
    )
    answer = (
        "You're projected to end the month with "
        f"{_currency(result.projected_end_balance_cents)}, {risk_note}."
    )
    why = (
        f"Forecast confidence is {result.confidence.level} "
        f"({round(result.confidence.score)}%)."
    )
    actions = [
        "See this month's spending insights",
        "Check your safe-to-spend",
    ]

    if emphasize == "why":
        answer, why = why, answer

    return answer, why, None, actions


def _render_monthly_insights(result, emphasize):
    flow_word = (
        "saved"
        if result.net_cents >= 0
        else "spent more than you earned by"
    )
    answer = (
        f"This month you {flow_word} {_currency(abs(result.net_cents))} "
        f"({_percent(result.savings_rate_percent)} savings rate)."
    )
    why = result.insights[0].description if result.insights else None
    actions = ["See what's driving this", "Check your safe-to-spend"]

    if emphasize == "why":
        answer, why = why, answer

    return answer, why, None, actions


def _render_recommendations(result, emphasize):
    items = result.recommendations

    if not items:
        return (
            "You're all caught up -- nothing needs your attention "
            "right now.",
            None,
            None,
            [],
        )

    top = items[0]

    if emphasize == "goals":
        lines = [f"{rec.title}" for rec in items[:3]]
        answer = "Your top priorities: " + "; ".join(lines)
    elif len(items) == 1:
        answer = f"Your top priority: {top.title}."
    else:
        answer = (
            f"Your top priority is {top.title}, plus "
            f"{len(items) - 1} more item(s) worth a look."
        )

    why = top.why
    what_this_means = top.recommended_action
    actions = [rec.title for rec in items[1:3]]

    if emphasize == "why":
        answer, why = why, answer

    return answer, why, what_this_means, actions


_RENDERERS = {
    "get_safe_to_spend": _render_safe_to_spend,
    "simulate_major_purchase": _render_major_purchase,
    "compare_purchase_scenarios": _render_compare_scenarios,
    "run_stress_test": _render_stress_test,
    "check_goal_conflicts": _render_goal_conflicts,
    "get_cash_flow_forecast": _render_cash_flow_forecast,
    "get_monthly_insights": _render_monthly_insights,
    "get_recommendations": _render_recommendations,
}


def deterministic_narration(
    tool_name: str, result, emphasize: str | None = None
) -> tuple[str, str | None, str | None, list[str]]:
    renderer = _RENDERERS.get(tool_name)
    if renderer is None:
        return ("Here's what I found.", None, None, [])
    return renderer(result, emphasize)
