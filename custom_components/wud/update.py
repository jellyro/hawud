"""Update entity platform for What's Up Docker."""
from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import nullcontext
from typing import Any

import aiohttp
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    INSTALL_ESTIMATED_DURATION,
    INSTALL_POLL_INTERVAL,
    INSTALL_TIMEOUT,
    PROGRESS_MAX_BEFORE_COMPLETE,
    PROGRESS_UPDATE_INTERVAL,
    TRIGGER_TYPES_UPDATER,
)
from .coordinator import WudCoordinator

_LOGGER = logging.getLogger(__name__)


def _short_digest(digest: str) -> str:
    """Return a short, human-readable form of an image digest.

    Strips any algorithm prefix (e.g. ``sha256:``) and truncates to the first
    12 characters, mirroring how Docker abbreviates digests.
    """
    return digest.split(":")[-1][:12]


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WUD update entities from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    known_keys: set[str] = set()

    def _handle_coordinator_update() -> None:
        """Add entities for any containers discovered since last poll."""
        if not coordinator.data:
            return
        new_entities: list[WudUpdateEntity] = []
        for container_key in coordinator.data:
            if container_key not in known_keys:
                known_keys.add(container_key)
                new_entities.append(WudUpdateEntity(coordinator, container_key, entry))
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
        container_key: str,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the update entity."""
        super().__init__(coordinator)
        self._container_key = container_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{container_key}"
        self._attr_in_progress: bool = False
        self._attr_update_percentage: int | None = None
        self._install_done: asyncio.Event | None = None

    def _container(self) -> dict[str, Any] | None:
        """Return the container data dict from the coordinator, or None."""
        if self.coordinator.data:
            return self.coordinator.data.get(self._container_key)
        return None

    def _wud_id(self) -> str | None:
        """Return the actual WUD container ID used for API calls."""
        data = self._container()
        return data.get("id") if data else None

    @property
    def available(self) -> bool:
        """Unavailable if the coordinator failed or the container vanished."""
        return self.coordinator.last_update_success and self._container() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional container metadata as state attributes."""
        data = self._container()
        if not data:
            return {}
        image = data.get("image", {})
        result = data.get("result") or {}
        attrs: dict[str, Any] = {
            "watcher": data.get("watcher"),
            "container_id": data.get("id"),
            "display_name": data.get("displayName"),
            "image_name": image.get("name"),
            "image_tag": image.get("tag", {}).get("value"),
            "image_digest": image.get("digest", {}).get("value"),
            "registry": image.get("registry", {}).get("url"),
            "new_tag": result.get("tag"),
            "new_digest": result.get("digest"),
            "last_checked": data.get("updateDate"),
        }
        return {k: v for k, v in attrs.items() if v is not None}

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this container."""
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

    @property
    def entity_picture(self) -> str | None:
        """Return a container icon URL from the walkxcode dashboard-icons CDN."""
        data = self._container()
        if not data:
            return None
        image = data.get("image", {})
        raw: str = image.get("name") or data.get("name", "")
        slug = (
            raw.split("/")[-1].split(":")[0].split("@")[0].lower().replace("_", "-")
        )
        if not slug:
            return None
        return f"https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/{slug}.png"

    @property
    def title(self) -> str:
        """Human-readable name shown in Settings > Updates."""
        data = self._container()
        if not data:
            return self._container_key
        return data.get("name", self._container_key)

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
        """Return the newest available version, or installed if up to date.
        """
        data = self._container()
        if not data:
            return None

        if not data.get("updateAvailable", False):
            return self.installed_version

        image = data.get("image", {})
        result = data.get("result") or {}
        installed_tag = image.get("tag", {}).get("value")
        new_tag = result.get("tag")

        # A genuine tag change: show the new tag.
        if new_tag and new_tag != installed_tag:
            return new_tag

        # Tag unchanged (or absent) but the digest moved: digest-only update.
        new_digest = result.get("digest")
        if new_digest:
            short = _short_digest(new_digest)
            return f"{installed_tag} ({short})" if installed_tag else new_digest

        if new_tag:
            return new_tag

        return self.installed_version

    @property
    def release_url(self) -> str | None:
        """Return the release notes / changelog URL if WUD provides one."""
        data = self._container()
        if not data:
            return None
        result = data.get("result") or {}
        return result.get("link")

    @property
    def icon(self) -> str:
        """Return the icon for the container based on its image name."""
        data = self._container()
        if not data:
            return "mdi:docker"

        image = data.get("image", {})
        image_name = image.get("name", "").lower()

        # Map common container images to appropriate icons
        icon_mapping = {
            # Home Assistant
            "homeassistant": "mdi:home-assistant",
            # Databases
            "postgres": "mdi:database",
            "mysql": "mdi:database",
            "mariadb": "mdi:database",
            "mongodb": "mdi:database",
            "redis": "mdi:database",
            "influxdb": "mdi:chart-line",
            # Media servers
            "plex": "mdi:plex",
            "jellyfin": "mdi:play-box-multiple",
            "emby": "mdi:play-box-multiple",
            "radarr": "mdi:filmstrip",
            "sonarr": "mdi:television",
            "lidarr": "mdi:music",
            "bazarr": "mdi:subtitles",
            "prowlarr": "mdi:magnify",
            # Download clients
            "transmission": "mdi:download",
            "deluge": "mdi:download",
            "qbittorrent": "mdi:download",
            "nzbget": "mdi:download",
            "sabnzbd": "mdi:download",
            # Home automation
            "zigbee2mqtt": "mdi:zigbee",
            "mosquitto": "mdi:server-network",
            "node-red": "mdi:nodejs",
            # Monitoring
            "prometheus": "mdi:chart-box",
            "grafana": "mdi:chart-line",
            "portainer": "mdi:docker",
            "watchtower": "mdi:autorenew",
            "ouroboros": "mdi:autorenew",
            # Web servers
            "nginx": "mdi:server",
            "apache": "mdi:server",
            "traefik": "mdi:router",
            "caddy": "mdi:server",
            # Network
            "pihole": "mdi:shield-check",
            "adguard": "mdi:shield-check",
            "cloudflared": "mdi:cloud",
            "wireguard": "mdi:vpn",
            "openvpn": "mdi:vpn",
            # Storage
            "nextcloud": "mdi:cloud",
            "syncthing": "mdi:sync",
            # Other common services
            "vaultwarden": "mdi:shield-key",
            "bitwarden": "mdi:shield-key",
            "paperlessngx": "mdi:file-document",
            "paperless": "mdi:file-document",
            "immich": "mdi:image",
            "homebox": "mdi:package-variant",
            "changedetection": "mdi:eye",
            "uptime-kuma": "mdi:pulse",
            "dozzle": "mdi:docker",
        }

        for key, icon in icon_mapping.items():
            if key in image_name:
                return icon

        return "mdi:docker"

    def install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Sync install not used; updates are handled via async_install."""
        raise NotImplementedError

    def release_notes(self) -> str | None:
        """Release notes are not supported by this integration."""
        return None

    async def _async_wait_for_update(self, wud_id: str) -> None:
        """Poll WUD until the container reports no pending update or timeout.

        Each cycle forces WUD to re-scan the image via the watch endpoint, then
        reads back the container state.  Exits early as soon as updateAvailable
        is False, or after INSTALL_TIMEOUT seconds.
        """
        iterations = max(int(INSTALL_TIMEOUT // INSTALL_POLL_INTERVAL), 1)
        for iteration in range(iterations):
            await asyncio.sleep(INSTALL_POLL_INTERVAL)
            elapsed = (iteration + 1) * INSTALL_POLL_INTERVAL
            try:
                await self.coordinator.async_watch_container(wud_id)
                data = await self.coordinator.async_get_single_container(wud_id)
            except aiohttp.ClientError as err:
                _LOGGER.debug(
                    "Poll %d/%d for '%s' failed: %s",
                    iteration + 1,
                    iterations,
                    self.title,
                    err,
                )
                continue

            if data is not None and not data.get("updateAvailable", True):
                _LOGGER.info(
                    "Container '%s' update confirmed after %d s",
                    self.title,
                    elapsed,
                )
                return

            _LOGGER.debug(
                "Container '%s' still updating — %d/%d s elapsed",
                self.title,
                elapsed,
                INSTALL_TIMEOUT,
            )

        _LOGGER.warning(
            "Update timed out after %d s for container '%s'; "
            "the container may still be updating in the background",
            INSTALL_TIMEOUT,
            self.title,
        )

    async def _async_run_progress(self) -> None:
        """Advance a simulated progress bar until the install is confirmed done.

        The percentage follows an asymptotic curve that approaches
        ``PROGRESS_MAX_BEFORE_COMPLETE`` over ``INSTALL_ESTIMATED_DURATION``
        seconds, so the bar keeps moving (and visibly decelerating) while the
        real pull/recreate runs in the background.  It snaps to 100% once the
        install completes.  Because this is decoupled from the trigger call, a
        transient WUD error no longer collapses the bar instantly.
        """
        assert self._install_done is not None
        start = time.monotonic()
        # Time constant so roughly 95% of the curve is covered within the
        # estimated duration (1 - e^-3 ~= 0.95).
        tau = max(INSTALL_ESTIMATED_DURATION / 3, 1)
        while not self._install_done.is_set():
            elapsed = time.monotonic() - start
            fraction = 1 - math.exp(-elapsed / tau)
            pct = min(
                PROGRESS_MAX_BEFORE_COMPLETE,
                round(PROGRESS_MAX_BEFORE_COMPLETE * fraction),
            )
            if pct != self._attr_update_percentage:
                self._attr_update_percentage = pct
                self.async_write_ha_state()
            try:
                await asyncio.wait_for(
                    self._install_done.wait(), timeout=PROGRESS_UPDATE_INTERVAL
                )
            except asyncio.TimeoutError:
                pass

        self._attr_update_percentage = 100
        self.async_write_ha_state()

    async def _async_trigger_update(self, wud_id: str) -> None:
        """Kick off the actual update via a WUD trigger or watch refresh.

        Prefers docker/compose triggers (which recreate the container) over
        notification-only triggers, falling back to a manual watch refresh when
        no triggers are configured.
        """
        triggers = await self.coordinator.async_get_container_triggers(wud_id)

        if not triggers:
            _LOGGER.info(
                "No triggers configured for container '%s'; "
                "running a watch refresh instead",
                self.title,
            )
            await self.coordinator.async_watch_container(wud_id)
            return

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
            wud_id,
            chosen["type"],
            chosen["name"],
        )

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Update this container, showing an estimated progress bar.

        Honours the coordinator's concurrent-update semaphore, then fires the
        update trigger and polls WUD until the container reports no pending
        update (or the timeout is reached).  A simulated progress bar runs for
        the whole duration so the UI shows continuous progress rather than
        snapping straight back to "update available".
        """
        wud_id = self._wud_id()
        if not wud_id:
            _LOGGER.error("No WUD container ID available for '%s'", self._container_key)
            return

        self._install_done = asyncio.Event()
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        semaphore = self.coordinator.update_semaphore
        progress_task: asyncio.Task[None] | None = None
        try:
            async with (semaphore if semaphore is not None else nullcontext()):
                # Start the bar only once we hold the semaphore, so its timing
                # reflects real work rather than time spent queued.
                progress_task = self.hass.async_create_task(
                    self._async_run_progress()
                )
                try:
                    await self._async_trigger_update(wud_id)
                except aiohttp.ClientError as err:
                    _LOGGER.error(
                        "Failed to trigger update for container '%s': %s; "
                        "continuing to poll in case it still completes",
                        self.title,
                        err,
                    )
                await self._async_wait_for_update(wud_id)
        finally:
            self._install_done.set()
            if progress_task is not None:
                await progress_task
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self._install_done = None
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
