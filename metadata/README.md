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
