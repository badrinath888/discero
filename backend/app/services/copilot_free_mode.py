"""Deterministic ("free mode") Discero Copilot -- zero LLM cost.

Pipeline: user message -> regex/keyword intent classifier -> allowlisted
Discero tool (the SAME dispatch table the Anthropic path uses) -> real
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
from datetime import date, timedelta
from typing import Literal

from app.schemas import CopilotMessageIn
from app.services.goal_impact_service import _add_months

CAPABILITY_EXPLANATION = (
    "I can help with questions Discero can calculate directly from "
    "your real data: your safe-to-spend, whether you can afford a "
    "specific purchase, what happens if a bill or rent payment goes "
    "up or down, your monthly cash flow and savings insights, "
    "whether your savings goals are on track and which one is most "
    "urgent, whether you should buy something now or wait, cash-flow "
    "forecasts, stress-testing an income drop, changes in your "
    "recurring bills, and unusual spending patterns. Try asking one "
    "of those."
)

_GOAL_STATUS_RANK = {
    "unaffected": 4,
    "reduced": 3,
    "delayed": 2,
    "at_risk": 1,
    "impossible": 0,
}

# Some regexes below run over raw, unbounded user chat text. The wording
# they look for (a horizon like "90 days", or a short bare-amount
# follow-up) is always near the start of a realistic message, so bounding
# the inspected slice to this many characters is behavior-preserving for
# real input while keeping worst-case regex work independent of message
# length (defends against adversarially long input, e.g. CodeQL ReDoS).
_MAX_REGEX_INSPECT_CHARS = 200


# The three routing outcomes every Copilot turn resolves to, whether
# routing came from this deterministic module or from a provider's
# DECIDE tool call (see RouteDecision in copilot_service.py, which
# adapts a provider's response into this same vocabulary). Kept as a
# plain type alias, not a class hierarchy -- Resolution/Clarify/None
# below already ARE these three outcomes; this just names them.
#   "tool"          -- Resolution: a registered tool + structured args
#   "clarification" -- Clarify: supported domain, missing/ambiguous info
#   "unsupported"   -- None: no Discero capability applies
RouteKind = Literal["tool", "clarification", "unsupported"]


@dataclass
class Clarify:
    question: str
    options: list[str] | None = None


@dataclass
class Resolution:
    tool_name: str
    tool_input: dict
    emphasize: str | None = None
    # Set only for get_goal_intelligence when the user named a specific
    # goal (resolved against the user's real goals in resolve_intent) --
    # narration then reports on that goal instead of the aggregate
    # "most urgent" one. None means no specific goal was named.
    target_goal_name: str | None = None


def _currency(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1f}%"


# --- Parameter extraction --------------------------------------------

_DOLLAR_SIGN_RE = re.compile(r"\$\s*([\d][\d,]*(?:\.\d{1,2})?)\s*([kK])?")
# No `\s*` between the digits and the optional `[kK]` suffix (unlike
# `_DOLLAR_SIGN_RE`, which is safe because its own optional `[kK]?` is
# the last token in the pattern -- nothing required follows it, so it
# never drives a backtracking search). Here a required literal
# (`dollars|bucks`) DOES follow, so two adjacent `\s*` groups around an
# optional group would give the engine ~N ways to split a run of N
# whitespace characters before concluding a match fails -- O(n^2)
# worst case, and CodeQL's py/polynomial-redos flags exactly this
# shape. A single `\s*` before the required literal has no such
# ambiguity to backtrack over.
_WORD_DOLLAR_RE = re.compile(
    r"\b([\d][\d,]*(?:\.\d{1,2})?)([kK])?\s*(?:dollars|bucks)\b",
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


_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_NAME_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\b", re.IGNORECASE
)
_RELATIVE_UNIT_RE = re.compile(
    r"\b(\d+)\s+(day|week|month)s?\b", re.IGNORECASE
)
_ONE_MONTH_RE = re.compile(r"\bone month\b", re.IGNORECASE)
_ONE_WEEK_RE = re.compile(r"\bone week\b", re.IGNORECASE)

# Spelled-out small counts ("two months", "three weeks") -- bounded to a
# fixed closed word list rather than a general number-word parser, which
# covers realistic durations (income loss, waiting periods) without
# taking on open-ended NLP.
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_WORD_RELATIVE_UNIT_RE = re.compile(
    r"\b(" + "|".join(_WORD_NUMBERS) + r")\s+(day|week|month)s?\b",
    re.IGNORECASE,
)
_DURATION_UNIT_WORD_RE = re.compile(
    r"\b(day|week|month)s?\b", re.IGNORECASE
)
_PAYCHECK_STOP_RE = re.compile(
    r"paychecks?\s+stop\w*|without (?:a )?paycheck|no (?:paycheck|"
    r"income) for",
    re.IGNORECASE,
)


def extract_future_date(text: str, as_of: date) -> date | None:
    """Deterministically resolves a future date phrase.

    Supports "in N day(s)/week(s)/month(s)", "one month"/"one week",
    and a bare month name (rolled forward to the next occurrence of
    that month if it's already passed this year). Never guesses --
    returns None if nothing matches.
    """
    match = _RELATIVE_UNIT_RE.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            return None
        if unit == "day":
            return as_of + timedelta(days=amount)
        if unit == "week":
            return as_of + timedelta(days=amount * 7)
        return _add_months(as_of, amount)

    if _ONE_MONTH_RE.search(text):
        return _add_months(as_of, 1)

    if _ONE_WEEK_RE.search(text):
        return as_of + timedelta(days=7)

    month_match = _MONTH_NAME_RE.search(text)
    if month_match:
        month_number = _MONTH_NAMES[month_match.group(1).lower()]
        year = as_of.year
        if month_number <= as_of.month:
            year += 1
        return date(year, month_number, 1)

    return None


def _duration_to_days(amount: int, unit: str) -> int:
    unit = unit.lower()
    if unit.startswith("day"):
        return amount
    if unit.startswith("week"):
        return amount * 7
    return amount * 30


def extract_duration_days(text: str) -> int | None:
    """Deterministically resolves a stated duration to whole days.

    Supports digit ("2 months") and spelled-out ("two months") small
    counts plus "one month"/"one week". Never guesses -- returns None
    if no duration is stated, so callers can distinguish "no duration
    given" (ask for one) from a genuinely parsed value.
    """
    match = _RELATIVE_UNIT_RE.search(text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
    else:
        word_match = _WORD_RELATIVE_UNIT_RE.search(text)
        if word_match:
            amount = _WORD_NUMBERS[word_match.group(1).lower()]
            unit = word_match.group(2)
        elif _ONE_MONTH_RE.search(text):
            amount, unit = 1, "month"
        elif _ONE_WEEK_RE.search(text):
            amount, unit = 1, "week"
        else:
            return None

    if amount <= 0:
        return None

    return min(_duration_to_days(amount, unit), 365)


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
        "get_recurring_intelligence",
        re.compile(
            r"\bduplicate subscriptions?\b|"
            r"\bwhat changed in my recurring\b|"
            r"\bhow much (do|does)[^.?!]{0,30}\brecurring\b|"
            r"\b(recurring (bills?|payments?|subscriptions?)|"
            r"subscriptions?)\b[^.?!]{0,40}\b(chang\w*|increas\w*|"
            r"decreas\w*|duplicate|coming up|due|upcoming|cost)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_spending_anomalies",
        re.compile(
            r"\bspend\w* unusual\w*\b|"
            r"\bunusual spending\b|"
            r"\bspending[^.?!]{0,20}unusual\b|"
            r"\banything (unusual|weird)[^.?!]{0,20}spending\b|"
            r"\bcharged (me )?twice\b|\bdouble charged\b|"
            r"\bduplicate charge\b|"
            r"\bwhy (was|is|did) my spending (higher|up|increas\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_financial_resilience",
        re.compile(
            r"\b(could i survive|how long would my savings last|how "
            r"financially resilient|emergency runway|financial runway|"
            r"income stops?|without income|cover \d+ days|essential "
            r"spending (is|of|would be|were))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "buy_now_vs_wait",
        re.compile(
            r"\b(now or wait|buy\w* (it |this )?now[^.?!]{0,20}\bwait\b|"
            r"wait (until|till|for)|wait one (month|week)|safest time to "
            r"buy|better to (buy|wait))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_goal_intelligence",
        re.compile(
            r"\b(most urgent|which goal[^.?!]{0,40}\b(urgent|shortfall|"
            r"causing|behind)\b|how much[^.?!]{0,30}\bsave\b[^.?!]{0,20}"
            r"\b(months?|monthly|goals?)\b|when (can|will) i[^.?!]{0,20}"
            r"\b(finish|complete|reach)\b|when will[^.?!]{0,30}\bgoal\b"
            r"[^.?!]{0,20}\b(done|finished|complete|finish)\b|will i"
            r"[^.?!]{0,20}"
            r"\b(?:actually |realistically )?(?:reach|hit|finish|"
            r"complete|make)\b|am i (?:on (?:pace|track)\b|going to "
            r"(?:reach|hit|miss|make)\b|likely to (?:reach|hit|miss)"
            r"\b)|realistically (finish|complete)|move (this|the|my) "
            r"goal|target date|smallest (change|action)|back on track|"
            r"how far (behind|ahead))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "run_stress_test",
        re.compile(
            r"\b(income (drop\w*|loss|reduc\w*|cut\w*)|lose\w* (my )?"
            r"income|lose my job|job loss|laid off|pay cut|paychecks?"
            r"\s+stop\w*|no (?:paycheck|income) for|without (?:a )?"
            r"paycheck|how long (?:would|could) i (?:last|survive|hold "
            r"up)|financial shock|hit with[^.?!]{0,25}emergency|"
            r"sudden(?:ly)? (?:had|have|got)[^.?!]{0,20}emergency|"
            r"emergency expense)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "run_what_if",
        re.compile(
            r"\b(rent|bill|bills|expense|expenses|premium|housing|"
            r"groceries|mortgage|subscription|insurance|utilities|"
            r"cost|costs)\b[^.?!]{0,40}\b(go(?:es)? up|go(?:es)? down|"
            r"increas\w*|decreas\w*|ris\w*|drop\w*|fall\w*|more "
            r"expensive|less expensive)\b|"
            r"\b(?:suppose|imagine|what if)\b[^.?!]{0,60}\b(?:go(?:es)? "
            r"up|go(?:es)? down|increas\w*|decreas\w*|ris\w*|drop\w*|"
            r"fall\w*|more (?:expensive|per month)|less (?:expensive|"
            r"per month))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "simulate_major_purchase",
        re.compile(
            r"\b(afford|can i (buy|get|purchase)|what if i (buy|spend|"
            r"purchase)|major purchase|thinking (of|about) buying)\b|"
            r"\bcan i spend\b[^.?!]{0,15}\$\d",
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
            r"balance|month.?end balance|run short|run out of money)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "get_safe_to_spend",
        re.compile(
            r"safe.to.spend|how much (can|could) i (\w+ )?spend|"
            r"spending room|room to spend|room[^.?!]{0,20}i have"
            r"[^.?!]{0,20}spend|available to spend|room[^.?!]{0,30}"
            r"before i (?:should )?stop spending|realistically "
            r"available|safe (?:for me )?to (?:use|spend)",
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


_COMPARISON_SIGNAL_RE = re.compile(
    r"\bcompare\b|\bversus\b|\bvs\.?\b", re.IGNORECASE
)


def _bounded_amount_count(text: str, *, limit: int) -> int:
    """Counts amount-like tokens in `text`, stopping as soon as `limit`
    is reached -- never `.findall()`, which walks the entire input and
    materializes every match before the caller gets to look at any of
    them, when this only ever needs to know "are there >= limit".
    Mirrors `extract_amount_cents`'s dollar-sign-first-then-word-form
    precedence: the word-form pattern is only consulted when no
    dollar-sign amount was found at all.
    """
    count = 0

    for _ in _DOLLAR_SIGN_RE.finditer(text):
        count += 1
        if count >= limit:
            return count

    if count:
        return count

    for _ in _WORD_DOLLAR_RE.finditer(text):
        count += 1
        if count >= limit:
            return count

    return count


def _looks_like_multi_option_comparison(text: str) -> bool:
    """A two-option comparison ("compare a $100 rent increase versus
    $300") has no deterministic parser -- `compare_purchase_scenarios`,
    the only tool built for it, isn't in `_INTENT_PATTERNS` at all.
    Without this check, `run_what_if`/`simulate_major_purchase`'s own
    patterns would still match this text (a rent increase, an amount)
    and silently answer about only the FIRST amount, dropping the
    comparison the user actually asked for. Detecting that signal here
    and deferring (returning None from `classify_intent`) sends it to
    provider DECIDE instead, which has `compare_purchase_scenarios` in
    its tool registry -- or, with no provider configured, to the
    capability explanation -- never a silently partial answer.

    Bounded to `_MAX_REGEX_INSPECT_CHARS` -- comparison wording is
    always near the start of a realistic message, the same convention
    this module already uses elsewhere -- so this has clearly bounded,
    not just average-case, cost on adversarially long input, on top of
    `_bounded_amount_count`'s early exit.
    """
    bounded = text[:_MAX_REGEX_INSPECT_CHARS]

    if not _COMPARISON_SIGNAL_RE.search(bounded):
        return False

    return _bounded_amount_count(bounded, limit=2) >= 2


def classify_intent(text: str) -> str | None:
    if _looks_like_multi_option_comparison(text):
        return None
    for name, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            return name
    return None


_URGENT_RE = re.compile(r"\bmost urgent\b", re.IGNORECASE)
_MOVE_DATE_RE = re.compile(r"\bmove (this|the|my) goal\b", re.IGNORECASE)
_SHORTFALL_CAUSE_RE = re.compile(
    r"\bcausing\b|\bshortfall\b", re.IGNORECASE
)
_REQUIRED_MONTHLY_RE = re.compile(
    r"how much[^.?!]{0,30}\bsave\b|per month for", re.IGNORECASE
)
_COMPLETION_RE = re.compile(
    r"when (can|will) i|realistically (finish|complete)", re.IGNORECASE
)
_BEST_ACTION_RE = re.compile(
    r"\bsmallest (change|action)\b|\bback on track\b", re.IGNORECASE
)


def _goal_intelligence_emphasis(text: str) -> str:
    if _URGENT_RE.search(text):
        return "urgent"
    if _BEST_ACTION_RE.search(text):
        return "best_action"
    if _MOVE_DATE_RE.search(text):
        return "move_date"
    if _SHORTFALL_CAUSE_RE.search(text):
        return "shortfall_cause"
    if _COMPLETION_RE.search(text):
        return "completion"
    if _REQUIRED_MONTHLY_RE.search(text):
        return "required_monthly"
    return "overview"


# A bare, unnamed reference to "my/this/the goal" (singular) -- as
# opposed to "goals" plural or a specific goal name -- signals the user
# means ONE particular goal without saying which. Combined with an
# unresolved name and 2+ real goals, that's genuine ambiguity worth a
# clarifying question rather than silently answering about whichever
# goal happens to be ranked most urgent.
_SINGULAR_GOAL_REF_RE = re.compile(
    r"\b(my|this|the) goal\b", re.IGNORECASE
)

# Common words inside a goal name that carry no identifying signal on
# their own -- excluded so a bare "goal" or "fund" mention doesn't
# spuriously match every goal that happens to contain one of these.
_GOAL_NAME_STOPWORDS = {
    "goal",
    "fund",
    "funds",
    "savings",
    "the",
    "my",
    "a",
    "an",
    "for",
    "and",
    "account",
}


def match_goal_names(
    text: str, goal_names: list[str]
) -> tuple[str | None, list[str]]:
    """Resolves a named-goal mention against the user's real goals.

    Returns (matched_name, candidates). matched_name is set only when
    exactly one goal is identified; candidates is the (>=2) ambiguous
    set when more than one plausibly matches, for a clarifying
    question -- never guessed. Deterministic, closed-form matching
    only: case-insensitive exact phrase, then conservative
    unique-word containment. No fuzzy distance, no embeddings.
    """
    if not goal_names:
        return None, []

    lowered = text.lower()

    exact = [
        name
        for name in goal_names
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered)
    ]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, exact

    contained = []
    for name in goal_names:
        words = [
            w
            for w in re.findall(r"[a-z0-9]+", name.lower())
            if w not in _GOAL_NAME_STOPWORDS and len(w) > 2
        ]
        if words and any(w in lowered for w in words):
            contained.append(name)

    if len(contained) == 1:
        return contained[0], []
    if len(contained) > 1:
        return None, contained

    return None, []


_ESSENTIAL_SPENDING_VERB_RE = re.compile(
    r"\b(essential spending|my spending (is|were|would be))\b",
    re.IGNORECASE,
)
# The caller only ever accepts 30/60/90-day and 1/2/3-month horizons, so
# the number is matched as a fixed literal alternation rather than an
# unbounded `\d+` -- there is no quantified repetition left to match a
# variable-length run of digits, so this cannot backtrack polynomially
# (CodeQL py/polynomial-redos). The leading/trailing `\b` still prevents
# a false match inside a larger number, e.g. "130 days" or "1230".
_RESILIENCE_HORIZON_DAYS_RE = re.compile(
    r"\b(30|60|90)\s*days?\b", re.IGNORECASE
)
_RESILIENCE_HORIZON_MONTHS_RE = re.compile(
    r"\b([123])\s*months?\b", re.IGNORECASE
)
_MONTHS_TO_HORIZON_DAYS = {1: 30, 2: 60, 3: 90}


def extract_essential_spending_cents(text: str) -> tuple[bool, int | None]:
    """Mirrors extract_monthly_capacity_cents for essential spending.

    `stated` is True whenever the text reads as an essential-spending
    statement, even with no parseable amount -- callers must ask for
    clarification then rather than silently letting a derived figure
    override what the user already said.
    """
    stated = bool(_ESSENTIAL_SPENDING_VERB_RE.search(text))
    if not stated:
        return False, None
    return True, extract_amount_cents(text)


def _resilience_emphasis(text: str) -> str | None:
    bounded = text[:_MAX_REGEX_INSPECT_CHARS]

    days_match = _RESILIENCE_HORIZON_DAYS_RE.search(bounded)
    if days_match:
        return f"horizon_{days_match.group(1)}"

    months_match = _RESILIENCE_HORIZON_MONTHS_RE.search(bounded)
    if months_match:
        mapped = _MONTHS_TO_HORIZON_DAYS[int(months_match.group(1))]
        return f"horizon_{mapped}"

    return None


def _recurring_intelligence_emphasis(text: str) -> str:
    lowered = text.lower()
    if "duplicate" in lowered:
        return "duplicates"
    if "coming up" in lowered or "due" in lowered or "upcoming" in lowered:
        return "upcoming"
    if "cost" in lowered or "per month" in lowered or "how much" in lowered:
        return "burden"
    if "chang" in lowered or "increas" in lowered or "decreas" in lowered:
        return "changes"
    return "overview"


def _spending_anomaly_emphasis(text: str) -> str:
    lowered = text.lower()
    if "twice" in lowered or "double" in lowered or "duplicate" in lowered:
        return "repeated"
    if "categor" in lowered:
        return "category"
    if "why" in lowered:
        return "why"
    return "overview"


_STRESS_EMERGENCY_RE = re.compile(
    r"\bemergency\b|\bfinancial shock\b|\bhit with\b", re.IGNORECASE
)


def build_tool_input(name: str, text: str, as_of: date) -> dict | Clarify:
    if name in (
        "get_safe_to_spend",
        "get_cash_flow_forecast",
        "get_monthly_insights",
        "get_recommendations",
        "get_recurring_intelligence",
        "get_spending_anomalies",
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

    if name == "get_financial_resilience":
        stated, amount = extract_essential_spending_cents(text)
        if stated and amount is None:
            return Clarify(
                "What's your monthly essential spending? "
                '(e.g. "$4,000 per month")'
            )
        if stated:
            return {"essential_spending_cents": amount}
        return {}

    if name == "get_goal_intelligence":
        # "How much should I save per month" is ASKING for the
        # required amount, not stating an available capacity -- don't
        # let the capacity-statement heuristic misread it as one.
        if _REQUIRED_MONTHLY_RE.search(text):
            return {}

        stated, amount = extract_monthly_capacity_cents(text)
        if stated and amount is None:
            return Clarify(
                "What's your monthly savings capacity available for "
                'goals? (e.g. "$100 per month")'
            )
        if stated:
            return {"monthly_capacity_cents": amount}
        return {}

    if name == "buy_now_vs_wait":
        amount = extract_amount_cents(text)
        if amount is None:
            return Clarify("What amount are you considering?")

        wait_until_date = extract_future_date(text, as_of)
        if wait_until_date is None:
            return Clarify(
                "Wait until when? (e.g. \"October\" or \"in 3 weeks\")"
            )

        return {
            "purchase_name": "This purchase",
            "purchase_amount_cents": amount,
            "buy_now_date": as_of.isoformat(),
            "wait_until_date": wait_until_date.isoformat(),
        }

    if name == "run_stress_test":
        percent = extract_percent(text)
        if percent is not None:
            return {
                "scenario_type": "income_reduction",
                "scenario_name": "Income reduction scenario",
                "income_reduction_percent": percent,
                "event_date": as_of.isoformat(),
            }

        if _STRESS_EMERGENCY_RE.search(text):
            amount = extract_amount_cents(text)
            if amount is None:
                return Clarify("How much would the emergency expense be?")
            return {
                "scenario_type": "emergency_expense",
                "scenario_name": "Emergency expense scenario",
                "stress_amount_cents": amount,
                "event_date": as_of.isoformat(),
            }

        duration_days = extract_duration_days(text)
        if duration_days is not None:
            return {
                "scenario_type": "temporary_income_loss",
                "scenario_name": "Temporary income loss scenario",
                "duration_days": duration_days,
                "event_date": as_of.isoformat(),
            }

        if _DURATION_UNIT_WORD_RE.search(text) or _PAYCHECK_STOP_RE.search(
            text
        ):
            return Clarify(
                "How many months (or days) would the income loss last?"
            )

        return Clarify(
            "What percentage income drop should I model?",
            ["10%", "20%", "30%"],
        )

    if name == "run_what_if":
        amount = extract_amount_cents(text)
        if amount is None:
            return Clarify(
                "How much would this change be per month?"
            )
        decrease = bool(
            re.search(
                r"\b(drop\w*|decreas\w*|go(?:es)? down|fall\w*|"
                r"lower\w*)\b",
                text,
                re.IGNORECASE,
            )
        )
        return {
            "scenario_type": "monthly_expense_change",
            "scenario_name": "Monthly expense change scenario",
            "monthly_amount_change_cents": -amount if decrease else amount,
        }

    return Clarify("Could you rephrase that?")


# --- Follow-up resolution ----------------------------------------------

_WHY_RE = re.compile(r"^\s*why\b", re.IGNORECASE)
_WHICH_GOAL_RE = re.compile(r"\bwhich goal|what goal\b", re.IGNORECASE)

# A bare-amount follow-up (e.g. "$3,000", "what about $500?", "20k?") used
# to be recognized with a single anchored regex. CodeQL still flagged it
# as py/polynomial-redos even after bounding the input length, so this is
# now plain, linear-time string parsing instead of a regex: every step
# below is a fixed-cost prefix/suffix check or a single O(n) scan, with
# no backtracking possible. The actual amount value is still parsed by
# the existing extract_amount_cents/_bare_number_cents helpers.
_FOLLOW_UP_AMOUNT_PREFIXES = ("what about", "how about", "and", "or")


def _looks_like_follow_up_amount(stripped: str) -> bool:
    remainder = stripped
    lowered = remainder.lower()
    for prefix in _FOLLOW_UP_AMOUNT_PREFIXES:
        if lowered.startswith(prefix):
            remainder = remainder[len(prefix) :].lstrip()
            break

    if remainder.startswith("$"):
        remainder = remainder[1:].lstrip()

    if remainder.endswith("?"):
        remainder = remainder[:-1].rstrip()

    if remainder.endswith(("k", "K")):
        remainder = remainder[:-1].rstrip()

    if not remainder:
        return False

    if "." in remainder:
        whole, _, fraction = remainder.partition(".")
        if not (1 <= len(fraction) <= 2) or not fraction.isdigit():
            return False
    else:
        whole = remainder

    return bool(whole) and whole[0].isdigit() and all(
        char.isdigit() or char == "," for char in whole
    )


_FOLLOW_UP_DATE_RE = re.compile(
    r"^(?:what about|how about|and|or)?\s*"
    r"(?:" + "|".join(_MONTH_NAMES) + r"|in \d+\s*(?:day|week|month)s?|"
    r"one (?:month|week))\s*\??$",
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
    messages: list[CopilotMessageIn],
    as_of: date,
    goal_names: list[str] | None = None,
) -> Resolution | Clarify | None:
    """Returns a Resolution to run, a Clarify to ask, or None (unknown).

    `goal_names` is the caller's real savings-goal names (optional) --
    only used to resolve a specific named-goal mention for
    get_goal_intelligence questions, or to ask which goal is meant when
    a bare "my goal" reference is ambiguous across 2+ real goals.
    Omitting it (the default) preserves prior behavior exactly.
    """
    current = messages[-1].content
    history = messages[:-1]

    name = classify_intent(current)

    if name is not None:
        built = build_tool_input(name, current, as_of)
        if isinstance(built, Clarify):
            return built

        if (
            name in ("check_goal_conflicts", "get_goal_intelligence")
            and "monthly_savings_capacity_cents" not in built
            and "monthly_capacity_cents" not in built
        ):
            # The current message didn't restate a capacity -- carry
            # forward an unambiguous one from earlier in this chat
            # rather than silently letting an auto-derived default
            # override what the user already told us.
            prior_capacity = _find_prior_monthly_capacity(history)
            if prior_capacity is not None:
                capacity_key = (
                    "monthly_savings_capacity_cents"
                    if name == "check_goal_conflicts"
                    else "monthly_capacity_cents"
                )
                built = {**built, capacity_key: prior_capacity}

        target_goal_name = None

        if name == "get_goal_intelligence":
            emphasize = _goal_intelligence_emphasis(current)

            if goal_names:
                matched, candidates = match_goal_names(current, goal_names)
                if matched is not None:
                    target_goal_name = matched
                elif candidates:
                    return Clarify(
                        "Which savings goal do you mean -- "
                        + " or ".join(candidates)
                        + "?",
                        candidates[:4],
                    )
                elif (
                    len(goal_names) > 1
                    and emphasize == "overview"
                    and _SINGULAR_GOAL_REF_RE.search(current)
                ):
                    return Clarify(
                        "Which savings goal do you mean -- "
                        + " or ".join(goal_names)
                        + "?",
                        goal_names[:4],
                    )
        elif name == "get_financial_resilience":
            emphasize = _resilience_emphasis(current)
        elif name == "get_recurring_intelligence":
            emphasize = _recurring_intelligence_emphasis(current)
        elif name == "get_spending_anomalies":
            emphasize = _spending_anomaly_emphasis(current)
        else:
            emphasize = None

        return Resolution(name, built, emphasize, target_goal_name)

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

    # A genuine short follow-up amount (e.g. "$500", "20k?") is never
    # long; a long message is by definition not a bare-amount reply, so
    # skip it and let this safely fall through to normal/unknown
    # handling below. The length check is defense-in-depth only --
    # _looks_like_follow_up_amount is plain linear-time string parsing,
    # not a regex, so it has no polynomial-time behavior to bound.
    if (
        len(stripped) <= _MAX_REGEX_INSPECT_CHARS
        and _looks_like_follow_up_amount(stripped)
    ):
        amount = extract_amount_cents(stripped) or _bare_number_cents(
            stripped
        )
        if amount is not None:
            prior = _find_prior_tool(history, as_of)
            if prior and prior[0] == "simulate_major_purchase":
                new_input = dict(prior[1])
                new_input["purchase_amount_cents"] = amount
                return Resolution(prior[0], new_input)
            if prior and prior[0] == "run_what_if":
                new_input = dict(prior[1])
                # Preserve the prior scenario's increase/decrease
                # direction; only the magnitude changes.
                was_decrease = (
                    new_input.get("monthly_amount_change_cents", 0) < 0
                )
                new_input["monthly_amount_change_cents"] = (
                    -amount if was_decrease else amount
                )
                return Resolution(prior[0], new_input)

    if _FOLLOW_UP_DATE_RE.match(stripped):
        follow_up_date = extract_future_date(stripped, as_of)
        if follow_up_date is not None:
            prior = _find_prior_tool(history, as_of)
            if prior and prior[0] == "buy_now_vs_wait":
                new_input = dict(prior[1])
                new_input["wait_until_date"] = follow_up_date.isoformat()
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


def _render_what_if(result, emphasize):
    impact = result.impact
    verb = "improves" if impact.safe_to_spend_delta_cents >= 0 else "reduces"
    answer = (
        "This changes your safe-to-spend from "
        f"{_currency(result.baseline.safe_to_spend_cents)} to "
        f"{_currency(result.scenario.safe_to_spend_cents)} ({verb} it "
        f"by {_currency(abs(impact.safe_to_spend_delta_cents))})."
    )
    why = result.explanation[0].message if result.explanation else None
    what_this_means = None

    if result.goal_impacts:
        worst = min(
            result.goal_impacts,
            key=lambda g: _GOAL_STATUS_RANK.get(g.status, 0),
        )
        if worst.status != "unaffected":
            what_this_means = (
                f"Your {worst.goal_name} goal would become "
                f"{worst.status.replace('_', ' ')} under this scenario."
            )

    actions = ["Try a different amount", "See how this affects your goals"]

    if emphasize == "why":
        answer, why = why, answer

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
    what_this_means_parts = []

    if result.estimated_recovery_days:
        what_this_means_parts.append(
            f"Estimated recovery time: {result.estimated_recovery_days} "
            "days."
        )

    if result.shortfall_cents and result.recovery_recommendation:
        what_this_means_parts.append(
            result.recovery_recommendation.message
        )

    what_this_means = " ".join(what_this_means_parts) or None
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
    top_driver = (
        result.confidence.drivers[0].message
        if result.confidence.drivers
        else None
    )
    why = (
        f"Forecast confidence is {result.confidence.level} "
        f"({round(result.confidence.score)}%)."
        + (f" {top_driver}" if top_driver else "")
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


def _render_goal_intelligence(result, emphasize, target_goal_name=None):
    if not result.goals:
        return (
            "You don't have any active savings goals yet.",
            None,
            None,
            [],
        )

    urgent = next(
        (g for g in result.goals if g.urgency_rank == 1), result.goals[0]
    )

    named = None
    if target_goal_name:
        named = next(
            (
                g
                for g in result.goals
                if g.name.lower() == target_goal_name.lower()
            ),
            None,
        )

    # A specifically named goal (e.g. "Will I reach my Emergency Fund?")
    # is answered about THAT goal, never the aggregate "most urgent"
    # one -- only for the plain overview case; a query that also asked
    # for a specific emphasis (urgent/best_action/etc.) below still gets
    # that emphasis, scoped to the named goal where applicable.
    if named is not None and emphasize in (None, "overview"):
        if named.status == "completed":
            answer = f"{named.name} is already complete."
        elif named.projected_completion_date:
            if named.status in ("on_track", "ahead"):
                answer = (
                    f"Yes -- at your current pace, {named.name} is on "
                    "track to complete around "
                    f"{named.projected_completion_date.isoformat()}."
                )
            else:
                answer = (
                    "Not at your current pace -- "
                    f"{named.name} is realistically projected to "
                    "complete around "
                    f"{named.projected_completion_date.isoformat()}."
                )
        else:
            answer = (
                f"{named.name} doesn't have enough monthly capacity "
                "currently to project a completion date."
            )
        return (
            answer,
            named.explanation,
            None,
            [
                "How much more should I save for it?",
                "What's the smallest change to get it back on track?",
            ],
        )

    if emphasize == "urgent":
        answer = f"{urgent.name} is your most urgent goal."
        return (
            answer,
            urgent.explanation,
            None,
            ["How much should I save for it?", "When can I finish it?"],
        )

    if emphasize == "best_action":
        subject = named or urgent
        action = subject.recommended_action
        if action.type == "no_change_needed":
            answer = action.message
        else:
            answer = f"For {subject.name}: {action.message}"
        why = f"Key driver: {subject.key_driver.replace('_', ' ')}."
        actions = [alt.message for alt in subject.alternative_actions[:2]]
        return (answer, why, None, actions)

    if emphasize == "shortfall_cause":
        if result.largest_pressure_goal_id is None:
            return (
                "You don't currently have a funding shortfall across "
                "your goals.",
                None,
                None,
                [],
            )
        pressure = next(
            g
            for g in result.goals
            if g.goal_id == result.largest_pressure_goal_id
        )
        return (
            f"{pressure.name} is contributing the most to your "
            "shortfall.",
            pressure.explanation,
            None,
            [],
        )

    if emphasize == "required_monthly":
        lines = [
            f"{g.name}: {_currency(g.required_monthly_cents)}/month"
            for g in result.goals
            if g.status != "completed"
        ]
        answer = (
            "Required monthly contributions -- " + "; ".join(lines)
            if lines
            else "All your goals are already funded."
        )
        return answer, result.explanation or None, None, []

    if emphasize == "completion":
        lines = [
            (
                f"{g.name}: {g.projected_completion_date.isoformat()}"
                if g.projected_completion_date
                else f"{g.name}: not enough capacity to project"
            )
            for g in result.goals
            if g.status != "completed"
        ]
        answer = (
            "Projected completion -- " + "; ".join(lines)
            if lines
            else "Your goals are already complete."
        )
        return answer, None, None, []

    if emphasize == "move_date":
        at_risk = [
            g for g in result.goals if g.status in ("at_risk", "conflict")
        ]
        target = at_risk[0] if len(at_risk) == 1 else urgent
        if target.suggested_feasible_target_date:
            answer = (
                f"At your current capacity, {target.name} would "
                "realistically complete around "
                f"{target.suggested_feasible_target_date.isoformat()}."
            )
        else:
            answer = (
                f"{target.name} is already on track for its current "
                "target date."
            )
        return answer, target.explanation, None, []

    answer = (
        f"You have {len(result.goals)} active goal(s); {urgent.name} "
        "needs the most attention."
    )
    return answer, result.explanation or None, None, []


def _render_buy_now_vs_wait(result, emphasize):
    timing_lead = {
        "buy_now": "Buy it now.",
        "wait": f"Wait until {result.wait_until_date.isoformat()}.",
        "either": "Either timing works.",
        "neither": "Neither timing works right now.",
    }[result.recommended_timing]

    answer = timing_lead
    # The methodology assumption is always disclosed alongside the
    # reason -- never just on request -- so the WAIT figures are never
    # mistaken for a real future income/spending forecast.
    why = f"{result.reason} {result.assumption}"
    what_this_means = result.goal_impact_note
    actions = ["Try a different wait date", "See the full comparison"]

    if emphasize == "why":
        answer, why = why, answer
    elif emphasize == "goals" and result.goal_impact_note:
        answer = result.goal_impact_note

    return answer, why, what_this_means, actions


def _render_financial_resilience(result, emphasize):
    runway_display = (
        f"{result.runway_months} month(s)"
        if result.runway_months is not None
        else "no measurable spending"
    )
    answer = f"{result.headline} -- about {runway_display} of runway."
    why = result.why
    what_this_means = result.what_this_means
    actions = result.suggested_actions[:2]

    if emphasize and emphasize.startswith("horizon_"):
        horizon_days = int(emphasize.split("_")[1])
        horizon = next(
            (h for h in result.horizons if h.horizon_days == horizon_days),
            None,
        )
        if horizon:
            spending_phrase = (
                "your essential spending"
                if result.essential_spending_source == "user_provided"
                else "your recent spending pace"
            )
            if horizon.shortfall_cents > 0:
                answer = (
                    f"Over {horizon_days} days without income, you'd be "
                    f"short {_currency(horizon.shortfall_cents)} against "
                    f"{spending_phrase}."
                )
            else:
                answer = (
                    f"Over {horizon_days} days without income, you'd "
                    f"still have {_currency(horizon.remaining_liquid_cents)} "
                    f"left ({horizon.coverage_percent}% covered)."
                )

    return answer, why, what_this_means, actions


def _render_recurring_intelligence(result, emphasize):
    burden = result.burden

    if emphasize == "duplicates":
        if not result.possible_duplicates:
            return (
                "I didn't find any likely duplicate subscriptions.",
                None,
                None,
                [],
            )
        pair = result.possible_duplicates[0]
        return (
            f"{pair.merchant_a} and {pair.merchant_b} look like they "
            "might be the same subscription tracked twice.",
            pair.reason,
            None,
            ["What are my upcoming recurring payments?"],
        )

    if emphasize == "upcoming":
        if not result.upcoming:
            return (
                "You don't have any active recurring payments.",
                None,
                None,
                [],
            )
        lines = [
            f"{o.merchant}: {_currency(o.amount_cents)} in "
            f"{o.days_until_due} day(s)"
            for o in result.upcoming[:5]
        ]
        return (
            "Upcoming recurring payments -- " + "; ".join(lines),
            None,
            None,
            [],
        )

    if emphasize == "burden":
        percent_note = (
            f" ({_percent(burden.percent_of_income)} of your average "
            "income)"
            if burden.percent_of_income is not None
            else ""
        )
        return (
            "Recurring bills cost about "
            f"{_currency(burden.monthly_recurring_cents)} per month "
            f"across {burden.active_recurring_count} active item(s)"
            f"{percent_note}.",
            None,
            None,
            [],
        )

    if emphasize == "changes":
        if not result.amount_changes:
            return (
                "No recurring bill has changed meaningfully recently.",
                None,
                None,
                [],
            )
        lines = [
            f"{c.merchant} {c.status} to "
            f"{_currency(c.current_amount_cents)} (from "
            f"{_currency(c.baseline_amount_cents)})"
            for c in result.amount_changes
        ]
        return (
            "Recurring bill changes -- " + "; ".join(lines),
            None,
            None,
            [],
        )

    answer = (
        f"You have {burden.active_recurring_count} active recurring "
        f"payment(s) costing about "
        f"{_currency(burden.monthly_recurring_cents)}/month."
    )
    notes = []
    if result.amount_changes:
        notes.append(
            f"{len(result.amount_changes)} bill(s) changed meaningfully"
        )
    if result.possible_duplicates:
        notes.append(
            f"{len(result.possible_duplicates)} possible duplicate(s)"
        )
    if result.possibly_missing:
        notes.append(
            f"{len(result.possibly_missing)} possibly missing payment(s)"
        )
    why = "; ".join(notes) if notes else None

    return (answer, why, None, [])


def _render_spending_anomalies(result, emphasize):
    anomalies = result.anomalies

    if emphasize == "repeated":
        repeated = [a for a in anomalies if a.type == "repeated_charge"]
        if not repeated:
            return (
                "I didn't find any repeated/duplicate charges recently.",
                None,
                None,
                [],
            )
        top = repeated[0]
        return (f"{top.title}.", top.reason, None, [])

    if emphasize == "category":
        spikes = [a for a in anomalies if a.type == "category_spike"]
        if not spikes:
            return (
                "No category spending spike stood out this month.",
                None,
                None,
                [],
            )
        top = spikes[0]
        return (f"{top.title}.", top.reason, None, [])

    if not anomalies:
        return (
            "No unusual spending patterns detected from the available "
            "data.",
            None,
            None,
            [],
        )

    top = anomalies[0]
    answer = (
        f"I found {len(anomalies)} unusual spending signal(s); the "
        f"most notable is: {top.title.lower()}."
    )
    why = top.reason

    if emphasize == "why":
        answer, why = why, answer

    return (answer, why, None, [])


_RENDERERS = {
    "get_safe_to_spend": _render_safe_to_spend,
    "simulate_major_purchase": _render_major_purchase,
    "run_what_if": _render_what_if,
    "compare_purchase_scenarios": _render_compare_scenarios,
    "run_stress_test": _render_stress_test,
    "check_goal_conflicts": _render_goal_conflicts,
    "get_cash_flow_forecast": _render_cash_flow_forecast,
    "get_monthly_insights": _render_monthly_insights,
    "get_recommendations": _render_recommendations,
    "get_goal_intelligence": _render_goal_intelligence,
    "buy_now_vs_wait": _render_buy_now_vs_wait,
    "get_financial_resilience": _render_financial_resilience,
    "get_recurring_intelligence": _render_recurring_intelligence,
    "get_spending_anomalies": _render_spending_anomalies,
}


def deterministic_narration(
    tool_name: str,
    result,
    emphasize: str | None = None,
    target_goal_name: str | None = None,
) -> tuple[str, str | None, str | None, list[str]]:
    renderer = _RENDERERS.get(tool_name)
    if renderer is None:
        return ("Here's what I found.", None, None, [])
    if tool_name == "get_goal_intelligence":
        return renderer(result, emphasize, target_goal_name)
    return renderer(result, emphasize)
