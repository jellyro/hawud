"""Time entity platform for What's Up Docker scheduled auto-update."""
from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD auto-update time entities from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    def _handle_coordinator_update() -> None:
        if not coordinator.data:
            return
        new_entities: list[WudUpdateTimeEntity] = []
        for container_key in coordinator.data:
            if container_key not in known_keys:
                known_keys.add(container_key)
                new_entities.append(
                    WudUpdateTimeEntity(coordinator, container_key, entry)
                )
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class WudUpdateTimeEntity(CoordinatorEntity[WudCoordinator], TimeEntity, RestoreEntity):
    """Time entity for scheduling a daily auto-update window for a container.

    When set, the auto-update switch will only trigger an available update
    at or after this time each day.  When left unset (None / unknown), updates
    trigger immediately as soon as they are detected.
    """

    _attr_has_entity_name = True
    _attr_name = "Auto update time"
    _attr_icon = "mdi:clock-outline"
    _attr_native_value: dt_time | None = None

    def __init__(
        self,
        coordinator: WudCoordinator,
        container_key: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the scheduled-update time entity."""
        super().__init__(coordinator)
        self._container_key = container_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{container_key}_auto_update_time"

    async def async_added_to_hass(self) -> None:
        """Restore previously saved time on startup and push it to the coordinator."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                parts = last_state.state.split(":")
                self._attr_native_value = dt_time(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                self._attr_native_value = None
        self.coordinator.set_auto_update_time(
            self._container_key, self._attr_native_value
        )
        self.async_write_ha_state()

    def _container(self) -> dict[str, Any] | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._container_key)
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._container() is not None

    @property
    def device_info(self) -> DeviceInfo:
        data = self._container() or {}
        container_name = data.get("name", self._container_key)
        watcher = data.get("watcher", "")
        integration_name = (
            self._entry.options.get(CONF_NAME) or self._entry.data.get(CONF_NAME, "")
        )
        display_name = (
            f"{integration_name} {container_name}" if integration_name else container_name
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._container_key}")},
            name=display_name,
            manufacturer="Docker",
            model=f"Container ({watcher})" if watcher else "Container",
            configuration_url=self.coordinator.url,
        )

    def set_value(self, value: dt_time) -> None:
        """Sync set_value not used; handled via async_set_value."""
        raise NotImplementedError

    async def async_set_value(self, value: dt_time) -> None:
        """Store the new scheduled time and propagate it to the coordinator."""
        self._attr_native_value = value
        self.coordinator.set_auto_update_time(self._container_key, value)
        self.async_write_ha_state()
