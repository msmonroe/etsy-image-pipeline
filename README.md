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
