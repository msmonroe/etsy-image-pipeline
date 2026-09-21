#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import sys
import time
from pathlib import PurePosixPath
from typing import Optional

import dropbox
import requests
from dotenv import load_dotenv
from PIL import Image
from pydantic import ValidationError

from listing_images import generate_listing_images
from pipeline_graph import PipelineGraph, PipelineStep
from pipeline_models import AssetContext, EtsyMetadata, ImageFacts, PipelineConfig, RunSummary

load_dotenv()
LOG = logging.getLogger("etsy-image-pipeline")

# Compatibility name for callers while the domain type lives in pipeline_models.
Config = PipelineConfig


def load_config() -> PipelineConfig:
    try:
        return PipelineConfig.from_env()
    except ValidationError as exc:
        raise RuntimeError(f"Invalid pipeline configuration: {exc}") from exc


def make_dropbox_client() -> dropbox.Dropbox:
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN", "").strip()
    app_key = os.getenv("DROPBOX_APP_KEY", "").strip()
    app_secret = os.getenv("DROPBOX_APP_SECRET", "").strip()
    if refresh_token and app_key and app_secret:
        LOG.info("Using Dropbox refresh-token authentication")
        return dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
    if access_token:
        LOG.info("Using Dropbox access-token authentication")
        return dropbox.Dropbox(access_token)
    raise RuntimeError("Configure DROPBOX_ACCESS_TOKEN or DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET")


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
            return
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


def upload_dropbox_file(dbx: dropbox.Dropbox, path: str, data: bytes, overwrite: bool) -> None:
    mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
    dbx.files_upload(data, path, mode=mode, mute=True)


def copy_to_review(dbx: dropbox.Dropbox, src_path: str, review_folder: str) -> None:
    dst = f"{review_folder.rstrip('/')}/{PurePosixPath(src_path).name}"
    if dropbox_file_exists(dbx, dst):
        LOG.warning("Needs-Review copy already exists: %s", dst)
        return
    dbx.files_copy_v2(src_path, dst)
    LOG.warning("Copied failed source to %s", dst)


def sidecar_path(src_image_path: str) -> str:
    src = PurePosixPath(src_image_path)
    return str(src.with_name(f"{src.stem}.etsy.json"))


def build_default_etsy_metadata(src_image_path: str, dst_image_path: str, final_png: bytes) -> dict:
    return EtsyMetadata.for_processed_asset(src_image_path, dst_image_path, final_png).model_dump(mode="json")


def read_etsy_metadata(dbx: dropbox.Dropbox, path: str) -> EtsyMetadata:
    raw = json.loads(download_dropbox_file(dbx, path).decode("utf-8"))
    return EtsyMetadata.model_validate(raw)


def write_etsy_metadata(dbx: dropbox.Dropbox, path: str, metadata: EtsyMetadata, overwrite: bool) -> None:
    payload = (metadata.model_dump_json(indent=2) + "\n").encode("utf-8")
    upload_dropbox_file(dbx, path, payload, overwrite=overwrite)


def ensure_etsy_sidecar(dbx: dropbox.Dropbox, src_image_path: str, dst_image_path: str, final_png: bytes) -> str:
    path = sidecar_path(src_image_path)
    if dropbox_file_exists(dbx, path):
        # Existing metadata is now type-checked before the graph can continue.
        read_etsy_metadata(dbx, path)
        return path
    metadata = EtsyMetadata.for_processed_asset(src_image_path, dst_image_path, final_png)
    write_etsy_metadata(dbx, path, metadata, overwrite=False)
    LOG.info("Created Etsy sidecar from processed asset -> %s", path)
    return path


def copy_sidecar_to_output(dbx: dropbox.Dropbox, src_image_path: str, output_folder: str, overwrite: bool) -> None:
    src = sidecar_path(src_image_path)
    if not dropbox_file_exists(dbx, src):
        return
    dst = f"{output_folder.rstrip('/')}/{PurePosixPath(src).name}"
    upload_dropbox_file(dbx, dst, download_dropbox_file(dbx, src), overwrite=overwrite)


