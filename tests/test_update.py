"""Tests for WudUpdateEntity — entity_picture slug derivation and version properties."""
from __future__ import annotations
# pylint: disable=protected-access

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.wud.update import WudUpdateEntity

from .conftest import CONTAINER_NO_UPDATE, CONTAINER_WITH_UPDATE, CONTAINER_DIGEST_UPDATE


def _make_entity(coordinator, entry, container_key="local_freshrss"):
    entity = WudUpdateEntity.__new__(WudUpdateEntity)
    entity.coordinator = coordinator
    entity._container_key = container_key
    entity._entry = entry
    entity._attr_unique_id = f"test_{container_key}"
    entity._attr_in_progress = False
    entity._attr_update_percentage = None
    entity._install_done = None
    return entity


def _make_install_entity(coordinator, entry, written, container_key="local_freshrss"):
    """Build an entity wired with a fake hass and a state-recording stub."""
    entity = _make_entity(coordinator, entry, container_key)
    loop = asyncio.get_event_loop()
    hass = MagicMock()
    hass.async_create_task = lambda coro: loop.create_task(coro)
    entity.hass = hass
    entity.async_write_ha_state = lambda: written.append(
        (entity._attr_in_progress, entity._attr_update_percentage)
    )
    return entity


# ---------------------------------------------------------------------------
# entity_picture / slug derivation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("image_name, expected_slug", [
    # Plain image name
    ("freshrss/freshrss",                      "freshrss"),
    # Linuxserver-style with registry prefix
    ("lscr.io/linuxserver/calibre-web",        "calibre-web"),
    # ghcr.io with tag
    ("ghcr.io/jellyfin/jellyfin:latest",       "jellyfin"),
    # Official image with digest
    ("postgres@sha256:abc123",                 "postgres"),
    # Underscores become hyphens
    ("my_app/my_service",                      "my-service"),
    # Already a simple slug
    ("portainer",                              "portainer"),
    # Registry + namespace + image + tag
    ("registry.example.com/ns/nextcloud:26",   "nextcloud"),
])
def test_entity_picture_slug(mock_coordinator, mock_entry, image_name, expected_slug):
    """entity_picture should produce the correct CDN slug for various image name formats."""
    mock_coordinator.data = {
        "local_freshrss": {
            **CONTAINER_NO_UPDATE,
            "image": {"name": image_name, "tag": {"value": "1.0"}},
        }
    }
    entity = _make_entity(mock_coordinator, mock_entry)
    picture = entity.entity_picture
    assert picture == f"https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/{expected_slug}.png"


def test_entity_picture_falls_back_to_container_name(mock_coordinator, mock_entry):
    """When image.name is absent, fall back to container name field."""
    mock_coordinator.data = {
        "local_freshrss": {
            **CONTAINER_NO_UPDATE,
            "name": "my-app",
            "image": {},
        }
    }
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.entity_picture == (
        "https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/png/my-app.png"
    )


def test_entity_picture_none_when_no_data(mock_coordinator, mock_entry):
    """entity_picture returns None when coordinator has no data for this container."""
    mock_coordinator.data = {}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.entity_picture is None


# ---------------------------------------------------------------------------
# installed_version / latest_version
# ---------------------------------------------------------------------------

def test_installed_version_returns_tag(mock_coordinator, mock_entry):
    """installed_version returns the tag value from the image dict."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.installed_version == "1.29.1"


def test_installed_version_falls_back_to_digest(mock_coordinator, mock_entry):
    """installed_version falls back to digest.repo when no tag is present."""
    mock_coordinator.data = {
        "local_freshrss": {
            **CONTAINER_NO_UPDATE,
            "image": {"digest": {"repo": "sha256:aaa"}},
        }
    }
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.installed_version == "sha256:aaa"


def test_latest_version_equals_installed_when_no_update(mock_coordinator, mock_entry):
    """latest_version equals installed_version when no update is available."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.latest_version == entity.installed_version


