"""Coordinator that polls the AH shopping list."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
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

    async def _async_update_data(self) -> list[ListItem]:
        try:
            return await self.client.async_get_list()
        except AhAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AhError as err:
            raise UpdateFailed(str(err)) from err
