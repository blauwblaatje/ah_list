"""Fixtures for the AH shopping list tests."""

from __future__ import annotations

import time

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from yarl import URL

from custom_components.ah_list.api import (
    BASE_URL,
    GRAPHQL_PATH,
    LIST_PATH,
    REFRESH_PATH,
    SEARCH_PATH,
    TOKEN_PATH,
)
from custom_components.ah_list.const import CONF_TOKENS, DOMAIN

MEMBER_ID = "12345678"

TOKEN_RESPONSE = {
    "access_token": "new-access",
    "refresh_token": "new-refresh",
    "expires_in": 604798,
}

# Shapes as returned by the live API (spike/FINDINGS.md).
LIST_RESPONSE = {
    "id": "list-1",
    "activeSorting": "DEFAULT",
    "storeNumber": 1,
    "dateLastSynced": "2026-10-29T16:17:08Z",
    "dateLastSyncedMillis": 0,
    "items": [
        {
            "listItemId": 0,
            "strikedthrough": False,
            "quantity": 2,
            "type": "SHOPPABLE",
            "originCode": "PRD",
            "position": 1,
            "sorting": {"position": 1},
            "productDetails": {
                "missingBonusOffersQuantity": 0,
                "product": {"webshopId": 441199, "title": "Campina Halfvolle melk"},
            },
        },
        {
            "listItemId": 0,
            "strikedthrough": True,
            "quantity": 1,
            "description": "ahlist test",
            "type": "SHOPPABLE",
            "originCode": "TXT",
            "position": 2,
            "sorting": {"position": 1},
            "vagueTermDetails": {"searchTermValue": "ahlist test", "bonus": False},
        },
    ],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry with a valid access token."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Albert Heijn",
        unique_id=MEMBER_ID,
        data={
            CONF_TOKENS: {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
            }
        },
    )


def mock_login(aioclient_mock: AiohttpClientMocker, member_id: str = MEMBER_ID) -> None:
    """Mock the code exchange and the member query."""
    aioclient_mock.post(BASE_URL + TOKEN_PATH, json=TOKEN_RESPONSE)
    aioclient_mock.post(
        BASE_URL + GRAPHQL_PATH, json={"data": {"member": {"id": int(member_id)}}}
    )


def mock_list(aioclient_mock: AiohttpClientMocker, **kwargs) -> None:
    """Mock the shopping list."""
    kwargs.setdefault("json", LIST_RESPONSE)
    aioclient_mock.get(BASE_URL + LIST_PATH, **kwargs)


def mock_refresh(aioclient_mock: AiohttpClientMocker, **kwargs) -> None:
    """Mock the token refresh."""
    kwargs.setdefault("json", TOKEN_RESPONSE)
    aioclient_mock.post(BASE_URL + REFRESH_PATH, **kwargs)


def search_result(
    product_id: int,
    title: str,
    brand: str,
    *,
    bought: bool = False,
    bonus: bool = False,
    status: str = "IN_ASSORTMENT",
) -> dict:
    """Return a product as the search endpoint does (real titles, made-up flags)."""
    return {
        "webshopId": product_id,
        "title": title,
        "brand": brand,
        "salesUnitSize": "1 l",
        "priceBeforeBonus": 1.29,
        "currentPrice": None,
        "isBonus": bonus,
        "isPreviouslyBought": bought,
        "orderAvailabilityStatus": status,
    }


def mock_search(
    aioclient_mock: AiohttpClientMocker, query: str, products: list[dict], **kwargs
) -> None:
    """Mock the product search for one query."""
    kwargs.setdefault("json", {"products": products})
    aioclient_mock.get(URL(BASE_URL + SEARCH_PATH).with_query(query=query), **kwargs)
