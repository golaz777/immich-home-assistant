"""The Immich Random Image integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .hub import ApiError, CannotConnect, ImmichHub

PLATFORMS: list[Platform] = [Platform.IMAGE]

type ImmichConfigEntry = ConfigEntry[ImmichHub]


async def async_setup_entry(hass: HomeAssistant, entry: ImmichConfigEntry) -> bool:
    """Set up Immich Random Image from a config entry."""
    hub = ImmichHub(
        session=async_get_clientsession(hass),
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
    )

    try:
        authenticated = await hub.authenticate()
    except CannotConnect as err:
        raise ConfigEntryNotReady(
            f"Could not reach the Immich server at {entry.data[CONF_HOST]}"
        ) from err
    except ApiError as err:
        raise ConfigEntryNotReady("The Immich server returned an error") from err

    if not authenticated:
        raise ConfigEntryAuthFailed("The Immich API key was rejected")

    entry.runtime_data = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ImmichConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: ImmichConfigEntry
) -> None:
    """Reload the entry when the watched albums change."""
    await hass.config_entries.async_reload(entry.entry_id)
