"""The AH shopping list as a to-do list."""

from __future__ import annotations

import re

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ListItem, text_entry
from .const import DOMAIN
from .coordinator import AhListConfigEntry, AhListCoordinator

# "2 × melk", "2x melk", "2 X melk": the format summaries are shown in.
_QUANTITY_PREFIX = re.compile(r"(\d+)\s*[×xX]\s+(.+)", re.DOTALL)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhListConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do list."""
    async_add_entities([AhTodoListEntity(entry.runtime_data)])


def _summary(item: ListItem) -> str:
    if item.quantity > 1:
        return f"{item.quantity} × {item.description}"
    return item.description


def _split_quantity(summary: str) -> tuple[int, str]:
    """Return the quantity and the name from a summary as shown."""
    summary = summary.strip()
    if match := _QUANTITY_PREFIX.fullmatch(summary):
        return int(match.group(1)), match.group(2).strip()
    return 1, summary


def _todo_item(item: ListItem) -> TodoItem:
    return TodoItem(
        uid=item.uid,
        summary=_summary(item),
        status=TodoItemStatus.COMPLETED
        if item.checked
        else TodoItemStatus.NEEDS_ACTION,
    )


class AhTodoListEntity(CoordinatorEntity[AhListCoordinator], TodoListEntity):
    """The main AH shopping list."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, coordinator: AhListCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_list"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the items on the list."""
        return [_todo_item(item) for item in self.coordinator.data]

    def _find(self, uid: str | None) -> ListItem:
        for item in self.coordinator.data:
            if item.uid == uid:
                return item
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="item_not_found",
            translation_placeholders={"uid": str(uid)},
        )

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item as a matched product or as free text."""
        await self.coordinator.async_add_items([(item.summary or "", ())])

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Check off, change the quantity of, or rename an item."""
        existing = self._find(item.uid)
        checked = item.status == TodoItemStatus.COMPLETED
        quantity, name = _split_quantity(item.summary or "")
        if name == existing.description:
            entries = [existing.patch_entry(quantity=quantity, checked=checked)]
        elif existing.product_id is not None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="product_rename"
            )
        else:
            # A renamed text item is a new item; AH has no item ids to rename by.
            entries = [
                existing.patch_entry(quantity=0),
                text_entry(item.summary.strip(), checked=checked),
            ]
        await self.coordinator.async_patch(entries)

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove items from the list."""
        await self.coordinator.async_patch(
            [self._find(uid).patch_entry(quantity=0) for uid in uids]
        )
