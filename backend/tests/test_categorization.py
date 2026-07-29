import pytest

from app.categorization import categorize


@pytest.mark.parametrize(
    "description,expected",
    [
        ("WHOLE FOODS MARKET #123", "Groceries"),
        ("Starbucks Coffee", "Dining"),
        ("UBER TRIP 4AM", "Transport"),
        ("AMAZON.COM*ABC123", "Shopping"),
        ("Comcast Internet", "Utilities"),
        ("Monthly Rent Payment", "Housing"),
        ("NETFLIX.COM", "Subscriptions"),
        ("ACME CORP PAYROLL", "Income"),
        ("CVS Pharmacy", "Health"),
        ("Some Random Vendor XYZ", "Uncategorized"),
    ],
)
def test_categorize(description, expected):
    assert categorize(description) == expected


def test_categorize_is_case_insensitive():
    assert categorize("netflix") == categorize("NETFLIX") == "Subscriptions"


def test_categorize_handles_empty():
    assert categorize("") == "Uncategorized"
    assert categorize(None) == "Uncategorized"
