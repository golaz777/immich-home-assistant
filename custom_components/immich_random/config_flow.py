"""Config flow for the Immich Random Image integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_WATCHED_ALBUMS, DOMAIN
from .hub import ApiError, CannotConnect, ImmichHub, InvalidAuth

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_API_KEY): str,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): str})


def normalize_host(host: str) -> str:
    """Normalize a user-entered host into a usable base URL.

    Replaces the former `url-normalize` dependency: assume http:// when no
    scheme is given, and drop any trailing slash so that URL joining in the
    hub stays predictable.
    """
    host = host.strip()

    if "://" not in host:
        host = f"http://{host}"

    return host.rstrip("/")


class ImmichRandomConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Immich Random Image."""

    VERSION = 1

    async def _validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        """Check that we can talk to Immich, and return the user profile."""
        hub = ImmichHub(
            session=async_get_clientsession(self.hass),
            host=normalize_host(data[CONF_HOST]),
            api_key=data[CONF_API_KEY],
        )

        if not await hub.authenticate():
            raise InvalidAuth

        return await hub.get_my_user_info()

    def _existing_data(self, step_id: str) -> dict[str, Any]:
        """Return the stored entry data that a step is amending, if any."""
        if step_id == "reauth_confirm":
            return dict(self._get_reauth_entry().data)
        if step_id == "reconfigure":
            return dict(self._get_reconfigure_entry().data)
        return {}

    async def _async_step_credentials(
        self,
        step_id: str,
        data_schema: vol.Schema,
        user_input: dict[str, Any] | None,
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Shared handling for the user, reauth and reconfigure steps."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {**self._existing_data(step_id), **user_input}

            try:
                user_info = await self._validate_input(data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except ApiError:
                _LOGGER.exception("Immich API returned an error")
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001 - surface anything unexpected as "unknown"
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                entry_data = {
                    CONF_HOST: normalize_host(data[CONF_HOST]),
                    CONF_API_KEY: data[CONF_API_KEY],
                }

                await self.async_set_unique_id(user_info["id"])

                if step_id == "user":
                    self._abort_if_unique_id_configured()
                    hostname = urlparse(entry_data[CONF_HOST]).hostname
                    return self.async_create_entry(
                        title=f"{user_info['name']} @ {hostname}", data=entry_data
                    )

                self._abort_if_unique_id_mismatch()
                entry = (
                    self._get_reauth_entry()
                    if step_id == "reauth_confirm"
                    else self._get_reconfigure_entry()
                )
                return self.async_update_reload_and_abort(entry, data=entry_data)

        return self.async_show_form(
            step_id=step_id,
            data_schema=data_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        return await self._async_step_credentials(
            "user", STEP_USER_DATA_SCHEMA, user_input
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication after the API key stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user for a fresh API key."""
        return await self._async_step_credentials(
            "reauth_confirm",
            STEP_REAUTH_DATA_SCHEMA,
            user_input,
            description_placeholders={"host": self._get_reauth_entry().data[CONF_HOST]},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the host and/or API key of an existing entry."""
        entry = self._get_reconfigure_entry()
        schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA,
            {CONF_HOST: entry.data[CONF_HOST], CONF_API_KEY: entry.data[CONF_API_KEY]},
        )
        return await self._async_step_credentials("reconfigure", schema, user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow.

        The handler deliberately takes no arguments: since Home Assistant
        2025.12 `OptionsFlow.config_entry` is a read-only property, and the
        old `self.config_entry = config_entry` pattern raises AttributeError.
        """
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Let the user pick which albums get an image entity."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        errors: dict[str, str] = {}
        config_entry = self.config_entry

        hub = ImmichHub(
            session=async_get_clientsession(self.hass),
            host=config_entry.data[CONF_HOST],
            api_key=config_entry.data[CONF_API_KEY],
        )

        albums: list[dict] = []

        try:
            albums = await hub.list_all_albums()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except ApiError:
            _LOGGER.exception("Could not list Immich albums")
            errors["base"] = "cannot_connect"

        album_map = {album["id"]: album["albumName"] for album in albums}

        # Drop any previously watched album that no longer exists.
        current_albums = [
            album
            for album in config_entry.options.get(CONF_WATCHED_ALBUMS, [])
            if album in album_map
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WATCHED_ALBUMS, default=current_albums
                    ): cv.multi_select(album_map)
                }
            ),
            errors=errors,
        )
