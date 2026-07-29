import pytest

from app.money import MoneyParseError, format_cents, parse_to_cents


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12.34", 1234),
        ("$1,234.56", 123456),
        ("-45.00", -4500),
        ("(45.00)", -4500),      # accounting-style negative
        ("  +9.9 ", 990),
        ("1000", 100000),
        ("0", 0),
        ("0.05", 5),
    ],
)
def test_parse_to_cents(raw, expected):
    assert parse_to_cents(raw) == expected


def test_parse_rounds_half_up():
    # 10.005 -> 1000.5 cents -> rounds to 1001, never truncates to 1000
    assert parse_to_cents("10.005") == 1001


@pytest.mark.parametrize("bad", ["", "   ", "abc", "$$", None])
def test_parse_rejects_garbage(bad):
    with pytest.raises(MoneyParseError):
        parse_to_cents(bad)


@pytest.mark.parametrize(
    "cents,expected",
    [(1234, "12.34"), (-4500, "-45.00"), (5, "0.05"), (0, "0.00")],
)
def test_format_cents(cents, expected):
    assert format_cents(cents) == expected


def test_roundtrip_no_precision_loss():
    for raw in ["19.99", "0.01", "123456.78", "-0.99"]:
        assert format_cents(parse_to_cents(raw)) == raw.lstrip("+")
