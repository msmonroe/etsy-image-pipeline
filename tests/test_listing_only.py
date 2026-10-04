from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

import pipeline
from listing_copy import GREEBLE_NAME, listing_text, metadata_for


def test_greeble_copy_and_unknown_sidecar():
    metadata = metadata_for(GREEBLE_NAME, None)
    result = listing_text(metadata).decode("utf-8")
    assert "TITLE\n" + metadata["title"] in result
    assert "DESCRIPTION\n" + metadata["description"] in result
    with pytest.raises(ValueError, match="Missing Etsy metadata"):
        metadata_for("unknown.png", None)


def test_supplied_sidecar_takes_precedence():
    custom = {"title": "Custom title", "description": "Custom description",
              "digital_files": [{"filename": GREEBLE_NAME}]}
    assert metadata_for(GREEBLE_NAME, custom)["title"] == "Custom title"


def test_listing_only_does_not_upscale_or_require_replicate(monkeypatch, png_bytes):
    from test_pipeline import make_config
    cfg = make_config(generate_listing_images=False)
    source = png_bytes((120, 120), transparent=True)
    entry = SimpleNamespace(name=GREEBLE_NAME,
                            path_display="/Etsy/Approved/" + GREEBLE_NAME)
    uploads = {}
    monkeypatch.setattr(pipeline, "load_config", lambda require_replicate=True:
                        cfg if not require_replicate else
                        (_ for _ in ()).throw(AssertionError("Replicate required")))
    monkeypatch.setattr(pipeline, "make_dropbox_client", lambda: object())
    monkeypatch.setattr(pipeline, "ensure_dropbox_folder", lambda *args: None)
    monkeypatch.setattr(pipeline, "list_pngs", lambda *args: iter([entry]))
    monkeypatch.setattr(pipeline, "download_dropbox_file", lambda *args: source)
    monkeypatch.setattr(pipeline, "dropbox_file_exists", lambda dbx, path: False)
    monkeypatch.setattr(pipeline, "upload_dropbox_file",
                        lambda dbx, path, data, overwrite: uploads.__setitem__(path, data))
    monkeypatch.setattr(pipeline, "run_replicate_upscale",
                        lambda *args: (_ for _ in ()).throw(AssertionError("Upscaler called")))
    assert pipeline.run_once(only_file=GREEBLE_NAME, listing_images_only=True) == 0
    assert len([path for path in uploads if path.endswith(".jpg")]) == 7
    assert any(path.endswith("05_journal_mockup.jpg") for path in uploads)
    assert any(path.endswith("06_card_mockup.jpg") for path in uploads)
    assert any(path.endswith("07_uses_collage.jpg") for path in uploads)
    assert any(path.endswith("_etsy_listing.txt") for path in uploads)
    assert "/Etsy/Approved/greeble_mushroom_forager_3600.etsy.json" in uploads
    assert not any(path.startswith("/Etsy/Upscaled/") for path in uploads)
    assert b"TITLE" in next(data for path, data in uploads.items()
                            if path.endswith("_etsy_listing.txt"))
