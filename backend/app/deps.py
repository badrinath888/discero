"""Shared FastAPI dependencies."""

from functools import lru_cache

from app.config import settings
from app.llm_categorization import LLMCategorizer


@lru_cache
def get_categorizer() -> LLMCategorizer:
    """One shared categorizer (its cache persists across requests)."""
    return LLMCategorizer(api_key=settings.anthropic_api_key, model=settings.llm_model)
