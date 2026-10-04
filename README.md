# Etsy Image Pipeline

A small Ubuntu-friendly worker that watches a Dropbox folder for approved PNG artwork, upscales it through Replicate, validates the result, and uploads the finished PNG back to Dropbox.

## Workflow

```text
Dropbox /Etsy/Approved
        |
        v
Python worker
        |
        +--> download source PNG
        +--> send to Replicate upscaler
        +--> restore/preserve source alpha channel
        +--> validate dimensions + transparency
        |
        v
Dropbox /Etsy/Upscaled
```

The worker is intentionally conservative. It does **not** publish to Etsy. It only prepares production-ready image files.

## 1. Clone

```bash
git clone https://github.com/msmonroe/etsy-image-pipeline.git
cd etsy-image-pipeline
```

## 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure secrets

```bash
cp .env.example .env
nano .env
```

Never commit `.env`.

You can authenticate to Dropbox with either:

- a long-lived development access token, or
- a refresh token plus Dropbox app key and secret

For unattended use, refresh-token authentication is preferable.

For Replicate, set your API token and the exact model version ID you want to use.

## 4. Test one pass

```bash
python pipeline.py --once
```

To limit a test run:

```bash
python pipeline.py --once --limit 1
```

## 5. Install as a systemd timer

Edit `systemd/etsy-image-pipeline.service` and replace `YOUR_LINUX_USER` and the project path if needed.

Then:

```bash
sudo cp systemd/etsy-image-pipeline.service /etc/systemd/system/
sudo cp systemd/etsy-image-pipeline.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now etsy-image-pipeline.timer
```

Check it:

```bash
systemctl list-timers | grep etsy-image
journalctl -u etsy-image-pipeline.service -n 100 --no-pager
```

## Dropbox folders

Defaults:

- Source: `/Etsy/Approved`
- Output: `/Etsy/Upscaled`
- Failed source copies: `/Etsy/Needs-Review`

The worker skips a source image when an output with the same basename already exists.

Example:

```text
/Etsy/Approved/samurai_cat_halloween_witch_black_master.png
/Etsy/Upscaled/samurai_cat_halloween_witch_black_master.png
```

## Transparency handling

Many image upscalers are optimized for RGB images and can lose or damage PNG transparency.

This worker therefore:

1. records the source alpha channel,
2. runs the image through the upscaler,
3. resizes the original alpha channel to the final output dimensions,
4. reattaches it to the upscaled RGB result,
5. verifies that transparency still exists when the source used transparency.

That is deliberately boring. Boring pipelines are good pipelines.

## Replicate model input

Different Replicate models use slightly different input fields. The defaults assume an ESRGAN-style model accepting:

```json
{
  "image": "...",
  "scale": 3,
  "face_enhance": false
}
```

If your chosen model differs, edit `run_replicate_upscale()` in `pipeline.py`.

## Safety

- Secrets are read only from environment variables.
- `.env` is ignored by Git.
- Existing Dropbox outputs are not overwritten by default.
- Failed files are copied to `Needs-Review` when possible.
- Etsy publishing is intentionally outside this version.

## Next phase

Once this worker is stable, the next layer can create Etsy draft listings from structured metadata while keeping a human review step before publication.


## Vector workflow

The repository now has a second production branch for vector-friendly line art. The existing `pipeline.py` raster/Real-ESRGAN workflow is unchanged.

```text
Dropbox /Etsy/Approved/Vector
        |
        v
vector_pipeline.py
        |
        +--> composite transparency onto white
        +--> threshold to clean 1-bit line art
        +--> Potrace -> genuine SVG paths
        +--> reject embedded raster images / missing paths
        +--> render SVG back to PNG with Inkscape
        +--> compare render against cleaned source
        +--> export SVG + PNG + PDF + EPS
        |
        +--> PASS -> /Etsy/Vectorized/{SVG,PNG,PDF,EPS}
        |
        +--> FAIL -> /Etsy/Needs-Review
```

Install the vector system dependencies on Ubuntu:

```bash
sudo apt update
sudo apt install potrace inkscape ghostscript
```

### Ubuntu / Snap VS Code note

