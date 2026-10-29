"""Tests for the search and mapping actions."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ah_list.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import mock_list, mock_search, search_result


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


async def call(hass: HomeAssistant, service: str, **data: Any) -> Any:
    """Call an ah_list action, with a response when it has one."""
    response = service in ("search_products", "get_mappings")
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
