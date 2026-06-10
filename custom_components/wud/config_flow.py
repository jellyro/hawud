"""Config flow and options flow for What's Up Docker."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
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
_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_INTERVAL,
        max=MAX_SCAN_INTERVAL,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="s",
    )
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): _URL_SELECTOR,
        vol.Optional(CONF_USERNAME, default=""): _TEXT_SELECTOR,
        vol.Optional(CONF_PASSWORD, default=""): _PASSWORD_SELECTOR,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): _BOOL_SELECTOR,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): _INTERVAL_SELECTOR,
    }
)

_REAUTH_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_USERNAME, default=""): _TEXT_SELECTOR,
        vol.Optional(CONF_PASSWORD, default=""): _PASSWORD_SELECTOR,
    }
)


class _InvalidAuth(Exception):
    """Invalid credentials."""


async def _validate_connection(
    hass: HomeAssistant, data: dict[str, Any]
) -> str:
    """Test that the WUD URL is reachable and credentials are valid.

    Returns a suggested config entry title on success.
    Raises aiohttp.ClientError or _InvalidAuth on failure.
    """
    url = data[CONF_URL].rstrip("/")
    verify_ssl: bool = data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
    auth: aiohttp.BasicAuth | None = None
    username = data.get(CONF_USERNAME, "")
    password = data.get(CONF_PASSWORD, "")
    if username or password:
        auth = aiohttp.BasicAuth(username or "", password or "")

    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    async with session.get(
        f"{url}/api/containers",
        auth=auth,
        timeout=aiohttp.ClientTimeout(total=15),
    ) as resp:
        if resp.status == 401:
            raise _InvalidAuth
        resp.raise_for_status()

    host = url.removeprefix("http://").removeprefix("https://").split("/")[0]
    return f"What's Up Docker ({host})"


class WudConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for What's Up Docker."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                title = await _validate_connection(self.hass, user_input)
            except _InvalidAuth:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientConnectionError:
                errors["base"] = "cannot_connect"
            except aiohttp.ClientResponseError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during WUD config validation")
                errors["base"] = "unknown"
            else:
                data: dict[str, Any] = {
                    CONF_URL: user_input[CONF_URL].rstrip("/"),
                    CONF_VERIFY_SSL: user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                }
                if user_input.get(CONF_USERNAME):
                    data[CONF_USERNAME] = user_input[CONF_USERNAME]
                if user_input.get(CONF_PASSWORD):
                    data[CONF_PASSWORD] = user_input[CONF_PASSWORD]

                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog asking the user to re-enter their credentials."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            merged = {**reauth_entry.data, **user_input}
            try:
                await _validate_connection(self.hass, merged)
            except _InvalidAuth:
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during WUD re-auth")
                errors["base"] = "unknown"
            else:
                new_data: dict[str, Any] = dict(reauth_entry.data)
                if user_input.get(CONF_USERNAME):
                    new_data[CONF_USERNAME] = user_input[CONF_USERNAME]
                else:
                    new_data.pop(CONF_USERNAME, None)
                if user_input.get(CONF_PASSWORD):
                    new_data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
                else:
                    new_data.pop(CONF_PASSWORD, None)

                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data=new_data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                CONF_URL: reauth_entry.data.get(CONF_URL, "")
            },
        )

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
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): _INTERVAL_SELECTOR,
                }
            ),
        )
