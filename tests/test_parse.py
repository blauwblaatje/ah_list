"""Tests for splitting list text into quantity and name."""

from __future__ import annotations

import pytest

from custom_components.ah_list.parse import parse_item


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("melk", (1, "melk")),
        ("2 pakken melk", (2, "melk")),
        ("twee pakken melk", (2, "melk")),
        ("een pak melk", (1, "melk")),
        ("tien zakjes thee", (10, "thee")),
        ("2x melk", (2, "melk")),
        ("2 × AH Halfvolle melk", (2, "AH Halfvolle melk")),
        ("melk x2", (2, "melk")),
        ("melk 2x", (2, "melk")),
        ("appels (3)", (3, "appels")),
        ("2 appels", (2, "appels")),
        ("  6  eieren ", (6, "eieren")),
        ("2 pk. melk", (2, "melk")),
        ("3 st avocado", (3, "avocado")),
        # Measures say how much is needed, not how many to buy.
        ("500 g gehakt", (1, "gehakt")),
        ("500g gehakt", (1, "gehakt")),
        ("1,5 l melk", (1, "melk")),
        ("2 kg aardappelen", (1, "aardappelen")),
        ("2 teentjes knoflook", (1, "knoflook")),
        ("2 el olijfolie", (1, "olijfolie")),
        # Names that start like a quantity.
        ("2 xl pizzadeeg", (2, "xl pizzadeeg")),
        ("AH XL pizzadeeg", (1, "AH XL pizzadeeg")),
        ("7up", (1, "7up")),
        ("eenpersoons dekbed", (1, "eenpersoons dekbed")),
        # Out of range.
        ("0 bananen", (1, "bananen")),
        ("200 bananen", (99, "bananen")),
    ],
)
def test_parse_item(text: str, expected: tuple[int, str]) -> None:
    """Quantities come from counts and packages, not from measures."""
    assert parse_item(text) == expected
