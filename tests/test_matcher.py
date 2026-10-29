"""Tests for choosing a product from search results.

Titles and brands are real AH search results; the previously-bought and
bonus flags are made up.
"""

from __future__ import annotations

import pytest

from custom_components.ah_list.api import Product
from custom_components.ah_list.matcher import (
    choose,
    fits,
    normalize,
    parse_alternative,
    product_name,
)

from .conftest import search_result


def products(*results: dict) -> list[Product]:
    """Build products from search results."""
    return [Product.from_response(r) for r in results]


def test_normalize() -> None:
    """Accents, case and punctuation don't matter."""
    assert normalize("Calvé  Pindakaas-pot!") == "calve pindakaas pot"
    assert normalize("AH Goudse jong 48+") == "ah goudse jong 48+"


def test_product_name_strips_brand() -> None:
    """The brand, also a sub-brand like AH Biologisch, is not part of the name."""
    [plain, organic, other] = products(
        search_result(1, "AH Rucola", "AH"),
        search_result(2, "AH Biologisch Rucola", "AH Biologisch"),
        search_result(3, "Philadelphia Philadelphia original", "Philadelphia"),
    )
    assert product_name(plain) == product_name(organic) == "rucola"
    assert product_name(other) == "philadelphia original"


def test_previously_bought_same_name() -> None:
    """Bought products with one name win, whatever the brand or AH's order."""
    results = products(
        search_result(1, "Campina Halfvolle melk voordeelverpakking", "Campina"),
        search_result(
            2, "Campina Langlekker halfvolle melk 3-pack", "Campina", bonus=True
        ),
        search_result(3, "AH Halfvolle melk", "AH", bought=True),
        search_result(
            4, "De Zaanse Hoeve Halfvolle melk", "De Zaanse Hoeve", bought=True
        ),
    )
    product, reason, candidates = choose("melk", results)
    assert (product.id, reason) == (3, "previously_bought")
    assert [p.id for p in candidates] == [3, 4, 1]


def test_whole_words_only() -> None:
    """ "eieren" does not match "aardbeien", even when that was bought."""
    results = products(
        search_result(1, "AH Nederlandse aardbeien", "AH", bought=True),
        search_result(2, "Johma Ei salade", "Johma", bought=True),
        search_result(3, "AH Biologisch Eieren S M L 4-pack", "AH Biologisch"),
    )
    product, reason, candidates = choose("eieren", results)
    assert (product, reason) == (None, "ambiguous")
    assert [p.id for p in candidates] == [3]


def test_no_fitting_result() -> None:
    """Unrelated results leave the item as free text."""
    results = products(search_result(1, "Greenminds Enveloppen C5 wit", "Greenminds"))
    assert choose("wc papier", results) == (None, "no_match", [])


def test_different_products_bought() -> None:
    """Several different bought products are ambiguous."""
    results = products(
        search_result(1, "AH Mozzarella geraspt", "AH", bought=True),
        search_result(2, "AH Mozzarella light", "AH", bought=True),
        search_result(3, "Galbani Mozzarella mini", "Galbani", bought=True),
        search_result(4, "Galbani Mozzarella", "Galbani"),
    )
    product, reason, candidates = choose("mozzarella", results)
    # Galbani Mozzarella is named exactly "mozzarella" but was never bought.
    assert (product, reason) == (None, "ambiguous")
    assert len(candidates) == 3


def test_exact_name_among_bought() -> None:
    """With several bought products, one named exactly like the query wins."""
    results = products(
        search_result(1, "AH Hagelslag melk", "AH", bought=True),
        search_result(2, "AH Hagelslag puur", "AH", bought=True),
        search_result(3, "AH Hagelslag", "AH", bought=True),
    )
    product, reason, _ = choose("hagelslag", results)
    assert (product.id, reason) == (3, "exact_name")


def test_exact_name_nothing_bought() -> None:
    """Without purchases, an exact name wins over multi-packs and bonus."""
    results = products(
        search_result(1, "AH XL pizzadeeg 2-pack", "AH", bonus=True),
        search_result(2, "AH XL pizzadeeg", "AH"),
    )
    product, reason, candidates = choose("xl pizzadeeg", results)
    assert (product.id, reason) == (2, "exact_name")
    assert [p.id for p in candidates] == [2, 1]
    # The brand may be part of the query.
    assert choose("ah xl pizzadeeg", results)[0].id == 2


def test_bonus_breaks_ties() -> None:
    """Between equally good bought products, the bonus one is chosen."""
    results = products(
        search_result(1, "AH Rucola", "AH", bought=True),
        search_result(
            2, "AH Biologisch Rucola", "AH Biologisch", bought=True, bonus=True
        ),
    )
    assert choose("rucola", results)[0].id == 2


def test_unavailable_skipped() -> None:
    """Products that can't be ordered are never chosen."""
    results = products(
        search_result(1, "AH Gele uien", "AH", bought=True, status="OUT_OF_ASSORTMENT"),
        search_result(2, "AH Rode uien", "AH"),
    )
    product, reason, candidates = choose("uien", results)
    assert (product, reason) == (None, "ambiguous")
    assert [p.id for p in candidates] == [2]


@pytest.mark.parametrize(
    ("term", "title", "expected"),
    [
        # Compounds may be split or joined, both ways.
        ("spek reepjes", "AH Spekreepjes gerookt", True),
        ("spekreepjes", "AH Spek reepjes gerookt", True),
        ("biologische spek reepjes", "AH Biologisch Spekreepjes gerookt", True),
        # Simple endings don't matter.
        ("biologische spekreepjes", "AH Biologisch Spekreepjes gerookt", True),
        ("eieren", "AH Biologisch Eieren S M L", True),
        # Whole words only.
        ("eieren", "AH Nederlandse aardbeien", False),
        ("melk", "AH Opschuimmelk", False),
        # A following word can make it another product.
        ("ei", "Johma Ei salade", False),
        ("aardbei", "Melkunie Breaker aardbei yoghurt", False),
        ("ei", "AH Witte vrije uitloop ei M", True),
    ],
)
def test_fits(term: str, title: str, expected: bool) -> None:
    """Words are compared the Dutch way."""
    assert fits(term, title) is expected


def test_bought_salad_is_not_eggs() -> None:
    """The one bought product with "ei" in it is a salad, so no match."""
    results = products(
        search_result(1, "Johma Ei salade", "Johma", bought=True),
        search_result(2, "AH Aardappel vrije-uitloop ei 3-pack", "AH"),
    )
    product, reason, _ = choose("ei", results)
    assert (product, reason) == (None, "ambiguous")


def test_compound_exact_name() -> None:
    """An exact name is exact whatever the spaces."""
    results = products(
        search_result(1, "AH Spekreepjes", "AH"),
        search_result(2, "AH Spekreepjes gerookt", "AH"),
    )
    product, reason, _ = choose("spek reepjes", results)
    assert (product.id, reason) == (1, "exact_name")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{'name': 'middelgrote scharreleieren'}", "middelgrote scharreleieren"),
        ("  eieren ", "eieren"),
        ("{not a dict", "{not a dict"),
        ("{'other': 1}", "{'other': 1}"),
    ],
)
def test_parse_alternative(text: str, expected: str) -> None:
    """Mealie aliases come as stringified dicts; plain text passes through."""
    assert parse_alternative(text) == expected
