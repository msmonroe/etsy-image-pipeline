# Etsy Image Pipeline

Ubuntu-friendly tooling for an original, IP-clean Etsy digital-art workflow built around Dropbox, Replicate, PNG transparency preservation, metadata sidecars, and a mock-first Etsy API layer.

The project is intentionally conservative:

- source art is read from Dropbox,
- approved PNGs are upscaled through Replicate,
- transparency is restored and validated,
- finished PNGs are written at 300 DPI metadata,
- failed source files are routed to `/Etsy/Needs-Review`,
- Etsy metadata travels beside each image as a matching `.etsy.json` sidecar,
- Etsy integration runs in mock mode by default,
- nothing is published to Etsy automatically.

## Current workflow

```text
Dropbox /Etsy/Approved
        |
        +--> image.png
        +--> image.etsy.json
        |
        v
Python worker
        |
        +--> download source PNG
        +--> send image to Replicate Real-ESRGAN
        +--> restore/preserve original alpha channel
        +--> write PNG with 300 DPI metadata
        +--> validate dimensions + transparency
        |
        +--> success
        |      |
        |      +--> /Etsy/Upscaled/image.png
        |      +--> /Etsy/Upscaled/image.etsy.json
        |
        +--> failure
               |
               +--> /Etsy/Needs-Review/image.png
```

The sidecar is optional for image processing. If a matching `.etsy.json` exists, the worker copies it forward with the successful image.

## Repository layout

```text
pipeline.py                         Main Dropbox -> Replicate -> Dropbox worker
etsy_api.py                         Mock/real Etsy API client abstraction
tools/create_etsy_metadata.py       Create Dropbox-native Etsy sidecars
tools/create_etsy_draft.py          Rehearse or create Etsy draft listings
listing_images.py                   Pillow listing-image renderer
tools/generate_listing_images.py    Generate Dropbox Etsy listing images
metadata/etsy_asset.schema.json     Sidecar metadata schema
metadata/README.md                  Detailed metadata documentation
dropbox_test/test_dropbox.py        Dropbox read/write smoke test
systemd/etsy-image-pipeline.service systemd oneshot service
systemd/etsy-image-pipeline.timer   recurring timer
.env.example                        configuration template
```

## Branch

Current development work is on:

```text
replicate-smoke-test
```

Clone and switch to it:

```bash
git clone https://github.com/msmonroe/etsy-image-pipeline.git
cd etsy-image-pipeline
git switch replicate-smoke-test
```

If the repository is already cloned:

```bash
git fetch
git switch replicate-smoke-test
git pull
```

## Python environment

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

A successful activation normally changes the shell prompt to begin with `(.venv)`.

## Configuration

Create the local environment file:

```bash
cp .env.example .env
nano .env
```

Never commit `.env`.

### Dropbox

For a quick test, an access token is sufficient:

```text
DROPBOX_ACCESS_TOKEN=
```

For unattended operation, refresh-token authentication is preferred:

```text
DROPBOX_REFRESH_TOKEN=
DROPBOX_APP_KEY=
DROPBOX_APP_SECRET=
```

Default folders:

```text
DROPBOX_APPROVED_FOLDER=/Etsy/Approved
DROPBOX_UPSCALED_FOLDER=/Etsy/Upscaled
DROPBOX_NEEDS_REVIEW_FOLDER=/Etsy/Needs-Review
```

The Dropbox app must have access to the real `/Etsy` tree. For this workflow, a Dropbox app created with **Full Dropbox** access is required rather than App Folder access.

The app needs file metadata/content read and write scopes sufficient to list, download, upload, copy, and inspect files.

## Dropbox smoke test

Before involving Replicate, verify Dropbox independently:

```bash
python dropbox_test/test_dropbox.py
```

A successful run ends with:

```text
Dropbox application test PASSED.
Read and write access required by the image pipeline are working.
```

The test uses:

```text
/Etsy/Test/dropbox_app_test.txt
```

and does not modify approved artwork.

## Replicate upscaler

The current model is:

```text
nightmareai/real-esrgan
```

Configure:

```text
REPLICATE_API_TOKEN=
REPLICATE_MODEL=nightmareai/real-esrgan
REPLICATE_MODEL_VERSION=
UPSCALE_FACTOR=4
FACE_ENHANCE=false
```

`REPLICATE_MODEL_VERSION` may be left blank to use the model endpoint/current version.

### Output sizing

The worker validates both:

