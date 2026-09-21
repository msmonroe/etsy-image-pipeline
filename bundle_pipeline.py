#!/usr/bin/env python3
"""Build Etsy-safe ZIP bundles from completed vector assets in Dropbox."""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import dropbox
from dotenv import load_dotenv

load_dotenv()
LOG = logging.getLogger("etsy-bundle-pipeline")
FORMATS = ("SVG", "PNG", "PDF", "EPS")


@dataclass(frozen=True)
class Config:
    vectorized_folder: str
    bundles_folder: str
    max_zip_bytes: int
    max_listing_files: int
    overwrite_output: bool


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    max_mb = float(os.getenv("BUNDLE_MAX_ZIP_MB", "19"))
    return Config(
        vectorized_folder=os.getenv("DROPBOX_VECTORIZED_FOLDER", "/Etsy/Vectorized"),
        bundles_folder=os.getenv("DROPBOX_BUNDLES_FOLDER", "/Etsy/Bundles"),
        max_zip_bytes=int(max_mb * 1024 * 1024),
        max_listing_files=int(os.getenv("BUNDLE_MAX_LISTING_FILES", "5")),
        overwrite_output=env_bool("OVERWRITE_OUTPUT", False),
    )


def make_dropbox_client() -> dropbox.Dropbox:
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN", "").strip()
    app_key = os.getenv("DROPBOX_APP_KEY", "").strip()
    app_secret = os.getenv("DROPBOX_APP_SECRET", "").strip()
    if refresh_token and app_key and app_secret:
        return dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
    if access_token:
        return dropbox.Dropbox(access_token)
    raise RuntimeError("Configure Dropbox credentials in .env")


def exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False


def ensure_folder(dbx: dropbox.Dropbox, path: str) -> None:
    current = ""
    for part in PurePosixPath(path).parts:
        if part == "/":
            continue
        current += "/" + part
        if not exists(dbx, current):
            dbx.files_create_folder_v2(current)


def list_files(dbx: dropbox.Dropbox, folder: str) -> dict[str, str]:
    result = dbx.files_list_folder(folder)
    found: dict[str, str] = {}
    while True:
        for entry in result.entries:
            if isinstance(entry, dropbox.files.FileMetadata):
                found[entry.name] = entry.path_display or entry.path_lower
        if not result.has_more:
            return found
        result = dbx.files_list_folder_continue(result.cursor)


def download(dbx: dropbox.Dropbox, path: str) -> bytes:
    _, response = dbx.files_download(path)
    return response.content


def upload(dbx: dropbox.Dropbox, path: str, data: bytes, overwrite: bool) -> None:
    mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
    dbx.files_upload(data, path, mode=mode, mute=True)


