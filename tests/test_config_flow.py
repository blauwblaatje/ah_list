"""Tests for the config flow."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.ah_list.api import BASE_URL, TOKEN_PATH
from custom_components.ah_list.const import CONF_REDIRECT_URL, CONF_TOKENS, DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MEMBER_ID, mock_list, mock_login

CONSOLE_LINE = (
    "Failed to launch 'appie://login-exit?code=0a1b2c3d-0000-4000-8000-123456789abc' "
    "because the scheme does not have a registered handler."
)


async def _start(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pasted console line logs in and creates the entry."""
    mock_login(aioclient_mock)
    mock_list(aioclient_mock)
    result = await _start(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: CONSOLE_LINE}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == MEMBER_ID
    assert result["data"][CONF_TOKENS]["refresh_token"] == "new-refresh"
    login_body = aioclient_mock.mock_calls[0][2]
    assert login_body["code"] == "0a1b2c3d-0000-4000-8000-123456789abc"


async def test_invalid_code(hass: HomeAssistant) -> None:
    """Text without a code shows an error without calling AH."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: "https://login.ah.nl/"}
    )
    assert result["errors"] == {CONF_REDIRECT_URL: "invalid_code"}


async def test_rejected_code(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An expired code shows invalid_auth and the form again."""
    aioclient_mock.post(
        BASE_URL + TOKEN_PATH, status=400, json={"title": "Bad Request"}
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: "appie://login-exit?code=old-code-123"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A server error shows cannot_connect."""
    aioclient_mock.post(BASE_URL + TOKEN_PATH, status=503)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: "some-bare-code"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The same AH account cannot be added twice."""
    config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: CONSOLE_LINE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Reauth stores the new tokens."""
    config_entry.add_to_hass(hass)
    mock_login(aioclient_mock)
    mock_list(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: CONSOLE_LINE}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKENS]["refresh_token"] == "new-refresh"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Reauth with another AH account is refused."""
    config_entry.add_to_hass(hass)
    mock_login(aioclient_mock, member_id="87654321")
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_REDIRECT_URL: CONSOLE_LINE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_TOKENS]["refresh_token"] == "refresh"
