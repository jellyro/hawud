"""Authentication helpers for the What's Up Docker API.

Supports every authentication strategy WUD can be configured with:

* ``none``   - anonymous access (WUD default).
* ``basic``  - HTTP Basic auth (WUD ``WUD_AUTH_BASIC_*``).
* ``bearer`` - a static, long-lived access/API token sent as ``Authorization: Bearer``.
* ``oidc``   - OpenID Connect using the ``client_credentials`` grant. The
  integration discovers the token endpoint, fetches an access token and
  transparently refreshes it before expiry. This matches the service-account
  style integration described for Authentik/Authelia/Keycloak.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AUTH_BASIC,
    AUTH_BEARER,
    AUTH_OIDC,
    CONF_AUTH_METHOD,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_OIDC_DISCOVERY_URL,
    CONF_OIDC_SCOPE,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_AUTH_METHOD,
    DEFAULT_OIDC_SCOPE,
    DEFAULT_VERIFY_SSL,
    OIDC_TOKEN_EXPIRY_MARGIN,
)

_LOGGER = logging.getLogger(__name__)


def resolve_auth_method(data: dict[str, Any]) -> str:
    """Return the configured auth method, inferring it from legacy entries.

    Config entries created before the auth method picker existed only stored
    a username/password, so fall back to ``basic`` when those are present.
    """
    method = data.get(CONF_AUTH_METHOD)
    if method:
        return method
    if data.get(CONF_USERNAME) or data.get(CONF_PASSWORD):
        return AUTH_BASIC
    return DEFAULT_AUTH_METHOD


class WudAuth:
    """Builds authentication for WUD API requests, refreshing OIDC tokens."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Initialize the authenticator from config entry data."""
        self._hass = hass
        self._data = data
        self._method = resolve_auth_method(data)
        self._verify_ssl: bool = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._token_endpoint: str | None = None

    @property
    def method(self) -> str:
        """Return the resolved authentication method."""
        return self._method

    async def async_request_kwargs(self) -> dict[str, Any]:
        """Return aiohttp request kwargs (``auth`` and/or ``headers``).

        Raises:
            ConfigEntryAuthFailed: if an OIDC token cannot be obtained.
        """
        if self._method == AUTH_BASIC:
            username = self._data.get(CONF_USERNAME, "") or ""
            password = self._data.get(CONF_PASSWORD, "") or ""
            return {"auth": aiohttp.BasicAuth(username, password)}

        if self._method == AUTH_BEARER:
            token = self._data.get(CONF_TOKEN, "") or ""
            return {"headers": {"Authorization": f"Bearer {token}"}}

        if self._method == AUTH_OIDC:
            token = await self._async_get_oidc_token()
            return {"headers": {"Authorization": f"Bearer {token}"}}

        return {}

    def invalidate(self) -> None:
        """Drop any cached OIDC token, forcing a refresh on the next request."""
        self._access_token = None
        self._token_expiry = 0.0

    async def _async_resolve_token_endpoint(self) -> str:
        """Resolve and cache the OIDC token endpoint from the discovery URL."""
        if self._token_endpoint:
            return self._token_endpoint

        discovery_url = (self._data.get(CONF_OIDC_DISCOVERY_URL) or "").strip()
        if not discovery_url:
            raise ConfigEntryAuthFailed("OIDC discovery URL is not configured")

        session = async_get_clientsession(self._hass, verify_ssl=self._verify_ssl)
        try:
            async with session.get(
                discovery_url,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                config: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise ConfigEntryAuthFailed(
                f"Failed to fetch OIDC discovery document: {err}"
            ) from err

        endpoint = config.get("token_endpoint")
        if not endpoint:
            raise ConfigEntryAuthFailed(
                "OIDC discovery document is missing 'token_endpoint'"
            )
        self._token_endpoint = endpoint
        return endpoint

    async def _async_get_oidc_token(self) -> str:
        """Return a valid OIDC access token, fetching/refreshing as needed."""
        now = time.monotonic()
        if self._access_token and now < self._token_expiry:
            return self._access_token

        token_endpoint = await self._async_resolve_token_endpoint()
        client_id = self._data.get(CONF_CLIENT_ID, "") or ""
        client_secret = self._data.get(CONF_CLIENT_SECRET, "") or ""
        scope = (self._data.get(CONF_OIDC_SCOPE) or DEFAULT_OIDC_SCOPE).strip()

        form: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scope:
            form["scope"] = scope

        session = async_get_clientsession(self._hass, verify_ssl=self._verify_ssl)
        try:
            async with session.post(
                token_endpoint,
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (400, 401, 403):
                    body = await resp.text()
                    raise ConfigEntryAuthFailed(
                        f"OIDC token request rejected ({resp.status}): {body}"
                    )
                resp.raise_for_status()
                payload: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise ConfigEntryAuthFailed(
                f"Failed to obtain OIDC access token: {err}"
            ) from err

        access_token = payload.get("access_token")
        if not access_token:
            raise ConfigEntryAuthFailed(
                "OIDC token response did not contain an access_token"
            )

        try:
            expires_in = int(payload.get("expires_in", 300))
        except (TypeError, ValueError):
            expires_in = 300

        self._access_token = access_token
        self._token_expiry = now + max(0, expires_in - OIDC_TOKEN_EXPIRY_MARGIN)
        return access_token
