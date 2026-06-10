"""Update entity platform for What's Up Docker."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, TRIGGER_TYPES_UPDATER
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD update entities from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    def _handle_coordinator_update() -> None:
        """Add entities for any containers discovered since last poll."""
        if not coordinator.data:
            return
        new_entities: list[WudUpdateEntity] = []
        for container_id in coordinator.data:
            if container_id not in known_ids:
                known_ids.add(container_id)
                new_entities.append(WudUpdateEntity(coordinator, container_id, entry))
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class WudUpdateEntity(CoordinatorEntity[WudCoordinator], UpdateEntity):
    """Update entity representing a single WUD-monitored Docker container."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    def __init__(
        self,
        coordinator: WudCoordinator,
        container_id: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._container_id = container_id
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_{container_id}"
        self._attr_in_progress: bool | int = False

    def _container(self) -> dict[str, Any] | None:
        """Return the container data dict from the coordinator, or None."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._container_id)
        return None

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator failed or the container vanished."""
        return self.coordinator.last_update_success and self._container() is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this container."""
        data = self._container() or {}
        container_name = data.get("name", self._container_id)
        watcher = data.get("watcher", "")
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._container_id}")},
            name=container_name,
            manufacturer="Docker",
            model=f"Container ({watcher})" if watcher else "Container",
            configuration_url=self.coordinator.url,
        )

    @property
    def title(self) -> str:
        """Human-readable name shown in Settings → Updates."""
        data = self._container()
        if not data:
            return self._container_id
        return data.get("name", self._container_id)

    @property
    def installed_version(self) -> str | None:
        """Return the currently running version tag or digest."""
        data = self._container()
        if not data:
            return None
        image = data.get("image", {})
        tag_value = image.get("tag", {}).get("value")
        if tag_value:
            return tag_value
        return image.get("digest", {}).get("repo")

    @property
    def latest_version(self) -> str | None:
        """Return the newest available version, or installed if up to date."""
        data = self._container()
        if not data:
            return None

        if not data.get("updateAvailable", False):
            return self.installed_version

        result = data.get("result") or {}
        tag = result.get("tag")
        if tag:
            return tag

        digest = result.get("digest")
        if digest:
            return digest

        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the release notes / changelog URL if WUD provides one."""
        data = self._container()
        if not data:
            return None
        result = data.get("result") or {}
        return result.get("link")

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Invoke the WUD trigger to update this container.

        Prefers docker/compose triggers (which actually recreate the container)
        over notification-only triggers. Falls back to a manual watch refresh
        when no triggers are configured.
        """
        self._attr_in_progress = True
        self.async_write_ha_state()

        try:
            triggers = await self.coordinator.async_get_container_triggers(
                self._container_id
            )

            if not triggers:
                _LOGGER.info(
                    "No triggers configured for container '%s'; "
                    "running a watch refresh instead",
                    self.title,
                )
                await self.coordinator.async_watch_container(self._container_id)
            else:
                chosen = next(
                    (t for t in triggers if t.get("type") in TRIGGER_TYPES_UPDATER),
                    triggers[0],
                )
                _LOGGER.info(
                    "Running trigger '%s/%s' for container '%s'",
                    chosen["type"],
                    chosen["name"],
                    self.title,
                )
                await self.coordinator.async_run_trigger(
                    self._container_id,
                    chosen["type"],
                    chosen["name"],
                )
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to trigger update for container '%s': %s",
                self.title,
                err,
            )
        finally:
            self._attr_in_progress = False
            await self.coordinator.async_request_refresh()
