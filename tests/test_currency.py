"""Tests for currency conversion."""

import pytest

from job_matcher.currency import to_eur


@pytest.mark.parametrize(
    "amount, currency, expected",
    [
        (100.0, "EUR", 100.0),
        (100.0, "USD", 92.0),
        (100.0, "PLN", 23.0),
        (100.0, "CHF", 105.0),
        (100.0, "GBP", 117.0),
        (0.0, "EUR", 0.0),
        (100.0, "eur", 100.0),  # case insensitive
    ],
)
def test_known_currencies(amount: float, currency: str, expected: float):
    assert to_eur(amount, currency) == expected


def test_unknown_currency_returns_none():
    assert to_eur(100.0, "JPY") is None


def test_unknown_currency_empty_string():
    assert to_eur(100.0, "") is None
