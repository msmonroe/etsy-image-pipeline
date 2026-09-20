#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path, PurePosixPath

import dropbox
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from listing_images import generate_listing_images  # noqa: E402


load_dotenv(REPO_ROOT / ".env")


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

    raise RuntimeError("Dropbox credentials are not configured")


def exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False


def download(dbx: dropbox.Dropbox, path: str) -> bytes:
    _, response = dbx.files_download(path)
    return response.content


def upload(
    dbx: dropbox.Dropbox,
    path: str,
    data: bytes,
    overwrite: bool,
) -> None:
    mode = (
        dropbox.files.WriteMode.overwrite
        if overwrite
        else dropbox.files.WriteMode.add
    )
    dbx.files_upload(data, path, mode=mode, mute=True)


def ensure_folder(dbx: dropbox.Dropbox, path: str) -> None:
    try:
        dbx.files_get_metadata(path)
    except dropbox.exceptions.ApiError:
        dbx.files_create_folder_v2(path)


def image_path_from_arg(value: str) -> str:
    path = PurePosixPath(value)
    if str(path).startswith("/"):
        return str(path)

    folder = os.getenv(
        "DROPBOX_UPSCALED_FOLDER", "/Etsy/Upscaled"
    ).rstrip("/")
    return f"{folder}/{path.name}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Etsy listing JPEGs from an upscaled Dropbox PNG"
        )
    )
    parser.add_argument(
        "image",
        help="Upscaled PNG basename or full Dropbox path",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing listing images and update sidecar",
    )
    args = parser.parse_args()

    dbx = make_dropbox_client()
    image_path = image_path_from_arg(args.image)
    image = PurePosixPath(image_path)
    sidecar_path = str(
        image.with_name(f"{image.stem}.etsy.json")
    )

    if not exists(dbx, image_path):
        raise SystemExit(f"Dropbox image not found: {image_path}")

    if not exists(dbx, sidecar_path):
        raise SystemExit(
            f"Dropbox Etsy sidecar not found: {sidecar_path}"
        )

    metadata = json.loads(
        download(dbx, sidecar_path).decode("utf-8")
    )
    listing_key = metadata.get("listing_key") or image.stem
    digital_files = [
        item["filename"]
        for item in metadata.get("digital_files", [])
        if item.get("filename")
    ]

    width = int(
        os.getenv("ETSY_LISTING_IMAGE_WIDTH", "2400")
    )
    height = int(
        os.getenv("ETSY_LISTING_IMAGE_HEIGHT", "2000")
    )
    quality = int(
        os.getenv("ETSY_LISTING_IMAGE_JPEG_QUALITY", "90")
    )
    root = os.getenv(
        "DROPBOX_LISTING_IMAGES_FOLDER",
        "/Etsy/Listing-Images",
    ).rstrip("/")
    output_folder = f"{root}/{listing_key}"

    ensure_folder(dbx, root)
    ensure_folder(dbx, output_folder)

    source_png = download(dbx, image_path)
    generated = generate_listing_images(
        source_png,
        digital_files,
        width=width,
        height=height,
        jpeg_quality=quality,
    )

    labels = {
        "01_hero.jpg": "Primary product preview",
        "02_detail.jpg": "Artwork detail preview",
        "03_specs.jpg": "Digital file specifications",
        "04_included.jpg": "Files included in this digital download",
    }

    entries = []
    for rank, (suffix, payload) in enumerate(
        generated.items(),
        start=1,
    ):
        filename = f"{image.stem}_{suffix}"
        path = f"{output_folder}/{filename}"

        if exists(dbx, path) and not args.force:
            raise SystemExit(
                f"Refusing to overwrite existing listing image: {path}"
            )

        upload(
            dbx,
            path,
            payload,
            overwrite=args.force,
        )
        entries.append(
            {
                "filename": path,
                "rank": rank,
                "alt_text": labels[suffix],
            }
        )
        print(path)

    metadata["listing_images"] = entries
    metadata_bytes = (
        json.dumps(metadata, indent=2) + "\n"
    ).encode("utf-8")
    upload(
        dbx,
        sidecar_path,
        metadata_bytes,
        overwrite=True,
    )

    print(f"Updated sidecar: {sidecar_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