If this worker is launched from a terminal inside a Snap-installed VS Code, VS Code can inject Snap GTK/GIO paths that break the native `/usr/bin/inkscape` with symbol lookup errors. The vector worker sanitizes those variables for its Inkscape subprocesses, so normal pipeline runs do not require shell workarounds.

Test one approved vector source:

```bash
python vector_pipeline.py --once --limit 1
```

Vector-specific optional environment settings:

```dotenv
DROPBOX_VECTOR_APPROVED_FOLDER=/Etsy/Approved/Vector
DROPBOX_VECTORIZED_FOLDER=/Etsy/Vectorized
VECTOR_PNG_SIZE=4500
VECTOR_PNG_DPI=300
VECTOR_THRESHOLD=180
VECTOR_MAX_DIFFERENCE=0.08
```

`VECTOR_THRESHOLD` controls which source pixels become black vector geometry. Lower values preserve only darker marks; higher values retain lighter details. `VECTOR_MAX_DIFFERENCE` is the normalized visual QC tolerance between the cleaned source and a fresh render of the generated SVG.

The SVG validator explicitly rejects SVG files containing `<image>` elements and requires real `<path>` geometry. This prevents a raster PNG wrapped in an SVG container from passing as a vector product.

DXF is intentionally not generated yet. Detailed engraved line art can produce poor cutting-machine DXF files, so DXF should be added only after a separate cutter-oriented simplification/QC stage.


### Proven vector QC

The first end-to-end production test (`cat_head_bowtie_001.png`) completed successfully with 169 SVG paths and a normalized visual difference of 0.0184 against the cleaned source, below the default 0.0800 rejection threshold. SVG, transparent PNG, PDF, and EPS exports all completed successfully.



## Etsy bundle workflow

Completed vector assets can be packaged into buyer-facing ZIP files with `bundle_pipeline.py`.

The bundler reads matching designs from:

```text
/Etsy/Vectorized/SVG
/Etsy/Vectorized/PNG
/Etsy/Vectorized/PDF
/Etsy/Vectorized/EPS
```

and writes:

```text
/Etsy/Bundles/Individual
/Etsy/Bundles/Collections
```

Each ZIP includes the applicable artwork plus `README.txt` and `MANIFEST.json`. The default safety ceiling is 19 MB per ZIP, leaving headroom below Etsy's 20 MB per-file limit. A collection is split into multiple ZIPs automatically. The run fails if more than five collection ZIPs would be required.

Build the Samurai Cats & Ramen individual products and collection:

```bash
python bundle_pipeline.py --prefix samurai_ramen_ \
  --collection-name samurai_cats_ramen_collection
```

To build only the collection ZIPs:

```bash
python bundle_pipeline.py --prefix samurai_ramen_ \
  --collection-name samurai_cats_ramen_collection \
  --no-individual
```

Optional settings:

```dotenv
DROPBOX_BUNDLES_FOLDER=/Etsy/Bundles
BUNDLE_MAX_ZIP_MB=19
BUNDLE_MAX_LISTING_FILES=5
```

Existing bundles are not overwritten unless `OVERWRITE_OUTPUT=true`.

The detailed vector collection is intended for print, sublimation, DTF, stickers, posters, engraving, and digital design. It should not be advertised as general-purpose Cricut/Silhouette cut-ready artwork. DXF remains reserved for a future simplified cutter-specific workflow.


## Safe product-specific exports and Etsy draft preparation

New modules: `production_workflow.py` and `etsy_drafts.py`. These are opt-in helpers; the existing scheduled Dropbox worker is unchanged until they are explicitly integrated into the production orchestration.

