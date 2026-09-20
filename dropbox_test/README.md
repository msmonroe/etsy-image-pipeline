# Dropbox Application Smoke Test

This mini-project verifies the Dropbox credentials and permissions used by the Etsy image pipeline without involving Replicate.

It tests:

1. Dropbox authentication
2. Reading `/Etsy/Approved`
3. Creating `/Etsy/Test` if needed
4. Uploading a harmless text file
5. Downloading that file
6. Verifying the downloaded bytes match the uploaded bytes

It does **not** modify or move any artwork.

## Run

From the repository root:

```bash
git switch dropbox-app-test
source .venv/bin/activate
pip install -r requirements.txt
python dropbox_test/test_dropbox.py
```

The script reads Dropbox credentials from the repo's existing `.env`.

Supported auth configurations:

```text
DROPBOX_ACCESS_TOKEN=...
```

or, preferred for unattended operation:

```text
DROPBOX_REFRESH_TOKEN=...
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
```

A successful run ends with:

```text
Dropbox application test PASSED.
Read and write access required by the image pipeline are working.
```

The test writes this harmless file:

```text
/Etsy/Test/dropbox_app_test.txt
```

It is overwritten on subsequent test runs.
