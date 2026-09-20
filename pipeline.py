#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

import dropbox
import requests
from dotenv import load_dotenv
from PIL import Image


load_dotenv()

LOG = logging.getLogger("etsy-image-pipeline")


@dataclass(frozen=True)
class Config:
    approved_folder: str
    upscaled_folder: str
    needs_review_folder: str
    upscale_factor: int
    face_enhance: bool
    min_output_width: int
    min_output_height: int
    request_timeout: int
    poll_interval: int
    max_poll_seconds: int
    copy_failures_to_review: bool
    overwrite_output: bool
    replicate_api_token: str
    replicate_model_version: str


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    token = os.getenv("REPLICATE_API_TOKEN", "").strip()
    version = os.getenv("REPLICATE_MODEL_VERSION", "").strip()

    if not token:
        raise RuntimeError("REPLICATE_API_TOKEN is required")
    if not version:
        raise RuntimeError("REPLICATE_MODEL_VERSION is required")

    factor = int(os.getenv("UPSCALE_FACTOR", "3"))
    if factor < 2 or factor > 8:
        raise RuntimeError("UPSCALE_FACTOR must be between 2 and 8")

    return Config(
        approved_folder=os.getenv("DROPBOX_APPROVED_FOLDER", "/Etsy/Approved"),
        upscaled_folder=os.getenv("DROPBOX_UPSCALED_FOLDER", "/Etsy/Upscaled"),
        needs_review_folder=os.getenv("DROPBOX_NEEDS_REVIEW_FOLDER", "/Etsy/Needs-Review"),
        upscale_factor=factor,
        face_enhance=env_bool("FACE_ENHANCE", False),
        min_output_width=int(os.getenv("MIN_OUTPUT_WIDTH", "4000")),
        min_output_height=int(os.getenv("MIN_OUTPUT_HEIGHT", "4000")),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT_SECONDS", "300")),
        poll_interval=int(os.getenv("POLL_INTERVAL_SECONDS", "2")),
        max_poll_seconds=int(os.getenv("MAX_POLL_SECONDS", "900")),
        copy_failures_to_review=env_bool("COPY_FAILURES_TO_REVIEW", True),
        overwrite_output=env_bool("OVERWRITE_OUTPUT", False),
        replicate_api_token=token,
        replicate_model_version=version,
    )


def make_dropbox_client() -> dropbox.Dropbox:
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN", "").strip()
    app_key = os.getenv("DROPBOX_APP_KEY", "").strip()
    app_secret = os.getenv("DROPBOX_APP_SECRET", "").strip()

    if refresh_token and app_key and app_secret:
        LOG.info("Using Dropbox refresh-token authentication")
        return dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )

    if access_token:
        LOG.info("Using Dropbox access-token authentication")
        return dropbox.Dropbox(access_token)

    raise RuntimeError(
        "Configure either DROPBOX_ACCESS_TOKEN or "
        "DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET"
    )


def ensure_dropbox_folder(dbx: dropbox.Dropbox, path: str) -> None:
    try:
        dbx.files_get_metadata(path)
    except dropbox.exceptions.ApiError:
        LOG.info("Creating Dropbox folder: %s", path)
        dbx.files_create_folder_v2(path)


def list_pngs(dbx: dropbox.Dropbox, folder: str):
    result = dbx.files_list_folder(folder)
    while True:
        for entry in result.entries:
            if isinstance(entry, dropbox.files.FileMetadata) and entry.name.lower().endswith(".png"):
                yield entry
        if not result.has_more:
            break
        result = dbx.files_list_folder_continue(result.cursor)


def dropbox_file_exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False


def download_dropbox_file(dbx: dropbox.Dropbox, path: str) -> bytes:
    _, response = dbx.files_download(path)
    return response.content


def upload_dropbox_file(
    dbx: dropbox.Dropbox,
    path: str,
    data: bytes,
    overwrite: bool,
) -> None:
    mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
    dbx.files_upload(data, path, mode=mode, mute=True)


def copy_to_review(dbx: dropbox.Dropbox, src_path: str, review_folder: str) -> None:
    dst = f"{review_folder.rstrip('/')}/{PurePosixPath(src_path).name}"
    if dropbox_file_exists(dbx, dst):
        LOG.warning("Needs-Review copy already exists: %s", dst)
        return
    dbx.files_copy_v2(src_path, dst)
    LOG.warning("Copied failed source to %s", dst)


def source_alpha(source_bytes: bytes) -> tuple[Optional[Image.Image], bool]:
    with Image.open(io.BytesIO(source_bytes)) as img:
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        lo, hi = alpha.getextrema()
        has_transparency = lo < 255
        return alpha.copy(), has_transparency