def generate_listing_assets(
    dbx: dropbox.Dropbox,
    src_image_path: str,
    dst_image_path: str,
    final_png: bytes,
    cfg: PipelineConfig,
) -> None:
    src = PurePosixPath(src_image_path)
    src_sidecar = sidecar_path(src_image_path)
    metadata = read_etsy_metadata(dbx, src_sidecar)
    safe_key = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in metadata.listing_key).strip("_") or src.stem
    listing_folder = f"{cfg.listing_images_folder.rstrip('/')}/{safe_key}"
    ensure_dropbox_folder(dbx, listing_folder)

    generated = generate_listing_images(
        final_png,
        [item.filename for item in metadata.digital_files],
        width=cfg.listing_image_width,
        height=cfg.listing_image_height,
        jpeg_quality=cfg.listing_image_jpeg_quality,
    )
    labels = {
        "01_hero.jpg": "Primary product preview",
        "02_detail.jpg": "Artwork detail preview",
        "03_specs.jpg": "Digital file specifications",
        "04_included.jpg": "Files included in this digital download",
    }
    entries = []
    for rank, (suffix, payload) in enumerate(generated.items(), 1):
        path = f"{listing_folder}/{src.stem}_{suffix}"
        if cfg.overwrite_output or not dropbox_file_exists(dbx, path):
            upload_dropbox_file(dbx, path, payload, overwrite=cfg.overwrite_output)
        entries.append({"filename": path, "rank": rank, "alt_text": labels[suffix]})

    metadata.listing_images = entries
    for item in metadata.digital_files:
        if item.filename == src.name:
            item.dropbox_path = dst_image_path

    write_etsy_metadata(dbx, src_sidecar, metadata, overwrite=True)
    write_etsy_metadata(dbx, f"{cfg.upscaled_folder.rstrip('/')}/{src.stem}.etsy.json", metadata, overwrite=True)


def source_alpha(source_bytes: bytes) -> tuple[Image.Image, bool]:
    with Image.open(io.BytesIO(source_bytes)) as image:
        alpha = image.convert("RGBA").getchannel("A")
        return alpha.copy(), alpha.getextrema()[0] < 255


def replicate_model_url(model: str) -> str:
    if "/" not in model:
        raise RuntimeError("Replicate model must look like owner/model")
    owner, name = model.split("/", 1)
    return f"https://api.replicate.com/v1/models/{owner}/{name}/predictions"


def download_replicate_output(prediction: dict, cfg: PipelineConfig) -> bytes:
    output = prediction.get("output")
    if isinstance(output, list):
        output = output[0] if output else None
    if not isinstance(output, str) or not output.startswith("http"):
        raise RuntimeError(f"Unexpected Replicate output: {prediction.get('output')!r}")
    response = requests.get(output, timeout=cfg.request_timeout)
    response.raise_for_status()
    return response.content


def run_replicate_prediction(model: str, input_payload: dict, cfg: PipelineConfig, version_id: str = "") -> bytes:
    headers = {"Authorization": f"Bearer {cfg.replicate_api_token}", "Accept": "application/json", "Content-Type": "application/json"}
    create_url = "https://api.replicate.com/v1/predictions" if version_id else replicate_model_url(model)
    payload = {"version": version_id, "input": input_payload} if version_id else {"input": input_payload}
    response = requests.post(create_url, headers=headers, json=payload, timeout=cfg.request_timeout)
    if not response.ok:
        raise RuntimeError(f"Replicate create request failed HTTP {response.status_code}: {response.text[:2000]}")
    prediction = response.json()
    if prediction.get("status") == "succeeded":
        return download_replicate_output(prediction, cfg)
    get_url = prediction.get("urls", {}).get("get")
    if not get_url:
        raise RuntimeError("Replicate response did not include polling URL")
    deadline = time.monotonic() + cfg.max_poll_seconds
    while time.monotonic() <= deadline:
        poll = requests.get(get_url, headers=headers, timeout=cfg.request_timeout)
        if not poll.ok:
            raise RuntimeError(f"Replicate poll failed HTTP {poll.status_code}: {poll.text[:2000]}")
        prediction = poll.json()
        if prediction.get("status") == "succeeded":
            return download_replicate_output(prediction, cfg)
        if prediction.get("status") in {"failed", "canceled"}:
            raise RuntimeError(f"Replicate prediction {prediction.get('status')}: {prediction.get('error') or prediction}")
        time.sleep(cfg.poll_interval)
    raise TimeoutError("Replicate prediction timed out")


