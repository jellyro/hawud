"""Config flow and options flow for What's Up Docker."""
from __future__ import annotations

import logging
import urllib.parse
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .auth import WudAuth, resolve_auth_method
from .const import (
    AUTH_BASIC,
    AUTH_BEARER,
    AUTH_METHODS,
    AUTH_OIDC,
    CONF_AUTH_METHOD,
    CONF_AUTO_UPDATE_TIME,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_MAX_CONCURRENT_UPDATES,
    CONF_OIDC_DISCOVERY_URL,
    CONF_OIDC_SCOPE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_AUTH_METHOD,
    DEFAULT_AUTO_UPDATE_TIME,
    DEFAULT_MAX_CONCURRENT_UPDATES,
    DEFAULT_OIDC_SCOPE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
_TEXT_SELECTOR = TextSelector()
_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_BOOL_SELECTOR = BooleanSelector()
_AUTH_METHOD_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[SelectOptionDict(value=method, label=method) for method in AUTH_METHODS],
        translation_key="auth_method",
        mode=SelectSelectorMode.DROPDOWN,
    )
)
_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="s",
    )
)
_MAX_CONCURRENT_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0,
        max=10,
        step=1,
        mode=NumberSelectorMode.BOX,
    )
)
_TIME_SELECTOR = TimeSelector()

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): _URL_SELECTOR,
        vol.Optional(CONF_NAME, default=""): _TEXT_SELECTOR,
        vol.Optional(CONF_AUTH_METHOD, default=DEFAULT_AUTH_METHOD): _AUTH_METHOD_SELECTOR,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): _BOOL_SELECTOR,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _INTERVAL_SELECTOR,
    }
)


def _basic_schema(username: str = "", password: str = "") -> vol.Schema:
    """Schema for HTTP Basic credentials."""
    return vol.Schema(
        {
            vol.Optional(CONF_USERNAME, default=username): _TEXT_SELECTOR,
            vol.Optional(CONF_PASSWORD, default=password): _PASSWORD_SELECTOR,
        }
    )


def _bearer_schema() -> vol.Schema:
    """Schema for a static bearer/API token."""
    return vol.Schema({vol.Required(CONF_TOKEN): _PASSWORD_SELECTOR})


def _oidc_schema(
    client_id: str = "",
    discovery_url: str = "",
    scope: str = DEFAULT_OIDC_SCOPE,
) -> vol.Schema:
    """Schema for OIDC client-credentials configuration."""
    return vol.Schema(
        {
            vol.Required(CONF_CLIENT_ID, default=client_id): _TEXT_SELECTOR,
            vol.Required(CONF_CLIENT_SECRET): _PASSWORD_SELECTOR,
            vol.Required(CONF_OIDC_DISCOVERY_URL, default=discovery_url): _URL_SELECTOR,
            vol.Optional(CONF_OIDC_SCOPE, default=scope): _TEXT_SELECTOR,
        }
    )


class _InvalidAuth(Exception):
    """Invalid credentials."""


async def _validate_connection(hass: HomeAssistant, data: dict[str, Any]) -> str:
    """Test that the WUD URL is reachable and the configured auth works.

    Returns a suggested config entry title on success.
    Raises aiohttp.ClientError or _InvalidAuth on failure.
    """
    url = data[CONF_URL].rstrip("/")
    verify_ssl: bool = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    try:
        kwargs = await WudAuth(hass, data).async_request_kwargs()
    except ConfigEntryAuthFailed as err:
        raise _InvalidAuth from err

    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    async with session.get(
        f"{url}/api/containers",
        timeout=aiohttp.ClientTimeout(total=15),
        **kwargs,
    ) as resp:
        if resp.status == 401:
            raise _InvalidAuth
        resp.raise_for_status()

    host = url.removeprefix("http://").removeprefix("https://").split("/")[0]
    return f"What's Up Docker ({host})"


class WudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for What's Up Docker."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._base_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the connection/auth-method selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            parsed = urllib.parse.urlparse(url)
            await self.async_set_unique_id(parsed.netloc.lower())
            self._abort_if_unique_id_configured()

            custom_name = user_input.get(CONF_NAME, "").strip()
            method = user_input.get(CONF_AUTH_METHOD, DEFAULT_AUTH_METHOD)
            self._base_data = {
                CONF_URL: url,
                CONF_AUTH_METHOD: method,
                CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
            }
            if custom_name:
                self._base_data[CONF_NAME] = custom_name

            if method == AUTH_BASIC:
                return await self.async_step_basic()
            if method == AUTH_BEARER:
                return await self.async_step_bearer()
            if method == AUTH_OIDC:
                return await self.async_step_oidc()
            return await self._async_validate_and_create({})

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect HTTP Basic credentials."""
        if user_input is not None:
            credentials = {
                k: v for k, v in user_input.items() if v
            }
            return await self._async_validate_and_create(
                credentials, step_id="basic", schema=_basic_schema()
            )
        return self.async_show_form(step_id="basic", data_schema=_basic_schema())

    async def async_step_bearer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a static bearer/API token."""
        if user_input is not None:
            return await self._async_validate_and_create(
                {CONF_TOKEN: user_input[CONF_TOKEN]},
                step_id="bearer",
                schema=_bearer_schema(),
            )
        return self.async_show_form(step_id="bearer", data_schema=_bearer_schema())

    async def async_step_oidc(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect OIDC client-credentials configuration."""
        if user_input is not None:
            credentials = {
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                CONF_OIDC_DISCOVERY_URL: user_input[CONF_OIDC_DISCOVERY_URL],
                CONF_OIDC_SCOPE: user_input.get(CONF_OIDC_SCOPE, DEFAULT_OIDC_SCOPE),
            }
            return await self._async_validate_and_create(
                credentials, step_id="oidc", schema=_oidc_schema()
            )
        return self.async_show_form(step_id="oidc", data_schema=_oidc_schema())

    async def _async_validate_and_create(
        self,
        credentials: dict[str, Any],
        step_id: str | None = None,
        schema: vol.Schema | None = None,
    ) -> ConfigFlowResult:
        """Validate the merged config and create the entry, or re-show the form."""
        data = {**self._base_data, **credentials}
        errors: dict[str, str] = {}
        try:
            url_title = await _validate_connection(self.hass, data)
        except _InvalidAuth:
            errors["base"] = "invalid_auth"
        except (aiohttp.ClientConnectionError, aiohttp.ClientResponseError):
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error during WUD config validation")
            errors["base"] = "unknown"
        else:
            title = self._base_data.get(CONF_NAME) or url_title
            return self.async_create_entry(title=title, data=data)

        if step_id is None or schema is None:
            # Anonymous auth has no dedicated form; report on the user step.
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
            )
        return self.async_show_form(step_id=step_id, data_schema=schema, errors=errors)

    async def async_step_reauth(
        self, _entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog asking the user to re-enter their credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        method = resolve_auth_method(reauth_entry.data)
        schema = self._reauth_schema(method, reauth_entry.data)

        if user_input is not None:
            new_data = self._merge_reauth_data(reauth_entry.data, method, user_input)
            try:
                await _validate_connection(self.hass, new_data)
            except _InvalidAuth:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error during WUD re-auth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=new_data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={CONF_URL: reauth_entry.data.get(CONF_URL, "")},
        )

    @staticmethod
    def _reauth_schema(method: str, data: dict[str, Any]) -> vol.Schema:
        """Return the reauth schema appropriate for the configured auth method."""
        if method == AUTH_BEARER:
            return _bearer_schema()
        if method == AUTH_OIDC:
            return _oidc_schema(
                client_id=data.get(CONF_CLIENT_ID, ""),
                discovery_url=data.get(CONF_OIDC_DISCOVERY_URL, ""),
                scope=data.get(CONF_OIDC_SCOPE, DEFAULT_OIDC_SCOPE),
            )
        return _basic_schema(username=data.get(CONF_USERNAME, ""))

    @staticmethod
    def _merge_reauth_data(
        existing: dict[str, Any], method: str, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge new reauth credentials over the existing config entry data."""
        new_data: dict[str, Any] = dict(existing)
        new_data[CONF_AUTH_METHOD] = method
        if method == AUTH_BEARER:
            new_data[CONF_TOKEN] = user_input[CONF_TOKEN]
        elif method == AUTH_OIDC:
            new_data[CONF_CLIENT_ID] = user_input[CONF_CLIENT_ID]
            new_data[CONF_CLIENT_SECRET] = user_input[CONF_CLIENT_SECRET]
            new_data[CONF_OIDC_DISCOVERY_URL] = user_input[CONF_OIDC_DISCOVERY_URL]
            new_data[CONF_OIDC_SCOPE] = user_input.get(CONF_OIDC_SCOPE, DEFAULT_OIDC_SCOPE)
        else:
            for key in (CONF_USERNAME, CONF_PASSWORD):
                if user_input.get(key):
                    new_data[key] = user_input[key]
                else:
                    new_data.pop(key, None)
        return new_data

    def is_matching(self, other_flow: WudConfigFlow) -> bool:
        """Return False; user-initiated flows are deduplicated via unique_id."""
        return False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow for this integration."""
        return WudOptionsFlow()


class WudOptionsFlow(OptionsFlow):
    """Handle options for the What's Up Docker integration."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_MAX_CONCURRENT_UPDATES: int(
                        user_input[CONF_MAX_CONCURRENT_UPDATES]
                    ),
                    CONF_AUTO_UPDATE_TIME: user_input[CONF_AUTO_UPDATE_TIME],
                }
            )

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        current_max_concurrent = self.config_entry.options.get(
            CONF_MAX_CONCURRENT_UPDATES,
            self.config_entry.data.get(
                CONF_MAX_CONCURRENT_UPDATES, DEFAULT_MAX_CONCURRENT_UPDATES
            ),
        )
        current_auto_update_time = self.config_entry.options.get(
            CONF_AUTO_UPDATE_TIME,
            self.config_entry.data.get(CONF_AUTO_UPDATE_TIME, DEFAULT_AUTO_UPDATE_TIME),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): _INTERVAL_SELECTOR,
                    vol.Optional(
                        CONF_MAX_CONCURRENT_UPDATES, default=current_max_concurrent
                    ): _MAX_CONCURRENT_SELECTOR,
                    vol.Optional(
                        CONF_AUTO_UPDATE_TIME, default=current_auto_update_time
                    ): _TIME_SELECTOR,
                }
            ),
        )
