"""Coordinator that polls the AH shopping list."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AhAuthError, AhClient, AhError, ListItem
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type AhListConfigEntry = ConfigEntry[AhListCoordinator]


class AhListCoordinator(DataUpdateCoordinator[list[ListItem]]):
    """Keep a copy of the AH shopping list."""

    config_entry: AhListConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: AhListConfigEntry, client: AhClient
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def async_patch(self, entries: list[dict[str, Any]]) -> None:
        """Write to the AH list and show the list AH returns."""
        try:
            items = await self.client.async_patch(entries)
        except AhAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except AhError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.async_set_updated_data(items)

    async def _async_update_data(self) -> list[ListItem]:
        try:
            return await self.client.async_get_list()
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AhError as err:
            raise UpdateFailed(str(err)) from err