def is_cuda_oom(error: Exception) -> bool:
    message = str(error).lower()
    return any(token in message for token in ("cuda out of memory", "out of gpu memory", "out-of-gpu-memory"))


def run_replicate_upscale(source_bytes: bytes, cfg: PipelineConfig) -> bytes:
    data_uri = "data:image/png;base64," + base64.b64encode(source_bytes).decode("ascii")
    primary = {"image": data_uri, "scale": cfg.upscale_factor, "face_enhance": cfg.face_enhance}
    try:
        return run_replicate_prediction(cfg.replicate_model, primary, cfg, version_id=cfg.replicate_model_version)
    except Exception as exc:
        if not cfg.replicate_fallback_on_oom or not is_cuda_oom(exc):
            raise
        fallback = {
            "img": data_uri,
            "scale": cfg.upscale_factor,
            "version": cfg.replicate_fallback_version_name,
            "face_enhance": cfg.face_enhance,
            "tile": cfg.replicate_fallback_tile,
        }
        return run_replicate_prediction(cfg.replicate_fallback_model, fallback, cfg)


def restore_alpha(source_bytes: bytes, upscaled_bytes: bytes) -> bytes:
    alpha, transparent = source_alpha(source_bytes)
    with Image.open(io.BytesIO(upscaled_bytes)) as upscaled:
        final = upscaled.convert("RGB").convert("RGBA")
        if transparent:
            final.putalpha(alpha.resize(final.size, Image.Resampling.LANCZOS))
        output = io.BytesIO()
        final.save(output, format="PNG", optimize=True, dpi=(300, 300))
        return output.getvalue()


def validate_output(source_bytes: bytes, output_bytes: bytes, cfg: PipelineConfig) -> tuple[int, int, bool]:
    source_facts = ImageFacts.from_png(source_bytes)
    output_facts = ImageFacts.from_png(output_bytes)
    expected = (source_facts.width_px * cfg.upscale_factor, source_facts.height_px * cfg.upscale_factor)
    actual = (output_facts.width_px, output_facts.height_px)
    if any(abs(a - e) > cfg.dimension_tolerance_px for a, e in zip(actual, expected)):
        raise ValueError(f"Unexpected output dimensions: {actual[0]}x{actual[1]}; expected about {expected[0]}x{expected[1]} (+/- {cfg.dimension_tolerance_px}px)")
    if source_facts.transparent and not output_facts.transparent:
        raise ValueError("Source used transparency but output alpha was lost")
    return actual[0], actual[1], output_facts.transparent


