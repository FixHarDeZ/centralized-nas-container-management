"""Synology Photos album sync — keeps Normal Albums in sync with wallpaper folders.

Creates one album per purpose (e.g., "Wallpapers — mobile", "Wallpapers — pc")
and adds newly downloaded images after each scrape cycle.

Uses raw Synology Photos API calls via synology-api's session/request_data
for maximum compatibility across library versions.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

_DSM_HOST = os.environ.get("DSM_HOST", "")
_DSM_PORT = os.environ.get("DSM_PORT", "5000")
_DSM_USER = os.environ.get("DSM_USER", "")
_DSM_PASS = os.environ.get("DSM_PASS", "")
_DSM_SECURE = os.environ.get("DSM_SECURE", "false").lower() == "true"

_ALBUM_PREFIX = "Wallpapers — "
_photos = None  # lazy singleton

# Synology auth/session error codes — SID expired or invalidated. On these we
# reconnect once, otherwise a dead session silently stops album sync forever.
_AUTH_ERR_CODES = {105, 106, 107, 119}


def _api(p, api_name: str, method: str, **extra_params):
    """Call a Synology Photos API endpoint, reconnecting once on session expiry."""
    info = p.photos_list[api_name]
    params = {"version": info["maxVersion"], "method": method, **extra_params}
    result = p.request_data(api_name, info["path"], params)
    if not result.get("success") and result.get("error", {}).get("code") in _AUTH_ERR_CODES:
        logger.warning("DSM session expired (code=%s) — reconnecting", result.get("error"))
        fresh = _get_photos(force=True)
        if fresh is not None:
            result = fresh.request_data(api_name, info["path"], params)
    return result


def _get_photos(force: bool = False):
    """Lazy-init Photos API connection. force=True rebuilds a dead session."""
    global _photos
    if _photos is not None and not force:
        return _photos
    _photos = None
    if not all([_DSM_HOST, _DSM_USER, _DSM_PASS]):
        logger.warning("DSM credentials not configured — album sync disabled")
        return None
    try:
        from synology_api.photos import Photos
        _photos = Photos(
            _DSM_HOST, _DSM_PORT, _DSM_USER, _DSM_PASS,
            secure=_DSM_SECURE, cert_verify=False, dsm_version=7, debug=False,
        )
        info = _photos.get_userinfo()
        if not info.get("success"):
            logger.error("DSM login failed: %s", info)
            _photos = None
            return None
        logger.info("Synology Photos API connected as user_id=%s", info["data"]["id"])
        return _photos
    except Exception as exc:
        logger.error("Failed to connect to Synology Photos API: %s", exc)
        _photos = None
        return None


def _find_album_by_name(p, name: str) -> int | None:
    """Find normal album ID by name."""
    offset = 0
    while True:
        result = _api(p, "SYNO.Foto.Browse.Album", "list", offset=offset, limit=100)
        if not result.get("success"):
            return None
        for album in result["data"]["list"]:
            if album["name"] == name and album["type"] == "normal":
                return album["id"]
        if len(result["data"]["list"]) < 100:
            break
        offset += 100
    return None


def _create_normal_album(p, name: str, item_ids: list[int]) -> int | None:
    """Create a normal album, return album ID or None."""
    result = _api(p, "SYNO.Foto.Browse.NormalAlbum", "create",
                  name=json.dumps(name), item=json.dumps(item_ids))
    if result.get("success"):
        return result["data"]["album"]["id"]
    logger.error("Failed to create album '%s': %s", name, result)
    return None


def _add_items_to_album(p, album_id: int, item_ids: list[int]) -> bool:
    """Add items to an existing normal album."""
    result = _api(p, "SYNO.Foto.Browse.NormalAlbum", "add_item",
                  id=album_id, item=json.dumps(item_ids))
    return result.get("success", False)


def _list_folder_items_recursive(p, folder_id: int) -> list[dict]:
    """List all items in a folder and its subfolders (recursive)."""
    items = []
    offset = 0
    while True:
        result = _api(p, "SYNO.Foto.Browse.Item", "list",
                      folder_id=folder_id, offset=offset, limit=500)
        if not result.get("success"):
            break
        batch = result["data"]["list"]
        items.extend(batch)
        if len(batch) < 500:
            break
        offset += 500

    # Recurse into subfolders
    sub_result = _api(p, "SYNO.Foto.Browse.Folder", "list",
                      id=folder_id, limit=1000, offset=0, additional=json.dumps([]))
    if sub_result.get("success"):
        for subfolder in sub_result["data"]["list"]:
            items.extend(_list_folder_items_recursive(p, subfolder["id"]))

    return items


def _find_subfolder_id(p, parent_id: int, name: str) -> int | None:
    """Find subfolder ID by name under a parent folder."""
    result = _api(p, "SYNO.Foto.Browse.Folder", "list",
                  id=parent_id, limit=1000, offset=0, additional=json.dumps([]))
    if not result.get("success"):
        return None
    for folder in result["data"]["list"]:
        if folder["name"].endswith(f"/{name}"):
            return folder["id"]
    return None


def _get_wallpapers_folder_id(p) -> int | None:
    """Get the wallpapers root folder ID."""
    result = _api(p, "SYNO.Foto.Browse.Folder", "list",
                  id=0, limit=100, offset=0, additional=json.dumps([]))
    if not result.get("success"):
        return None
    for folder in result["data"]["list"]:
        if "wallpaper" in folder["name"].lower():
            return folder["id"]
    return None


def sync_albums() -> dict[str, int]:
    """Sync wallpaper folders to Synology Photos albums.

    Returns dict of {purpose: items_added}.
    """
    p = _get_photos()
    if p is None:
        return {}

    wallpapers_folder_id = _get_wallpapers_folder_id(p)
    if wallpapers_folder_id is None:
        logger.warning("Wallpapers folder not found in Synology Photos")
        return {}

    photos_root = Path(os.environ.get("PHOTOS_ROOT", "/photos_root"))
    results = {}

    for purpose_dir in sorted(photos_root.iterdir()):
        if not purpose_dir.is_dir():
            continue
        purpose = purpose_dir.name
        album_name = f"{_ALBUM_PREFIX}{purpose}"

        # Find or create album
        album_id = _find_album_by_name(p, album_name)
        if album_id is None:
            album_id = _create_normal_album(p, album_name, [])
            if album_id is None:
                continue
            logger.info("Created album '%s' (id=%d)", album_name, album_id)

        # Find purpose subfolder in Photos
        purpose_folder_id = _find_subfolder_id(p, wallpapers_folder_id, purpose)
        if purpose_folder_id is None:
            logger.info("Purpose folder '%s' not yet indexed in Photos — skipping", purpose)
            results[purpose] = 0
            continue

        # Get all items in purpose folder (including subfolders)
        all_items = _list_folder_items_recursive(p, purpose_folder_id)
        if not all_items:
            results[purpose] = 0
            continue

        # Add all items to album (add_item is idempotent for duplicates)
        all_ids = [item["id"] for item in all_items]
        if _add_items_to_album(p, album_id, all_ids):
            logger.info("Synced %d items to album '%s'", len(all_ids), album_name)
        else:
            logger.error("Failed to sync items to '%s'", album_name)

        results[purpose] = len(all_ids)

    return results


def ensure_albums_exist() -> None:
    """Create albums for any missing purposes on startup (idempotent)."""
    p = _get_photos()
    if p is None:
        return

    photos_root = Path(os.environ.get("PHOTOS_ROOT", "/photos_root"))
    for purpose_dir in sorted(photos_root.iterdir()):
        if not purpose_dir.is_dir():
            continue
        purpose = purpose_dir.name
        album_name = f"{_ALBUM_PREFIX}{purpose}"
        if _find_album_by_name(p, album_name) is None:
            album_id = _create_normal_album(p, album_name, [])
            if album_id is not None:
                logger.info("Created album '%s' (id=%d)", album_name, album_id)
