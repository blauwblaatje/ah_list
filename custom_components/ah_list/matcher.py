"""Match shopping list text to AH products.

AH's search ranks bonus multi-packs first and returns loosely related
products ("eieren" finds "aardbeien"), so a product is only chosen when it
clearly fits; everything else becomes a free-text item, which is fine for
shopping in the store.

A product is chosen when, in this order:
1. the term has a mapping set by the user;
2. every previously bought result that contains all query words has the
   same name (title without brand), e.g. AH Halfvolle melk in two sizes;
3. a result's name is exactly the query, e.g. "rucola" → AH Rucola. When
   several different fitting products were bought, only those count.

Words are compared the Dutch way: spaces in compounds don't matter ("spek
reepjes" is "spekreepjes"), nor do simple endings ("biologische" is
"biologisch"). A word followed by one that makes it another product ("ei
salade") does not fit. Alternatives, such as Mealie's food aliases, are
tried when the item itself finds no product.
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import logging
import re
from typing import Any
import unicodedata

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api import AhAuthError, AhClient, AhError, Product
from .const import DOMAIN
from .parse import parse_item

_LOGGER = logging.getLogger(__name__)

SEARCH_SIZE = 30
SUGGESTIONS = 3
STORAGE_VERSION = 1

_MULTIPACK = re.compile(r"\b\d+\s*-?\s*(?:pack|pck|pk)\b")

# Words that, right after the query, make it a different product: "ei
# salade" is not eggs, "aardbei yoghurt" not strawberries.
OTHER_PRODUCT = {
    "salade", "saus", "soep", "spread", "dip", "chips", "snack", "snacks",
    "koek", "koeken", "koekjes", "taart", "taartjes", "wafels", "pancakes",
    "crackers", "toast", "yoghurt", "kwark", "vla", "ijs", "drank", "drink",
    "sap", "smoothie", "siroop", "reep", "repen", "mix", "kruiden", "smaak",
    "burger", "burgers", "schotel", "ovenschotel", "maaltijd", "pizza", "wrap",
}  # fmt: skip

# Joining more title words than this into one compound is not tried.
_MAX_COMPOUND = 3


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w+]", " ", text).split())


def compact(text: str) -> str:
    """Return normalized text without spaces, for comparing compounds."""
    return normalize(text).replace(" ", "")


def _stem(word: str) -> str:
    """Drop a simple Dutch ending: biologische → biologisch, eieren → eier."""
    for ending in ("en", "e", "s"):
        if word.endswith(ending) and len(word) - len(ending) >= 4:
            return word[: -len(ending)]
    return word


def fits(term: str, title: str) -> bool:
    """Return whether every word of a normalized term is in a title.

    Consecutive query words may make up one title word and the other way
    round; the word after the last match must not make it another product.
    """
    words = term.split()
    title_words = normalize(title).split()
    # Stem of each title word and of joined neighbours → index of the last.
    spans: dict[str, int] = {}
    for start in range(len(title_words)):
        for end in range(start + 1, min(start + _MAX_COMPOUND, len(title_words)) + 1):
            spans.setdefault(_stem("".join(title_words[start:end])), end - 1)
    last = -1
    i = 0
    while i < len(words):
        for j in range(len(words), i, -1):
            if (index := spans.get(_stem("".join(words[i:j])))) is not None:
                last = max(last, index)
                i = j
                break
        else:
            return False
    return last + 1 >= len(title_words) or title_words[last + 1] not in OTHER_PRODUCT


def parse_alternative(text: str) -> str:
    """Return the name in a Mealie alias ("{'name': 'x'}") or the text."""
    text = text.strip()
    if text.startswith("{"):
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return text
        if isinstance(value, dict) and isinstance(value.get("name"), str):
            return value["name"].strip()
    return text


def product_name(product: Product) -> str:
    """Return the normalized title without the brand."""
    title = normalize(product.title)
    brand = normalize(product.brand or "")
    if brand and title.startswith(brand + " "):
        return title[len(brand) + 1 :]
    return title


@dataclass
class Match:
    """The outcome of matching one item."""

    text: str
    quantity: int
    name: str
    product: Product | None = None
    reason: str = "no_match"
    candidates: list[Product] = field(default_factory=list)
    alternative: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the match for service responses."""
        return {
            "text": self.text,
            "quantity": self.quantity,
            "name": self.name,
            "result": "matched" if self.product else "free_text",
            "reason": self.reason,
            "product": self.product.as_dict() if self.product else None,
            "candidates": [p.as_dict() for p in self.candidates],
            "alternative": self.alternative,
        }


