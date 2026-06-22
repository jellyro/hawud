"""Binary sensor platform for What's Up Docker (service health)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WudCoordinator


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the WUD connectivity binary sensor from a config entry."""
    coordinator: WudCoordinator = entry.runtime_data
    async_add_entities([WudConnectivitySensor(coordinator, entry)])


class WudConnectivitySensor(CoordinatorEntity[WudCoordinator], BinarySensorEntity):
    """Reports whether the WUD service is reachable.

    Unlike the per-container entities, this sensor stays available even when the
    connection fails, so the integration can surface the outage instead of just
    hiding everything.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WudCoordinator, entry: ConfigEntry) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_connectivity"

    @property
    def available(self) -> bool:
        """Always available so it can report the connection going down."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the last poll of the WUD API succeeded."""
        return bool(self.coordinator.last_update_success)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the hub device representing the WUD instance."""
        integration_name = (
            self._entry.options.get(CONF_NAME)
            or self._entry.data.get(CONF_NAME, "")
            or "What's Up Docker"
        )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=integration_name,
            manufacturer="What's Up Docker",
            model="WUD Server",
            configuration_url=self.coordinator.url,
        )
