"""Currency conversion for salary normalization.

Static rates (EUR base). Override in scoring.yaml if needed.
"""

# Rates: 1 unit of currency X = Y EUR (approximate, as of 2026-04)
_TO_EUR: dict[str, float] = {
    "EUR": 1.0,
    "USD": 0.92,
    "PLN": 0.23,
    "CHF": 1.05,
    "GBP": 1.17,
}


def to_eur(amount: float, currency: str) -> float | None:
    """Convert amount to EUR. Returns None if currency is unknown."""
    rate = _TO_EUR.get(currency.upper())
    if rate is None:
        return None
    return round(amount * rate, 2)
