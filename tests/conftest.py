"""Fixtures for the Immich Random Image tests."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import CONF_API_KEY, CONF_HOST
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.immich_random.const import CONF_WATCHED_ALBUMS, DOMAIN

HOST = "http://immich.local"
API_KEY = "test-api-key"
USER_ID = "11111111-1111-4111-8111-111111111111"
ALBUM_ID = "22222222-2222-4222-8222-222222222222"
OTHER_ALBUM_ID = "33333333-3333-4333-8333-333333333333"
ASSET_ID = "44444444-4444-4444-8444-444444444444"

JPEG_BYTES = b"\xff\xd8\xff\xe0 fake jpeg"


def user_info(user_id: str = USER_ID, name: str = "Klemen") -> dict[str, Any]:
    """Return a stub /api/users/me response."""
    return {"id": user_id, "name": name, "email": "klemen@example.com"}


def albums() -> list[dict[str, Any]]:
    """Return a stub /api/albums response.

    Deliberately omits an `assets` key, matching Immich API v3 where
    AlbumResponseDto carries only `assetCount`.
    """
    return [
        {"id": ALBUM_ID, "albumName": "Holidays", "assetCount": 12},
        {"id": OTHER_ALBUM_ID, "albumName": "Pets", "assetCount": 3},
    ]


def assets(count: int = 2) -> list[dict[str, Any]]:
    """Return a stub /api/search/random response."""
    return [
        {
            "id": ASSET_ID if index == 0 else f"{index}{ASSET_ID[1:]}",
            "type": "IMAGE",
            "originalFileName": f"IMG_{index}.jpg",
            "localDateTime": "2026-07-01T12:00:00.000Z",
            "exifInfo": {"make": "Fujifilm", "model": "X-T5"},
        }
        for index in range(count)
    ]


def mock_immich(
    aioclient_mock: AiohttpClientMocker,
    *,
    host: str = HOST,
    auth_status: bool = True,
    user_id: str = USER_ID,
) -> None:
    """Register a full set of happy-path Immich API responses."""
    aioclient_mock.post(
        f"{host}/api/auth/validateToken", json={"authStatus": auth_status}
    )
    aioclient_mock.get(f"{host}/api/users/me", json=user_info(user_id))
    aioclient_mock.get(f"{host}/api/albums", json=albums())
    # A single asset keeps the entity's random pick deterministic.
    aioclient_mock.post(f"{host}/api/search/random", json=assets(1))
    aioclient_mock.get(
        f"{host}/api/assets/{ASSET_ID}/thumbnail",
        content=JPEG_BYTES,
        headers={"Content-Type": "image/jpeg"},
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry watching one album."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Klemen @ immich.local",
        unique_id=USER_ID,
        data={CONF_HOST: HOST, CONF_API_KEY: API_KEY},
        options={CONF_WATCHED_ALBUMS: [ALBUM_ID]},
    )
