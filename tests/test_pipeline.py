from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

import pipeline
from pipeline_graph import PipelineGraph, PipelineStep
from pipeline_models import AssetContext, EtsyMetadata, PipelineConfig, RunSummary


def make_config(**overrides):
    values = dict(
        generate_listing_images=False,
        upscale_factor=4,
        dimension_tolerance_px=0,
        poll_interval=0,
        copy_failures_to_review=False,
        overwrite_output=True,
        replicate_api_token="test-token",
    )
    values.update(overrides)
    return PipelineConfig(**values)


def test_config_is_type_driven_and_rejects_invalid_factor():
    with pytest.raises(ValidationError):
        make_config(upscale_factor=1)


def test_load_config_allows_blank_model_version(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("REPLICATE_MODEL", "nightmareai/real-esrgan")
    monkeypatch.setenv("REPLICATE_MODEL_VERSION", "")
    cfg = pipeline.load_config()
    assert cfg.replicate_model_version == ""


def test_load_config_rejects_bad_model_name(monkeypatch):
    monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")
    monkeypatch.setenv("REPLICATE_MODEL", "not-a-model")
    with pytest.raises(RuntimeError, match="owner/model"):
        pipeline.load_config()


def test_replicate_model_url():
    assert pipeline.replicate_model_url("nightmareai/real-esrgan").endswith(
        "/models/nightmareai/real-esrgan/predictions"
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
    result = pipeline.restore_alpha(
        png_bytes((4, 4), transparent=True),
        png_bytes((16, 16), transparent=False),
    )
    with Image.open(io.BytesIO(result)) as image:
        assert image.size == (16, 16)
        assert image.getchannel("A").getextrema()[0] < 255
        assert image.info["dpi"][0] == pytest.approx(300, abs=1)


def test_validate_output_accepts_exact_4x_dimensions(png_bytes):
    assert pipeline.validate_output(
        png_bytes((10, 12)), png_bytes((40, 48)), make_config()
    ) == (40, 48, False)


def test_validate_output_accepts_vertical_below_old_square_minimum(png_bytes):
    assert pipeline.validate_output(
        png_bytes((1122, 1402)), png_bytes((4488, 5608)), make_config()
    ) == (4488, 5608, False)


def test_validate_output_rejects_wrong_dimensions(png_bytes):
    with pytest.raises(ValueError, match="Unexpected output dimensions"):
        pipeline.validate_output(
            png_bytes((10, 10)), png_bytes((39, 40)), make_config()
        )


def test_validate_output_rejects_lost_alpha(png_bytes):
    with pytest.raises(ValueError, match="alpha was lost"):
        pipeline.validate_output(
            png_bytes((10, 10), transparent=True),
            png_bytes((40, 40), transparent=False),
            make_config(),
        )


def test_oom_uses_tiled_fallback(monkeypatch, png_bytes):
    calls = []

    def fake_prediction(model, input_payload, config, version_id=""):
        calls.append((model, input_payload, version_id))
        if len(calls) == 1:
            raise RuntimeError("CUDA out of memory")
        return b"fallback-result"

    monkeypatch.setattr(pipeline, "run_replicate_prediction", fake_prediction)
    assert pipeline.run_replicate_upscale(png_bytes(), make_config()) == b"fallback-result"
    assert calls[1][0] == "xinntao/realesrgan"
    assert calls[1][1]["tile"] == 400


def test_metadata_model_uses_actual_output_properties(png_bytes):
    final_png = pipeline.restore_alpha(png_bytes((10, 10)), png_bytes((40, 40)))
    metadata = EtsyMetadata.for_processed_asset(
        "/Etsy/Approved/cat.png", "/Etsy/Upscaled/cat.png", final_png
    )
    assert metadata.image.width_px == 40
    assert metadata.image.height_px == 40
    assert metadata.image.dpi == 300
    assert metadata.ip_review.status == "pending"
    assert metadata.digital_files[0].dropbox_path == "/Etsy/Upscaled/cat.png"


def test_build_default_metadata_keeps_dict_compatibility(png_bytes):
    metadata = pipeline.build_default_etsy_metadata(
        "/Etsy/Approved/cat.png", "/Etsy/Upscaled/cat.png", png_bytes((40, 40))
    )
    assert metadata["image"]["width_px"] == 40
    assert metadata["etsy"]["tags"] == []


def test_ensure_sidecar_creates_typed_metadata(monkeypatch, png_bytes):
    uploads = []
    monkeypatch.setattr(pipeline, "dropbox_file_exists", lambda *args: False)
    monkeypatch.setattr(
        pipeline,
        "upload_dropbox_file",
        lambda dbx, path, data, overwrite: uploads.append((path, data, overwrite)),
    )
    path = pipeline.ensure_etsy_sidecar(
        object(), "/Etsy/Approved/cat.png", "/Etsy/Upscaled/cat.png", png_bytes((40, 40))
    )
    assert path.endswith("cat.etsy.json")
    parsed = EtsyMetadata.model_validate_json(uploads[0][1])
    assert parsed.image.width_px == 40
    assert parsed.ip_review.status == "pending"


def test_ensure_sidecar_validates_existing_metadata(monkeypatch, png_bytes):
    monkeypatch.setattr(pipeline, "dropbox_file_exists", lambda *args: True)
    monkeypatch.setattr(
        pipeline, "download_dropbox_file", lambda *args: b'{"invalid": true}'
    )
    with pytest.raises(ValidationError):
        pipeline.ensure_etsy_sidecar(
            object(), "/Etsy/Approved/cat.png", "/Etsy/Upscaled/cat.png", png_bytes()
        )


def test_declarative_graph_has_stable_order():
    cfg = make_config()
    graph = pipeline.build_asset_graph(object(), cfg)
    assert graph.step_names == (
        "download",
        "upscale",
        "normalize_png",
        "validate",
        "upload_master",
        "ensure_metadata",
        "listing_assets",
    )


def test_graph_executes_declaratively():
    seen = []
    graph = PipelineGraph((
        PipelineStep("a", lambda x: seen.append("a") or x),
        PipelineStep("b", lambda x: seen.append("b") or x),
    ))
    assert graph.run("context") == "context"
    assert seen == ["a", "b"]


def test_asset_context_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        AssetContext(
            source_name="cat.png",
            source_path="/a/cat.png",
            destination_path="/b/cat.png",
            surprise=True,
        )


def test_run_summary_enforces_counter_invariant():
    with pytest.raises(ValidationError):
        RunSummary(attempted=1, processed=2)


def test_run_once_file_filter_processes_only_requested(monkeypatch):
    cfg = make_config()
    entries = [
        SimpleNamespace(name="other.png", path_display="/Etsy/Approved/other.png"),
        SimpleNamespace(name="cat.png", path_display="/Etsy/Approved/cat.png"),
    ]
    processed = []
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(pipeline, "make_dropbox_client", lambda: object())
    monkeypatch.setattr(pipeline, "ensure_dropbox_folder", lambda *args: None)
    monkeypatch.setattr(pipeline, "list_pngs", lambda *args: iter(entries))
    monkeypatch.setattr(
        pipeline, "process_file", lambda dbx, entry, config: processed.append(entry.name) or True
    )
    assert pipeline.run_once(only_file="cat.png") == 0
    assert processed == ["cat.png"]


def test_run_once_missing_requested_file_fails(monkeypatch):
    cfg = make_config()
    monkeypatch.setattr(pipeline, "load_config", lambda: cfg)
    monkeypatch.setattr(pipeline, "make_dropbox_client", lambda: object())
    monkeypatch.setattr(pipeline, "ensure_dropbox_folder", lambda *args: None)
    monkeypatch.setattr(pipeline, "list_pngs", lambda *args: iter([]))
    assert pipeline.run_once(only_file="missing.png") == 1
