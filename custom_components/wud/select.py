"""Select entity platform for What's Up Docker auto-update scheduling."""
from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from datetime import time as dt_time
from typing import Any

import aiohttp
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    AUTO_UPDATE_CONTAINER_TIME,
    AUTO_UPDATE_IMMEDIATELY,
    AUTO_UPDATE_INTEGRATION_TIME,
    AUTO_UPDATE_NEVER,
    DOMAIN,
    TRIGGER_TYPES_UPDATER,
)
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)

AUTO_UPDATE_OPTIONS = [
    AUTO_UPDATE_NEVER,
    AUTO_UPDATE_IMMEDIATELY,
    AUTO_UPDATE_INTEGRATION_TIME,
    AUTO_UPDATE_CONTAINER_TIME,
]


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD auto-update select entities from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    def _handle_coordinator_update() -> None:
        if not coordinator.data:
            return
        new_entities: list[WudAutoUpdateSelect] = []
        for container_key in coordinator.data:
            if container_key not in known_keys:
                known_keys.add(container_key)
                new_entities.append(
                    WudAutoUpdateSelect(coordinator, container_key, entry)
                )
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class WudAutoUpdateSelect(CoordinatorEntity[WudCoordinator], SelectEntity, RestoreEntity):
    """Select entity that controls the auto-update schedule for a WUD-monitored container.

    Options:
    - never: disabled, no automatic updates.
    - immediately: update as soon as a newer image is detected.
    - integration_update_time: update at the time configured in integration options.
    - container_update_time: update at the per-container time (falls back to
      integration time when no container-specific time has been set).
    """

    _attr_has_entity_name = True
    _attr_name = "Auto update"
    _attr_icon = "mdi:update"
    _attr_translation_key = "auto_update"
    _attr_options = AUTO_UPDATE_OPTIONS

    def __init__(
        self,
        coordinator: WudCoordinator,
        container_key: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the auto-update select entity."""
        super().__init__(coordinator)
        self._container_key = container_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{container_key}_auto_update"
        self._attr_current_option = AUTO_UPDATE_NEVER
        self._last_triggered: str | None = None
        self._install_lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Restore previously selected option and trigger key on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            if last_state.state in AUTO_UPDATE_OPTIONS:
                self._attr_current_option = last_state.state
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

    def select_option(self, option: str) -> None:
        """Sync select_option not used; handled via async_select_option."""
        raise NotImplementedError

    async def async_select_option(self, option: str) -> None:
        """Handle user selecting a new option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        if option != AUTO_UPDATE_NEVER:
            await self._async_maybe_trigger()

    @callback
    def _handle_coordinator_update(self) -> None:
        """On each coordinator poll, check whether auto-update should fire."""
        super()._handle_coordinator_update()
        if self._attr_current_option != AUTO_UPDATE_NEVER:
            self.hass.async_create_task(self._async_maybe_trigger())

    def _pending_version(self) -> str | None:
        """Return a version identifier if an update is pending, else None."""
        data = self._container()
        if not data or not data.get("updateAvailable"):
            return None
        result = data.get("result") or {}
        return result.get("tag") or result.get("digest") or "update"

    async def _async_maybe_trigger(self) -> None:
        """Trigger an install if all conditions are met for the current mode."""
        mode = self._attr_current_option
        if mode == AUTO_UPDATE_NEVER or mode is None:
            return

        version = self._pending_version()
        if not version:
            return

        if mode == AUTO_UPDATE_IMMEDIATELY:
            trigger_key = version
        else:
            if mode == AUTO_UPDATE_INTEGRATION_TIME:
                scheduled: dt_time = self.coordinator.get_integration_auto_update_time()
            else:
                scheduled = self.coordinator.get_auto_update_time(self._container_key)
                if scheduled is None:
                    scheduled = self.coordinator.get_integration_auto_update_time()

            now = dt_util.now()
            current = now.time().replace(second=0, microsecond=0)
            if current < scheduled.replace(second=0, microsecond=0):
                return
            trigger_key = f"{version}_{now.date()}"

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
