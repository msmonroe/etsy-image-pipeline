from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image
import io

import pipeline


def make_config(**overrides):
    values = dict(
        approved_folder="/Etsy/Approved",
        upscaled_folder="/Etsy/Upscaled",
        needs_review_folder="/Etsy/Needs-Review",
        listing_images_folder="/Etsy/Listing-Images",
        generate_listing_images=False,
        listing_image_width=2400,
        listing_image_height=2000,
        listing_image_jpeg_quality=90,
        upscale_factor=4,
        face_enhance=False,
        min_output_width=1,
        min_output_height=1,
        dimension_tolerance_px=0,
        request_timeout=300,
        poll_interval=0,
        max_poll_seconds=900,
        copy_failures_to_review=False,
        overwrite_output=True,
        replicate_api_token="test-token",
        replicate_model="nightmareai/real-esrgan",
        replicate_model_version="",
        replicate_fallback_on_oom=True,
        replicate_fallback_model="xinntao/realesrgan",
        replicate_fallback_tile=400,
        replicate_fallback_version_name="General - v3",
    )
    values.update(overrides)
    return pipeline.Config(**values)


def test_load_config_allows_blank_model_version(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("REPLICATE_MODEL", "nightmareai/real-esrgan")
    monkeypatch.setenv("REPLICATE_MODEL_VERSION", "")
    cfg = pipeline.load_config()
    assert cfg.replicate_model == "nightmareai/real-esrgan"
    assert cfg.replicate_model_version == ""


def test_load_config_rejects_bad_model_name(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("REPLICATE_MODEL", "not-a-model")
    with pytest.raises(RuntimeError, match="owner/model"):
        pipeline.load_config()


def test_replicate_model_url():
    assert pipeline.replicate_model_url("nightmareai/real-esrgan") == (
        "https://api.replicate.com/v1/models/nightmareai/real-esrgan/predictions"
    )


@pytest.mark.parametrize(
    "message,expected",
    [
        ("CUDA out of memory", True),
        ("out of GPU memory", True),
        ("out-of-gpu-memory", True),
        ("HTTP 500", False),
    ],
)
def test_is_cuda_oom(message, expected):
    assert pipeline.is_cuda_oom(RuntimeError(message)) is expected


def test_restore_alpha_preserves_transparency_and_writes_300_dpi(png_bytes):
    source = png_bytes((4, 4), transparent=True)
    upscaled = png_bytes((16, 16), transparent=False)

    result = pipeline.restore_alpha(source, upscaled)

    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (16, 16)
        assert image.getchannel("A").getextrema()[0] < 255
        dpi = image.info.get("dpi")
        assert dpi is not None
        assert dpi[0] == pytest.approx(300, abs=1)


def test_validate_output_accepts_exact_4x_dimensions(png_bytes):
    source = png_bytes((10, 12), transparent=False)
    output = png_bytes((40, 48), transparent=False)
    cfg = make_config(upscale_factor=4)

    assert pipeline.validate_output(source, output, cfg) == (40, 48, False)


def test_validate_output_rejects_wrong_dimensions(png_bytes):
    source = png_bytes((10, 10), transparent=False)
    output = png_bytes((39, 40), transparent=False)
    cfg = make_config(upscale_factor=4, dimension_tolerance_px=0)

    with pytest.raises(ValueError, match="Unexpected output dimensions"):
        pipeline.validate_output(source, output, cfg)


def test_validate_output_rejects_lost_alpha(png_bytes):
    source = png_bytes((10, 10), transparent=True)
    output = png_bytes((40, 40), transparent=False)
    cfg = make_config(upscale_factor=4)

    with pytest.raises(ValueError, match="alpha was lost"):
        pipeline.validate_output(source, output, cfg)


def test_run_once_file_filter_processes_only_requested(monkeypatch):
    cfg = make_config()
    entries = [
        SimpleNamespace(name="other.png", path_display="/Etsy/Approved/other.png"),
        SimpleNamespace(name="gamer_corgi.png", path_display="/Etsy/Approved/gamer_corgi.png"),
    ]
    processed = []

    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(pipeline, "make_dropbox_client", lambda: object())
    monkeypatch.setattr(pipeline, "ensure_dropbox_folder", lambda *args: None)
    monkeypatch.setattr(pipeline, "list_pngs", lambda *args: iter(entries))
    monkeypatch.setattr(
        pipeline,
        "process_file",
        lambda dbx, entry, config: processed.append(entry.name) or True,
    )

    assert pipeline.run_once(only_file="gamer_corgi.png") == 0
    assert processed == ["gamer_corgi.png"]


def test_run_once_missing_requested_file_fails(monkeypatch):
    cfg = make_config()
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(pipeline, "make_dropbox_client", lambda: object())
    monkeypatch.setattr(pipeline, "ensure_dropbox_folder", lambda *args: None)
    monkeypatch.setattr(pipeline, "list_pngs", lambda *args: iter([]))

    assert pipeline.run_once(only_file="missing.png") == 1


def test_oom_uses_tiled_fallback(monkeypatch, png_bytes):
    cfg = make_config()
    calls = []

    def fake_prediction(model, input_payload, config, version_id=""):
        calls.append((model, input_payload, version_id))
        if len(calls) == 1:
            raise RuntimeError("CUDA out of memory")
        return b"fallback-result"

    monkeypatch.setattr(pipeline, "run_replicate_prediction", fake_prediction)

    result = pipeline.run_replicate_upscale(png_bytes(), cfg)

    assert result == b"fallback-result"
    assert calls[0][0] == "nightmareai/real-esrgan"
    assert calls[1][0] == "xinntao/realesrgan"
    assert calls[1][1]["tile"] == 400
    assert calls[1][1]["version"] == "General - v3"


def test_build_default_etsy_metadata_uses_actual_output_properties(png_bytes):
    final_png = pipeline.restore_alpha(
        png_bytes((10, 10), transparent=False),
        png_bytes((40, 40), transparent=False),
    )

    metadata = pipeline.build_default_etsy_metadata(
        "/Etsy/Approved/samurai_cat_ramen_v2.png",
        "/Etsy/Upscaled/samurai_cat_ramen_v2.png",
        final_png,
    )

    assert metadata["image"]["width_px"] == 40
    assert metadata["image"]["height_px"] == 40
    assert metadata["image"]["dpi"] == 300
    assert metadata["image"]["transparent"] is False
    assert metadata["image"]["format"] == "PNG"
    assert metadata["ip_review"]["status"] == "pending"
    assert metadata["etsy"]["title"] == ""
    assert metadata["etsy"]["tags"] == []
    assert metadata["digital_files"][0]["dropbox_path"] == (
        "/Etsy/Upscaled/samurai_cat_ramen_v2.png"
    )


def test_ensure_etsy_sidecar_creates_missing_sidecar(monkeypatch, png_bytes):
    uploads = []
    monkeypatch.setattr(pipeline, "dropbox_file_exists", lambda *args: False)
    monkeypatch.setattr(
        pipeline,
        "upload_dropbox_file",
        lambda dbx, path, data, overwrite: uploads.append((path, data, overwrite)),
    )

    path = pipeline.ensure_etsy_sidecar(
        object(),
        "/Etsy/Approved/samurai_cat_ramen_v2.png",
        "/Etsy/Upscaled/samurai_cat_ramen_v2.png",
        png_bytes((40, 40), transparent=False),
    )

    assert path == "/Etsy/Approved/samurai_cat_ramen_v2.etsy.json"
    assert len(uploads) == 1
    assert uploads[0][0] == path
    assert uploads[0][2] is False
    metadata = __import__("json").loads(uploads[0][1])
    assert metadata["image"]["width_px"] == 40
    assert metadata["image"]["height_px"] == 40
    assert metadata["image"]["transparent"] is False


def test_ensure_etsy_sidecar_preserves_existing_sidecar(monkeypatch, png_bytes):
    uploads = []
    monkeypatch.setattr(pipeline, "dropbox_file_exists", lambda *args: True)
    monkeypatch.setattr(
        pipeline,
        "upload_dropbox_file",
        lambda *args, **kwargs: uploads.append((args, kwargs)),
    )

    path = pipeline.ensure_etsy_sidecar(
        object(),
        "/Etsy/Approved/existing.png",
        "/Etsy/Upscaled/existing.png",
        png_bytes((40, 40), transparent=False),
    )

    assert path == "/Etsy/Approved/existing.etsy.json"
    assert uploads == []
