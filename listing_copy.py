"""Manual Etsy listing copy and a curated fallback for Greeble #01."""
from __future__ import annotations

from pathlib import PurePosixPath

GREEBLE_NAME = "greeble_mushroom_forager_3600.png"

GREEBLE = {
    "listing_key": "greeble_mushroom_forager",
    "title": "Greeble Mushroom Forager PNG | Whimsical Goblin Clipart | Autumn Fantasy Art",
    "description": (
        "Meet Greeble, a cheerful little woodland goblin with a basket of mushrooms "
        "and a fondness for autumn adventures. This original, detailed fantasy "
        "illustration is supplied as a high-resolution transparent PNG, ideal for "
        "junk journals, scrapbooking, printable crafts, stickers, and personal "
        "creative projects.\n\n"
        "YOU WILL RECEIVE\n"
        "• 1 transparent PNG illustration\n"
        "• 3600 × 3600 pixels, 300 PPI metadata\n"
        "• Digital download only; no physical item will be shipped\n\n"
        "The listing preview backgrounds are for display only. The downloadable "
        "artwork has a transparent background. Please review the file dimensions "
        "and your intended print size before purchasing.\n\n"
        "This is original fantasy character artwork. The pictured mushroom is "
        "decorative illustration, not mushroom-identification or foraging advice."
    ),
    "digital_files": [{"filename": GREEBLE_NAME}],
}


def metadata_for(source_name: str, supplied: dict | None) -> dict:
    """Prefer the user's sidecar; only Greeble has an approved fallback."""
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError("Etsy sidecar must be a JSON object")
        metadata = dict(supplied)
    elif source_name == GREEBLE_NAME:
        metadata = {
            **GREEBLE,
            "digital_files": [dict(item) for item in GREEBLE["digital_files"]],
        }
    else:
        raise ValueError(
            "Missing Etsy metadata sidecar; create <image-stem>.etsy.json "
            "with title, description, and digital_files before listing-only mode"
        )
    if not str(metadata.get("title", "")).strip() or not str(metadata.get("description", "")).strip():
        raise ValueError("Metadata needs a nonempty title and description")
    if not isinstance(metadata.get("digital_files"), list) or not metadata["digital_files"]:
        raise ValueError("Metadata needs at least one digital_files entry")
    return metadata


def listing_text(metadata: dict) -> bytes:
    """UTF-8 text for copying into Etsy manually; not a customer download."""
    title = str(metadata["title"]).strip()
    description = str(metadata["description"]).strip()
    lines = ["ETSY LISTING COPY", "", "TITLE", title, "", "DESCRIPTION",
             description, ""]
    tags = metadata.get("tags")
    if isinstance(tags, list) and tags:
        lines.extend(["TAGS (OPTIONAL)", ", ".join(str(t) for t in tags), ""])
    return ("\n".join(lines)).encode("utf-8")
