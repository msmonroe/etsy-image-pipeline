# Etsy metadata sidecars

Each production image gets a JSON sidecar with the same filename stem.

Example:

```text
samurai_cat_halloween_witch_black_master.png
samurai_cat_halloween_witch_black_master.etsy.json
```

The exact image stem is stored as `asset_key`. A separate `listing_key` groups multiple assets into one future Etsy bundle.

Example bundle:

```text
samurai_cat_halloween_witch_black_master.png
samurai_cat_halloween_witch_black_master.etsy.json
samurai_cat_halloween_oni_tuxedo_master.png
samurai_cat_halloween_oni_tuxedo_master.etsy.json
```

Both sidecars can use:

```json
"listing_key": "samurai_cat_halloween"
```

This gives us two stable identifiers:

- `asset_key`: exactly which image/file this metadata belongs to
- `listing_key`: which Etsy product/bundle it belongs to

## Create a sidecar

```bash
python tools/create_etsy_metadata.py \
  samurai_cat_halloween_witch_black_master.png \
  --listing-key samurai_cat_halloween
```

This produces:

```text
samurai_cat_halloween_witch_black_master.etsy.json
```

The metadata starts in `metadata_only` state. It is not permission to publish anything. Future Etsy automation should create drafts only until a human review step is explicitly enabled.

## IP review

Every sidecar contains:

```json
"ip_review": {
  "status": "pending",
  "original_art_only": true,
  "notes": ""
}
```

A future listing builder should refuse to create an Etsy draft unless `ip_review.status` is `approved`.

## Listing images and buyer download files

The sidecar now tracks both kinds of Etsy assets explicitly:

```json
"listing_images": [
  {
    "filename": "samurai_cat_halloween_preview.jpg",
    "rank": 1,
    "alt_text": "Halloween samurai cat digital art preview"
  }
],
"digital_files": [
  {
    "filename": "samurai_cat_halloween_witch_black_master.png",
    "display_name": "Samurai Cat Witch PNG"
  }
]
```

Filenames are resolved relative to the sidecar file unless an absolute path is supplied.

The metadata generator seeds the source filename into `digital_files` because the current upscaler preserves the basename when writing the production PNG. Listing preview/mockup images are left empty until they are generated.

## Mock Etsy API

The repository contains a mockable Etsy API layer:

```text
etsy_api.py
tools/create_etsy_draft.py
```

Keep this in `.env` while developing:

```text
ETSY_MODE=mock
ETSY_API_KEYSTRING=
ETSY_SHARED_SECRET=
ETSY_ACCESS_TOKEN=
ETSY_SHOP_ID=
ETSY_OUTBOX_DIR=.etsy_mock_outbox
```

To rehearse draft creation:

```bash
python tools/create_etsy_draft.py path/to/item.etsy.json
```

To also rehearse listing-image and digital-file uploads:

```bash
python tools/create_etsy_draft.py path/to/item.etsy.json --include-assets
```

Mock calls write JSON event records into `.etsy_mock_outbox/`. Nothing is sent to Etsy.

The draft tool refuses to proceed unless:

- `ip_review.status` is `approved`
- `original_art_only` is `true`
- required Etsy listing fields are populated
- the listing type is `download`

Even after real credentials are added, `ETSY_MODE=real` is not enough by itself. The command also requires the explicit `--allow-real-api` switch. This is a second safety latch so a local configuration change cannot accidentally send requests to Etsy.
