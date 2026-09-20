#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_metadata(image: Path, listing_key: str | None) -> dict:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Etsy metadata sidecar tied to an image filename."
    )
    parser.add_argument("image", help="Image filename or path")
    parser.add_argument(
        "--listing-key",
        help="Stable listing/bundle key. Defaults to the image stem."
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional output directory. Defaults to the image directory."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing sidecar."
    )
    args = parser.parse_args()

    image = Path(args.image)
    output_dir = Path(args.output_dir) if args.output_dir else image.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    sidecar = output_dir / f"{image.stem}.etsy.json"
    if sidecar.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing sidecar: {sidecar}")

    metadata = build_metadata(image, args.listing_key)
    sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
