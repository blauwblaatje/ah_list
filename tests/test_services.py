"""Tests for the search and mapping actions."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ah_list.api import BASE_URL, LIST_PATH, SEARCH_PATH
from custom_components.ah_list.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import LIST_RESPONSE, mock_list, mock_search, search_result


@pytest.fixture
async def setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Set up the integration."""
    mock_list(aioclient_mock)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def mock_patch_list(aioclient_mock: AiohttpClientMocker) -> None:
    """Mock a write that returns the standard list."""
    aioclient_mock.patch(BASE_URL + LIST_PATH, json=LIST_RESPONSE)


async def call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    """Call an ah_list action, with a response when it has one."""
    response = service in ("search_products", "get_mappings", "add_item")
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


@pytest.mark.usefixtures("setup")
async def test_search_products(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Search returns the products and the matcher's choice."""
    mock_search(
        aioclient_mock,
        "tomatenpuree",
        [
            search_result(3527, "AH Tomatenpuree", "AH", bought=True),
            search_result(481844, "Mutti Tomaten concentraat dubbel", "Mutti"),
        ],
    )
    result = await call(hass, "search_products", query="2 blikjes tomatenpuree")

    assert result["match"]["product_id"] == 3527
    assert result["reason"] == "previously_bought"
    assert [p["product_id"] for p in result["products"]] == [3527, 481844]


@pytest.mark.usefixtures("setup")
async def test_mappings(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    """Mappings are stored by normalized term and can be removed."""
    await call(hass, "set_mapping", term="2 pakken Melk", product_id=1525)
    await call(
        hass, "set_mapping", term="pindakaas", product_id=99, title="Calvé Pindakaas"
    )

    result = await call(hass, "get_mappings")
    assert result == {
        "mappings": {
            "melk": {"product_id": 1525, "title": "2 pakken Melk"},
            "pindakaas": {"product_id": 99, "title": "Calvé Pindakaas"},
        }
    }
    await hass.async_block_till_done()
    [stored] = [v for k, v in hass_storage.items() if k.endswith(".mappings")]
    assert stored["data"]["mappings"] == result["mappings"]

    await call(hass, "remove_mapping", term="MELK")
    assert list((await call(hass, "get_mappings"))["mappings"]) == ["pindakaas"]

    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "remove_mapping", term="melk")
    assert err.value.translation_key == "no_mapping"


@pytest.mark.usefixtures("setup")
async def test_empty_term(hass: HomeAssistant) -> None:
    """A term that is only a quantity is refused."""
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "set_mapping", term="!!", product_id=1)
    assert err.value.translation_key == "empty_term"


async def test_no_entry(hass: HomeAssistant) -> None:
    """Actions need a loaded account."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "get_mappings")
    assert err.value.translation_key == "no_entry"


@pytest.mark.usefixtures("setup")
async def test_add_item_tries_alternatives(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """When the item finds no product, the Mealie aliases are tried in order."""
    mock_search(
        aioclient_mock,
        "ei",
        [search_result(1, "Johma Ei salade", "Johma", bought=True)],
    )
    mock_search(aioclient_mock, "eieren", [])
    mock_search(
        aioclient_mock,
        "middelgrote scharreleieren",
        [search_result(2, "AH Middelgrote scharreleieren", "AH")],
    )
    mock_patch_list(aioclient_mock)

    result = await call(
        hass,
        "add_item",
        item="2 stuk ei",
        alternatives=["eieren", "{'name': 'middelgrote scharreleieren'}"],
    )

    assert result["result"] == "matched"
    assert result["product"]["product_id"] == 2
    assert result["alternative"] == "middelgrote scharreleieren"
    assert result["quantity"] == 2
    searched = [
        c[1].query.get("query")
        for c in aioclient_mock.mock_calls
        if c[1].path == SEARCH_PATH
    ]
    assert searched == ["ei", "eieren", "middelgrote scharreleieren"]


@pytest.mark.usefixtures("setup")
async def test_add_item_no_alternative_fits(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without any product the item goes on as its own text."""
    mock_search(aioclient_mock, "peterselie", [])
    mock_search(aioclient_mock, "verse platte peterselie", [])
    mock_patch_list(aioclient_mock)

    result = await call(
        hass,
        "add_item",
        item="10 gram peterselie",
        alternatives=["{'name': 'verse platte peterselie'}"],
    )

    assert result["result"] == "free_text"
    assert result["alternative"] is None
    [patch] = [c for c in aioclient_mock.mock_calls if c[0] == "PATCH"]
    assert patch[2]["items"][0]["description"] == "10 gram peterselie"


@pytest.mark.usefixtures("setup")
async def test_mapping_ignores_spaces(hass: HomeAssistant) -> None:
    """A mapping for "spekreepjes" also serves "spek reepjes"; setting replaces."""
    await call(hass, "set_mapping", term="spekreepjes", product_id=1)
    await call(hass, "set_mapping", term="spek reepjes", product_id=2)
    assert (await call(hass, "get_mappings"))["mappings"] == {
        "spek reepjes": {"product_id": 2, "title": "spek reepjes"}
    }
    await call(hass, "remove_mapping", term="SPEKREEPJES")
    assert (await call(hass, "get_mappings"))["mappings"] == {}
