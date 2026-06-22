"""What's Up Docker integration for Home Assistant."""
from __future__ import annotations

from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import WudCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.TIME,
    Platform.UPDATE,
]

WudConfigEntry: TypeAlias = ConfigEntry[WudCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: WudConfigEntry) -> bool:
    """Set up What's Up Docker from a config entry."""
    coordinator = WudCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WudConfigEntry) -> bool:
    """Unload a What's Up Docker config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: WudConfigEntry
) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
