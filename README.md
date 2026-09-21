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
