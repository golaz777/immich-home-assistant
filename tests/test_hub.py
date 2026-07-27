"""Tests for the Immich API hub."""

from __future__ import annotations

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.immich_random.hub import CannotConnect, ImmichHub

from .conftest import (
    ALBUM_ID,
    API_KEY,
    ASSET_ID,
    HOST,
    JPEG_BYTES,
    albums,
    assets,
    user_info,
)


def build_hub(hass: HomeAssistant, host: str = HOST) -> ImmichHub:
    """Build a hub on Home Assistant's (mocked) shared session."""
    return ImmichHub(
        session=async_get_clientsession(hass), host=host, api_key=API_KEY
    )


async def test_authenticate_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A valid token reports success."""
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", json={"authStatus": True})

    assert await build_hub(hass).authenticate() is True


async def test_authenticate_rejects_bad_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 from Immich is reported as failed authentication, not an error."""
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", status=401)

    assert await build_hub(hass).authenticate() is False


async def test_authenticate_false_when_auth_status_false(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 200 with authStatus false is still a failed authentication."""
    aioclient_mock.post(f"{HOST}/api/auth/validateToken", json={"authStatus": False})

    assert await build_hub(hass).authenticate() is False


async def test_connection_error_raises_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Transport failures surface as CannotConnect."""
    aioclient_mock.post(
        f"{HOST}/api/auth/validateToken", exc=aiohttp.ClientConnectionError("boom")
    )

    with pytest.raises(CannotConnect):
        await build_hub(hass).authenticate()


async def test_get_my_user_info(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The user profile is returned verbatim."""
    aioclient_mock.get(f"{HOST}/api/users/me", json=user_info())

    assert (await build_hub(hass).get_my_user_info())["name"] == "Klemen"


async def test_list_all_albums(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Albums are listed from /api/albums."""
    aioclient_mock.get(f"{HOST}/api/albums", json=albums())

    result = await build_hub(hass).list_all_albums()

    assert [album["albumName"] for album in result] == ["Holidays", "Pets"]


async def test_list_favorite_images_posts_json_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Favorites are fetched from search/random with a JSON body.

    Regression test: the old code sent a form-encoded body to
    /api/search/metadata, which Immich API v3 rejects. A form body could not
    carry the JSON booleans asserted below.
    """
    aioclient_mock.post(f"{HOST}/api/search/random", json=assets())

    result = await build_hub(hass).list_favorite_images()

    assert len(result) == 2

    method, url, body, headers = aioclient_mock.mock_calls[0]
    assert method.lower() == "post"
    assert str(url) == f"{HOST}/api/search/random"
    assert body == {
        "type": "IMAGE",
        "size": 1000,
        "withExif": True,
        "isFavorite": True,
    }
    assert headers["x-api-key"] == API_KEY


async def test_list_album_images_uses_search_not_album_endpoint(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Album contents come from search/random filtered by albumIds.

    Regression test: in Immich API v3, GET /api/albums/{id} no longer embeds
    an `assets` array, so the old implementation raised KeyError.
    """
    aioclient_mock.post(f"{HOST}/api/search/random", json=assets())

    result = await build_hub(hass).list_album_images(ALBUM_ID)

    assert len(result) == 2
    assert [str(url) for _, url, _, _ in aioclient_mock.mock_calls] == [
        f"{HOST}/api/search/random"
    ]
    assert aioclient_mock.mock_calls[0][2]["albumIds"] == [ALBUM_ID]


async def test_non_image_assets_are_filtered_out(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A server that ignores the type filter does not leak videos through."""
    aioclient_mock.post(
        f"{HOST}/api/search/random", json=[*assets(1), {"id": "vid", "type": "VIDEO"}]
    )

    result = await build_hub(hass).list_favorite_images()

    assert [asset["type"] for asset in result] == ["IMAGE"]


async def test_download_image_prefers_preview(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The preview rendition is used when available."""
    aioclient_mock.get(
        f"{HOST}/api/assets/{ASSET_ID}/thumbnail?size=preview",
        content=JPEG_BYTES,
        headers={"Content-Type": "image/jpeg"},
    )

    assert await build_hub(hass).download_image(ASSET_ID) == (JPEG_BYTES, "image/jpeg")


async def test_download_image_falls_back_to_original(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """If no preview exists, the original is downloaded instead."""
    aioclient_mock.get(f"{HOST}/api/assets/{ASSET_ID}/thumbnail", status=404)
    aioclient_mock.get(
        f"{HOST}/api/assets/{ASSET_ID}/original",
        content=JPEG_BYTES,
        headers={"Content-Type": "image/png"},
    )

    assert await build_hub(hass).download_image(ASSET_ID) == (JPEG_BYTES, "image/png")


async def test_download_image_rejects_non_image_content(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Non-image responses yield None rather than bogus bytes."""
    aioclient_mock.get(
        f"{HOST}/api/assets/{ASSET_ID}/thumbnail",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    aioclient_mock.get(
        f"{HOST}/api/assets/{ASSET_ID}/original",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )

    assert await build_hub(hass).download_image(ASSET_ID) is None


async def test_download_image_accepts_any_image_type(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Formats beyond PNG/JPEG are accepted.

    Regression test: the old code hard-coded an allowlist of image/png and
    image/jpeg and discarded everything else.
    """
    aioclient_mock.get(
        f"{HOST}/api/assets/{ASSET_ID}/thumbnail",
        content=JPEG_BYTES,
        headers={"Content-Type": "image/webp"},
    )

    assert await build_hub(hass).download_image(ASSET_ID) == (JPEG_BYTES, "image/webp")


async def test_subpath_host_is_preserved(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reverse-proxied instance served from a subpath keeps that prefix."""
    host = "https://example.com/immich"
    aioclient_mock.get(f"{host}/api/albums", json=albums())

    await build_hub(hass, host).list_all_albums()

    assert str(aioclient_mock.mock_calls[0][1]) == f"{host}/api/albums"
