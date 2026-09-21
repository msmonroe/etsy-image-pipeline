#!/usr/bin/env python3
"""Vector production branch for Etsy line-art assets.

Requires system packages:
  sudo apt install potrace ghostscript

Optional for PDF/EPS export:
  sudo apt install inkscape
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional

import dropbox
from dotenv import load_dotenv
from PIL import Image, ImageChops, ImageOps, ImageStat

load_dotenv()
LOG = logging.getLogger("etsy-vector-pipeline")


@dataclass(frozen=True)
class Config:
    approved_folder: str
    vectorized_folder: str
    needs_review_folder: str
    png_size: int
    png_dpi: int
    threshold: int
    max_difference: float
    overwrite_output: bool
    copy_failures_to_review: bool


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    return Config(
        approved_folder=os.getenv("DROPBOX_VECTOR_APPROVED_FOLDER", "/Etsy/Approved/Vector"),
        vectorized_folder=os.getenv("DROPBOX_VECTORIZED_FOLDER", "/Etsy/Vectorized"),
        needs_review_folder=os.getenv("DROPBOX_NEEDS_REVIEW_FOLDER", "/Etsy/Needs-Review"),
        png_size=int(os.getenv("VECTOR_PNG_SIZE", "4500")),
        png_dpi=int(os.getenv("VECTOR_PNG_DPI", "300")),
        threshold=int(os.getenv("VECTOR_THRESHOLD", "180")),
        max_difference=float(os.getenv("VECTOR_MAX_DIFFERENCE", "0.08")),
        overwrite_output=env_bool("OVERWRITE_OUTPUT", False),
        copy_failures_to_review=env_bool("COPY_FAILURES_TO_REVIEW", True),
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


def ensure_folder(dbx: dropbox.Dropbox, path: str) -> None:
    try:
        dbx.files_get_metadata(path)
    except dropbox.exceptions.ApiError:
        dbx.files_create_folder_v2(path)


def exists(dbx: dropbox.Dropbox, path: str) -> bool:
    try:
        dbx.files_get_metadata(path)
        return True
    except dropbox.exceptions.ApiError:
        return False


def list_pngs(dbx: dropbox.Dropbox, folder: str):
    result = dbx.files_list_folder(folder)
    while True:
        for entry in result.entries:
            if isinstance(entry, dropbox.files.FileMetadata) and entry.name.lower().endswith(".png"):
                yield entry
        if not result.has_more:
            break
        result = dbx.files_list_folder_continue(result.cursor)


def download(dbx: dropbox.Dropbox, path: str) -> bytes:
    _, response = dbx.files_download(path)
    return response.content


def upload(dbx: dropbox.Dropbox, path: str, data: bytes, overwrite: bool) -> None:
    mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
    dbx.files_upload(data, path, mode=mode, mute=True)


def copy_to_review(dbx: dropbox.Dropbox, src: str, folder: str) -> None:
    dst = f"{folder.rstrip('/')}/{PurePosixPath(src).name}"
    if not exists(dbx, dst):
        dbx.files_copy_v2(src, dst)


def prepare_bitmap(source: bytes, threshold: int, path: Path) -> Image.Image:
    with Image.open(io.BytesIO(source)) as img:
        rgba = img.convert("RGBA")
        # Composite transparency onto white, then force pure 1-bit line art.
        white = Image.new("RGBA", rgba.size, "white")
        gray = ImageOps.grayscale(Image.alpha_composite(white, rgba))
        bw = gray.point(lambda p: 0 if p < threshold else 255, mode="1")
        bw.save(path, format="BMP")
        return bw.convert("L")


def trace_svg(bitmap: Path, svg: Path) -> None:
    if not shutil.which("potrace"):
        raise RuntimeError("potrace is required: sudo apt install potrace")
    subprocess.run(
        ["potrace", str(bitmap), "-s", "-o", str(svg), "--opttolerance", "0.2"],
        check=True, capture_output=True, text=True,
    )


def validate_svg(svg: Path) -> tuple[int, int]:
    root = ET.parse(svg).getroot()
    images = root.findall(".//{http://www.w3.org/2000/svg}image")
    paths = root.findall(".//{http://www.w3.org/2000/svg}path")
    if images:
        raise ValueError("SVG contains embedded raster <image> elements")
    if not paths:
        raise ValueError("SVG contains no vector <path> elements")
    commands = sum((p.get("d") or "").count(" ") for p in paths)
    return len(paths), commands


def render_svg(svg: Path, png: Path, size: int, dpi: int) -> None:
    if not shutil.which("inkscape"):
        raise RuntimeError("inkscape is required for SVG rendering/export")
    subprocess.run(
        ["inkscape", str(svg), "--export-type=png", f"--export-filename={png}",
         f"--export-width={size}", f"--export-height={size}", f"--export-dpi={dpi}"],
        check=True, capture_output=True, text=True,
    )


def visual_difference(source_l: Image.Image, rendered_path: Path) -> float:
    with Image.open(rendered_path) as rendered:
        r = ImageOps.grayscale(rendered.convert("RGBA"))
        s = source_l.resize(r.size, Image.Resampling.LANCZOS)
        diff = ImageChops.difference(s, r)
        return ImageStat.Stat(diff).mean[0] / 255.0


def export_vector(svg: Path, out: Path, kind: str) -> None:
    subprocess.run(
        ["inkscape", str(svg), f"--export-type={kind}", f"--export-filename={out}"],
        check=True, capture_output=True, text=True,
    )


def process_file(dbx: dropbox.Dropbox, entry: dropbox.files.FileMetadata, cfg: Config) -> bool:
    src = entry.path_display or entry.path_lower
    if not src:
        raise RuntimeError("Dropbox entry has no path")
    stem = Path(entry.name).stem
    base = cfg.vectorized_folder.rstrip("/")
    svg_dst = f"{base}/SVG/{stem}.svg"
    if not cfg.overwrite_output and exists(dbx, svg_dst):
        LOG.info("SKIP %s, vector output exists", entry.name)
        return False

    source = download(dbx, src)
    with tempfile.TemporaryDirectory(prefix="etsy-vector-") as td:
        td = Path(td)
        bmp, svg, png = td/"source.bmp", td/f"{stem}.svg", td/f"{stem}.png"
        source_l = prepare_bitmap(source, cfg.threshold, bmp)
        trace_svg(bmp, svg)
        path_count, command_count = validate_svg(svg)
        render_svg(svg, png, cfg.png_size, cfg.png_dpi)
        difference = visual_difference(source_l, png)
        LOG.info("%s paths=%s commands~=%s visual_difference=%.4f", stem, path_count, command_count, difference)
        if difference > cfg.max_difference:
            raise ValueError(
                f"Vector render differs too much from source: {difference:.4f} > {cfg.max_difference:.4f}"
            )

        pdf, eps = td/f"{stem}.pdf", td/f"{stem}.eps"
        export_vector(svg, pdf, "pdf")
        export_vector(svg, eps, "eps")

        outputs = {
            f"{base}/SVG/{stem}.svg": svg.read_bytes(),
            f"{base}/PNG/{stem}.png": png.read_bytes(),
            f"{base}/PDF/{stem}.pdf": pdf.read_bytes(),
            f"{base}/EPS/{stem}.eps": eps.read_bytes(),
        }
        for path, data in outputs.items():
            upload(dbx, path, data, cfg.overwrite_output)
        LOG.info("DONE %s -> SVG/PNG/PDF/EPS", entry.name)
        return True


def run_once(limit: Optional[int] = None) -> int:
    cfg = load_config()
    dbx = make_dropbox_client()
    ensure_folder(dbx, cfg.approved_folder)
    ensure_folder(dbx, cfg.needs_review_folder)
    for sub in ("SVG", "PNG", "PDF", "EPS"):
        ensure_folder(dbx, f"{cfg.vectorized_folder.rstrip('/')}/{sub}")

    processed = failures = 0
    for entry in list_pngs(dbx, cfg.approved_folder):
        if limit is not None and processed >= limit:
            break
        try:
            if process_file(dbx, entry, cfg):
                processed += 1
        except Exception:
            failures += 1
            LOG.exception("FAILED %s", entry.name)
            if cfg.copy_failures_to_review and entry.path_display:
                try:
                    copy_to_review(dbx, entry.path_display, cfg.needs_review_folder)
                except Exception:
                    LOG.exception("Could not copy to Needs-Review")
    LOG.info("Vector run complete. processed=%s failures=%s", processed, failures)
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Create genuine vector Etsy assets from approved line-art PNGs")
    p.add_argument("--once", action="store_true")
    p.add_argument("--limit", type=int)
    args = p.parse_args()
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run_once(args.limit)
    except Exception:
        LOG.exception("Fatal vector pipeline error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