- a minimum output size, and
- the expected output dimensions based on source dimensions x `UPSCALE_FACTOR`.

For example:

```text
1254 x 1254 source at 4x -> approximately 5016 x 5016
1536 x 1536 source at 3x -> approximately 4608 x 4608
```

Current minimums are controlled by:

```text
MIN_OUTPUT_WIDTH=4500
MIN_OUTPUT_HEIGHT=4500
DIMENSION_TOLERANCE_PX=8
```

Choose the upscale factor based on the actual source size. A 1254 px source needs 4x to clear a 4500 px minimum.

## Transparency and PNG output

Many RGB-oriented upscalers can lose or damage PNG transparency.

The worker therefore:

1. reads and preserves the source alpha channel,
2. sends the image through the upscaler,
3. resizes the original alpha channel to match the returned image,
4. reattaches it,
5. validates that transparency still exists when the source used transparency.

Final PNGs are written with:

```text
300 DPI metadata
RGBA transparency when applicable
PNG format
```

DPI is metadata only. Pixel dimensions determine the actual image resolution.

## Single-image smoke test

Do not enable unattended processing until a single-image test passes.

Example:

```bash
python pipeline.py --once \
  --file samurai_cat_halloween_witch_black_master.png
```

The exact filename selector prevents the smoke test from processing other approved assets.

A successful run should end with something similar to:

```text
Run complete. attempted=1 processed=1 skipped=0 failures=0
```

If the destination PNG already exists and `OVERWRITE_OUTPUT=false`, the file is skipped.

For a deliberate retest, temporarily set:

```text
OVERWRITE_OUTPUT=true
```

or remove the existing output first.

## Failure handling

If an image fails processing, the source is copied to:

```text
/Etsy/Needs-Review/
```

If a copy with the same filename already exists there, the worker logs that condition and does not create another duplicate.

A failed file remains in `/Etsy/Approved`; the current behavior is a copy-to-review workflow, not a move.

## Etsy metadata sidecars

Each image can have a matching JSON sidecar with the exact same filename stem:

```text
/Etsy/Approved/samurai_cat_halloween_witch_black_master.png
/Etsy/Approved/samurai_cat_halloween_witch_black_master.etsy.json
```

The sidecar contains two stable identifiers:

- `asset_key`: identifies the specific image,
- `listing_key`: groups one or more images into a future Etsy listing/bundle.

Example:

```json
{
  "asset_key": "samurai_cat_halloween_witch_black_master",
  "source_filename": "samurai_cat_halloween_witch_black_master.png",
  "listing_key": "samurai_cat_halloween"
}
```

### Create a sidecar directly in Dropbox

Using only a basename:

```bash
python tools/create_etsy_metadata.py \
  samurai_cat_halloween_witch_black_master.png \
  --listing-key samurai_cat_halloween
```

A basename resolves under `DROPBOX_APPROVED_FOLDER`.

You can also use the full Dropbox path:

```bash
python tools/create_etsy_metadata.py \
  /Etsy/Approved/samurai_cat_halloween_witch_black_master.png \
  --listing-key samurai_cat_halloween
```

The tool refuses to overwrite an existing sidecar unless `--force` is supplied.

### IP review gate

Sidecars begin with:

```json
"ip_review": {
  "status": "pending",
  "original_art_only": true,
  "notes": ""
}
```

The Etsy draft tool refuses to proceed unless:

```text
ip_review.status == approved
original_art_only == true
```

This project is intended for original, no-brand, no-character, low-copyright-risk artwork only.

## Etsy listing metadata

The sidecar schema includes fields for:

```text
title
description
price
quantity
who_made
when_made
taxonomy_id
type
tags
materials
sku
listing_id
state
```

It also tracks two different asset groups:

### Listing images

These are images shown on the Etsy product page:

```json
"listing_images": [
  {
    "filename": "samurai_cat_halloween_preview.jpg",
    "rank": 1,
    "alt_text": "Halloween samurai cat digital art preview"
  }
]
```

### Digital files

These are files delivered to the buyer:

```json
"digital_files": [
  {
    "filename": "samurai_cat_halloween_witch_black_master.png",
    "display_name": "Samurai Cat Witch PNG"
  }
]
```

The metadata generator automatically seeds the source PNG into `digital_files`.

## Mock Etsy API

The Etsy API layer is implemented now, but mock mode is the default.

Configure:

```text
ETSY_MODE=mock
ETSY_API_KEYSTRING=
ETSY_SHARED_SECRET=
ETSY_ACCESS_TOKEN=
ETSY_SHOP_ID=
ETSY_OUTBOX_DIR=.etsy_mock_outbox
```

