"""Button entity platform for What's Up Docker."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD check-for-updates buttons from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    def _handle_coordinator_update() -> None:
        """Add button entities for any containers discovered since last poll."""
        if not coordinator.data:
            return
        new_entities: list[WudCheckUpdateButton] = []
        for container_key in coordinator.data:
            if container_key not in known_keys:
                known_keys.add(container_key)
                new_entities.append(
                    WudCheckUpdateButton(coordinator, container_key, entry)
                )
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class WudCheckUpdateButton(CoordinatorEntity[WudCoordinator], ButtonEntity):
    """Button that triggers WUD to re-check a container for updates."""

    _attr_has_entity_name = True
    _attr_name = "Check for updates"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: WudCoordinator,
        container_key: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._container_key = container_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{container_key}_check_update"

    def _container(self) -> dict[str, Any] | None:
        """Return the container data dict from the coordinator, or None."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._container_key)
        return None

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator failed or the container vanished."""
        return self.coordinator.last_update_success and self._container() is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info matching the corresponding update entity."""
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

    def press(self) -> None:
        """Sync press not used; handled via async_press."""
        raise NotImplementedError

    async def async_press(self) -> None:
        """Ask WUD to re-check this container for a newer image."""
        data = self._container()
        if not data:
            _LOGGER.warning(
                "Cannot check updates: container '%s' not found in coordinator data",
                self._container_key,
            )
            return
        wud_id = data.get("id")
        if not wud_id:
            _LOGGER.warning(
                "Cannot check updates: no WUD ID for container '%s'",
                self._container_key,
            )
            return
        container_name = data.get("name", self._container_key)
        try:
            await self.coordinator.async_watch_container(wud_id)
            _LOGGER.debug("Triggered update check for container '%s'", container_name)
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to check updates for container '%s': %s", container_name, err
            )
            return
        await self.coordinator.async_request_refresh()
