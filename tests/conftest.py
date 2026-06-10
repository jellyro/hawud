"""Shared fixtures for WUD integration tests."""
from __future__ import annotations

from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

import pytest


CONTAINER_NO_UPDATE = {
    "id": "container-abc",
    "name": "freshrss",
    "watcher": "local",
    "updateAvailable": False,
    "image": {
        "name": "freshrss/freshrss",
        "tag": {"value": "1.29.1"},
        "digest": {"repo": "sha256:aaa"},
    },
    "result": {},
}

CONTAINER_WITH_UPDATE = {
    **CONTAINER_NO_UPDATE,
    "updateAvailable": True,
    "result": {"tag": "1.30.0"},
}

CONTAINER_DIGEST_UPDATE = {
    **CONTAINER_NO_UPDATE,
    "updateAvailable": True,
    "result": {"digest": "sha256:newdigest"},
}


@pytest.fixture
def mock_entry():
    """Config entry mock with a display name and no options."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {"name": "Potatoflix"}
    entry.options = {}
    return entry


@pytest.fixture
def mock_coordinator():
    """Coordinator mock pre-populated with a single container that has no pending update."""
    coord = MagicMock()
    coord.data = {"local_freshrss": CONTAINER_NO_UPDATE}
    coord.last_update_success = True
    coord.url = "http://wud:3000"
    coord.get_auto_update_time = MagicMock(return_value=None)
    coord.set_auto_update_time = MagicMock()
    coord.get_integration_auto_update_time = MagicMock(return_value=dt_time(5, 0))
    coord.async_watch_container = AsyncMock(return_value={"id": "container-abc", "name": "freshrss"})
    coord.async_get_container_triggers = AsyncMock(return_value=[])
    coord.async_run_trigger = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_set_updated_data = MagicMock()
    coord.update_semaphore = None
    return coord
