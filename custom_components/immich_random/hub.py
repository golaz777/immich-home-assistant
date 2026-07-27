"""Hub for the Immich Random Image integration.

Targets the Immich API as of major version 3. Two notable differences from
older Immich releases shaped this module:

* ``GET /api/albums/{id}`` no longer embeds an ``assets`` array in its
  response (only ``assetCount``), so album contents have to be fetched
  through the search API instead.
* The search endpoints accept a JSON body only; a form-encoded body is
  rejected.

Both listings therefore go through ``POST /api/search/random``, which returns
a flat list of assets and accepts the filters we need.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError
from yarl import URL

from .const import MAX_SEARCH_RESULTS

_HEADER_API_KEY = "x-api-key"
_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Size of the rendition we ask Immich for. Previews are always transcoded to a
# browser-safe format, unlike originals which may be HEIC, AVIF, DNG, ...
_PREVIEW_SIZE = "preview"


class ImmichHub:
    """Thin async client for the Immich REST API."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, api_key: str
    ) -> None:
        """Initialize the hub with a shared Home Assistant aiohttp session."""
        self._session = session
        self._base_url = URL(host)
        self._api_key = api_key

    @property
    def host(self) -> str:
        """Return the configured host URL."""
        return str(self._base_url)

    def _url(self, *path: str, **query: str) -> URL:
        """Build an API URL, preserving any subpath in the configured host.

        Joining relative segments (rather than an absolute "/api/..." path)
        keeps reverse-proxy setups such as https://example.com/immich working.
        """
        url = self._base_url / "api"
        for segment in path:
            url = url / segment
        return url.with_query(query) if query else url

    async def _request(
        self,
        method: str,
        url: URL,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Perform a JSON API request and return the decoded body."""
        headers = {"Accept": "application/json", _HEADER_API_KEY: self._api_key}

        try:
            async with self._session.request(
                method, url, headers=headers, json=json, timeout=_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise InvalidAuth(f"Immich rejected the API key ({response.status})")

                if response.status != 200:
                    body = await response.text()
                    _LOGGER.error(
                        "Error from Immich API: %s %s status=%d body=%s",
                        method,
                        url.path,
                        response.status,
                        body,
                    )
                    raise ApiError(f"Immich API returned status {response.status}")

                return await response.json()
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error connecting to the Immich API: %s", err)
            raise CannotConnect from err

    async def authenticate(self) -> bool:
        """Return True if the configured API key is accepted by the server."""
        try:
            result = await self._request("POST", self._url("auth", "validateToken"))
        except InvalidAuth:
            return False

        return bool(result.get("authStatus"))

    async def get_my_user_info(self) -> dict:
        """Return the profile of the user owning the API key."""
        return await self._request("GET", self._url("users", "me"))

    async def list_all_albums(self) -> list[dict]:
        """Return every album visible to the user."""
        return await self._request("GET", self._url("albums"))

    async def list_favorite_images(self) -> list[dict]:
        """Return the user's favorited images, with EXIF metadata included."""
        return await self._search_random({"isFavorite": True})

    async def list_album_images(self, album_id: str) -> list[dict]:
        """Return the images in an album, with EXIF metadata included."""
        return await self._search_random({"albumIds": [album_id]})

    async def _search_random(self, filters: dict[str, Any]) -> list[dict]:
        """Query POST /api/search/random and return the matching image assets."""
        body: dict[str, Any] = {
            "type": "IMAGE",
            "size": MAX_SEARCH_RESULTS,
            "withExif": True,
            **filters,
        }

        assets = await self._request("POST", self._url("search", "random"), json=body)

        # The `type` filter is applied server-side; this guards against a
        # server that ignores it rather than doing real work.
        return [asset for asset in assets if asset.get("type") == "IMAGE"]

    async def download_image(self, asset_id: str) -> tuple[bytes, str] | None:
        """Download an asset as displayable image bytes.

        Returns a (bytes, content type) tuple, or None if the asset could not
        be fetched in an image format. The preview rendition is preferred: it
        is always a browser-safe format and is far smaller than the original.
        """
        for url in (
            self._url("assets", asset_id, "thumbnail", size=_PREVIEW_SIZE),
            self._url("assets", asset_id, "original"),
        ):
            result = await self._download(url)
            if result is not None:
                return result

        _LOGGER.error("Could not download asset %s as an image", asset_id)
        return None

    async def _download(self, url: URL) -> tuple[bytes, str] | None:
        """Fetch binary content, returning None unless it is an image."""
        headers = {_HEADER_API_KEY: self._api_key}

        try:
            async with self._session.get(
                url, headers=headers, timeout=_TIMEOUT
            ) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "Download of %s failed with status %d", url.path, response.status
                    )
                    return None

                content_type = response.content_type or ""

                if not content_type.startswith("image/"):
                    _LOGGER.debug(
                        "Download of %s returned unsupported type %s",
                        url.path,
                        content_type,
                    )
                    return None

                return await response.read(), content_type
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error connecting to the Immich API: %s", err)
            raise CannotConnect from err


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class ApiError(HomeAssistantError):
    """Error to indicate that the API returned an error."""
