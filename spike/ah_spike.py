"""Spike: check the Albert Heijn mobile API calls the integration needs.

Usage:
  python ah_spike.py login-url
  python ah_spike.py login <appie://login-exit?code=... or bare code>
  python ah_spike.py refresh
  python ah_spike.py list
  python ah_spike.py search <query>
  python ah_spike.py roundtrip <query> <free text>

Tokens go to ~/.config/ah_list/spike-tokens.json (mode 600). Every raw
response is written to spike/out/ so the payloads can be studied.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlparse

import aiohttp

BASE_URL = "https://api.ah.nl"
CLIENT_ID = "appie-ios"
CLIENT_VERSION = "9.28"
USER_AGENT = "Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)"
LOGIN_URL = (
    "https://login.ah.nl/login"
    f"?client_id={CLIENT_ID}&redirect_uri=appie://login-exit&response_type=code"
)
LIST_PATH = "/mobile-services/shoppinglist/v2/items"
SEARCH_PATH = "/mobile-services/product/search/v2"

TOKEN_PATH = Path.home() / ".config" / "ah_list" / "spike-tokens.json"
OUT_DIR = Path(__file__).parent / "out"

HEADERS = {
    "User-Agent": USER_AGENT,
    "x-client-name": CLIENT_ID,
    "x-client-version": CLIENT_VERSION,
    "x-application": "AHWEBSHOP",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def parse_code(value: str) -> str:
    value = value.strip()
    if "://" not in value and "?" not in value and "=" not in value:
        return value
    code = parse_qs(urlparse(value).query).get("code", [None])[0]
    if not code:
        raise SystemExit("No code found in input")
    return code


def dump(name: str, status: int, payload: object) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{time.strftime('%H%M%S')}-{name}.json"
    path.write_text(
        json.dumps({"status": status, "body": payload}, indent=2, ensure_ascii=False)
    )
    print(f"  [{status}] raw response -> {path.name}")


def save_tokens(payload: dict) -> None:
    access = payload.get("access_token") or payload.get("accessToken")
    refresh = payload.get("refresh_token") or payload.get("refreshToken")
    expires_in = payload.get("expires_in") or payload.get("expiresIn") or 0
    if not access or not refresh:
        raise SystemExit(f"Token response without tokens; keys: {sorted(payload)}")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.touch(mode=0o600)
    TOKEN_PATH.write_text(
        json.dumps(
            {
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": time.time() + expires_in,
            }
        )
    )
    print(f"  token keys: {sorted(payload)}; expires_in={expires_in}s")


async def read_body(resp: aiohttp.ClientResponse) -> object:
    text = await resp.text()
    try:
        return json.loads(text)
    except ValueError:
        return text


async def auth_post(
    session: aiohttp.ClientSession, path: str, body: dict, name: str
) -> dict:
    async with session.post(BASE_URL + path, json=body, headers=HEADERS) as resp:
        payload = await read_body(resp)
        # Token bodies are not dumped: they hold secrets.
        if resp.status != 200 or not isinstance(payload, dict):
            dump(name, resp.status, payload)
            raise SystemExit(f"{name} failed with HTTP {resp.status}")
        return payload


async def access_token(session: aiohttp.ClientSession) -> str:
    if not TOKEN_PATH.exists():
        raise SystemExit("No tokens; run login first")
    tokens = json.loads(TOKEN_PATH.read_text())
    if tokens["expires_at"] - 60 < time.time():
        print("access token expiring, refreshing")
        payload = await auth_post(
            session,
            "/mobile-auth/v1/auth/token/refresh",
            {"clientId": CLIENT_ID, "refreshToken": tokens["refresh_token"]},
            "refresh",
        )
        save_tokens(payload)
        tokens = json.loads(TOKEN_PATH.read_text())
    return tokens["access_token"]


async def api(
    session: aiohttp.ClientSession, method: str, path: str, name: str, **kwargs
) -> object:
    headers = {**HEADERS, "Authorization": f"Bearer {await access_token(session)}"}
    async with session.request(
        method, BASE_URL + path, headers=headers, **kwargs
    ) as resp:
        payload = await read_body(resp)
        dump(name, resp.status, payload)
        if resp.status >= 400:
            raise SystemExit(f"{method} {path} failed with HTTP {resp.status}")
        return payload


def describe(item: dict) -> str:
    product = (item.get("productDetails") or {}).get("product") or {}
    desc = (
        item.get("description")
        or product.get("title")
        or (item.get("vagueTermDetails") or {}).get("searchTermValue")
    )
    pid = product.get("webshopId")
    kind = f"product {pid}" if pid else "text"
    return f"{item.get('quantity')} x {desc!r} ({kind}, listItemId={item.get('listItemId')})"


async def get_list(session: aiohttp.ClientSession, name: str = "list") -> list[dict]:
    payload = await api(session, "GET", LIST_PATH, name)
    items = (payload.get("items") if isinstance(payload, dict) else None) or []
    print(
        f"  {len(items)} items; top-level keys: {sorted(payload) if isinstance(payload, dict) else '-'}"
    )
    for item in items:
        print("   ", describe(item))
    return items


async def search(session: aiohttp.ClientSession, query: str) -> list[dict]:
    payload = await api(
        session,
        "GET",
        SEARCH_PATH,
        "search",
        params={"query": query, "sortOn": "RELEVANCE", "size": 10, "page": 0},
    )
    products = payload.get("products") or []
    for p in products:
        print(
            f"    {p.get('webshopId')}: {p.get('title')} | {p.get('salesUnitSize')} | "
            f"{p.get('currentPrice') or p.get('priceBeforeBonus')} | bonus={p.get('isBonus')}"
        )
    return products


def product_entry(product_id: int, description: str, quantity: int) -> dict:
    return {
        "productId": product_id,
        "quantity": quantity,
        "type": "SHOPPABLE",
        "originCode": "PRD",
        "description": description,
        "searchTerm": description,
        "strikeThrough": False,
    }


def text_entry(description: str, quantity: int) -> dict:
    return {
        "description": description,
        "quantity": quantity,
        "type": "SHOPPABLE",
        "originCode": "TXT",
        "strikeThrough": False,
    }


async def patch(session: aiohttp.ClientSession, entries: list[dict], name: str) -> None:
    payload = await api(session, "PATCH", LIST_PATH, name, json={"items": entries})
    if isinstance(payload, dict):
        print(f"  response keys: {sorted(payload)}")


async def roundtrip(session: aiohttp.ClientSession, query: str, text: str) -> None:
    print("== list before")
    before = await get_list(session, "list-before")
    print(f"== search {query!r}")
    products = await search(session, query)
    if not products:
        raise SystemExit("No products found")
    product = products[0]
    pid, title = int(product["webshopId"]), product["title"]
    # Removal is by product/description, so it would also remove a real item.
    for item in before:
        listed = ((item.get("productDetails") or {}).get("product") or {}).get(
            "webshopId"
        )
        if listed == pid or item.get("description") == text:
            raise SystemExit(
                f"{describe(item)} is already on the list; pick another query/text"
            )

    print(f"== add product {pid} ({title}) and free text {text!r}")
    await patch(session, [product_entry(pid, query, 1), text_entry(text, 1)], "add")
    print("== list after add")
    after = await get_list(session, "list-after-add")
    print(f"  {len(after) - len(before)} items added")

    print("== remove both (quantity 0)")
    await patch(session, [product_entry(pid, query, 0), text_entry(text, 0)], "remove")
    print("== list after remove")
    final = await get_list(session, "list-after-remove")
    print(
        "  back to start"
        if len(final) == len(before)
        else "  ITEM COUNT DIFFERS FROM START"
    )


async def main(args: list[str]) -> None:
    if not args or args[0] == "login-url":
        print(LOGIN_URL)
        return
    async with aiohttp.ClientSession() as session:
        match args:
            case ["login", value]:
                payload = await auth_post(
                    session,
                    "/mobile-auth/v1/auth/token",
                    {"clientId": CLIENT_ID, "code": parse_code(value)},
                    "login",
                )
                save_tokens(payload)
                print(f"logged in; tokens in {TOKEN_PATH}")
            case ["refresh"]:
                tokens = json.loads(TOKEN_PATH.read_text())
                payload = await auth_post(
                    session,
                    "/mobile-auth/v1/auth/token/refresh",
                    {"clientId": CLIENT_ID, "refreshToken": tokens["refresh_token"]},
                    "refresh",
                )
                save_tokens(payload)
                print("refreshed")
            case ["list"]:
                await get_list(session)
            case ["search", *words]:
                await search(session, " ".join(words))
            case ["roundtrip", query, text]:
                await roundtrip(session, query, text)
            case _:
                raise SystemExit(__doc__)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
