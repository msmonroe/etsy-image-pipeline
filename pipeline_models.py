from __future__ import annotations

import io
import os
from pathlib import PurePosixPath
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class PipelineConfig(StrictModel):
    approved_folder: str = "/Etsy/Approved"
    upscaled_folder: str = "/Etsy/Upscaled"
    needs_review_folder: str = "/Etsy/Needs-Review"
    listing_images_folder: str = "/Etsy/Listing-Images"
    generate_listing_images: bool = True
    listing_image_width: int = Field(default=2400, gt=0)
    listing_image_height: int = Field(default=2000, gt=0)
    listing_image_jpeg_quality: int = Field(default=90, ge=1, le=100)
    upscale_factor: int = Field(default=3, ge=2, le=8)
    face_enhance: bool = False
    dimension_tolerance_px: int = Field(default=8, ge=0)
    request_timeout: int = Field(default=300, gt=0)
    poll_interval: int = Field(default=2, ge=0)
    max_poll_seconds: int = Field(default=900, gt=0)
    copy_failures_to_review: bool = True
    overwrite_output: bool = False
    replicate_api_token: str = Field(min_length=1)
    replicate_model: str = "nightmareai/real-esrgan"
    replicate_model_version: str = ""
    replicate_fallback_on_oom: bool = True
    replicate_fallback_model: str = "xinntao/realesrgan"
    replicate_fallback_tile: int = Field(default=400, gt=0)
    replicate_fallback_version_name: str = "General - v3"

    @field_validator("replicate_model", "replicate_fallback_model")
    @classmethod
    def valid_model_name(cls, value: str) -> str:
        value = value.strip()
        if "/" not in value:
            raise ValueError("Replicate model must look like owner/model")
        return value

    @classmethod
    def from_env(cls) -> "PipelineConfig":
        def b(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            approved_folder=os.getenv("DROPBOX_APPROVED_FOLDER", "/Etsy/Approved"),
            upscaled_folder=os.getenv("DROPBOX_UPSCALED_FOLDER", "/Etsy/Upscaled"),
            needs_review_folder=os.getenv("DROPBOX_NEEDS_REVIEW_FOLDER", "/Etsy/Needs-Review"),
            listing_images_folder=os.getenv("DROPBOX_LISTING_IMAGES_FOLDER", "/Etsy/Listing-Images"),
            generate_listing_images=b("GENERATE_LISTING_IMAGES", True),
            listing_image_width=os.getenv("ETSY_LISTING_IMAGE_WIDTH", "2400"),
            listing_image_height=os.getenv("ETSY_LISTING_IMAGE_HEIGHT", "2000"),
            listing_image_jpeg_quality=os.getenv("ETSY_LISTING_IMAGE_JPEG_QUALITY", "90"),
            upscale_factor=os.getenv("UPSCALE_FACTOR", "3"),
            face_enhance=b("FACE_ENHANCE", False),
            dimension_tolerance_px=os.getenv("DIMENSION_TOLERANCE_PX", "8"),
            request_timeout=os.getenv("REQUEST_TIMEOUT_SECONDS", "300"),
            poll_interval=os.getenv("POLL_INTERVAL_SECONDS", "2"),
            max_poll_seconds=os.getenv("MAX_POLL_SECONDS", "900"),
            copy_failures_to_review=b("COPY_FAILURES_TO_REVIEW", True),
            overwrite_output=b("OVERWRITE_OUTPUT", False),
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN", "").strip(),
            replicate_model=os.getenv("REPLICATE_MODEL", "nightmareai/real-esrgan"),
            replicate_model_version=os.getenv("REPLICATE_MODEL_VERSION", "").strip(),
            replicate_fallback_on_oom=b("REPLICATE_FALLBACK_ON_OOM", True),
            replicate_fallback_model=os.getenv("REPLICATE_FALLBACK_MODEL", "xinntao/realesrgan"),
            replicate_fallback_tile=os.getenv("REPLICATE_FALLBACK_TILE", "400"),
            replicate_fallback_version_name=os.getenv("REPLICATE_FALLBACK_VERSION_NAME", "General - v3"),
        )


class ImageFacts(StrictModel):
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    dpi: int = Field(default=300, gt=0)
    transparent: bool
    format: Literal["PNG"] = "PNG"

    @classmethod
    def from_png(cls, payload: bytes) -> "ImageFacts":
        with Image.open(io.BytesIO(payload)) as image:
            rgba = image.convert("RGBA")
            dpi = image.info.get("dpi") or (300, 300)
            return cls(
                width_px=image.width,
                height_px=image.height,
                dpi=int(round(dpi[0])),
                transparent=rgba.getchannel("A").getextrema()[0] < 255,
            )


class IPReview(StrictModel):
    status: Literal["pending", "approved", "rejected"] = "pending"
    original_art_only: bool = True
    notes: str = ""


class ListingImage(StrictModel):
    filename: str
    rank: int = Field(gt=0)
    alt_text: str


class DigitalFile(StrictModel):
    filename: str
    display_name: str
    dropbox_path: str


class EtsyFields(StrictModel):
    title: str = ""
    description: str = ""
    price: float | None = None
    quantity: int = Field(default=999, ge=0)
    who_made: str = "i_did"
    when_made: str = "2020_2026"
    taxonomy_id: int | None = None
    type: Literal["download"] = "download"
    tags: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    sku: str | None = None
    listing_id: int | None = None
    state: str = "metadata_only"


class EtsyMetadata(StrictModel):
    asset_key: str
    source_filename: str
    listing_key: str
    role: Literal["master"] = "master"
    ip_review: IPReview = Field(default_factory=IPReview)
    image: ImageFacts
    listing_images: list[ListingImage] = Field(default_factory=list)
    digital_files: list[DigitalFile]
    etsy: EtsyFields = Field(default_factory=EtsyFields)

    @classmethod
    def for_processed_asset(cls, src_path: str, dst_path: str, png: bytes) -> "EtsyMetadata":
        src = PurePosixPath(src_path)
        return cls(
            asset_key=src.stem,
            source_filename=src.name,
            listing_key=src.stem,
            image=ImageFacts.from_png(png),
            digital_files=[DigitalFile(filename=src.name, display_name=src.name, dropbox_path=dst_path)],
        )


class AssetContext(StrictModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, arbitrary_types_allowed=True)
    source_name: str
    source_path: str
    destination_path: str
    source_bytes: bytes | None = None
    upscaled_bytes: bytes | None = None
    final_png: bytes | None = None
    output_facts: ImageFacts | None = None
    sidecar_path: str | None = None
    listing_assets_generated: bool = False


class RunSummary(StrictModel):
    attempted: int = Field(default=0, ge=0)
    processed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    matched_file: bool = False

    @model_validator(mode="after")
    def totals_are_sane(self) -> "RunSummary":
        if self.processed + self.skipped + self.failures > self.attempted:
            raise ValueError("run counters exceed attempted files")
        return self
