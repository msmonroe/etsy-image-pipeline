import pytest
from etsy_drafts import EtsyDraftClient


class Response:
    def raise_for_status(self): pass
    def json(self): return {"listing_id": 123}


class Session:
    def __init__(self): self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()


def client():
    session = Session()
    return EtsyDraftClient(7, "key", "token", session), session


def test_draft_only_with_uploads():
    api, session = client()
    listing_id = api.create_draft(
        {"title": "Greeble", "description": "Digital art", "price": 3,
         "quantity": 999, "taxonomy_id": 1, "who_made": "i_did",
         "when_made": "2020_2026"},
        [("preview.jpg", b"jpeg")], [("greeble.zip", b"zip")])
    assert listing_id == 123
    assert len(session.calls) == 3
    assert session.calls[0][1]["data"]["state"] == "draft"
    assert session.calls[0][1]["data"]["type"] == "download"
    assert session.calls[1][1]["data"]["rank"] == 1
    assert session.calls[2][0].endswith("/files")
    assert all("active" not in str(call) for call in session.calls)


def test_activation_rejected_before_network():
    api, session = client()
    with pytest.raises(ValueError, match="draft"):
        api.create_draft({"title": "x", "description": "y", "state": "active"},
                         [("a.jpg", b"x")], [("a.zip", b"x")])
    assert session.calls == []


def test_preflight_rejects_missing_downloads():
    api, session = client()
    with pytest.raises(ValueError):
        api.create_draft({"title": "x", "description": "y"},
                         [("a.jpg", b"x")], [])
    assert session.calls == []