def zip_bytes(entries: list[tuple[str, bytes]], manifest: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for arcname, data in entries:
            zf.writestr(arcname, data)
        zf.writestr("MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True))
        zf.writestr(
            "README.txt",
            "Samurai Cats & Ramen digital art bundle\n\n"
            "Included formats may include SVG, PNG, PDF, and EPS.\n"
            "PNG files are production renders from the vector workflow.\n"
            "Detailed artwork is intended for print, sublimation, DTF, stickers, "
            "posters, engraving, and digital design. It is not advertised as "
            "general-purpose Cricut/Silhouette cut-ready artwork.\n",
        )
    return out.getvalue()


def split_archives(entries: list[tuple[str, bytes]], base_manifest: dict, max_bytes: int) -> list[bytes]:
    chunks: list[list[tuple[str, bytes]]] = []
    current: list[tuple[str, bytes]] = []

    for entry in entries:
        candidate = current + [entry]
        test_manifest = {**base_manifest, "files": [name for name, _ in candidate]}
        if len(zip_bytes(candidate, test_manifest)) <= max_bytes:
            current = candidate
            continue
        if not current:
            raise RuntimeError(f"Single asset exceeds ZIP safety limit: {entry[0]}")
        chunks.append(current)
        current = [entry]
        test_manifest = {**base_manifest, "files": [entry[0]]}
        if len(zip_bytes(current, test_manifest)) > max_bytes:
            raise RuntimeError(f"Single asset exceeds ZIP safety limit: {entry[0]}")
    if current:
        chunks.append(current)

    archives: list[bytes] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks, 1):
        manifest = {
            **base_manifest,
            "part": i,
            "parts": total,
            "files": [name for name, _ in chunk],
        }
        archives.append(zip_bytes(chunk, manifest))
    return archives


def discover_designs(dbx: dropbox.Dropbox, cfg: Config, prefix: str) -> dict[str, dict[str, str]]:
    by_format = {fmt: list_files(dbx, f"{cfg.vectorized_folder.rstrip('/')}/{fmt}") for fmt in FORMATS}
    stems: set[str] = set()
    for fmt, files in by_format.items():
        ext = "." + fmt.lower()
        for name in files:
            if name.lower().endswith(ext) and Path(name).stem.startswith(prefix):
                stems.add(Path(name).stem)

    designs: dict[str, dict[str, str]] = {}
    for stem in sorted(stems):
        assets: dict[str, str] = {}
        for fmt in FORMATS:
            expected = f"{stem}.{fmt.lower()}"
            path = by_format[fmt].get(expected)
            if not path:
                raise RuntimeError(f"Missing {fmt} for {stem}: expected {expected}")
            assets[fmt] = path
        designs[stem] = assets
    if not designs:
        raise RuntimeError(f"No completed vector assets found for prefix: {prefix}")
    return designs


def fetch_entries(dbx: dropbox.Dropbox, designs: dict[str, dict[str, str]]) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for stem, assets in designs.items():
        for fmt in FORMATS:
            path = assets[fmt]
            LOG.info("Downloading %s", path)
            entries.append((f"{stem}/{fmt}/{PurePosixPath(path).name}", download(dbx, path)))
    return entries


def save_archives(dbx: dropbox.Dropbox, cfg: Config, folder: str, base_name: str,
                  archives: list[bytes]) -> list[str]:
    if len(archives) > cfg.max_listing_files:
        raise RuntimeError(
            f"{base_name} requires {len(archives)} ZIPs, exceeding Etsy listing limit "
            f"of {cfg.max_listing_files}. Reduce the bundle or raise compression."
        )
    ensure_folder(dbx, folder)
    paths: list[str] = []
    total = len(archives)
    for i, data in enumerate(archives, 1):
        suffix = "" if total == 1 else f"_part_{i:02d}"
        name = f"{base_name}{suffix}.zip"
        path = f"{folder.rstrip('/')}/{name}"
        if exists(dbx, path) and not cfg.overwrite_output:
            LOG.info("SKIP existing %s", path)
            paths.append(path)
            continue
        LOG.info("Uploading %s (%.2f MB)", path, len(data) / 1024 / 1024)
        upload(dbx, path, data, cfg.overwrite_output)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Etsy-safe ZIP bundles from /Etsy/Vectorized")
    parser.add_argument("--prefix", required=True, help="Design filename prefix, e.g. samurai_ramen_")
    parser.add_argument("--collection-name", default="samurai_cats_ramen_collection",
                        help="Base filename for collection ZIPs")
    parser.add_argument("--individual", action=argparse.BooleanOptionalAction, default=True,
                        help="Also build per-design ZIPs (default: true)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    dbx = make_dropbox_client()
    designs = discover_designs(dbx, cfg, args.prefix)
    LOG.info("Found %d complete designs", len(designs))

    downloaded: dict[str, list[tuple[str, bytes]]] = {}
    all_entries: list[tuple[str, bytes]] = []
    for stem, assets in designs.items():
        entries = fetch_entries(dbx, {stem: assets})
        downloaded[stem] = entries
        all_entries.extend(entries)

    if args.individual:
        for stem, entries in downloaded.items():
            archives = split_archives(
                entries,
                {"bundle_type": "individual", "design": stem, "formats": list(FORMATS)},
                cfg.max_zip_bytes,
            )
            save_archives(
                dbx, cfg, f"{cfg.bundles_folder.rstrip('/')}/Individual",
                stem, archives,
            )

    collection_archives = split_archives(
        all_entries,
        {"bundle_type": "collection", "designs": list(designs), "formats": list(FORMATS)},
        cfg.max_zip_bytes,
    )
    paths = save_archives(
        dbx, cfg, f"{cfg.bundles_folder.rstrip('/')}/Collections",
        args.collection_name, collection_archives,
    )
    LOG.info("DONE collection designs=%d zip_files=%d", len(designs), len(paths))
    for path in paths:
        LOG.info("  %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
