"""Transaction categorization.

Phase 1 uses deterministic keyword rules: fast, free, and fully testable with
no API key. Phase 2 swaps in an LLM categorizer behind the SAME `categorize()`
signature, so nothing downstream changes. Keeping this seam clean is the point
— deterministic logic you can unit-test now, model-based enrichment later.
"""

CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "Groceries": ("whole foods", "trader joe", "safeway", "kroger", "aldi", "grocery"),
    "Dining": ("starbucks", "mcdonald", "chipotle", "restaurant", "cafe", "doordash", "uber eats"),
    "Transport": ("uber", "lyft", "shell", "chevron", "exxon", "gas", "transit", "parking"),
    "Shopping": ("amazon", "target", "walmart", "best buy", "ebay"),
    "Utilities": ("at&t", "verizon", "comcast", "electric", "water", "utility", "internet"),
    "Housing": ("rent", "mortgage", "landlord", "apartment"),
    "Subscriptions": ("netflix", "spotify", "hulu", "disney", "prime", "subscription"),
    "Income": ("payroll", "direct deposit", "salary", "deposit"),
    "Health": ("pharmacy", "cvs", "walgreens", "clinic", "hospital", "dental"),
}

DEFAULT_CATEGORY = "Uncategorized"


def categorize(description: str) -> str:
    """Return a category for a transaction description via keyword match.

    Case-insensitive; first matching rule wins. Falls back to Uncategorized.
    """
    text = (description or "").lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(kw in text for kw in keywords):
            return category
    return DEFAULT_CATEGORY
