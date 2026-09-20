#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from etsy_api import load_etsy_client, load_etsy_config  # noqa: E402


load_dotenv(REPO_ROOT / ".env")

REQUIRED_ETSY_FIELDS = (
    "title",
    "description",
    "price",
    "quantity",
    "who_made",
    "when_made",
    "taxonomy_id",
    "type",
)


def load_metadata(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_metadata(metadata: dict) -> None:
    ip_review = metadata.get("ip_review", {})
    if ip_review.get("status") != "approved":
        raise RuntimeError(
            "Refusing to create Etsy draft: ip_review.status must be 'approved'"
        )
    if ip_review.get("original_art_only") is not True:
        raise RuntimeError(
            "Refusing to create Etsy draft: original_art_only must be true"
        )

    etsy = metadata.get("etsy", {})
    missing = [
        field
        for field in REQUIRED_ETSY_FIELDS
        if etsy.get(field) in (None, "", [])
    ]
    if missing:
        raise RuntimeError("Missing Etsy fields: " + ", ".join(missing))

    if etsy.get("type") != "download":
        raise RuntimeError("Only Etsy digital-download listings are supported")


def resolve_asset(sidecar: Path, filename: str) -> Path:
    path = Path(filename)
    if path.is_absolute():
        return path
    return sidecar.parent / path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an Etsy draft from a filename-linked .etsy.json sidecar."
    )
    parser.add_argument("metadata_file", help="Path to the .etsy.json sidecar")
    parser.add_argument(
        "--include-assets",
        action="store_true",
        help="Also send/mock listing image and digital file upload operations.",
    )
    parser.add_argument(
        "--allow-real-api",
        action="store_true",
        help="Required safety switch when ETSY_MODE=real.",
    )
    args = parser.parse_args()

    sidecar = Path(args.metadata_file).resolve()
    metadata = load_metadata(sidecar)
    validate_metadata(metadata)

    cfg = load_etsy_config()
    if cfg.mode == "real" and not args.allow_real_api:
        raise RuntimeError(
            "ETSY_MODE=real is configured, but --allow-real-api was not supplied. "
            "No Etsy request was sent."
        )

    client = load_etsy_client()
    draft = client.create_draft_listing(metadata)
    listing_id = int(draft["listing_id"])

    result = {
        "draft": draft,
        "listing_images": [],
        "digital_files": [],
    }

    if args.include_assets:
        for image in metadata.get("listing_images", []):
            path = resolve_asset(sidecar, image["filename"])
            if cfg.mode == "real" and not path.is_file():
                raise FileNotFoundError(f"Listing image not found: {path}")
            result["listing_images"].append(
                client.upload_listing_image(listing_id, path)
            )

        for item in metadata.get("digital_files", []):
            path = resolve_asset(sidecar, item["filename"])
            if cfg.mode == "real" and not path.is_file():
                raise FileNotFoundError(f"Digital file not found: {path}")
            result["digital_files"].append(
                client.upload_listing_file(listing_id, path)
            )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