def build_asset_graph(dbx: dropbox.Dropbox, cfg: PipelineConfig) -> PipelineGraph[AssetContext]:
    def download(ctx: AssetContext) -> AssetContext:
        ctx.source_bytes = download_dropbox_file(dbx, ctx.source_path)
        return ctx

    def upscale(ctx: AssetContext) -> AssetContext:
        assert ctx.source_bytes is not None
        ctx.upscaled_bytes = run_replicate_upscale(ctx.source_bytes, cfg)
        return ctx

    def normalize(ctx: AssetContext) -> AssetContext:
        assert ctx.source_bytes is not None and ctx.upscaled_bytes is not None
        ctx.final_png = restore_alpha(ctx.source_bytes, ctx.upscaled_bytes)
        return ctx

    def validate(ctx: AssetContext) -> AssetContext:
        assert ctx.source_bytes is not None and ctx.final_png is not None
        validate_output(ctx.source_bytes, ctx.final_png, cfg)
        ctx.output_facts = ImageFacts.from_png(ctx.final_png)
        return ctx

    def upload(ctx: AssetContext) -> AssetContext:
        assert ctx.final_png is not None
        upload_dropbox_file(dbx, ctx.destination_path, ctx.final_png, overwrite=cfg.overwrite_output)
        return ctx

    def metadata(ctx: AssetContext) -> AssetContext:
        assert ctx.final_png is not None
        ctx.sidecar_path = ensure_etsy_sidecar(dbx, ctx.source_path, ctx.destination_path, ctx.final_png)
        return ctx

    def listing(ctx: AssetContext) -> AssetContext:
        assert ctx.final_png is not None
        if cfg.generate_listing_images:
            generate_listing_assets(dbx, ctx.source_path, ctx.destination_path, ctx.final_png, cfg)
            ctx.listing_assets_generated = True
        else:
            copy_sidecar_to_output(dbx, ctx.source_path, cfg.upscaled_folder, cfg.overwrite_output)
        return ctx

    return PipelineGraph((
        PipelineStep("download", download),
        PipelineStep("upscale", upscale),
        PipelineStep("normalize_png", normalize),
        PipelineStep("validate", validate),
        PipelineStep("upload_master", upload),
        PipelineStep("ensure_metadata", metadata),
        PipelineStep("listing_assets", listing),
    ))


def process_file(dbx: dropbox.Dropbox, entry: dropbox.files.FileMetadata, cfg: PipelineConfig) -> bool:
    src_path = entry.path_display or entry.path_lower
    if not src_path:
        raise RuntimeError(f"Dropbox entry has no usable path: {entry.name}")
    dst_path = f"{cfg.upscaled_folder.rstrip('/')}/{entry.name}"
    if not cfg.overwrite_output and dropbox_file_exists(dbx, dst_path):
        LOG.info("SKIP %s, output already exists", entry.name)
        return False
    context = AssetContext(source_name=entry.name, source_path=src_path, destination_path=dst_path)
    result = build_asset_graph(dbx, cfg).run(context)
    facts = result.output_facts
    LOG.info("DONE %s -> %s (%sx%s, transparency=%s)", entry.name, dst_path, facts.width_px if facts else "?", facts.height_px if facts else "?", facts.transparent if facts else "?")
    return True


def run_once(limit: Optional[int] = None, only_file: Optional[str] = None) -> int:
    cfg = load_config()
    dbx = make_dropbox_client()
    for folder, enabled in (
        (cfg.approved_folder, True),
        (cfg.upscaled_folder, True),
        (cfg.listing_images_folder, cfg.generate_listing_images),
        (cfg.needs_review_folder, cfg.copy_failures_to_review),
    ):
        if enabled:
            ensure_dropbox_folder(dbx, folder)

    summary = RunSummary()
    for entry in list_pngs(dbx, cfg.approved_folder):
        if only_file and entry.name != only_file:
            continue
        summary.matched_file = True
        if limit is not None and summary.attempted >= limit:
            break
        summary.attempted += 1
        try:
            if process_file(dbx, entry, cfg):
                summary.processed += 1
            else:
                summary.skipped += 1
        except Exception:
            summary.failures += 1
            LOG.exception("FAILED %s", entry.name)
            if cfg.copy_failures_to_review and entry.path_display:
                try:
                    copy_to_review(dbx, entry.path_display, cfg.needs_review_folder)
                except Exception:
                    LOG.exception("Could not copy %s to Needs-Review", entry.name)

    if only_file and not summary.matched_file:
        LOG.error("Requested source file was not found in %s: %s", cfg.approved_folder, only_file)
        return 1
    LOG.info("Run complete. attempted=%s processed=%s skipped=%s failures=%s", summary.attempted, summary.processed, summary.skipped, summary.failures)
    return 1 if summary.failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upscale approved Etsy PNGs from Dropbox")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--file", dest="only_file", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        return run_once(limit=args.limit, only_file=args.only_file)
    except KeyboardInterrupt:
        return 130
    except Exception:
        LOG.exception("Fatal pipeline error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
