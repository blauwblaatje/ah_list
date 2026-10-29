"""Config flow: log in by pasting the appie:// redirect after the AH login."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    LOGIN_URL,
    AhAuthError,
    AhClient,
    AhError,
    Tokens,
    async_login,
    parse_code,
)
from .const import CONF_REDIRECT_URL, CONF_TOKENS, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCHEMA = vol.Schema({vol.Required(CONF_REDIRECT_URL): str})


class AhListConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the AH shopping list."""

    VERSION = 1

    async def _async_login(
        self, user_input: dict[str, Any]
    ) -> tuple[Tokens | None, str | None, dict[str, str]]:
        """Return tokens and member id, or form errors."""
        code = parse_code(user_input[CONF_REDIRECT_URL])
        if code is None:
            return None, None, {CONF_REDIRECT_URL: "invalid_code"}
        session = async_get_clientsession(self.hass)
        tokens: Tokens | None = None
        try:
            tokens = await async_login(session, code)

            def keep(new: Tokens) -> None:
                nonlocal tokens
                tokens = new

            member_id = await AhClient(session, tokens, keep).async_get_member_id()
        except AhAuthError:
            return None, None, {"base": "invalid_auth"}
        except AhError:
            return None, None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error during AH login")
            return None, None, {"base": "unknown"}
        return tokens, member_id, {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the redirect URL after logging in at AH."""
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, member_id, errors = await self._async_login(user_input)
            if tokens is not None:
                await self.async_set_unique_id(member_id)
                if self.source == SOURCE_REAUTH:
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        data_updates={CONF_TOKENS: tokens.as_dict()},
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Albert Heijn", data={CONF_TOKENS: tokens.as_dict()}
                )
        return self.async_show_form(
            step_id="reauth_confirm" if self.source == SOURCE_REAUTH else "user",
            data_schema=SCHEMA,
            errors=errors,
            description_placeholders={"login_url": LOGIN_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication when the refresh token stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log in again."""
        return await self.async_step_user(user_input)
