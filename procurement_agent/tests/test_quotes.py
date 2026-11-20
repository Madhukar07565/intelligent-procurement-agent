from datetime import date

import pytest


def test_q1_case_insensitive_and_alias(repo, today):
    for name in ["laptop", "LAPTOPS", " Notebook "]:
        quotes, _ = repo.find(name, 1, today)
        assert {q.supplier for q in quotes} == {"Acme Supplies", "TechWorld", "QuickShip Ltd"}


def test_q2_expired_excluded_and_reported(repo, today):
    quotes, excluded = repo.find("laptop", 1, today)
    assert "OldDeals Inc" not in {q.supplier for q in quotes}
    assert [e["supplier"] for e in excluded] == ["OldDeals Inc"]
    assert "expired" in excluded[0]["reason"]


def test_q3_totals_and_delivery_date(repo, today):
    quotes, _ = repo.find("laptop", 50, today)
    acme = next(q for q in quotes if q.supplier == "Acme Supplies")
    assert acme.total_price == 47500.0
    assert acme.delivery_date == date(2026, 11, 30)


def test_q4_unknown_product_is_empty(repo, today):
    assert repo.find("submarine", 1, today) == ([], [])


def test_multiword_product_with_plural(repo, today):
    quotes, _ = repo.find("office chairs", 10, today)
    assert len(quotes) == 2


def test_nonpositive_quantity_rejected(repo, today):
    with pytest.raises(ValueError):
        repo.find("laptop", 0, today)


@pytest.mark.parametrize("requested,expected", [
    ("Dell laptops", "laptop"), ("HP laptop", "laptop"), ("laptop computers", "laptop"),
    ("24-inch monitors", "monitor"), ("4K Monitor", "monitor"), ("displays", "monitor"),
    ("ergonomic chairs", "office chair"), ("Office Chairs", "office chair"),
])
def test_descriptive_product_names_match(repo, today, requested, expected):
    quotes, _ = repo.find(requested, 1, today)
    assert quotes and {q.product for q in quotes} == {expected}


@pytest.mark.parametrize("requested", ["macbook", "desk", "printer paper", "keyboard"])
def test_unrelated_products_do_not_match(repo, today, requested):
    assert repo.find(requested, 1, today) == ([], [])


def test_products_lists_catalog(repo):
    assert repo.products() == ["flow meter", "laptop", "level sensor", "monitor", "office chair",
                               "pressure sensor", "proximity sensor", "temperature sensor"]