def choose(
    term: str, results: list[Product]
) -> tuple[Product | None, str, list[Product]]:
    """Pick a product for a normalized term from search results.

    Returns the product or None, the reason, and the best candidates.
    """
    fitting = [p for p in results if p.available and fits(term, p.title)]

    def exact(product: Product) -> bool:
        return compact(term) in (compact(product_name(product)), compact(product.title))

    def rank(product: Product) -> tuple:
        name = product_name(product)
        return (
            not product.previously_bought,
            not exact(product),
            bool(_MULTIPACK.search(name)),
            -SequenceMatcher(None, term, name).ratio(),
            not product.is_bonus,
            results.index(product),
        )

    candidates = sorted(fitting, key=rank)[:SUGGESTIONS]
    bought = [p for p in fitting if p.previously_bought]
    if bought and len({compact(product_name(p)) for p in bought}) == 1:
        return min(bought, key=rank), "previously_bought", candidates
    # With several different products bought, only one of those can win.
    if named := [p for p in bought or fitting if exact(p)]:
        return min(named, key=rank), "exact_name", candidates
    return None, "ambiguous" if fitting else "no_match", candidates


class Matcher:
    """Match items, with the user's term → product mappings."""

    def __init__(self, hass: HomeAssistant, entry_id: str, client: AhClient) -> None:
        """Initialise the matcher."""
        self._client = client
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.mappings"
        )
        self.mappings: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load the mappings."""
        data = await self._store.async_load() or {}
        self.mappings = data.get("mappings", {})

    def _mapping_key(self, term: str) -> str | None:
        """Return the stored key that matches a term, ignoring spaces."""
        wanted = compact(parse_item(term)[1])
        return next((key for key in self.mappings if compact(key) == wanted), None)

    async def async_match(self, text: str, alternatives: Sequence[str] = ()) -> Match:
        """Match text to a product, trying the alternatives when it finds none.

        The quantity always comes from the text; without a product the item
        stays free text with its whole text.
        """
        match = await self._async_match_one(text)
        for alternative in alternatives:
            if match.product is not None:
                break
            name = parse_alternative(alternative)
            if not normalize(name) or compact(name) == compact(match.name):
                continue
            found = await self._async_match_one(name)
            if found.product is not None:
                match.product, match.reason = found.product, found.reason
                match.candidates = found.candidates
                match.alternative = name
            elif not match.candidates:
                match.candidates = found.candidates
        return match

    async def _async_match_one(self, text: str) -> Match:
        quantity, name = parse_item(text)
        match = Match(text=text.strip(), quantity=quantity, name=name)
        term = normalize(name)
        if not term:
            return match
        if (key := self._mapping_key(term)) is not None:
            mapped = self.mappings[key]
            match.product = Product(id=mapped["product_id"], title=mapped["title"])
            match.reason = "mapping"
            return match
        try:
            results = await self._client.async_search(name, SEARCH_SIZE)
        except AhAuthError:
            raise
        except AhError as err:
            _LOGGER.warning("Search for %r failed, adding it as text: %s", name, err)
            match.reason = "search_failed"
            return match
        match.product, match.reason, match.candidates = choose(term, results)
        return match

    async def async_set_mapping(self, term: str, product_id: int, title: str) -> str:
        """Map a term to a product; return the normalized term."""
        if (existing := self._mapping_key(term)) is not None:
            del self.mappings[existing]
        key = normalize(parse_item(term)[1])
        self.mappings[key] = {"product_id": product_id, "title": title}
        await self._store.async_save({"mappings": self.mappings})
        return key

    async def async_remove_mapping(self, term: str) -> bool:
        """Remove a mapping; return whether it existed."""
        if (key := self._mapping_key(term)) is None:
            return False
        del self.mappings[key]
        await self._store.async_save({"mappings": self.mappings})
        return True
