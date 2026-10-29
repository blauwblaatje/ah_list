"""Actions for searching products and managing term → product mappings."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import AhAuthError, AhError
from .const import DOMAIN
from .coordinator import AhListCoordinator
from .matcher import SEARCH_SIZE, choose, normalize
from .parse import parse_item

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_QUERY = "query"
ATTR_TERM = "term"
ATTR_PRODUCT_ID = "product_id"
ATTR_TITLE = "title"
ATTR_ITEM = "item"
ATTR_ALTERNATIVES = "alternatives"

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

ADD_ITEM_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ITEM): cv.string,
        vol.Optional(ATTR_ALTERNATIVES, default=[]): vol.All(
            cv.ensure_list, [cv.string]
        ),
    }
)
SEARCH_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_QUERY): cv.string})
SET_MAPPING_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_TERM): cv.string,
        vol.Required(ATTR_PRODUCT_ID): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_TITLE): cv.string,
    }
)
REMOVE_MAPPING_SCHEMA = vol.Schema({**_ENTRY, vol.Required(ATTR_TERM): cv.string})
GET_MAPPINGS_SCHEMA = vol.Schema(_ENTRY)


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> AhListCoordinator:
    """Return the coordinator of the given or the only loaded entry."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and call.data.get(ATTR_CONFIG_ENTRY_ID) in (None, entry.entry_id)
    ]
    if len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_entry" if not entries else "choose_entry",
        )
    return entries[0].runtime_data


async def _add_item(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    [match] = await coordinator.async_add_items(
        [(call.data[ATTR_ITEM], call.data[ATTR_ALTERNATIVES])]
    )
    return match.as_dict()


async def _search(call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(call.hass, call)
    query = call.data[ATTR_QUERY]
    try:
        results = await coordinator.client.async_search(
            parse_item(query)[1], SEARCH_SIZE
        )
    except AhAuthError as err:
        coordinator.auth_failed(err)
    except AhError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="search_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    product, reason, _ = choose(normalize(parse_item(query)[1]), results)
    return {
        "match": product.as_dict() if product else None,
        "reason": reason,
        "products": [p.as_dict() for p in results],
    }


async def _set_mapping(call: ServiceCall) -> None:
    matcher = _coordinator(call.hass, call).matcher
    term = call.data[ATTR_TERM]
    if not normalize(parse_item(term)[1]):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="empty_term"
        )
    await matcher.async_set_mapping(
        term, call.data[ATTR_PRODUCT_ID], call.data.get(ATTR_TITLE, term)
    )


async def _remove_mapping(call: ServiceCall) -> None:
    matcher = _coordinator(call.hass, call).matcher
    if not await matcher.async_remove_mapping(call.data[ATTR_TERM]):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_mapping",
            translation_placeholders={"term": call.data[ATTR_TERM]},
        )


async def _get_mappings(call: ServiceCall) -> ServiceResponse:
    matcher = _coordinator(call.hass, call).matcher
    return {"mappings": dict(sorted(matcher.mappings.items()))}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    hass.services.async_register(
        DOMAIN,
        "add_item",
        _add_item,
        schema=ADD_ITEM_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "search_products",
        _search,
        schema=SEARCH_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, "set_mapping", _set_mapping, schema=SET_MAPPING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "remove_mapping", _remove_mapping, schema=REMOVE_MAPPING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "get_mappings",
        _get_mappings,
        schema=GET_MAPPINGS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
