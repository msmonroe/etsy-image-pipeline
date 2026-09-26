#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import PurePosixPath

from dotenv import load_dotenv

from etsy_delivery import create_etsy_delivery_png
from pipeline import (
    download_dropbox_file,
    dropbox_file_exists,
    ensure_dropbox_folder,
    make_dropbox_client,
    upload_dropbox_file,
)


load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Etsy-safe delivery PNG from an existing upscaled Dropbox PNG"
    )
    parser.add_argument("filename", help="Upscaled PNG basename or full Dropbox path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing delivery output")
    args = parser.parse_args()

    upscaled_folder = os.getenv("DROPBOX_UPSCALED_FOLDER", "/Etsy/Upscaled").rstrip("/")
    delivery_folder = os.getenv("DROPBOX_DELIVERY_FOLDER", "/Etsy/Delivery").rstrip("/")
    max_mb = float(os.getenv("ETSY_MAX_FILE_MB", "19"))
    min_dimension = int(os.getenv("ETSY_DELIVERY_MIN_DIMENSION", "4000"))

    source_path = args.filename
    if not source_path.startswith("/"):
        source_path = f"{upscaled_folder}/{source_path}"

    src = PurePosixPath(source_path)
    delivery_path = f"{delivery_folder}/{src.stem}_etsy.png"

    dbx = make_dropbox_client()
    ensure_dropbox_folder(dbx, delivery_folder)

    if not dropbox_file_exists(dbx, source_path):
        raise FileNotFoundError(f"Upscaled Dropbox file not found: {source_path}")

    if dropbox_file_exists(dbx, delivery_path) and not args.force:
        raise FileExistsError(
            f"Delivery file already exists: {delivery_path}. Use --force to replace it."
        )

    master = download_dropbox_file(dbx, source_path)
    result = create_etsy_delivery_png(
        master,
        max_file_bytes=int(max_mb * 1024 * 1024),
        min_dimension=min_dimension,
        dpi=300,
    )

    upload_dropbox_file(
        dbx,
        delivery_path,
        result.png_bytes,
        overwrite=args.force,
    )

    sidecar_path = f"{upscaled_folder}/{src.stem}.etsy.json"
    if dropbox_file_exists(dbx, sidecar_path):
        metadata = json.loads(
            download_dropbox_file(dbx, sidecar_path).decode("utf-8")
        )
        for item in metadata.get("digital_files", []):
            if item.get("filename") in {src.name, f"{src.stem}.png"}:
                item["dropbox_path"] = delivery_path
                item["master_dropbox_path"] = source_path
                item["file_size_bytes"] = result.size_bytes
                item["width_px"] = result.width
                item["height_px"] = result.height

        payload = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
        upload_dropbox_file(dbx, sidecar_path, payload, overwrite=True)

        approved_folder = os.getenv(
            "DROPBOX_APPROVED_FOLDER", "/Etsy/Approved"
        ).rstrip("/")
        approved_sidecar = f"{approved_folder}/{src.stem}.etsy.json"
        if dropbox_file_exists(dbx, approved_sidecar):
            upload_dropbox_file(
                dbx, approved_sidecar, payload, overwrite=True
            )

    print(delivery_path)
    print(
        f"{result.width}x{result.height} "
        f"{result.size_bytes / (1024 * 1024):.2f} MiB"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Etsy delivery generation failed: {exc}", file=sys.stderr)
        raise
