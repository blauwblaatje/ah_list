"""Coordinator that polls the AH shopping list."""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AhAuthError, AhClient, AhError, ListItem, product_entry, text_entry
from .const import DOMAIN, UPDATE_INTERVAL
from .matcher import Match, Matcher

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
        self.matcher = Matcher(hass, entry.entry_id, client)

    async def async_add_items(self, texts: list[str]) -> list[Match]:
        """Match items to products and add them to the AH list in one write.

        AH sets a product's quantity rather than adding to it, so a product
        already on the list gets the new quantity on top; a checked-off one
        starts again from the new quantity.
        """
        matches = []
        for text in texts:
            try:
                matches.append(await self.matcher.async_match(text))
            except AhAuthError as err:
                self.auth_failed(err)
        quantities = {
            item.product_id: item.quantity
            for item in self.data or []
            if item.product_id is not None and not item.checked
        }
        entries: dict[int | str, dict[str, Any]] = {}
        for match in matches:
            if match.product is None:
                # The whole text, so "2 pakken melk" keeps its amount.
                entries[match.text] = text_entry(match.text)
                continue
            product = match.product
            quantities[product.id] = quantities.get(product.id, 0) + match.quantity
            entries[product.id] = product_entry(
                product.id, product.title, quantities[product.id]
            )
        if entries:
            await self.async_patch(list(entries.values()))
        return matches

    def auth_failed(self, err: AhAuthError) -> NoReturn:
        """Start reauth and raise a user-facing error."""
        self.config_entry.async_start_reauth(self.hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err

    async def async_patch(self, entries: list[dict[str, Any]]) -> None:
        """Write to the AH list and show the list AH returns."""
        try:
            items = await self.client.async_patch(entries)
        except AhAuthError as err:
            self.auth_failed(err)
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