def test_latest_version_returns_new_tag_when_update_available(mock_coordinator, mock_entry):
    """latest_version returns the result tag when an update is available."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_WITH_UPDATE}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.latest_version == "1.30.0"


def test_latest_version_appends_short_digest_for_digest_update(mock_coordinator, mock_entry):
    """For a digest-only update (tag unchanged), latest_version appends a short digest.

    This is the common case for moving tags like ``latest``: WUD keeps the same
    tag but reports a new digest. Without the digest suffix, installed_version
    and latest_version would be identical and Home Assistant would not show the
    update.
    """
    mock_coordinator.data = {"local_freshrss": CONTAINER_DIGEST_UPDATE}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.installed_version == "1.29.1"
    assert entity.latest_version == "1.29.1 (newdigest)"
    assert entity.latest_version != entity.installed_version


def test_latest_version_returns_raw_digest_when_no_tag(mock_coordinator, mock_entry):
    """latest_version returns the raw digest when the image has no tag at all."""
    mock_coordinator.data = {
        "local_freshrss": {
            **CONTAINER_DIGEST_UPDATE,
            "image": {"name": "freshrss/freshrss", "digest": {"repo": "sha256:aaa"}},
            "result": {"digest": "sha256:newdigest"},
        }
    }
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.latest_version == "sha256:newdigest"


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------

def test_available_when_coordinator_ok_and_container_present(mock_coordinator, mock_entry):
    """available is True when coordinator succeeded and container is in data."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.available is True


def test_not_available_when_coordinator_failed(mock_coordinator, mock_entry):
    """available is False when last_update_success is False."""
    mock_coordinator.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    mock_coordinator.last_update_success = False
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.available is False


def test_not_available_when_container_missing(mock_coordinator, mock_entry):
    """available is False when coordinator data does not contain this container."""
    mock_coordinator.data = {}
    entity = _make_entity(mock_coordinator, mock_entry)
    assert entity.available is False


# ---------------------------------------------------------------------------
# async_install — progress bar & resilience
# ---------------------------------------------------------------------------

async def test_async_install_runs_progress_and_completes(mock_coordinator, mock_entry):
    """A successful install shows progress, snaps to 100%, then clears state."""
    mock_coordinator.update_semaphore = None
    mock_coordinator.async_get_container_triggers = AsyncMock(return_value=[])
    mock_coordinator.async_watch_container = AsyncMock()
    # First poll already reports no pending update -> confirmed complete.
    mock_coordinator.async_get_single_container = AsyncMock(
        return_value=CONTAINER_NO_UPDATE
    )
    mock_coordinator.async_request_refresh = AsyncMock()

    written: list[tuple[bool, int | None]] = []
    entity = _make_install_entity(mock_coordinator, mock_entry, written)

    with patch("custom_components.wud.update.INSTALL_POLL_INTERVAL", 0.01), \
            patch("custom_components.wud.update.PROGRESS_UPDATE_INTERVAL", 0.01), \
            patch("custom_components.wud.update.INSTALL_ESTIMATED_DURATION", 0.05):
        await entity.async_install(None, False)

    # Bar reached 100% at some point and state was cleared on completion.
    assert any(pct == 100 for _, pct in written)
    assert entity._attr_in_progress is False
    assert entity._attr_update_percentage is None
    assert entity._install_done is None
    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_async_install_keeps_polling_when_trigger_errors(
    mock_coordinator, mock_entry
):
    """A trigger ClientError must not abort polling or collapse progress instantly."""
    mock_coordinator.update_semaphore = None
    mock_coordinator.async_get_container_triggers = AsyncMock(
        return_value=[{"type": "docker", "name": "update"}]
    )
    mock_coordinator.async_run_trigger = AsyncMock(
        side_effect=aiohttp.ClientError("boom")
    )
    mock_coordinator.async_watch_container = AsyncMock()
    # Still updating on the first poll, confirmed done on the second.
    mock_coordinator.async_get_single_container = AsyncMock(
        side_effect=[CONTAINER_WITH_UPDATE, CONTAINER_NO_UPDATE]
    )
    mock_coordinator.async_request_refresh = AsyncMock()

    written: list[tuple[bool, int | None]] = []
    entity = _make_install_entity(mock_coordinator, mock_entry, written)

    with patch("custom_components.wud.update.INSTALL_POLL_INTERVAL", 0.01), \
            patch("custom_components.wud.update.PROGRESS_UPDATE_INTERVAL", 0.01), \
            patch("custom_components.wud.update.INSTALL_ESTIMATED_DURATION", 0.05):
        await entity.async_install(None, False)

    # Polling continued past the failed trigger (two single-container reads).
    assert mock_coordinator.async_get_single_container.await_count == 2
    assert entity._attr_in_progress is False
    mock_coordinator.async_request_refresh.assert_awaited_once()
