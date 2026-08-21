"""Privacy-conscious audit trail for Discero Copilot activity.

Records only bounded operational/security metadata about each Copilot
turn -- e.g. which tool ran, whether it succeeded, latency, and a
stable error code. Never the user's prompt text, the model's prose
answer, chain-of-thought, or raw financial payloads (account numbers,
balances, transaction lists, Plaid/auth tokens).

One audit row covers one "meaningful event" (see PHASE 26 in the
hardening spec this module implements): normally exactly one row per
Copilot turn, with a second row only for the case where an Anthropic
provider failure triggers a free-mode fallback -- both the failed
attempt and the fallback outcome are worth keeping.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import CopilotAuditEvent

logger = logging.getLogger(__name__)

# Stable operational error codes. Internal-only: never surfaced to the
# end user as-is, but safe to log/store since they carry no secrets or
# free-text content.
MODEL_TIMEOUT = "MODEL_TIMEOUT"
MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
MODEL_INVALID_RESPONSE = "MODEL_INVALID_RESPONSE"
TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
TOOL_VALIDATION_FAILED = "TOOL_VALIDATION_FAILED"
TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
RATE_LIMITED = "RATE_LIMITED"
FREE_MODE_FALLBACK = "FREE_MODE_FALLBACK"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

_MAX_METADATA_KEYS = 12
_MAX_STRING_LEN = 200


def new_request_id() -> str:
    """One correlation id per Copilot HTTP request/turn."""
    return uuid.uuid4().hex


def _sanitize_metadata(
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Bounds stored metadata: primitives only, capped keys/length.

    Silently drops anything not a plain str/int/float/bool/None --
    nested objects, lists, or raw payloads never make it into storage.
    """
    if not metadata:
        return None

    clean: dict[str, Any] = {}

    for key, value in list(metadata.items())[:_MAX_METADATA_KEYS]:
        if isinstance(value, str):
            clean[key] = value[:_MAX_STRING_LEN]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value

    return clean or None


def classify_provider_error(exc: Exception) -> str:
    """Maps a provider SDK exception (Anthropic or Groq) to a stable
    error code -- callers never need to know which provider raised it.
    """
    import anthropic
    import groq

    if isinstance(exc, (anthropic.APITimeoutError, groq.APITimeoutError)):
        return MODEL_TIMEOUT
    if isinstance(
        exc,
        (
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
            anthropic.RateLimitError,
            groq.APIConnectionError,
            groq.InternalServerError,
            groq.RateLimitError,
        ),
    ):
        return MODEL_UNAVAILABLE
    if isinstance(
        exc,
        (
            anthropic.APIResponseValidationError,
            anthropic.APIStatusError,
            groq.APIResponseValidationError,
            groq.APIStatusError,
        ),
    ):
        return MODEL_INVALID_RESPONSE
    return UNKNOWN_ERROR


def record_event(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    mode: str,
    event_type: str,
    tool_name: str | None = None,
    intent: str | None = None,
    success: bool | None = None,
    error_code: str | None = None,
    latency_ms: int | None = None,
    model: str | None = None,
    tool_call_count: int | None = None,
    response_kind: str | None = None,
    provenance: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit write -- never raises, never blocks the turn.

    A failure here (e.g. a transient DB error) must not break the
    user-facing Copilot response, so any exception is logged and
    swallowed, and the session is rolled back to keep it usable for
    the rest of the request.
    """
    try:
        event = CopilotAuditEvent(
            user_id=user_id,
            request_id=request_id,
            mode=mode,
            event_type=event_type,
            tool_name=tool_name,
            intent=intent,
            success=success,
            error_code=error_code,
            latency_ms=latency_ms,
            model=model,
            tool_call_count=tool_call_count,
            response_kind=response_kind,
            provenance=provenance,
            event_metadata=_sanitize_metadata(metadata),
        )
        db.add(event)
        db.commit()
    except Exception:
        logger.warning("copilot audit event write failed", exc_info=True)
        db.rollback()
