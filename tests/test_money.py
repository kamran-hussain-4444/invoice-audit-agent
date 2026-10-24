from decimal import Decimal

import pytest

from invoice_audit.money import format_money, quantize, to_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234.50", "1234.50"),
        ("£1,234.50", "1234.50"),
        ("(100.00)", "-100.00"),
        ("-100", "-100.00"),
        ("1234.5", "1234.50"),
        (" 612.35 ", "612.35"),
        ("€3,200.00", "3200.00"),
        (1243.5, "1243.50"),
        (0.1, "0.10"),
        (1000, "1000.00"),
        (Decimal("9.999"), "10.00"),
    ],
)
def test_to_money_parses(raw, expected):
    assert to_money(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_blank_is_none(raw):
    assert to_money(raw) is None


@pytest.mark.parametrize("raw", ["abc", "12.3.4", True, float("nan")])
def test_garbage_raises(raw):
    with pytest.raises(ValueError):
        to_money(raw)


def test_floats_go_through_str_so_no_binary_noise():
    # Decimal(0.1) would be 0.1000000000000000055511151231257827...
    assert to_money(0.1) + to_money(0.2) == Decimal("0.30")


def test_quantize_rounds_half_up():
    assert quantize(Decimal("2.345")) == Decimal("2.35")
    assert quantize(Decimal("2.344")) == Decimal("2.34")
    assert quantize(Decimal("-2.345")) == Decimal("-2.35")


def test_format_money():
    assert format_money(Decimal("1234.5")) == "£1,234.50"
    assert format_money(Decimal("-9"), "GBP") == "-£9.00"
    assert format_money(Decimal("3200"), "EUR") == "€3,200.00"
    assert format_money(Decimal("10"), "CHF") == "CHF 10.00"
    assert format_money(None) == "amount unknown"
