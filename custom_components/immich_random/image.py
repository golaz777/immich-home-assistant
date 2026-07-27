"""Image entities for the Immich Random Image integration."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta

from homeassistant.components.image import ImageEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ImmichConfigEntry
from .const import CONF_WATCHED_ALBUMS, DOMAIN
from .hub import CannotConnect, ImmichHub

SCAN_INTERVAL = timedelta(minutes=5)

# How often to re-query Immich for the set of assets an entity can choose from.
_ASSET_LIST_REFRESH_INTERVAL = timedelta(hours=12)

# Give up after this many unusable assets rather than looping forever.
_MAX_DOWNLOAD_ATTEMPTS = 3

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ImmichConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Immich image platform."""
    hub = config_entry.runtime_data

    entities: list[BaseImmichImage] = [ImmichImageFavorite(hass, config_entry, hub)]

    watched_albums = set(config_entry.options.get(CONF_WATCHED_ALBUMS, []))

    if watched_albums:
        entities.extend(
            ImmichImageAlbum(
                hass,
                config_entry,
                hub,
                album_id=album["id"],
                album_name=album["albumName"],
            )
            for album in await hub.list_all_albums()
            if album["id"] in watched_albums
        )

    async_add_entities(entities)


class BaseImmichImage(ImageEntity):
    """Base image entity showing a random Immich photo.

    Subclasses decide which pool of assets the photo is drawn from.
    """

    _attr_has_entity_name = True

    # Polling is what rotates the picture, so each entity refreshes on its own
    # schedule and picks independently from its own pool.
    _attr_should_poll = True

    def __init__(
        self, hass: HomeAssistant, config_entry: ImmichConfigEntry, hub: ImmichHub
    ) -> None:
        """Initialize the Immich image entity."""
        super().__init__(hass=hass, verify_ssl=True)
        self.hub = hub
        self._config_entry = config_entry

        self._current_image_bytes: bytes | None = None
        self._cached_assets: list[dict] | None = None
        self._assets_last_updated: datetime | None = None

        self._attr_extra_state_attributes = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.title,
            manufacturer="Immich",
            configuration_url=config_entry.data[CONF_HOST],
        )

    async def _fetch_assets(self) -> list[dict]:
        """Return the assets this entity may choose from."""
        raise NotImplementedError

    async def async_update(self) -> None:
        """Rotate to a new random image."""
        await self._load_and_cache_next_image()

    async def async_image(self) -> bytes | None:
        """Return the current image, loading one if we have none yet."""
        if not self._current_image_bytes:
            await self._load_and_cache_next_image()

        return self._current_image_bytes

    async def _get_next_asset(self) -> dict | None:
        """Pick a random asset, refreshing the cached pool when it is stale."""
        now = dt_util.utcnow()

        if (
            self._assets_last_updated is None
            or (now - self._assets_last_updated) > _ASSET_LIST_REFRESH_INTERVAL
        ):
            _LOGGER.debug("Refreshing available assets for %s", self.entity_id)
            try:
                self._cached_assets = await self._fetch_assets()
            except CannotConnect:
                _LOGGER.warning("Could not reach Immich while refreshing assets")
                return None
            self._assets_last_updated = now

        if not self._cached_assets:
            _LOGGER.warning("No images are available for %s", self.entity_id)
            return None

        return random.choice(self._cached_assets)

    async def _load_and_cache_next_image(self) -> None:
        """Download a random image and cache it as the entity's current image."""
        for _ in range(_MAX_DOWNLOAD_ATTEMPTS):
            asset = await self._get_next_asset()

            if asset is None:
                return

            try:
                result = await self.hub.download_image(asset["id"])
            except CannotConnect:
                _LOGGER.warning("Could not reach Immich while downloading an image")
                return

            if result is None:
                # Unusable asset (e.g. a format Immich could not render);
                # drop it from the pool so we do not keep picking it.
                if self._cached_assets:
                    self._cached_assets = [
                        cached
                        for cached in self._cached_assets
                        if cached["id"] != asset["id"]
                    ]
                continue

            image_bytes, content_type = result

            self._current_image_bytes = image_bytes
            self._attr_content_type = content_type
            self._attr_image_last_updated = dt_util.utcnow()
            self._attr_extra_state_attributes = {
                "media_filename": asset.get("originalFileName") or "",
                "media_exif": asset.get("exifInfo") or "",
                "media_localdatetime": asset.get("localDateTime") or "",
            }
            self.async_write_ha_state()
            return

        _LOGGER.error(
            "Gave up loading an image for %s after %d attempts",
            self.entity_id,
            _MAX_DOWNLOAD_ATTEMPTS,
        )


class ImmichImageFavorite(BaseImmichImage):
    """Random image drawn from the user's favorites."""

    _attr_name = "Random favorite image"

    def __init__(
        self, hass: HomeAssistant, config_entry: ImmichConfigEntry, hub: ImmichHub
    ) -> None:
        """Initialize the favorites image entity."""
        super().__init__(hass, config_entry, hub)
        self._attr_unique_id = f"{config_entry.entry_id}_favorites"

    async def _fetch_assets(self) -> list[dict]:
        """Return the user's favorited images."""
        return await self.hub.list_favorite_images()


class ImmichImageAlbum(BaseImmichImage):
    """Random image drawn from a specific album."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ImmichConfigEntry,
        hub: ImmichHub,
        album_id: str,
        album_name: str,
    ) -> None:
        """Initialize the album image entity."""
        super().__init__(hass, config_entry, hub)
        self._album_id = album_id
        self._attr_unique_id = f"{config_entry.entry_id}_{album_id}"
        self._attr_name = album_name

    async def _fetch_assets(self) -> list[dict]:
        """Return the images in this album."""
        return await self.hub.list_album_images(self._album_id)
