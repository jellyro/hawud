"""DataUpdateCoordinator and WUD API client for What's Up Docker."""
from __future__ import annotations

import asyncio
import logging
from datetime import time as dt_time, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MAX_CONCURRENT_UPDATES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_MAX_CONCURRENT_UPDATES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class WudCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for polling WUD container data."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.url = entry.data[CONF_URL].rstrip("/")
        self._auth: aiohttp.BasicAuth | None = None

        username = entry.data.get(CONF_USERNAME, "")
        password = entry.data.get(CONF_PASSWORD, "")
        if username or password:
            self._auth = aiohttp.BasicAuth(username or "", password or "")

        self._verify_ssl: bool = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self._auto_update_times: dict[str, dt_time | None] = {}

        max_concurrent = int(
            entry.options.get(
                CONF_MAX_CONCURRENT_UPDATES,
                entry.data.get(CONF_MAX_CONCURRENT_UPDATES, DEFAULT_MAX_CONCURRENT_UPDATES),
            )
        )
        self._update_semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        )

        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def update_semaphore(self) -> asyncio.Semaphore | None:
        """Return the semaphore limiting concurrent updates, or None for unlimited."""
        return self._update_semaphore

    def get_auto_update_time(self, container_key: str) -> dt_time | None:
        """Return the scheduled auto-update time for a container, or None."""
        return self._auto_update_times.get(container_key)

    def set_auto_update_time(self, container_key: str, value: dt_time | None) -> None:
        """Store the scheduled auto-update time for a container."""
        self._auto_update_times[container_key] = value

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all container data from the WUD API."""
        session = async_get_clientsession(self.hass, verify_ssl=self._verify_ssl)
        try:
            async with session.get(
                f"{self.url}/api/containers",
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 401:
                    raise ConfigEntryAuthFailed(
                        "Invalid credentials for WUD instance"
                    )
                resp.raise_for_status()
                containers: list[dict[str, Any]] = await resp.json()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Error communicating with WUD API: {err}") from err

        return {
            f"{c.get('watcher', '')}_{c.get('name', c.get('id', ''))}": c
            for c in containers
        }

    async def async_get_container_triggers(
        self, container_id: str
    ) -> list[dict[str, Any]]:
        """Return the list of triggers associated with a container."""
        session = async_get_clientsession(self.hass, verify_ssl=self._verify_ssl)
        try:
            async with session.get(
                f"{self.url}/api/containers/{container_id}/triggers",
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 404:
                    return []
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Failed to fetch triggers for container %s: %s", container_id, err
            )
            return []

    async def async_run_trigger(
        self, container_id: str, trigger_type: str, trigger_name: str
    ) -> None:
        """Execute a specific trigger on a container."""
        session = async_get_clientsession(self.hass, verify_ssl=self._verify_ssl)
        async with session.post(
            f"{self.url}/api/containers/{container_id}/triggers/{trigger_type}/{trigger_name}",
            auth=self._auth,
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            resp.raise_for_status()

    async def async_get_single_container(
        self, container_id: str
    ) -> dict[str, Any] | None:
        """Fetch the current state of a single container from the WUD API."""
        session = async_get_clientsession(self.hass, verify_ssl=self._verify_ssl)
        try:
            async with session.get(
                f"{self.url}/api/containers/{container_id}",
                auth=self._auth,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.debug(
                "Failed to fetch single container %s: %s", container_id, err
            )
            return None

    async def async_watch_container(self, container_id: str) -> dict[str, Any]:
        """Trigger a manual image watch on a specific container."""
        session = async_get_clientsession(self.hass, verify_ssl=self._verify_ssl)
        async with session.post(
            f"{self.url}/api/containers/{container_id}/watch",
            auth=self._auth,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
