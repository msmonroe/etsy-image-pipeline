#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import dropbox
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

TEST_FOLDER = "/Etsy/Test"
TEST_FILE = f"{TEST_FOLDER}/dropbox_app_test.txt"


def make_client() -> dropbox.Dropbox:
    access_token = os.getenv("DROPBOX_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN", "").strip()
    app_key = os.getenv("DROPBOX_APP_KEY", "").strip()
    app_secret = os.getenv("DROPBOX_APP_SECRET", "").strip()

    if refresh_token and app_key and app_secret:
        print("Auth mode: refresh token")
        return dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )

    if access_token:
        print("Auth mode: access token")
        return dropbox.Dropbox(access_token)

    raise RuntimeError(
        "Missing Dropbox credentials. Configure either DROPBOX_ACCESS_TOKEN "
        "or DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET in .env"
    )


def ensure_folder(dbx: dropbox.Dropbox, path: str) -> None:
    try:
        dbx.files_get_metadata(path)
        print(f"PASS folder exists: {path}")
    except dropbox.exceptions.ApiError:
        dbx.files_create_folder_v2(path)
        print(f"PASS folder created: {path}")


def main() -> int:
    try:
        dbx = make_client()

        account = dbx.users_get_current_account()
        print(f"PASS authenticated as: {account.name.display_name}")

        approved = os.getenv("DROPBOX_APPROVED_FOLDER", "/Etsy/Approved")
        listing = dbx.files_list_folder(approved)
        pngs = [
            entry.name
            for entry in listing.entries
            if isinstance(entry, dropbox.files.FileMetadata)
            and entry.name.lower().endswith(".png")
        ]
        print(f"PASS listed {approved}: {len(pngs)} PNG file(s)")
        for name in pngs[:10]:
            print(f"  - {name}")

        ensure_folder(dbx, TEST_FOLDER)

        payload = (
            "Dropbox app test\n"
            f"utc={datetime.now(timezone.utc).isoformat()}\n"
            "repo=msmonroe/etsy-image-pipeline\n"
        ).encode("utf-8")

        local_hash = hashlib.sha256(payload).hexdigest()

        dbx.files_upload(
            payload,
            TEST_FILE,
            mode=dropbox.files.WriteMode.overwrite,
            mute=True,
        )
        print(f"PASS uploaded: {TEST_FILE}")

        metadata, response = dbx.files_download(TEST_FILE)
        downloaded = response.content
        remote_hash = hashlib.sha256(downloaded).hexdigest()

        if downloaded != payload:
            raise RuntimeError("Downloaded content did not match uploaded content")

        print(f"PASS downloaded: {metadata.path_display or TEST_FILE}")
        print(f"PASS SHA-256 match: {local_hash == remote_hash}")

        print("\nDropbox application test PASSED.")
        print("Read and write access required by the image pipeline are working.")
        return 0

    except Exception as exc:
        print(f"\nDropbox application test FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