- Plan output by product: `clipart` 4500x4500, `sticker` 3000x3000, `shirt` 4500x5400, `wall_3x4` 3600x4800. All PNG exports carry 300 PPI metadata.
- `plan_export(source_size, product)` skips unnecessary enlargement. When enlargement is needed, it returns a scale for the existing upscaler. Run image QC before `export_png`; a resize is not a substitute for genuine detail.
- Keep colorful illustration assets separate from cutting designs. `validate_cut_design` requires simplified, closed, non-overlapping paths before advertising cut-ready SVG/DXF. The current vector worker does **not** produce DXF automatically.
- `validate_downloads` checks Etsy's five-file and 20,000,000-byte per-file ceilings before a network call. Bundle archives conservatively (the existing bundler defaults to 19 MiB, which is larger than 19 decimal MB; keep actual Etsy payloads below 20,000,000 bytes).
- `EtsyDraftClient.create_draft(metadata, images, downloads)` creates a draft and uploads separate JPEG previews and digital download files. It never publishes. Validate titles, descriptions, formats, artwork rights, Etsy category and current API field requirements during human review.
- The draft client expects an existing Etsy OAuth access token with `listings_w` and `ETSY_API_KEY` / `ETSY_SHOP_ID`. OAuth authorization and refresh-token management must be configured separately before unattended operation. Never commit tokens.
- Network failures can leave a partial draft. Record the returned listing ID and reconcile uploads before retrying; do not blindly recreate a listing.

Run tests: `python -m pytest`. GitHub Actions runs the suite on pushes and pull requests.

**Money boundary:** no API activation method is provided. A person reviews each Etsy draft and publishes it manually, accepting any listing fee at that point.

### Etsy upload safety switch

Etsy uploads are disabled by default. Set `ETSY_UPLOAD_ENABLED=false` in `.env`. Credentials alone do not enable uploads. When API access is ready, explicitly set `ETSY_UPLOAD_ENABLED=true` to allow draft-only uploads. No automatic publishing is implemented.

## Listing images only (no Replicate, no Etsy API)

Use this for an already-exported transparent PNG in `/Etsy/Approved`:

```bash
python pipeline.py --once --file greeble_mushroom_forager_3600.png --listing-images-only
```

The mode reads the existing PNG without resizing or calling Replicate. It creates four JPEG previews in `/Etsy/Listing-Images/<listing_key>/`, writes `<image-stem>_etsy_listing.txt` in the same folder for manual title/description copying, and updates `/Etsy/Approved/<image-stem>.etsy.json` with listing image paths. Greeble #01 has curated fallback copy if its sidecar does not yet exist. Other artwork requires a sidecar with `title`, `description`, and `digital_files`. An existing sidecar takes priority over Greeble's fallback.

This mode does not write to `/Etsy/Upscaled`, use Replicate, or call Etsy. It does not overwrite existing JPEG previews unless `OVERWRITE_OUTPUT=true`. The metadata sidecar and manual TXT are refreshed each run; edit the sidecar rather than the generated TXT to preserve copy changes.

For Greeble, listing-only mode also composites the exact approved PNG into a journal example, greeting-card example, and four-use collage. All three extra JPEGs explicitly state **DIGITAL PNG ONLY / MOCKUP FOR INSPIRATION**. These are generated illustrative scenes, not photographs of physical merchandise. Other designs continue to produce four standard previews unless mockups are explicitly enabled in code.

## Automatic Etsy PNG size limit

The normal pipeline keeps the full-resolution master in `/Etsy/Upscaled/<name>.png` and also creates `/Etsy/Upscaled/<name>_etsy.png`. The latter is exported at **3600 × 3600 for square artwork**, or 3600 pixels on the longest side for other aspect ratios, then lossless-compressed under 19,000,000 bytes. True transparency and 300 PPI metadata are retained. If the upscaled master is too small or the required dimensions cannot fit, the job fails and sends the source to Needs-Review instead of uploading an oversized or aggressively color-reduced file. The generated Etsy listing previews use the optimized PNG. This does not call the Etsy API.

To fix an existing upscaled file **without another paid Replicate call**:

```bash
python pipeline.py --once --file greeble_cauldron_toad_alchemist.png --optimize-existing
```

The approved source must still be in `/Etsy/Approved`, and the upscaled master must exist in `/Etsy/Upscaled`. If a matching Etsy sidecar exists in Approved, listing previews and a manual title/description TXT are also generated. `--optimize-existing` overwrites only the separate `_etsy.png` derivative, never the full-resolution master. The source image uploaded in chat is 2048x2048; do not substitute it for the 31 MB upscaled master if you want the larger print resolution.
