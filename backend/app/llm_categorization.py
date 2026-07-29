"""LLM-powered transaction categorization.

This sits behind the SAME idea as the rule-based `categorize()` — given a
description, return a category — but uses an LLM for descriptions the rules
would miss. Three production concerns are handled deliberately:

  1. Fallback: if no API key is configured, it transparently uses the
     deterministic rules. Tests and CI therefore need no secret and stay fast.
  2. Cost: results are cached per description, and uncached descriptions are
     sent in ONE batched request — not one call per row. Categorizing the same
     merchant twice never costs twice.
  3. Testability: the actual network call is isolated in `_call_llm`, so tests
     monkeypatch that one method and exercise all the batching/caching logic
     without touching the network.
"""

from __future__ import annotations

import json

from app.categorization import CATEGORY_RULES, DEFAULT_CATEGORY, categorize

VALID_CATEGORIES = tuple(CATEGORY_RULES.keys()) + (DEFAULT_CATEGORY,)


class LLMCategorizer:
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6") -> None:
        self.api_key = api_key
        self.model = model
        self._cache: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        """LLM path is only used when a key is present; otherwise rules."""
        return bool(self.api_key)

    def categorize(self, description: str) -> str:
        return self.categorize_batch([description])[0]

    def categorize_batch(self, descriptions: list[str]) -> list[str]:
        """Return a category for each description, in order.

        Cached descriptions are served from memory; the rest are resolved in a
        single batched step, then cached.
        """
        if not self.enabled:
            return [categorize(d) for d in descriptions]

        # Which distinct descriptions still need resolving?
        uncached = [d for d in dict.fromkeys(descriptions) if d not in self._cache]
        if uncached:
            predicted = self._call_llm(uncached)
            for desc, cat in zip(uncached, predicted):
                # Guard against the model inventing a category.
                self._cache[desc] = cat if cat in VALID_CATEGORIES else categorize(desc)

        return [self._cache[d] for d in descriptions]

    def _build_prompt(self, descriptions: list[str]) -> str:
        cats = ", ".join(VALID_CATEGORIES)
        items = "\n".join(f"{i}. {d}" for i, d in enumerate(descriptions))
        return (
            "Categorize each bank transaction description into exactly one of "
            f"these categories: {cats}.\n"
            "Reply with ONLY a JSON array of strings, one category per item, in "
            "the same order. No prose.\n\n"
            f"{items}"
        )

    def _call_llm(self, descriptions: list[str]) -> list[str]:
        """Send one batched request and parse the JSON array of categories.

        Isolated so tests can monkeypatch it. Any failure falls back to rules,
        because a categorizer that crashes an upload is worse than one that's
        occasionally less clever.
        """
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)
            resp = client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{"role": "user", "content": self._build_prompt(descriptions)}],
            )
            text = resp.content[0].text.strip()
            categories = json.loads(text)
            if len(categories) != len(descriptions):
                raise ValueError("length mismatch from model")
            return [str(c) for c in categories]
        except Exception:
            return [categorize(d) for d in descriptions]
