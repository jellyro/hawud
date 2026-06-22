"""Tests for the WUD authentication helper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.wud.auth import WudAuth, resolve_auth_method
from custom_components.wud.const import (
    AUTH_BASIC,
    AUTH_BEARER,
    AUTH_NONE,
    AUTH_OIDC,
    CONF_AUTH_METHOD,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_OIDC_DISCOVERY_URL,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)


class _FakeResp:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json = json_data if json_data is not None else {}
        self._text = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=self.status
            )

    async def json(self):
        return self._json

    async def text(self):
        return self._text


class _FakeSession:
    """Fake aiohttp session returning preconfigured responses."""

    def __init__(self, get_resp=None, post_resp=None):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self.get_calls: list[tuple] = []
        self.post_calls: list[tuple] = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._get_resp

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self._post_resp


def _patch_session(session):
    return patch(
        "custom_components.wud.auth.async_get_clientsession", return_value=session
    )


def test_resolve_auth_method_explicit():
    assert resolve_auth_method({CONF_AUTH_METHOD: AUTH_OIDC}) == AUTH_OIDC


def test_resolve_auth_method_legacy_basic_inference():
    assert resolve_auth_method({CONF_USERNAME: "john"}) == AUTH_BASIC
    assert resolve_auth_method({CONF_PASSWORD: "secret"}) == AUTH_BASIC


def test_resolve_auth_method_defaults_to_none():
    assert resolve_auth_method({}) == AUTH_NONE


async def test_basic_request_kwargs():
    auth = WudAuth(MagicMock(), {CONF_AUTH_METHOD: AUTH_BASIC, CONF_USERNAME: "u", CONF_PASSWORD: "p"})
    kwargs = await auth.async_request_kwargs()
    assert kwargs == {"auth": aiohttp.BasicAuth("u", "p")}


async def test_bearer_request_kwargs():
    auth = WudAuth(MagicMock(), {CONF_AUTH_METHOD: AUTH_BEARER, CONF_TOKEN: "abc123"})
    kwargs = await auth.async_request_kwargs()
    assert kwargs == {"headers": {"Authorization": "Bearer abc123"}}


async def test_none_request_kwargs():
    auth = WudAuth(MagicMock(), {CONF_AUTH_METHOD: AUTH_NONE})
    assert await auth.async_request_kwargs() == {}


async def test_oidc_fetches_and_caches_token():
    session = _FakeSession(
        get_resp=_FakeResp(json_data={"token_endpoint": "https://idp/token"}),
        post_resp=_FakeResp(json_data={"access_token": "tok", "expires_in": 3600}),
    )
    auth = WudAuth(
        MagicMock(),
        {
            CONF_AUTH_METHOD: AUTH_OIDC,
            CONF_CLIENT_ID: "cid",
            CONF_CLIENT_SECRET: "csec",
            CONF_OIDC_DISCOVERY_URL: "https://idp/.well-known/openid-configuration",
        },
    )

    with _patch_session(session):
        kwargs = await auth.async_request_kwargs()
        assert kwargs == {"headers": {"Authorization": "Bearer tok"}}
        # Token endpoint discovered once and client_credentials grant used.
        assert session.post_calls[0][0] == "https://idp/token"
        assert session.post_calls[0][1]["data"]["grant_type"] == "client_credentials"

        # Second call uses the cache: no extra discovery or token requests.
        await auth.async_request_kwargs()
        assert len(session.post_calls) == 1
        assert len(session.get_calls) == 1


async def test_oidc_invalid_credentials_raises_auth_failed():
    session = _FakeSession(
        get_resp=_FakeResp(json_data={"token_endpoint": "https://idp/token"}),
        post_resp=_FakeResp(status=401, text_data="invalid_client"),
    )
    auth = WudAuth(
        MagicMock(),
        {
            CONF_AUTH_METHOD: AUTH_OIDC,
            CONF_CLIENT_ID: "cid",
            CONF_CLIENT_SECRET: "bad",
            CONF_OIDC_DISCOVERY_URL: "https://idp/.well-known/openid-configuration",
        },
    )
    with _patch_session(session), pytest.raises(ConfigEntryAuthFailed):
        await auth.async_request_kwargs()


async def test_oidc_missing_token_endpoint_raises():
    session = _FakeSession(get_resp=_FakeResp(json_data={}))
    auth = WudAuth(
        MagicMock(),
        {
            CONF_AUTH_METHOD: AUTH_OIDC,
            CONF_CLIENT_ID: "cid",
            CONF_CLIENT_SECRET: "csec",
            CONF_OIDC_DISCOVERY_URL: "https://idp/.well-known/openid-configuration",
        },
    )
    with _patch_session(session), pytest.raises(ConfigEntryAuthFailed):
        await auth.async_request_kwargs()


async def test_oidc_invalidate_forces_refresh():
    session = _FakeSession(
        get_resp=_FakeResp(json_data={"token_endpoint": "https://idp/token"}),
        post_resp=_FakeResp(json_data={"access_token": "tok", "expires_in": 3600}),
    )
    auth = WudAuth(
        MagicMock(),
        {
            CONF_AUTH_METHOD: AUTH_OIDC,
            CONF_CLIENT_ID: "cid",
            CONF_CLIENT_SECRET: "csec",
            CONF_OIDC_DISCOVERY_URL: "https://idp/.well-known/openid-configuration",
        },
    )
    with _patch_session(session):
        await auth.async_request_kwargs()
        auth.invalidate()
        await auth.async_request_kwargs()
        assert len(session.post_calls) == 2
