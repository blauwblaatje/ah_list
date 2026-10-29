"""Diagnostics; tokens are redacted and list contents left out."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_TOKENS
from .coordinator import AhListConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AhListConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    items = coordinator.data or []
    return {
        "entry": async_redact_data(entry.as_dict(), {CONF_TOKENS, "unique_id"}),
        "last_update_success": coordinator.last_update_success,
        "items": {
            "total": len(items),
            "products": sum(item.product_id is not None for item in items),
            "free_text": sum(item.product_id is None for item in items),
            "checked": sum(item.checked for item in items),
        },
    }
