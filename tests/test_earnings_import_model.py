from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.main import EarningsReading


def test_earnings_reading_rejects_negative_balance():
    with pytest.raises(ValidationError):
        EarningsReading(slug="earnfm", balance=-0.01, date="2026-09-14")


def test_earnings_reading_rejects_unbounded_balance():
    with pytest.raises(ValidationError):
        EarningsReading(slug="earnfm", balance=1_000_000_000_001, date="2026-09-14")
