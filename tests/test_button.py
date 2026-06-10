"""Tests for WudCheckUpdateButton.async_press."""
from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.wud.button import WudCheckUpdateButton

from .conftest import CONTAINER_NO_UPDATE


def _make_button(coordinator, entry, container_key="local_freshrss"):
    entity = WudCheckUpdateButton.__new__(WudCheckUpdateButton)  # pylint: disable=protected-access
    entity.coordinator = coordinator
    entity._container_key = container_key  # pylint: disable=protected-access
    entity._entry = entry  # pylint: disable=protected-access
    entity._attr_unique_id = f"test_{container_key}_check_update"  # pylint: disable=protected-access
    return entity


async def test_press_injects_watch_result_into_coordinator(mock_coordinator, mock_entry):
    """When watch returns a dict, async_set_updated_data should be called, not refresh."""
    updated_container = {**CONTAINER_NO_UPDATE, "updateAvailable": False}
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    mock_coordinator.async_watch_container = AsyncMock(return_value=updated_container)

    entity = _make_button(mock_coordinator, mock_entry)
    await entity.async_press()

    mock_coordinator.async_watch_container.assert_called_once_with("container-abc")
    mock_coordinator.async_set_updated_data.assert_called_once()
    injected = mock_coordinator.async_set_updated_data.call_args[0][0]
    assert injected["local_freshrss"] == updated_container
    mock_coordinator.async_request_refresh.assert_not_called()


async def test_press_falls_back_to_refresh_when_watch_returns_empty(mock_coordinator, mock_entry):
    """When watch returns None/empty, fall back to a full coordinator refresh."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    mock_coordinator.async_watch_container = AsyncMock(return_value=None)

    entity = _make_button(mock_coordinator, mock_entry)
    await entity.async_press()

    mock_coordinator.async_set_updated_data.assert_not_called()
    mock_coordinator.async_request_refresh.assert_called_once()


async def test_press_falls_back_to_refresh_when_watch_returns_non_dict(mock_coordinator, mock_entry):
    """A non-dict response (e.g. empty list) should also fall back to refresh."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    mock_coordinator.async_watch_container = AsyncMock(return_value=[])

    entity = _make_button(mock_coordinator, mock_entry)
    await entity.async_press()

    mock_coordinator.async_set_updated_data.assert_not_called()
    mock_coordinator.async_request_refresh.assert_called_once()


async def test_press_skips_when_no_container_data(mock_coordinator, mock_entry):
    """If coordinator has no data for this container, nothing should be called."""
    mock_coordinator.data = {}

    entity = _make_button(mock_coordinator, mock_entry)
    await entity.async_press()

    mock_coordinator.async_watch_container.assert_not_called()


async def test_press_skips_when_container_has_no_id(mock_coordinator, mock_entry):
    """If the container entry has no 'id', nothing should be called."""
    mock_coordinator.data = {
        "local_freshrss": {**CONTAINER_NO_UPDATE, "id": None}
    }

    entity = _make_button(mock_coordinator, mock_entry)
    await entity.async_press()

    mock_coordinator.async_watch_container.assert_not_called()
