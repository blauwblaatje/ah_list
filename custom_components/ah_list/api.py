"""Thin client for the Albert Heijn mobile API (unofficial).

Only the calls this integration needs; see spike/FINDINGS.md for what the
live API accepts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import re
import time
from typing import Any

import aiohttp

BASE_URL = "https://api.ah.nl"
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"
LOGIN_URL = (
    "https://login.ah.nl/login"
    f"?client_id={CLIENT_ID}&redirect_uri=appie://login-exit&response_type=code"
)

TOKEN_PATH = "/mobile-auth/v1/auth/token"
REFRESH_PATH = "/mobile-auth/v1/auth/token/refresh"
LIST_PATH = "/mobile-services/shoppinglist/v2/items"
SEARCH_PATH = "/mobile-services/product/search/v2"
GRAPHQL_PATH = "/graphql"

# Refresh the access token this long before it expires.
EXPIRY_MARGIN = 300

_HEADERS = {
    "User-Agent": USER_AGENT,
    "x-client-name": CLIENT_ID,
    "x-client-version": CLIENT_VERSION,
    "x-application": "AHWEBSHOP",
    "Accept": "application/json",
    "Content-Type": "application/json",
}

_CODE_IN_URL = re.compile(r"code=([\w-]+)")
_BARE_CODE = re.compile(r"[\w-]{8,}")


class AhError(Exception):
    """Error talking to the AH API."""


class AhAuthError(AhError):
    """The login code or refresh token was rejected."""


def parse_code(text: str) -> str | None:
    """Return the login code from a pasted redirect URL, console line or bare code."""
    if match := _CODE_IN_URL.search(text):
        return match.group(1)
    text = text.strip()
    if _BARE_CODE.fullmatch(text):
        return text
    return None


@dataclass(frozen=True)
class Tokens:
    """An access/refresh token pair."""

    access_token: str
    refresh_token: str
    expires_at: float

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> Tokens:
        """Build tokens from an auth endpoint response."""
        try:
            return cls(
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
                expires_at=time.time() + int(payload["expires_in"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise AhError(f"Unexpected token response: {sorted(payload)}") from err

    def as_dict(self) -> dict[str, Any]:
        """Return the tokens for storage in a config entry."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class Product:
    """A product from the AH product search."""

    id: int
    title: str
    brand: str | None = None
    unit_size: str | None = None
    price: float | None = None
    is_bonus: bool = False
    previously_bought: bool = False
    available: bool = True

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> Product:
        """Build a product from a search result."""
        price = payload.get("currentPrice") or payload.get("priceBeforeBonus")
        return cls(
            id=int(payload["webshopId"]),
            title=payload.get("title") or "",
            brand=payload.get("brand"),
            unit_size=payload.get("salesUnitSize"),
            price=float(price) if price is not None else None,
            is_bonus=bool(payload.get("isBonus")),
            previously_bought=bool(payload.get("isPreviouslyBought")),
            available=payload.get("orderAvailabilityStatus", "IN_ASSORTMENT")
            == "IN_ASSORTMENT",
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the product for service responses."""
        return {
            "product_id": self.id,
            "title": self.title,
            "unit_size": self.unit_size,
            "price": self.price,
            "bonus": self.is_bonus,
            "previously_bought": self.previously_bought,
        }


@dataclass(frozen=True)
class ListItem:
    """An item on the AH shopping list."""

    description: str
    quantity: int
    checked: bool
    product_id: int | None = None

    @property
    def uid(self) -> str:
        """Return a stable id; AH sends listItemId 0 for every item."""
        if self.product_id is not None:
            return f"prd:{self.product_id}"
        return f"txt:{self.description}"

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> ListItem:
        """Build an item from a shopping list entry."""
        product = (payload.get("productDetails") or {}).get("product") or {}
        product_id = product.get("webshopId")
        description = (
            payload.get("description")
            or product.get("title")
            or (payload.get("vagueTermDetails") or {}).get("searchTermValue")
            or ""
        )
        return cls(
            description=description,
            quantity=int(payload.get("quantity") or 1),
            checked=bool(payload.get("strikedthrough")),
            product_id=int(product_id) if product_id is not None else None,
        )

    def patch_entry(
        self, quantity: int | None = None, checked: bool | None = None
    ) -> dict[str, Any]:
        """Return a PATCH entry for this item; quantity 0 removes it.

        Uses the description as AH stored it, since AH rewrites free text.
        """
        quantity = self.quantity if quantity is None else quantity
        checked = self.checked if checked is None else checked
        if self.product_id is not None:
            return product_entry(self.product_id, self.description, quantity, checked)
        return text_entry(self.description, quantity, checked)


def product_entry(
    product_id: int, description: str, quantity: int = 1, checked: bool = False
) -> dict[str, Any]:
    """Return a PATCH entry for a product."""
    return {
        "productId": product_id,
        "quantity": quantity,
        "type": "SHOPPABLE",
        "originCode": "PRD",
        "description": description,
        "searchTerm": description,
        "strikeThrough": checked,
    }


def text_entry(
    description: str, quantity: int = 1, checked: bool = False
) -> dict[str, Any]:
    """Return a PATCH entry for a free-text item; AH ignores its quantity."""
    return {
        "description": description,
        "quantity": quantity,
        "type": "SHOPPABLE",
        "originCode": "TXT",
        "strikeThrough": checked,
    }


async def _read_json(resp: aiohttp.ClientResponse) -> Any:
    try:
        return await resp.json(content_type=None)
    except ValueError as err:
        raise AhError(
            f"Invalid JSON from {resp.url.path} (HTTP {resp.status})"
        ) from err


async def _auth_post(
    session: aiohttp.ClientSession, path: str, body: dict[str, str]
) -> Tokens:
    try:
        async with session.post(BASE_URL + path, json=body, headers=_HEADERS) as resp:
            if resp.status in (400, 401, 403):
                raise AhAuthError(f"{path} rejected with HTTP {resp.status}")
            if resp.status != 200:
                raise AhError(f"{path} failed with HTTP {resp.status}")
            return Tokens.from_response(await _read_json(resp))
    except aiohttp.ClientError as err:
        raise AhError(f"{path} failed: {err}") from err


async def async_login(session: aiohttp.ClientSession, code: str) -> Tokens:
    """Exchange a login code for tokens."""
    return await _auth_post(session, TOKEN_PATH, {"clientId": CLIENT_ID, "code": code})


class AhClient:
    """Authenticated AH API client that refreshes its own tokens."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens,
        on_tokens: Callable[[Tokens], None],
    ) -> None:
        """Initialise; on_tokens is called with every new token pair."""
        self._session = session
        self._tokens = tokens
        self._on_tokens = on_tokens
        self._refresh_lock = asyncio.Lock()

    async def _refresh(self, stale: Tokens) -> None:
        """Refresh unless another request already replaced the stale tokens."""
        async with self._refresh_lock:
            if self._tokens is not stale:
                return
            self._tokens = await _auth_post(
                self._session,
                REFRESH_PATH,
                {"clientId": CLIENT_ID, "refreshToken": stale.refresh_token},
            )
            self._on_tokens(self._tokens)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if self._tokens.expires_at - EXPIRY_MARGIN < time.time():
            await self._refresh(self._tokens)
        for attempt in range(2):
            tokens = self._tokens
            headers = {
                **_HEADERS,
                "Authorization": f"Bearer {tokens.access_token}",
            }
            try:
                async with self._session.request(
                    method, BASE_URL + path, headers=headers, **kwargs
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        await self._refresh(tokens)
                        continue
                    if resp.status in (401, 403):
                        raise AhAuthError(
                            f"{method} {path} rejected with HTTP {resp.status}"
                        )
                    if resp.status >= 400:
                        raise AhError(f"{method} {path} failed with HTTP {resp.status}")
                    return await _read_json(resp)
            except aiohttp.ClientError as err:
                raise AhError(f"{method} {path} failed: {err}") from err
        raise AhAuthError(f"{method} {path} rejected after token refresh")

    async def async_get_member_id(self) -> str:
        """Return the AH account id."""
        payload = await self._request(
            "POST",
            GRAPHQL_PATH,
            json={"query": "query FetchMember { member { id } }", "variables": {}},
        )
        try:
            return str(payload["data"]["member"]["id"])
        except (KeyError, TypeError) as err:
            raise AhError("No member id in GraphQL response") from err

    async def async_get_list(self) -> list[ListItem]:
        """Return the items on the main shopping list."""
        payload = await self._request("GET", LIST_PATH)
        return [ListItem.from_response(item) for item in payload.get("items") or []]

    async def async_search(self, query: str, size: int = 10) -> list[Product]:
        """Search products, in AH's relevance order."""
        payload = await self._request(
            "GET",
            SEARCH_PATH,
            params={"query": query, "sortOn": "RELEVANCE", "size": size, "page": 0},
        )
        return [
            Product.from_response(item)
            for item in payload.get("products") or []
            if item.get("webshopId") is not None
        ]

    async def async_patch(self, entries: list[dict[str, Any]]) -> list[ListItem]:
        """Add, change or remove items; return the list as it is afterwards."""
        payload = await self._request("PATCH", LIST_PATH, json={"items": entries})
        return [ListItem.from_response(item) for item in payload.get("items") or []]