Mock output is ignored by Git.

### Create a mock draft

Once the required metadata is filled in and the IP review is approved:

```bash
python tools/create_etsy_draft.py \
  path/to/actual-item.etsy.json
```

The path above must point to a real local sidecar file. It is an example, not a literal filename.

To also rehearse listing-image and digital-file upload operations:

```bash
python tools/create_etsy_draft.py \
  path/to/actual-item.etsy.json \
  --include-assets
```

Mock events are written to:

```text
.etsy_mock_outbox/
```

Nothing is sent to Etsy while:

```text
ETSY_MODE=mock
```

## Real Etsy API safety latch

Later, after Etsy credentials are configured, changing:

```text
ETSY_MODE=real
```

is still not sufficient to send requests.

The command also requires:

```bash
--allow-real-api
```

This gives the Etsy integration two independent safety gates:

1. environment configuration must explicitly select real mode,
2. the command must explicitly authorize a real API operation.

The current design creates drafts. It does not automatically publish listings.

## systemd unattended operation

Only enable the timer after Dropbox, Replicate, transparency, dimensions, and metadata behavior have all been tested.

Edit:

```text
systemd/etsy-image-pipeline.service
```

and replace `YOUR_LINUX_USER` and the repository path as needed.

Install:

```bash
sudo cp systemd/etsy-image-pipeline.service /etc/systemd/system/
sudo cp systemd/etsy-image-pipeline.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now etsy-image-pipeline.timer
```

Check status:

```bash
systemctl list-timers | grep etsy-image
journalctl -u etsy-image-pipeline.service -n 100 --no-pager
```

Disable:

```bash
sudo systemctl disable --now etsy-image-pipeline.timer
```

## Safety summary

- `.env` is ignored by Git.
- Secrets remain local.
- Existing output files are not overwritten by default.
- One-image smoke tests can target an exact basename.
- Failed images are copied to `Needs-Review`.
- PNG transparency is preserved and validated.
- Final PNGs are written with 300 DPI metadata.
- Etsy metadata follows the image through the Dropbox pipeline.
- Etsy integration defaults to mock mode.
- Real Etsy requests require an additional explicit command-line switch.
- No automatic Etsy publishing is enabled.

## Current development path

The intended progression is:

```text
Dropbox app test
    ->
single-image Replicate test
    ->
validate transparency / dimensions / DPI
    ->
create Dropbox-native .etsy.json
    ->
populate listing metadata
    ->
mock Etsy draft
    ->
mock asset uploads
    ->
enable unattended image processing
    ->
later connect real Etsy credentials
    ->
create Etsy drafts with human review
```


## Generate Etsy listing images

Etsy listing images are separate from the transparent PNG files delivered to buyers. The generator creates flattened JPEG previews from an upscaled production PNG and stores them under:

```text
/Etsy/Listing-Images/<listing_key>/
```

The current set is:

```text
01 hero      clean primary product preview
02 detail    close-up artwork view
03 specs     pixel dimensions / DPI / transparency / digital-only notice
04 included  summary of downloadable files
```

Default configuration:

```text
DROPBOX_LISTING_IMAGES_FOLDER=/Etsy/Listing-Images
ETSY_LISTING_IMAGE_WIDTH=2400
ETSY_LISTING_IMAGE_HEIGHT=2000
ETSY_LISTING_IMAGE_JPEG_QUALITY=90
```

The 2400 x 2000 default keeps both dimensions above Etsy's current 2000-pixel recommendation for listing photos. Listing previews are JPEG because transparent PNG listing images are not suitable for Etsy display; buyer download PNGs remain transparent.

Generate listing images for an upscaled asset:

```bash
python tools/generate_listing_images.py \
  samurai_cat_halloween_witch_black_master.png
```

A basename resolves under `DROPBOX_UPSCALED_FOLDER`.

The tool requires the matching production sidecar:

```text
/Etsy/Upscaled/image.png
/Etsy/Upscaled/image.etsy.json
```

It uploads the generated JPEGs to the listing-images folder and updates the sidecar's `listing_images` array with Dropbox paths, rank, and alt text.

Existing listing images are protected. Use `--force` only for a deliberate regeneration:

```bash
python tools/generate_listing_images.py \
  samurai_cat_halloween_witch_black_master.png \
  --force
```

This stage does not call Etsy and does not publish anything.
