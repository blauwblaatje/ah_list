"""Tests for setup, the coordinator and the to-do entity."""

from __future__ import annotations

import time

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.ah_list.api import parse_code
from custom_components.ah_list.const import CONF_TOKENS, DOMAIN
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import mock_list, mock_refresh

ENTITY_ID = "todo.ah_lijst"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_todo_items(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The entity shows the AH list; state counts unchecked items."""
    mock_list(aioclient_mock)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_ID).state == "1"
    result = await hass.services.async_call(
        TODO_DOMAIN,
        "get_items",
        {},
        target={"entity_id": ENTITY_ID},
        blocking=True,
        return_response=True,
    )
    items = result[ENTITY_ID]["items"]
    assert [(i["uid"], i["summary"], i["status"]) for i in items] == [
        ("prd:441199", "2 × Campina Halfvolle melk", "needs_action"),
        ("txt:ahlist test", "ahlist test", "completed"),
    ]
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer access"


async def test_expired_access_token_is_refreshed(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """An expired access token is refreshed first and the new pair stored."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=config_entry.unique_id,
        data={
            CONF_TOKENS: {**config_entry.data[CONF_TOKENS], "expires_at": time.time()}
        },
    )
    mock_refresh(aioclient_mock)
    mock_list(aioclient_mock)
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_TOKENS]["refresh_token"] == "new-refresh"
    assert aioclient_mock.mock_calls[1][3]["Authorization"] == "Bearer new-access"


async def test_unauthorized_refreshes_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A 401 triggers one refresh; when that fails, reauth starts."""
    mock_list(aioclient_mock, status=401, json={})
    mock_refresh(aioclient_mock, status=400, json={})
    await _setup(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_server_error_retries(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """A server error makes setup retry later."""
    mock_list(aioclient_mock, status=500, json={})
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics_redacts_tokens(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Diagnostics have no tokens and no list contents."""
    mock_list(aioclient_mock)
    await _setup(hass, config_entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)

    assert diag["entry"]["data"][CONF_TOKENS] == "**REDACTED**"
    assert diag["items"] == {"total": 2, "products": 1, "free_text": 1, "checked": 1}
    assert "access" not in str(diag)


def test_parse_code() -> None:
    """Codes come out of URLs, console lines and bare input."""
    code = "0a1b2c3d-0000-4000-8000-123456789abc"
    assert parse_code(f"appie://login-exit?code={code}") == code
    assert (
        parse_code(f"Failed to launch 'appie://login-exit?code={code}' because") == code
    )
    assert parse_code(f"  {code}\n") == code
    assert parse_code("https://login.ah.nl/") is None
    assert parse_code("") is None
