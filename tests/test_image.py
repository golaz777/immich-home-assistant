"""Tests for the Immich Random Image image entities."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.immich_random.const import CONF_WATCHED_ALBUMS, DOMAIN

from .conftest import (
    ALBUM_ID,
    API_KEY,
    HOST,
    JPEG_BYTES,
    OTHER_ALBUM_ID,
    mock_immich,
)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_created_for_favorites_and_watched_albums(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """One entity for favorites, plus one per watched album."""
    mock_immich(aioclient_mock)
    await _setup(hass, mock_config_entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, mock_config_entry.entry_id)

    assert {entry.unique_id for entry in entries} == {
        f"{mock_config_entry.entry_id}_favorites",
        f"{mock_config_entry.entry_id}_{ALBUM_ID}",
    }


async def test_unwatched_albums_get_no_entity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Albums the user did not select are ignored."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Klemen @ immich.local",
        unique_id="user-a",
        data={CONF_HOST: HOST, CONF_API_KEY: API_KEY},
        options={CONF_WATCHED_ALBUMS: []},
    )
    mock_immich(aioclient_mock)
    await _setup(hass, entry)

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)

    assert len(entries) == 1
    assert entries[0].unique_id == f"{entry.entry_id}_favorites"


async def test_unique_ids_are_scoped_per_config_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Two Immich servers produce four distinct entities.

    Regression test: the favorites entity used to hard-code the unique ID
    "favorite_image", so a second config entry silently lost its entity.
    """
    other_host = "http://immich2.local"

    first = MockConfigEntry(
        domain=DOMAIN,
        title="First",
        unique_id="user-a",
        data={CONF_HOST: HOST, CONF_API_KEY: API_KEY},
        options={CONF_WATCHED_ALBUMS: [ALBUM_ID]},
    )
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        unique_id="user-b",
        data={CONF_HOST: other_host, CONF_API_KEY: API_KEY},
        options={CONF_WATCHED_ALBUMS: [OTHER_ALBUM_ID]},
    )

    mock_immich(aioclient_mock)
    mock_immich(aioclient_mock, host=other_host, user_id="user-b")

    await _setup(hass, first)
    await _setup(hass, second)

    registry = er.async_get(hass)
    unique_ids = {
        entity.unique_id
        for entry in (first, second)
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    assert unique_ids == {
        f"{first.entry_id}_favorites",
        f"{first.entry_id}_{ALBUM_ID}",
        f"{second.entry_id}_favorites",
        f"{second.entry_id}_{OTHER_ALBUM_ID}",
    }


async def test_image_is_downloaded_with_metadata_attributes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Fetching the image caches bytes and exposes the photo's metadata."""
    mock_immich(aioclient_mock)
    await _setup(hass, mock_config_entry)

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "image", DOMAIN, f"{mock_config_entry.entry_id}_favorites"
    )
    assert entity_id is not None

    component = hass.data["image"]
    entity = component.get_entity(entity_id)

    assert await entity.async_image() == JPEG_BYTES
    assert entity.content_type == "image/jpeg"

    attributes = hass.states.get(entity_id).attributes
    assert attributes["media_filename"] == "IMG_0.jpg"
    assert attributes["media_exif"] == {"make": "Fujifilm", "model": "X-T5"}
    assert attributes["media_localdatetime"] == "2026-07-01T12:00:00.000Z"


async def test_setup_retries_when_server_unreachable(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unreachable Immich server leaves the entry in a retry state."""
    import aiohttp

    aioclient_mock.post(
        f"{HOST}/api/auth/validateToken", exc=aiohttp.ClientConnectionError("down")
    )
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_api_key_triggers_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A rejected API key puts the entry into the reauth state."""
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", status=401)
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )
