"""Tests for WudAutoUpdateSwitch — trigger logic, deduplication, time scheduling."""
from __future__ import annotations
# pylint: disable=protected-access

import asyncio
from datetime import datetime, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.wud.switch import WudAutoUpdateSwitch

from .conftest import CONTAINER_NO_UPDATE, CONTAINER_WITH_UPDATE


def _make_switch(coordinator, entry, container_key="local_freshrss"):
    """Build a WudAutoUpdateSwitch bypassing HA entity lifecycle via __new__."""
    entity = WudAutoUpdateSwitch.__new__(WudAutoUpdateSwitch)
    entity.coordinator = coordinator
    entity._container_key = container_key
    entity._entry = entry
    entity._attr_unique_id = f"test_{container_key}_auto_update"
    entity._attr_is_on = False
    entity._last_triggered = None
    entity._install_lock = asyncio.Lock()
    entity.async_write_ha_state = MagicMock()
    entity.hass = MagicMock()
    return entity


# ---------------------------------------------------------------------------
# _pending_version
# ---------------------------------------------------------------------------

def test_pending_version_none_when_no_update(mock_coordinator, mock_entry):
    """_pending_version returns None when updateAvailable is False."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    entity = _make_switch(mock_coordinator, mock_entry)
    assert entity._pending_version() is None


def test_pending_version_returns_tag(mock_coordinator, mock_entry):
    """_pending_version returns the result tag when an update is available."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    entity = _make_switch(mock_coordinator, mock_entry)
    assert entity._pending_version() == "1.30.0"


def test_pending_version_returns_digest_when_no_tag(mock_coordinator, mock_entry):
    """_pending_version falls back to result digest when no tag is present."""
    mock_coordinator.data = {
        "local_freshrss": {**CONTAINER_NO_UPDATE, "updateAvailable": True, "result": {"digest": "sha256:xyz"}}
    }
    entity = _make_switch(mock_coordinator, mock_entry)
    assert entity._pending_version() == "sha256:xyz"


def test_pending_version_fallback_string(mock_coordinator, mock_entry):
    """_pending_version returns the literal string 'update' when result has no tag or digest."""
    mock_coordinator.data = {
        "local_freshrss": {**CONTAINER_NO_UPDATE, "updateAvailable": True, "result": {}}
    }
    entity = _make_switch(mock_coordinator, mock_entry)
    assert entity._pending_version() == "update"


def test_pending_version_none_when_container_missing(mock_coordinator, mock_entry):
    """_pending_version returns None when the container is absent from coordinator data."""
    mock_coordinator.data = {}
    entity = _make_switch(mock_coordinator, mock_entry)
    assert entity._pending_version() is None


# ---------------------------------------------------------------------------
# _async_maybe_trigger — switch is off
# ---------------------------------------------------------------------------

async def test_no_trigger_when_switch_off(mock_coordinator, mock_entry):
    """No API calls should be made when the auto-update switch is off."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = False

    await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_not_called()
    mock_coordinator.async_request_refresh.assert_not_called()


# ---------------------------------------------------------------------------
# _async_maybe_trigger — immediate mode (no scheduled time)
# ---------------------------------------------------------------------------

async def test_triggers_immediately_when_update_available(mock_coordinator, mock_entry):
    """Switch fires an install as soon as an update is detected when no time is scheduled."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = None

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True

    await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()
    assert entity._last_triggered == "1.30.0"


async def test_no_double_trigger_same_version(mock_coordinator, mock_entry):
    """When the same version has already been triggered, skip the install."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = None

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True
    entity._last_triggered = "1.30.0"

    await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_not_called()


async def test_re_triggers_for_new_version(mock_coordinator, mock_entry):
    """A new upstream version resets deduplication and triggers a fresh install."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = None

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True
    entity._last_triggered = "1.29.1"  # previously triggered version

    await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_called_once()
    assert entity._last_triggered == "1.30.0"


async def test_no_trigger_when_no_update_available(mock_coordinator, mock_entry):
    """No install is fired when updateAvailable is False, even with switch on."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = None

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True

    await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_not_called()


# ---------------------------------------------------------------------------
# _async_maybe_trigger — timed mode
# ---------------------------------------------------------------------------

async def test_triggers_when_time_has_passed(mock_coordinator, mock_entry):
    """Install fires when the current time is at or past the scheduled time."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = dt_time(3, 0)

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True

    fake_now = datetime(2024, 1, 15, 4, 0)  # 4:00 AM, after scheduled 3:00 AM
    with patch("custom_components.wud.switch.dt_util.now", return_value=fake_now):
        await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_called_once()
    assert entity._last_triggered == "1.30.0_2024-01-15"


