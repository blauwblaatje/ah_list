"""Tests for writing to the AH list through the to-do entity."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ah_list.api import BASE_URL, LIST_PATH
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import LIST_RESPONSE, mock_list, mock_refresh

ENTITY_ID = "todo.ah_lijst"
MILK = "prd:441199"
TEXT = "txt:ahlist test"


@pytest.fixture
async def setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Set up the integration with the standard list."""
    mock_list(aioclient_mock)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def mock_patch(aioclient_mock: AiohttpClientMocker, **kwargs: Any) -> None:
    """Mock a write; by default AH answers with the list plus one new item."""
    response = copy.deepcopy(LIST_RESPONSE)
    response["items"].append(
        {"quantity": 1, "strikedthrough": False, "description": "brood"}
    )
    kwargs.setdefault("json", response)
    aioclient_mock.patch(BASE_URL + LIST_PATH, **kwargs)


def patch_body(aioclient_mock: AiohttpClientMocker) -> list[dict[str, Any]]:
    """Return the items sent in the last PATCH."""
    calls = [call for call in aioclient_mock.mock_calls if call[0] == "PATCH"]
    assert len(calls) == 1
    return calls[0][2]["items"]


async def call(hass: HomeAssistant, service: str, **data: Any) -> None:
    """Call a todo service on the AH list."""
    await hass.services.async_call(
        TODO_DOMAIN, service, data, target={"entity_id": ENTITY_ID}, blocking=True
    )


@pytest.mark.usefixtures("setup")
async def test_add_item(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A new item goes to AH as free text and the response is shown."""
    mock_patch(aioclient_mock)
    await call(hass, "add_item", item=" brood ")

    assert patch_body(aioclient_mock) == [
        {
            "description": "brood",
            "quantity": 1,
            "type": "SHOPPABLE",
            "originCode": "TXT",
            "strikeThrough": False,
        }
    ]
    assert hass.states.get(ENTITY_ID).state == "2"


@pytest.mark.usefixtures("setup")
async def test_check_off_product(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Completing an item sends strikeThrough and keeps the quantity."""
    mock_patch(aioclient_mock)
    await call(hass, "update_item", item=MILK, status="completed")

    assert patch_body(aioclient_mock) == [
        {
            "productId": 441199,
            "quantity": 2,
            "type": "SHOPPABLE",
            "originCode": "PRD",
            "description": "Campina Halfvolle melk",
            "searchTerm": "Campina Halfvolle melk",
            "strikeThrough": True,
        }
    ]


@pytest.mark.usefixtures("setup")
async def test_uncheck_text(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Unchecking a text item uses the description as AH stored it."""
    mock_patch(aioclient_mock)
    await call(hass, "update_item", item=TEXT, status="needs_action")

    [entry] = patch_body(aioclient_mock)
    assert entry["description"] == "ahlist test"
    assert entry["strikeThrough"] is False


@pytest.mark.parametrize(
    ("rename", "quantity"),
    [
        ("5 × Campina Halfvolle melk", 5),
        ("3x Campina Halfvolle melk", 3),
        ("Campina Halfvolle melk", 1),
    ],
)
@pytest.mark.usefixtures("setup")
async def test_change_quantity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, rename: str, quantity: int
) -> None:
    """Editing the "N ×" prefix of a product changes its quantity."""
    mock_patch(aioclient_mock)
    await call(hass, "update_item", item=MILK, rename=rename)

    [entry] = patch_body(aioclient_mock)
    assert (entry["productId"], entry["quantity"]) == (441199, quantity)
    assert entry["strikeThrough"] is False


@pytest.mark.usefixtures("setup")
async def test_rename_product_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A product can't be renamed; nothing is sent."""
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "update_item", item=MILK, rename="Volle melk")
    assert err.value.translation_key == "product_rename"
    assert not [c for c in aioclient_mock.mock_calls if c[0] == "PATCH"]


@pytest.mark.usefixtures("setup")
async def test_rename_text(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Renaming a text item removes the old text and adds the new one."""
    mock_patch(aioclient_mock)
    await call(hass, "update_item", item=TEXT, rename="brood")

    old, new = patch_body(aioclient_mock)
    assert (old["description"], old["quantity"]) == ("ahlist test", 0)
    assert (new["description"], new["quantity"], new["strikeThrough"]) == (
        "brood",
        1,
        True,
    )


@pytest.mark.usefixtures("setup")
async def test_delete_items(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Deleting sends quantity 0 for every item in one request."""
    mock_patch(aioclient_mock, json={"items": []})
    await call(hass, "remove_item", item=[MILK, TEXT])

    assert [
        (e.get("productId"), e["description"], e["quantity"])
        for e in patch_body(aioclient_mock)
    ] == [
        (441199, "Campina Halfvolle melk", 0),
        (None, "ahlist test", 0),
    ]
    assert hass.states.get(ENTITY_ID).state == "0"


@pytest.mark.usefixtures("setup")
async def test_write_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failed write raises and leaves the list as it was."""
    mock_patch(aioclient_mock, status=400, json={"title": "Bad Request"})
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "add_item", item="brood")
    assert err.value.translation_key == "write_failed"
    assert hass.states.get(ENTITY_ID).state == "1"


@pytest.mark.usefixtures("setup")
async def test_write_auth_error_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A revoked login during a write starts reauth."""
    mock_patch(aioclient_mock, status=401, json={})
    mock_refresh(aioclient_mock, status=400, json={})
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "add_item", item="brood")
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
