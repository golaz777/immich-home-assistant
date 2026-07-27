# Immich Random Image × Home Assistant ![GitHub Release](https://img.shields.io/github/v/release/golaz777/immich-home-assistant) ![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/golaz777/immich-home-assistant/validate.yml)

This custom integration for Home Assistant displays random pictures from your Immich instance right inside your dashboards.

> [!IMPORTANT]
> **This complements, and does not replace, the official Immich integration.**
> Home Assistant 2025.6 added a built-in `immich` integration providing a media source, sensors and an update entity — but no random-image entity. This project uses the separate domain **`immich_random`** so both can be installed side by side.
>
> Requires **Immich server 2.x/3.x** (API v3) and **Home Assistant 2025.12** or newer.

### What is Immich?

Immich is a "high performance self-hosted photo and video backup solution".  
[Find more on their website](https://immich.app).

### What is Home Assistant?

Home Assistant provides "open source home automation that puts local control and privacy first".  
[Find more on their website](https://www.home-assistant.io).

## Installation

Install this component _via_ [HACS](https://hacs.xyz).

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?repository=immich-home-assistant&category=Integration&owner=golaz777)

Restart Home Assistant once the integration has been installed.

### Upgrading from the old `immich` custom integration

Version 1.0.0 renamed the domain from `immich` to `immich_random` so that it stops shadowing Home Assistant's built-in Immich integration. Config entries do **not** migrate automatically:

1. Remove the old **Immich** integration from _Settings → Devices & Services_.
2. Delete the `custom_components/immich` folder (HACS will not remove it for you).
3. Restart Home Assistant, then add **Immich Random Image** as described below.
4. Update any dashboard cards: entity IDs change from `image.immich_*` to `image.immich_random_*`.

## What can I do with this project?

As a suggestion, you could use this integration to create a picture frame. You can create a "panel" dashboard, and display your picture entity inside of it:

```yaml
type: panel
title: Photo frame
path: photo-frame
icon: mdi:image-frame
subview: true
cards:
  - type: picture-entity
    entity: image.immich_random_random_favorite_image
    show_state: false
    show_name: false
    aspect_ratio: "16:9"
    fit_mode: contain
```

You can then use this dashboard on a dedicated device in kiosk mode.

You could even display it onto a Nest Hub device with the [Home Assistant Cast](https://www.home-assistant.io/integrations/cast/#home-assistant-cast) feature − you can finally say goodbye to Google Photos! 🎉

```yaml
- action: cast.show_lovelace_view
  data:
    entity_id: media_player.<your-chromecast-device>
    dashboard_path: lovelace
    view_path: photo-frame
```

![A Nest Hub 2 showing a cat picture, straight from Home Assistant](assets/demo.jpg)

## How does it work?

The integration provides one `image` entity for your favorites, plus one per album you choose to watch. Each entity switches to a new random image every 5 minutes, picking independently from its own pool.

Each entity also exposes the current photo's metadata as attributes: `media_filename`, `media_exif` and `media_localdatetime`.

These entities can be displayed using standard Lovelace cards − for example, the `picture` or `picture-entity` cards.

<img src="assets/entity-card.png" width="600" alt="Example usage: a picture card showing a picture from Immich">

## Configuration

You can set up the integration right from the web UI.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=immich_random)

You will need to enter your instance's URL and an API key. You can generate it from your Account Settings, on your Immich instance.

<img src="assets/immich-api-key.png" width="600" alt="'API Keys' section on the Immich account settings page">

Reverse-proxied instances served from a subpath (for example `https://example.com/immich`) are supported.

If your API key is ever revoked, Home Assistant will prompt you to re-authenticate rather than requiring you to delete and re-add the integration.

### Exposing other albums

By default, only your Favorites are exposed as an entity.

You can expose more albums on the integration's options page.

> [!WARNING]  
> Exposing many albums might consume a lot of resources on your Home Assistant machine, and will also increase the number of calls to your Immich instance.

<img src="assets/entity-list.png" width="600" alt="A list of four image entities provided by the Immich integration">

## Development

```bash
pip install -r requirements_test.txt
ruff check custom_components tests
pytest tests -v
```