async def test_no_trigger_before_scheduled_time(mock_coordinator, mock_entry):
    """Install is held back when current time is before the scheduled time."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = dt_time(3, 0)

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True

    fake_now = datetime(2024, 1, 15, 2, 0)  # 2:00 AM, before scheduled 3:00 AM
    with patch("custom_components.wud.switch.dt_util.now", return_value=fake_now):
        await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_not_called()


async def test_no_double_trigger_same_version_same_day(mock_coordinator, mock_entry):
    """Timed trigger does not fire twice for the same version on the same day."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = dt_time(3, 0)

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True
    entity._last_triggered = "1.30.0_2024-01-15"

    fake_now = datetime(2024, 1, 15, 4, 0)
    with patch("custom_components.wud.switch.dt_util.now", return_value=fake_now):
        await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_not_called()


async def test_triggers_again_next_day(mock_coordinator, mock_entry):
    """Timed trigger fires on a new day even when the same version was triggered yesterday."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    mock_coordinator.get_auto_update_time.return_value = dt_time(3, 0)

    entity = _make_switch(mock_coordinator, mock_entry)
    entity._attr_is_on = True
    entity._last_triggered = "1.30.0_2024-01-14"  # yesterday's trigger key

    fake_now = datetime(2024, 1, 15, 4, 0)  # today, after scheduled time
    with patch("custom_components.wud.switch.dt_util.now", return_value=fake_now):
        await entity._async_maybe_trigger()

    mock_coordinator.async_watch_container.assert_called_once()


# ---------------------------------------------------------------------------
# _async_run_install — trigger selection
# ---------------------------------------------------------------------------

async def test_run_install_calls_watch_when_no_triggers(mock_coordinator, mock_entry):
    """With no WUD triggers configured, async_watch_container is used as fallback."""
    mock_coordinator.async_get_container_triggers = AsyncMock(return_value=[])

    entity = _make_switch(mock_coordinator, mock_entry)
    await entity._async_run_install("container-abc", "freshrss")

    mock_coordinator.async_watch_container.assert_called_once_with("container-abc")
    mock_coordinator.async_request_refresh.assert_called_once()


async def test_run_install_prefers_docker_trigger(mock_coordinator, mock_entry):
    """docker/compose triggers are preferred over notification-only triggers."""
    triggers = [
        {"type": "slack", "name": "my-slack"},
        {"type": "docker", "name": "local"},
    ]
    mock_coordinator.async_get_container_triggers = AsyncMock(return_value=triggers)

    entity = _make_switch(mock_coordinator, mock_entry)
    await entity._async_run_install("container-abc", "freshrss")

    mock_coordinator.async_run_trigger.assert_called_once_with("container-abc", "docker", "local")
    mock_coordinator.async_watch_container.assert_not_called()
    mock_coordinator.async_request_refresh.assert_called_once()


async def test_run_install_falls_back_to_first_trigger(mock_coordinator, mock_entry):
    """When no updater trigger exists, the first available trigger is used."""
    triggers = [
        {"type": "slack", "name": "my-slack"},
        {"type": "gotify", "name": "my-gotify"},
    ]
    mock_coordinator.async_get_container_triggers = AsyncMock(return_value=triggers)

    entity = _make_switch(mock_coordinator, mock_entry)
    await entity._async_run_install("container-abc", "freshrss")

    mock_coordinator.async_run_trigger.assert_called_once_with("container-abc", "slack", "my-slack")


async def test_run_install_always_refreshes_even_on_error(mock_coordinator, mock_entry):
    """async_request_refresh is always called via finally, even when the install raises."""
    mock_coordinator.async_get_container_triggers = AsyncMock(
        side_effect=aiohttp.ClientError("network error")
    )

    entity = _make_switch(mock_coordinator, mock_entry)
    with pytest.raises(aiohttp.ClientError):
        await entity._async_run_install("container-abc", "freshrss")

    mock_coordinator.async_request_refresh.assert_called_once()
