from app.llm_categorization import LLMCategorizer


def test_falls_back_to_rules_when_no_key():
    c = LLMCategorizer(api_key=None)
    assert c.enabled is False
    # Behaves exactly like the deterministic rules.
    assert c.categorize("WHOLE FOODS MARKET") == "Groceries"
    assert c.categorize_batch(["Netflix", "Starbucks"]) == ["Subscriptions", "Dining"]


def test_uses_llm_when_key_present(monkeypatch):
    c = LLMCategorizer(api_key="fake-key")
    assert c.enabled is True

    calls = []

    def fake_call(descriptions):
        calls.append(list(descriptions))
        return ["Dining" for _ in descriptions]

    monkeypatch.setattr(c, "_call_llm", fake_call)
    assert c.categorize_batch(["Mystery Bistro"]) == ["Dining"]
    assert calls == [["Mystery Bistro"]]


def test_cache_avoids_repeat_calls(monkeypatch):
    c = LLMCategorizer(api_key="fake-key")
    call_count = {"n": 0}

    def fake_call(descriptions):
        call_count["n"] += 1
        return ["Shopping" for _ in descriptions]

    monkeypatch.setattr(c, "_call_llm", fake_call)

    c.categorize_batch(["Acme Store", "Acme Store", "Acme Store"])
    c.categorize_batch(["Acme Store"])  # already cached

    # Three identical descriptions + a later repeat = exactly ONE llm call.
    assert call_count["n"] == 1


def test_batch_only_sends_uncached(monkeypatch):
    c = LLMCategorizer(api_key="fake-key")
    c._cache["Known Vendor"] = "Shopping"
    sent = []

    def fake_call(descriptions):
        sent.extend(descriptions)
        return ["Dining" for _ in descriptions]

    monkeypatch.setattr(c, "_call_llm", fake_call)
    result = c.categorize_batch(["Known Vendor", "New Vendor"])

    assert result == ["Shopping", "Dining"]
    assert sent == ["New Vendor"]  # cached one was not re-sent


def test_invalid_model_category_falls_back_to_rules(monkeypatch):
    c = LLMCategorizer(api_key="fake-key")

    def fake_call(descriptions):
        return ["NotARealCategory" for _ in descriptions]

    monkeypatch.setattr(c, "_call_llm", fake_call)
    # Model returned junk -> we fall back to the rule result for that item.
    assert c.categorize_batch(["Whole Foods"]) == ["Groceries"]
