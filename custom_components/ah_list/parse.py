"""Split shopping list text into a quantity to buy and a name to search for.

"2 pakken melk", "melk x2", "2x melk" and "twee pakken melk" buy two of
"melk". A weight, volume or cooking measure ("500 g gehakt", "2 teentjes
knoflook") describes the amount needed, not a count: those buy one.
"""

from __future__ import annotations

import re

MAX_QUANTITY = 99

NUMBER_WORDS = {
    "een": 1,
    "één": 1,
    "twee": 2,
    "drie": 3,
    "vier": 4,
    "vijf": 5,
    "zes": 6,
    "zeven": 7,
    "acht": 8,
    "negen": 9,
    "tien": 10,
}

# Packaging: the number counts these, so it is the quantity to buy.
PACKAGES = {
    "pak", "pakken", "pakje", "pakjes",
    "fles", "flessen", "flesje", "flesjes",
    "zak", "zakken", "zakje", "zakjes",
    "blik", "blikken", "blikje", "blikjes",
    "pot", "potten", "potje", "potjes",
    "doos", "dozen", "doosje", "doosjes",
    "bak", "bakken", "bakje", "bakjes",
    "bos", "bossen", "bosje", "bosjes",
    "rol", "rollen", "net", "netten", "krat", "kratten",
    "stuk", "stuks", "st", "stk", "pk", "tray", "trays",
}  # fmt: skip

# Measures: the number is an amount needed, so one is bought.
MEASURES = {
    "g", "gr", "gram", "kg", "kilo", "mg", "ml", "cl", "dl", "l", "liter",
    "el", "tl", "eetlepel", "eetlepels", "theelepel", "theelepels",
    "snuf", "snufje", "teen", "teentje", "teentjes", "takje", "takjes",
    "plak", "plakken", "plakje", "plakjes", "cup", "cups", "tbsp", "tsp",
}  # fmt: skip


def _alternation(words: set[str] | dict[str, int]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


# A number word needs a space after it, so "eenpersoons" stays a name; an
# "x" only means times when a space follows, so "2 xl pizzadeeg" keeps "xl".
_NUMBER = rf"\d+(?:[.,]\d+)?|(?:{_alternation(NUMBER_WORDS)})(?=\s)"
_UNIT = _alternation(PACKAGES | MEASURES)
_PREFIX = re.compile(
    rf"(?P<number>{_NUMBER})(?:\s*[×x](?=\s))?"
    rf"(?:\s*(?P<unit>{_UNIT})\.?(?=\s))?\s+(?P<rest>.+)",
    re.IGNORECASE | re.DOTALL,
)
_SUFFIX = re.compile(
    r"(?P<rest>.+?)\s*(?:[×x]\s*(?P<times>\d+)|(?P<times2>\d+)\s*[×x]|\((?P<paren>\d+)\))",
    re.IGNORECASE | re.DOTALL,
)


def _number(text: str) -> float:
    text = text.lower()
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    return float(text.replace(",", "."))


def _clamp(quantity: float) -> int:
    return max(1, min(MAX_QUANTITY, int(quantity)))


def parse_item(text: str) -> tuple[int, str]:
    """Return the quantity to buy and the name to search for."""
    text = " ".join(text.split())
    if match := _PREFIX.fullmatch(text):
        if (match["unit"] or "").lower() in MEASURES:
            return 1, match["rest"]
        return _clamp(_number(match["number"])), match["rest"]
    if match := _SUFFIX.fullmatch(text):
        times = match["times"] or match["times2"] or match["paren"]
        return _clamp(int(times)), match["rest"]
    return 1, text
