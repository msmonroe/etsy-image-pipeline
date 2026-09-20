# Etsy Image Pipeline

A small Ubuntu-friendly worker that scans a Dropbox folder for approved PNG artwork, upscales it through Replicate, validates the result, and uploads the finished PNG back to Dropbox.

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
        +--> success: Dropbox /Etsy/Upscaled
        |
        +--> failure: copy source to Dropbox /Etsy/Needs-Review
```

The worker is intentionally conservative. It does **not** publish to Etsy. It only prepares production-ready image files.

## Replicate model

The current smoke-test configuration uses the official Replicate model:

```text
nightmareai/real-esrgan
```

Its API accepts the fields used by this worker:

```json
{
  "image": "...",
  "scale": 3,
  "face_enhance": false
}
```

At 3x, a 1536 x 1536 source should produce approximately 4608 x 4608 output. The worker validates both a minimum size and the expected scale so an accidental 2x or 4x model response does not silently pass.

The model slug is configured with `REPLICATE_MODEL`. `REPLICATE_MODEL_VERSION` is optional; leave it blank to call Replicate's model endpoint, or set an exact version ID if you later want to pin a version.

## 1. Clone

```bash
git clone https://github.com/msmonroe/etsy-image-pipeline.git
cd etsy-image-pipeline
```

For the current smoke-test branch:

```bash
git switch replicate-smoke-test
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

- a development access token, or
- a refresh token plus Dropbox app key and secret

For unattended use, refresh-token authentication is preferable.

For Replicate, add your API token:

```text
REPLICATE_API_TOKEN=...
```

The default model settings are already in `.env.example`:

```text
REPLICATE_MODEL=nightmareai/real-esrgan
UPSCALE_FACTOR=3
FACE_ENHANCE=false
```

## 4. Smoke-test exactly one approved image

Do **not** enable the timer yet.

Use the exact filename selector so the test cannot spill into other approved assets:

```bash
python pipeline.py --once --file samurai_cat_halloween_witch_black_master.png
```

Expected success path:

```text
/Etsy/Approved/samurai_cat_halloween_witch_black_master.png
        ->
/Etsy/Upscaled/samurai_cat_halloween_witch_black_master.png
```

If processing fails, the source is copied to:

```text
/Etsy/Needs-Review/samurai_cat_halloween_witch_black_master.png
```

The process exits non-zero on a processing failure.

You can also limit a general scan by attempted file count:

```bash
python pipeline.py --once --limit 1
```

Important: `--limit` counts attempted files, not only successful files.

## 5. Inspect the result before automation

Check the log output for:

- source dimensions and mode,
- output dimensions near 4608 x 4608 for a 1536 x 1536 source,
- `transparency=True` when the source contains transparent pixels,
- a final `processed=1 failures=0` summary.

Also visually inspect edges against both light and dark backgrounds. The pipeline restores the source alpha channel after upscaling, but edge quality still deserves a human check before unattended operation.

## 6. Install as a systemd timer only after the smoke test passes

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

To disable it:

```bash
sudo systemctl disable --now etsy-image-pipeline.timer
```

## Dropbox folders

Defaults:

- Source: `/Etsy/Approved`
- Output: `/Etsy/Upscaled`
- Failed source copies: `/Etsy/Needs-Review`

The worker skips a source image when an output with the same basename already exists unless `OVERWRITE_OUTPUT=true`.

## Transparency handling

Many image upscalers are optimized for RGB images and can lose or damage PNG transparency.

This worker therefore:

1. records the source alpha channel,
2. runs the image through the upscaler,
3. resizes the original alpha channel to the final output dimensions,
4. reattaches it to the upscaled RGB result,
5. verifies that transparency still exists when the source used transparency.

That is deliberately boring. Boring pipelines are good pipelines.

## Safety

- Secrets are read only from environment variables.
- `.env` is ignored by Git.
- Existing Dropbox outputs are not overwritten by default.
- Failed files are copied to `Needs-Review` when possible.
- A smoke test can target one exact filename.
- Etsy publishing is intentionally outside this version.

## Next phase

Once this worker is stable, the next layer can create Etsy draft listings from structured metadata while keeping a human review step before publication.
