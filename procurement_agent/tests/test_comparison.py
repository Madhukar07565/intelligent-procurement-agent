from datetime import date, timedelta

import pytest

from procurement.comparison import compare
from procurement.models import Quote

TODAY = date(2026, 11, 20)


def mk(supplier, total, lead):
    return Quote(
        supplier=supplier, quote_ref=supplier[:3], product="laptop",
        unit_price=total, total_price=total, currency="USD",
        lead_time_days=lead, delivery_date=TODAY + timedelta(days=lead),
        valid_until=date(2027, 12, 31),
    )


REQ = TODAY + timedelta(days=14)


def test_c1_cheapest_wins_when_delivery_equal():
    c = compare([mk("A", 100, 7), mk("B", 90, 7)], REQ)
    assert c.recommended.quote.supplier == "B"


def test_c2_cheapest_but_late_loses():
    c = compare([mk("Cheap", 50, 30), mk("OnTime", 100, 7)], REQ)
    assert c.recommended.quote.supplier == "OnTime"
    cheap = next(s for s in c.ranked if s.quote.supplier == "Cheap")
    assert not cheap.eligible and cheap.days_late == 16
    assert c.warnings


def test_c3_none_on_time_closest_wins_with_warning():
    c = compare([mk("A", 100, 20), mk("B", 90, 30)], REQ)
    assert c.recommended.quote.supplier == "A"
    assert any("No supplier can deliver" in w for w in c.warnings)


def test_c4_tie_breaks_on_delivery_then_price():
    # symmetric trade-off with equal weights -> equal score
    c = compare([mk("Fast", 200, 2), mk("Cheap", 100, 12)], REQ, 0.5, 0.5)
    assert c.ranked[0].score == pytest.approx(c.ranked[1].score)
    assert c.recommended.quote.supplier == "Fast"
    # same score and same delivery -> lower price
    c2 = compare([mk("X", 100, 5), mk("Y", 100, 5)], REQ)
    assert {s.quote.supplier for s in c2.ranked} == {"X", "Y"}


def test_c5_single_quote_scores_100():
    c = compare([mk("Solo", 100, 5)], REQ)
    assert c.recommended.score == 100.0


def test_c6_empty_input():
    c = compare([], REQ)
    assert c.recommended is None and c.warnings


@pytest.mark.parametrize("pw,dw", [(0.5, 0.6), (-0.1, 1.1), (0.2, 0.2)])
def test_c7_bad_weights(pw, dw):
    with pytest.raises(ValueError):
        compare([mk("A", 1, 1)], REQ, pw, dw)


def test_weights_change_outcome():
    quotes = [mk("Cheap", 100, 13), mk("Fast", 200, 1)]
    assert compare(quotes, REQ, 0.9, 0.1).recommended.quote.supplier == "Cheap"
    assert compare(quotes, REQ, 0.1, 0.9).recommended.quote.supplier == "Fast"


def test_to_dict_is_json_serializable():
    import json
    json.dumps(compare([mk("A", 100, 7), mk("B", 90, 30)], REQ).to_dict())


def test_winner_vs_runner_up_sentence_is_factual():
    c = compare([mk("Pricey", 150, 2), mk("Cheap", 100, 12)], REQ, 0.4, 0.6)
    assert c.recommended.quote.supplier == "Pricey"
    s = c.to_dict()["winner_vs_runner_up"]
    assert s == "Pricey costs 50.00 USD more than Cheap and delivers 10 day(s) earlier."
    assert compare([mk("Solo", 1, 1)], REQ).to_dict()["winner_vs_runner_up"] is None
