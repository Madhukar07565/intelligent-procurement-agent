from datetime import date
from pathlib import Path

import pytest

from procurement.quotes import QuoteRepository

TODAY = date(2026, 11, 20)
DATA = Path(__file__).resolve().parent.parent / "data" / "quotes.json"


@pytest.fixture
def today():
    return TODAY


@pytest.fixture
def repo():
    return QuoteRepository(DATA)
