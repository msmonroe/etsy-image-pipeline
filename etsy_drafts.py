"""Draft-only Etsy API client. Intentionally contains no publishing operation."""
from __future__ import annotations

import os
import requests
from production_workflow import validate_downloads

BASE = "https://openapi.etsy.com/v3/application"


class EtsyDraftClient:
    def __init__(self, shop_id: int, api_key: str, access_token: str,
                 session=None):
        if not (shop_id and api_key and access_token):
            raise ValueError("Shop ID, API key and OAuth token are required")
        self.shop_id = shop_id
        self.session = session or requests.Session()
        self.headers = {"x-api-key": api_key, "Authorization": f"Bearer {access_token}"}

    def _post(self, endpoint: str, *, data=None, files=None):
        response = self.session.post(f"{BASE}{endpoint}", headers=self.headers,
                                     data=data, files=files, timeout=60)
        response.raise_for_status()
        return response.json()

    def create_draft(self, metadata: dict, images: list[tuple[str, bytes]],
                     downloads: list[tuple[str, bytes]]) -> int:
        """Preflight first; create draft, attach previews and digital downloads."""
        validate_downloads(downloads)
        if not images:
            raise ValueError("At least one listing preview is required")
        if not metadata.get("title") or not metadata.get("description"):
            raise ValueError("Title and description are required")
        # Deliberately reject activation even if metadata is externally generated.
        if metadata.get("state") not in (None, "draft"):
            raise ValueError("Only draft listings are permitted")
        allowed = ("title", "description", "price", "quantity", "taxonomy_id",
                   "who_made", "when_made")
        payload = {key: metadata[key] for key in allowed if key in metadata}
        payload["type"] = "download"
        payload["state"] = "draft"
        result = self._post(f"/shops/{self.shop_id}/listings", data=payload)
        listing_id = result["listing_id"]
        for rank, (filename, content) in enumerate(images, 1):
            self._post(f"/shops/{self.shop_id}/listings/{listing_id}/images",
                       data={"rank": rank},
                       files={"image": (filename, content, "image/jpeg")})
        for filename, content in downloads:
            self._post(f"/shops/{self.shop_id}/listings/{listing_id}/files",
                       files={"file": (filename, content, "application/octet-stream")})
        return listing_id


def client_from_env(session=None):
    return EtsyDraftClient(int(os.environ["ETSY_SHOP_ID"]),
                           os.environ["ETSY_API_KEY"],
                           os.environ["ETSY_ACCESS_TOKEN"], session=session)
