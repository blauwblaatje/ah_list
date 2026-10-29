"""The AH shopping list as a to-do list."""

from __future__ import annotations

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ListItem
from .coordinator import AhListConfigEntry, AhListCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AhListConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the to-do list."""
    async_add_entities([AhTodoListEntity(entry.runtime_data)])


def _todo_item(item: ListItem) -> TodoItem:
    summary = item.description
    if item.quantity > 1:
        summary = f"{item.quantity} × {summary}"
    return TodoItem(
        uid=item.uid,
        summary=summary,
        status=TodoItemStatus.COMPLETED
        if item.checked
        else TodoItemStatus.NEEDS_ACTION,
    )


class AhTodoListEntity(CoordinatorEntity[AhListCoordinator], TodoListEntity):
    """The main AH shopping list."""

    _attr_has_entity_name = True
    _attr_translation_key = "shopping_list"

    def __init__(self, coordinator: AhListCoordinator) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_list"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the items on the list."""
        return [_todo_item(item) for item in self.coordinator.data]
