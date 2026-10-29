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
"""

from __future__ import annotations

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


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w+]", " ", text).split())


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
        }


def choose(
    term: str, results: list[Product]
) -> tuple[Product | None, str, list[Product]]:
    """Pick a product for a normalized term from search results.

    Returns the product or None, the reason, and the best candidates.
    """
    words = term.split()
    fits = [
        p
        for p in results
        if p.available and all(w in normalize(p.title).split() for w in words)
    ]

    def rank(product: Product) -> tuple:
        name = product_name(product)
        return (
            not product.previously_bought,
            name != term,
            bool(_MULTIPACK.search(name)),
            -SequenceMatcher(None, term, name).ratio(),
            not product.is_bonus,
            results.index(product),
        )

    candidates = sorted(fits, key=rank)[:SUGGESTIONS]
    bought = [p for p in fits if p.previously_bought]
    if bought and len({product_name(p) for p in bought}) == 1:
        return min(bought, key=rank), "previously_bought", candidates
    # With several different products bought, only one of those can win.
    exact = [p for p in bought or fits if term in (product_name(p), normalize(p.title))]
    if exact:
        return min(exact, key=rank), "exact_name", candidates
    return None, "ambiguous" if fits else "no_match", candidates


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

    async def async_match(self, text: str) -> Match:
        """Match shopping list text to a product, or leave it as free text."""
        quantity, name = parse_item(text)
        match = Match(text=text.strip(), quantity=quantity, name=name)
        term = normalize(name)
        if not term:
            return match
        if mapped := self.mappings.get(term):
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
        key = normalize(parse_item(term)[1])
        self.mappings[key] = {"product_id": product_id, "title": title}
        await self._store.async_save({"mappings": self.mappings})
        return key

    async def async_remove_mapping(self, term: str) -> bool:
        """Remove a mapping; return whether it existed."""
        key = normalize(parse_item(term)[1])
        if self.mappings.pop(key, None) is None:
            return False
        await self._store.async_save({"mappings": self.mappings})
        return True