def run_replicate_upscale(source_bytes: bytes, cfg: Config) -> bytes:
    headers = {
        "Authorization": f"Bearer {cfg.replicate_api_token}",
        "Accept": "application/json",
    }

    create_url = "https://api.replicate.com/v1/predictions"

    files = {
        "image": ("input.png", source_bytes, "image/png"),
    }

    # Replicate prediction endpoints generally accept JSON/base64 or hosted URLs.
    # To avoid committing provider-specific hosting logic, this worker uses a
    # data URI for the source image.
    import base64

    data_uri = "data:image/png;base64," + base64.b64encode(source_bytes).decode("ascii")

    payload = {
        "version": cfg.replicate_model_version,
        "input": {
            "image": data_uri,
            "scale": cfg.upscale_factor,
            "face_enhance": cfg.face_enhance,
        },
    }

    response = requests.post(
        create_url,
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=cfg.request_timeout,
    )
    response.raise_for_status()
    prediction = response.json()

    get_url = prediction.get("urls", {}).get("get")
    if not get_url:
        raise RuntimeError(f"Replicate response did not include polling URL: {prediction}")

    deadline = time.monotonic() + cfg.max_poll_seconds
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError("Replicate prediction timed out")

        poll = requests.get(get_url, headers=headers, timeout=cfg.request_timeout)
        poll.raise_for_status()
        prediction = poll.json()
        status = prediction.get("status")

        if status == "succeeded":
            output = prediction.get("output")
            if isinstance(output, list):
                output = output[0] if output else None
            if not isinstance(output, str) or not output.startswith("http"):
                raise RuntimeError(f"Unexpected Replicate output: {prediction.get('output')!r}")

            image_response = requests.get(output, timeout=cfg.request_timeout)
            image_response.raise_for_status()
            return image_response.content

        if status in {"failed", "canceled"}:
            raise RuntimeError(
                f"Replicate prediction {status}: {prediction.get('error') or prediction}"
            )

        time.sleep(cfg.poll_interval)


def restore_alpha(source_bytes: bytes, upscaled_bytes: bytes) -> bytes:
    alpha, had_transparency = source_alpha(source_bytes)

    with Image.open(io.BytesIO(upscaled_bytes)) as upscaled:
        rgb = upscaled.convert("RGB")

        if had_transparency and alpha is not None:
            alpha = alpha.resize(rgb.size, Image.Resampling.LANCZOS)
            final = rgb.convert("RGBA")
            final.putalpha(alpha)
        else:
            final = rgb.convert("RGBA")

        output = io.BytesIO()
        final.save(output, format="PNG", optimize=True)
        return output.getvalue()


def validate_output(
    source_bytes: bytes,
    output_bytes: bytes,
    cfg: Config,
) -> tuple[int, int, bool]:
    _, source_has_transparency = source_alpha(source_bytes)

    with Image.open(io.BytesIO(output_bytes)) as img:
        img.verify()

    with Image.open(io.BytesIO(output_bytes)) as img:
        width, height = img.size
        rgba = img.convert("RGBA")
        alpha = rgba.getchannel("A")
        min_alpha, _ = alpha.getextrema()
        output_has_transparency = min_alpha < 255

    if width < cfg.min_output_width or height < cfg.min_output_height:
        raise ValueError(
            f"Upscaled image too small: {width}x{height}; "
            f"minimum is {cfg.min_output_width}x{cfg.min_output_height}"
        )

    if source_has_transparency and not output_has_transparency:
        raise ValueError("Source used transparency but output alpha was lost")

    return width, height, output_has_transparency


def process_file(
    dbx: dropbox.Dropbox,
    entry: dropbox.files.FileMetadata,
    cfg: Config,
) -> bool:
    src_path = entry.path_display or entry.path_lower
    if not src_path:
        raise RuntimeError(f"Dropbox entry has no usable path: {entry.name}")

    dst_path = f"{cfg.upscaled_folder.rstrip('/')}/{entry.name}"

    if not cfg.overwrite_output and dropbox_file_exists(dbx, dst_path):
        LOG.info("SKIP %s, output already exists", entry.name)
        return False

    LOG.info("Processing %s", src_path)
    source = download_dropbox_file(dbx, src_path)

    with Image.open(io.BytesIO(source)) as src_img:
        LOG.info("Source dimensions: %sx%s mode=%s", *src_img.size, src_img.mode)

    upscaled_raw = run_replicate_upscale(source, cfg)
    final_png = restore_alpha(source, upscaled_raw)
    width, height, has_alpha = validate_output(source, final_png, cfg)

    upload_dropbox_file(dbx, dst_path, final_png, overwrite=cfg.overwrite_output)
    LOG.info(
        "DONE %s -> %s (%sx%s, transparency=%s)",
        entry.name,
        dst_path,
        width,
        height,
        has_alpha,
    )
    return True


def run_once(limit: Optional[int] = None) -> int:
    cfg = load_config()
    dbx = make_dropbox_client()

    ensure_dropbox_folder(dbx, cfg.approved_folder)
    ensure_dropbox_folder(dbx, cfg.upscaled_folder)
    if cfg.copy_failures_to_review:
        ensure_dropbox_folder(dbx, cfg.needs_review_folder)

    processed = 0
    failures = 0

    for entry in list_pngs(dbx, cfg.approved_folder):
        if limit is not None and processed >= limit:
            break

        try:
            changed = process_file(dbx, entry, cfg)
            if changed:
                processed += 1
        except Exception:
            failures += 1
            LOG.exception("FAILED %s", entry.name)
            if cfg.copy_failures_to_review and entry.path_display:
                try:
                    copy_to_review(dbx, entry.path_display, cfg.needs_review_folder)
                except Exception:
                    LOG.exception("Could not copy %s to Needs-Review", entry.name)

    LOG.info("Run complete. processed=%s failures=%s", processed, failures)
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upscale approved Etsy PNGs from Dropbox")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one Dropbox scan and exit. This is the normal systemd-timer mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of newly processed files for this run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.once:
        LOG.info("No daemon loop is implemented by design; running one pass.")

    try:
        return run_once(limit=args.limit)
    except KeyboardInterrupt:
        LOG.warning("Interrupted")
        return 130
    except Exception:
        LOG.exception("Fatal pipeline error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
