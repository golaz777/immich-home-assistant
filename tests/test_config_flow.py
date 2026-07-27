"""Tests for the Immich Random Image config and options flows."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.immich_random.config_flow import normalize_host
from custom_components.immich_random.const import CONF_WATCHED_ALBUMS, DOMAIN

from .conftest import ALBUM_ID, API_KEY, HOST, OTHER_ALBUM_ID, USER_ID, mock_immich


def test_normalize_host() -> None:
    """Hosts get a scheme and lose any trailing slash."""
    assert normalize_host("immich.local") == "http://immich.local"
    assert normalize_host("  immich.local:2283/ ") == "http://immich.local:2283"
    assert normalize_host("https://example.com/immich/") == "https://example.com/immich"


async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid host and API key create an entry."""
    mock_immich(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "immich.local/", CONF_API_KEY: API_KEY}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Klemen @ immich.local"
    assert result["data"] == {CONF_HOST: HOST, CONF_API_KEY: API_KEY}
    assert result["result"].unique_id == USER_ID


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A rejected API key is reported on the form."""
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_API_KEY: "wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unreachable server is reported on the form."""
    aioclient_mock.post(
        f"{HOST}/api/auth/validateToken", exc=aiohttp.ClientConnectionError("nope")
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_API_KEY: API_KEY}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_on_duplicate(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The same Immich account cannot be configured twice."""
    mock_config_entry.add_to_hass(hass)
    mock_immich(aioclient_mock)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST, CONF_API_KEY: API_KEY}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_updates_api_key(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-authentication replaces the stored API key in place."""
    mock_config_entry.add_to_hass(hass)
    mock_immich(aioclient_mock)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "fresh-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "fresh-key"
    assert mock_config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_flow_updates_host(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfiguration can move an entry to a new URL."""
    mock_config_entry.add_to_hass(hass)
    new_host = "https://photos.example.com/immich"
    mock_immich(aioclient_mock, host=new_host)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: f"{new_host}/", CONF_API_KEY: API_KEY}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_HOST] == new_host


async def test_options_flow_lists_albums(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The album picker opens and saves a selection.

    Regression test: the previous OptionsFlowHandler assigned to
    `self.config_entry`, which is a read-only property since Home Assistant
    2025.12, so opening this form raised AttributeError.
    """
    mock_config_entry.add_to_hass(hass)
    mock_immich(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert result["errors"] == {}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WATCHED_ALBUMS: [ALBUM_ID, OTHER_ALBUM_ID]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WATCHED_ALBUMS] == [ALBUM_ID, OTHER_ALBUM_ID]


async def test_options_flow_reports_connection_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A server that goes away while opening the options form shows an error."""
    mock_config_entry.add_to_hass(hass)
    mock_immich(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{HOST}/api/albums", exc=aiohttp.ClientConnectionError("gone")
    )

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
