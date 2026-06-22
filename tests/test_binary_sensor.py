"""Tests for the WUD connectivity (health) binary sensor."""
from __future__ import annotations

from custom_components.wud.binary_sensor import WudConnectivitySensor


def _make_sensor(coordinator, entry):
    entity = WudConnectivitySensor.__new__(WudConnectivitySensor)  # pylint: disable=protected-access
    entity.coordinator = coordinator
    entity._entry = entry  # pylint: disable=protected-access
    entity._attr_unique_id = "test_entry_id_connectivity"  # pylint: disable=protected-access
    return entity


def test_is_on_when_last_update_succeeded(mock_coordinator, mock_entry):
    mock_coordinator.last_update_success = True
    entity = _make_sensor(mock_coordinator, mock_entry)
    assert entity.is_on is True


def test_is_off_when_last_update_failed(mock_coordinator, mock_entry):
    mock_coordinator.last_update_success = False
    entity = _make_sensor(mock_coordinator, mock_entry)
    assert entity.is_on is False


def test_stays_available_even_when_disconnected(mock_coordinator, mock_entry):
    """Unlike container entities, the health sensor must report outages."""
    mock_coordinator.last_update_success = False
    entity = _make_sensor(mock_coordinator, mock_entry)
    assert entity.available is True


def test_device_info_is_hub(mock_coordinator, mock_entry):
    entity = _make_sensor(mock_coordinator, mock_entry)
    info = entity.device_info
    assert ("wud", "test_entry_id") in info["identifiers"]
    assert info["name"] == "Potatoflix"
