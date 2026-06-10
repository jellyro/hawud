"""Switch entity platform for What's Up Docker auto-update feature."""
from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import time as dt_time
from typing import Any

import aiohttp
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, TRIGGER_TYPES_UPDATER
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD auto-update switch entities from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    def _handle_coordinator_update() -> None:
        if not coordinator.data:
            return
        new_entities: list[WudAutoUpdateSwitch] = []
        for container_key in coordinator.data:
            if container_key not in known_keys:
                known_keys.add(container_key)
                new_entities.append(
                    WudAutoUpdateSwitch(coordinator, container_key, entry)
                )
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class WudAutoUpdateSwitch(CoordinatorEntity[WudCoordinator], SwitchEntity, RestoreEntity):
    """Switch that enables automatic updates for a WUD-monitored container."""

    _attr_has_entity_name = True
    _attr_name = "Auto update"
    _attr_icon = "mdi:update"

    def __init__(
        self,
        coordinator: WudCoordinator,
        container_key: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the auto-update switch."""
        super().__init__(coordinator)
        self._container_key = container_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{container_key}_auto_update"
        self._attr_is_on = False
        self._last_triggered: str | None = None
        self._install_lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            self._last_triggered = last_state.attributes.get("last_triggered")
        self.async_write_ha_state()

    def _container(self) -> dict[str, Any] | None:
        if self.coordinator.data:
            return self.coordinator.data.get(self._container_key)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Persist trigger tracking key across restarts via state attributes."""
        attrs: dict[str, Any] = {}
        if self._last_triggered:
            attrs["last_triggered"] = self._last_triggered
        return attrs

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

    def turn_on(self, **kwargs: Any) -> None:
        """Sync turn-on not used; handled via async_turn_on."""
        raise NotImplementedError

    def turn_off(self, **kwargs: Any) -> None:
        """Sync turn-off not used; handled via async_turn_off."""
        raise NotImplementedError

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()
        await self._async_maybe_trigger()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """On each coordinator poll, check whether auto-update should fire."""
        super()._handle_coordinator_update()
        if self._attr_is_on:
            self.hass.async_create_task(self._async_maybe_trigger())

    def _pending_version(self) -> str | None:
        """Return a version identifier if an update is pending, else None."""
        data = self._container()
        if not data or not data.get("updateAvailable"):
            return None
        result = data.get("result") or {}
        return result.get("tag") or result.get("digest") or "update"

    async def _async_maybe_trigger(self) -> None:
        """Trigger an install if all conditions (enabled, update available, time) are met."""
        if not self._attr_is_on:
            return

        version = self._pending_version()
        if not version:
            return

        scheduled: dt_time | None = self.coordinator.get_auto_update_time(
            self._container_key
        )
        if scheduled is not None:
            now = dt_util.now()
            current = now.time().replace(second=0, microsecond=0)
            if current < scheduled.replace(second=0, microsecond=0):
                return
            trigger_key = f"{version}_{now.date()}"
        else:
            trigger_key = version

        if self._last_triggered == trigger_key:
            return
        if self._install_lock.locked():
            return

        async with self._install_lock:
            if self._last_triggered == trigger_key:
                return
            data = self._container()
            if not data:
                return
            wud_id = data.get("id")
            if not wud_id:
                return
            container_name = data.get("name", self._container_key)
            _LOGGER.info(
                "Auto-update: triggering container '%s' (version: %s)",
                container_name,
                version,
            )
            try:
                await self._async_run_install(wud_id, container_name)
                self._last_triggered = trigger_key
                self.async_write_ha_state()
            except aiohttp.ClientError as err:
                _LOGGER.error(
                    "Auto-update failed for container '%s': %s", container_name, err
                )

    async def _async_run_install(self, wud_id: str, container_name: str) -> None:
        """Invoke WUD triggers for the container, then request a coordinator refresh."""
        semaphore = self.coordinator.update_semaphore
        try:
            async with (semaphore if semaphore is not None else nullcontext()):
                triggers = await self.coordinator.async_get_container_triggers(wud_id)
                if not triggers:
                    await self.coordinator.async_watch_container(wud_id)
                else:
                    chosen = next(
                        (t for t in triggers if t.get("type") in TRIGGER_TYPES_UPDATER),
                        triggers[0],
                    )
                    _LOGGER.debug(
                        "Auto-update: running trigger '%s/%s' for '%s'",
                        chosen["type"],
                        chosen["name"],
                        container_name,
                    )
                    await self.coordinator.async_run_trigger(
                        wud_id, chosen["type"], chosen["name"]
                    )
        finally:
            await self.coordinator.async_request_refresh()
