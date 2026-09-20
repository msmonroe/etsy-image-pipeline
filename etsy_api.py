#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class EtsyConfig:
    mode: str
    api_keystring: str
    shared_secret: str
    access_token: str
    shop_id: str
    outbox_dir: Path


def load_etsy_config() -> EtsyConfig:
    mode = os.getenv("ETSY_MODE", "mock").strip().lower()
    if mode not in {"mock", "real"}:
        raise RuntimeError("ETSY_MODE must be 'mock' or 'real'")

    return EtsyConfig(
        mode=mode,
        api_keystring=os.getenv("ETSY_API_KEYSTRING", "").strip(),
        shared_secret=os.getenv("ETSY_SHARED_SECRET", "").strip(),
        access_token=os.getenv("ETSY_ACCESS_TOKEN", "").strip(),
        shop_id=os.getenv("ETSY_SHOP_ID", "").strip(),
        outbox_dir=Path(os.getenv("ETSY_OUTBOX_DIR", ".etsy_mock_outbox")).resolve(),
    )


class BaseEtsyClient:
    def create_draft_listing(self, metadata: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def upload_listing_image(self, listing_id: int, image_path: Path) -> dict[str, Any]:
        raise NotImplementedError

    def upload_listing_file(self, listing_id: int, file_path: Path) -> dict[str, Any]:
        raise NotImplementedError


class MockEtsyClient(BaseEtsyClient):
    def __init__(self, cfg: EtsyConfig):
        self.cfg = cfg
        self.cfg.outbox_dir.mkdir(parents=True, exist_ok=True)

    def _write_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        created_ms = int(time.time() * 1000)
        event_id = str(uuid.uuid4())
        path = self.cfg.outbox_dir / f"{created_ms}_{event_type}_{event_id}.json"

        document = {
            "mode": "mock",
            "event_type": event_type,
            "event_id": event_id,
            "created_at_unix_ms": created_ms,
            "payload": payload,
        }
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "mode": "mock",
            "event_type": event_type,
            "event_id": event_id,
            "outbox_file": str(path),
        }

    def create_draft_listing(self, metadata: dict[str, Any]) -> dict[str, Any]:
        fake_listing_id = int(time.time() * 1000)

        payload = {
            "listing_id": fake_listing_id,
            "state": "draft",
            "shop_id": self.cfg.shop_id or None,
            "asset_key": metadata.get("asset_key"),
            "listing_key": metadata.get("listing_key"),
            "etsy": metadata.get("etsy", {}),
        }
        result = self._write_event("create_draft_listing", payload)
        result.update({"listing_id": fake_listing_id, "state": "draft"})
        return result

    def upload_listing_image(self, listing_id: int, image_path: Path) -> dict[str, Any]:
        return self._write_event(
            "upload_listing_image",
            {
                "listing_id": listing_id,
                "filename": image_path.name,
                "path": str(image_path),
            },
        )

    def upload_listing_file(self, listing_id: int, file_path: Path) -> dict[str, Any]:
        return self._write_event(
            "upload_listing_file",
            {
                "listing_id": listing_id,
                "filename": file_path.name,
                "path": str(file_path),
            },
        )


class RealEtsyClient(BaseEtsyClient):
    BASE_URL = "https://api.etsy.com/v3/application"

    def __init__(self, cfg: EtsyConfig):
        self.cfg = cfg
        missing = [
            name
            for name, value in {
                "ETSY_API_KEYSTRING": cfg.api_keystring,
                "ETSY_SHARED_SECRET": cfg.shared_secret,
                "ETSY_ACCESS_TOKEN": cfg.access_token,
                "ETSY_SHOP_ID": cfg.shop_id,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing Etsy real-mode configuration: " + ", ".join(missing)
            )

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": f"{self.cfg.api_keystring}:{self.cfg.shared_secret}",
            "Authorization": f"Bearer {self.cfg.access_token}",
            "Accept": "application/json",
        }

    @staticmethod
    def _raise_with_body(response: requests.Response) -> None:
        if response.ok:
            return
        body = response.text[:2000]
        raise RuntimeError(
            f"Etsy API returned HTTP {response.status_code}: {body}"
        )

    def create_draft_listing(self, metadata: dict[str, Any]) -> dict[str, Any]:
        etsy = metadata["etsy"]
        payload: dict[str, Any] = {
            "quantity": etsy["quantity"],
            "title": etsy["title"],
            "description": etsy["description"],
            "price": etsy["price"],
            "who_made": etsy["who_made"],
            "when_made": etsy["when_made"],
            "taxonomy_id": etsy["taxonomy_id"],
            "type": "download",
        }

        for optional in ("tags", "materials"):
            if etsy.get(optional):
                payload[optional] = etsy[optional]

        response = requests.post(
            f"{self.BASE_URL}/shops/{self.cfg.shop_id}/listings",
            headers=self._headers(),
            data=payload,
            timeout=60,
        )
        self._raise_with_body(response)
        return response.json()

    def upload_listing_image(self, listing_id: int, image_path: Path) -> dict[str, Any]:
        with image_path.open("rb") as handle:
            response = requests.post(
                f"{self.BASE_URL}/shops/{self.cfg.shop_id}/listings/{listing_id}/images",
                headers=self._headers(),
                files={"image": (image_path.name, handle)},
                timeout=120,
            )
        self._raise_with_body(response)
        return response.json()

    def upload_listing_file(self, listing_id: int, file_path: Path) -> dict[str, Any]:
        with file_path.open("rb") as handle:
            response = requests.post(
                f"{self.BASE_URL}/shops/{self.cfg.shop_id}/listings/{listing_id}/files",
                headers=self._headers(),
                files={"file": (file_path.name, handle)},
                timeout=120,
            )
        self._raise_with_body(response)
        return response.json()


def load_etsy_client() -> BaseEtsyClient:
    cfg = load_etsy_config()
    if cfg.mode == "mock":
        return MockEtsyClient(cfg)
    return RealEtsyClient(cfg)
