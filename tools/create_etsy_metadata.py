#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import PurePosixPath

import dropbox
from dotenv import load_dotenv


REPO_ROOT = PurePosixPath(__file__).parent.parent
load_dotenv(".env")


def make_dropbox_client() -> dropbox.Dropbox:
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN", "").strip()
    app_key = os.getenv("DROPBOX_APP_KEY", "").strip()
    app_secret = os.getenv("DROPBOX_APP_SECRET", "").strip()

    if refresh_token and app_key and app_secret:
        return dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )

    if access_token:
        return dropbox.Dropbox(access_token)

    raise RuntimeError(
        "Configure either DROPBOX_ACCESS_TOKEN or "
        "DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET"
    )


def build_metadata(image_name: str, listing_key: str | None) -> dict:
    image = PurePosixPath(image_name)
    asset_key = image.stem
    listing_key = listing_key or asset_key

    return {
        "asset_key": asset_key,
        "source_filename": image.name,
        "listing_key": listing_key,
        "role": "master",
        "ip_review": {
            "status": "pending",
            "original_art_only": True,
            "notes": ""
        },
        "image": {
            "target_width_px": 4600,
            "target_height_px": 4600,
            "dpi": 300,
            "transparent": True,
            "format": "PNG"
        },
        "listing_images": [],
        "digital_files": [
            {
                "filename": image.name,
                "display_name": image.name
            }
        ],
        "etsy": {
            "title": "",
            "description": "",
            "price": None,
            "quantity": 999,
            "who_made": "i_did",
            "when_made": "2020_2026",
            "taxonomy_id": None,
            "type": "download",
            "tags": [],
            "materials": [],
            "sku": None,
            "listing_id": None,
            "state": "metadata_only"
        }
    }


def normalize_dropbox_image_path(value: str) -> str:
    path = PurePosixPath(value)
    if str(path).startswith("/"):
        return str(path)

    approved = os.getenv("DROPBOX_APPROVED_FOLDER", "/Etsy/Approved").rstrip("/")
    return f"{approved}/{path.name}"


def dropbox_exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Etsy metadata sidecar beside a Dropbox image."
    )
    parser.add_argument(
        "image",
        help=(
            "Dropbox image path or basename. A basename is resolved under "
            "DROPBOX_APPROVED_FOLDER."
        ),
    )
    parser.add_argument(
        "--listing-key",
        help="Stable listing/bundle key. Defaults to the image stem.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing Dropbox sidecar.",
    )
    args = parser.parse_args()

    image_path = normalize_dropbox_image_path(args.image)
    image = PurePosixPath(image_path)
    sidecar_path = str(image.with_name(f"{image.stem}.etsy.json"))

    dbx = make_dropbox_client()

    if not dropbox_exists(dbx, image_path):
        raise SystemExit(f"Dropbox image not found: {image_path}")

    if dropbox_exists(dbx, sidecar_path) and not args.force:
        raise SystemExit(
            f"Refusing to overwrite existing Dropbox sidecar: {sidecar_path}"
        )

    metadata = build_metadata(image.name, args.listing_key)
    payload = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")

    mode = (
        dropbox.files.WriteMode.overwrite
        if args.force
        else dropbox.files.WriteMode.add
    )
    dbx.files_upload(payload, sidecar_path, mode=mode, mute=True)

    print(sidecar_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Etsy metadata creation failed: {exc}", file=sys.stderr)
        raise
