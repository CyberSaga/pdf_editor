# OCR model-weight verification (finding F9 / CWE-494)

The OCR feature uses [surya-ocr](https://github.com/datalab-to/surya). On first use
surya downloads its detection and recognition weights from datalab's host
(`https://models.datalab.to`) into a per-user cache. That download path performs
**no content-hash verification** and the checkpoints are pinned only by a dated S3
path that an upstream release can silently change. A man-in-the-middle, a poisoned
mirror, or an upstream revision swap could therefore feed the app tampered weights.

`model/tools/ocr_weights.py` adds a verification layer that the OCR adapter
(`_SuryaAdapter._ensure_loaded`) invokes **before any predictor is constructed**.

## What the layer enforces

1. **Revision pinning.** The surya checkpoint settings are pinned to explicit values
   (`PINNED_CHECKPOINTS` in `ocr_weights.py`) via environment variables surya's
   `BaseSettings` reads at import time. An upstream bump cannot move the app to
   different weights without an explicit edit here.
2. **Offline / bundled loading.** Set `PDF_EDITOR_OCR_WEIGHTS_DIR` to a local,
   vetted bundle directory. The checkpoints are then redirected to its
   subdirectories (`text_detection/`, `text_recognition/`) and surya/transformers
   are forced offline (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`) so no network
   fetch can occur.
3. **SHA256 verification.** Before a bundle is used, every file listed in
   `WEIGHTS_MANIFEST` (a `bundle-relative-path -> sha256` map) is hashed and
   compared to its pinned digest. A missing file or any mismatch raises
   `OcrWeightsError` and **loading is refused**. An empty manifest with a configured
   bundle also fails closed — there is nothing to verify against.

### Environment variables

| Variable                        | Purpose                                              |
|---------------------------------|------------------------------------------------------|
| `PDF_EDITOR_OCR_WEIGHTS_DIR`    | Local vetted bundle dir; enables offline + hash check |
| `PDF_EDITOR_OCR_REVISION`       | Optional override of the recognition checkpoint id   |

## The pinned hashes: source and update process

`WEIGHTS_MANIFEST` is **empty by default** — no vetted bundle ships with the repo
yet (tracked in `TODOS.md` → "F9 bundle distribution"). While it is empty,
configuring `PDF_EDITOR_OCR_WEIGHTS_DIR` fails closed by design.

To populate it for a release that ships a bundle:

1. **Obtain the weights once, from a trusted network**, by letting surya download
   the pinned revision into its cache (or by pulling the dated S3 paths directly):

   ```bash
   # pinned checkpoints live in model/tools/ocr_weights.py:
   #   detection    : s3://text_detection/2025_05_07
   #   recognition  : s3://text_recognition/2025_09_23
   python -c "from surya.detection import DetectionPredictor; DetectionPredictor()"
   python -c "from surya.recognition import RecognitionPredictor, FoundationPredictor; \
              RecognitionPredictor(FoundationPredictor())"
   ```

   The cache dir is `platformdirs.user_cache_dir('datalab')/models` unless
   `MODEL_CACHE_DIR` is overridden.

2. **Assemble the bundle** with the expected layout:

   ```
   <bundle>/text_detection/<files…>
   <bundle>/text_recognition/<files…>
   ```

3. **Compute each file's SHA256** and record it, bundle-relative:

   ```bash
   python - <<'PY'
   import hashlib, pathlib
   root = pathlib.Path("<bundle>")
   for p in sorted(root.rglob("*")):
       if p.is_file():
           h = hashlib.sha256(p.read_bytes()).hexdigest()
           print(f'    "{p.relative_to(root).as_posix()}": "{h}",')
   PY
   ```

   (For large files use the streamed helper `ocr_weights.sha256_file(path)`.)

4. **Paste the lines into `WEIGHTS_MANIFEST`** in `model/tools/ocr_weights.py`.
   Commit the manifest change together with the pinned-revision values it was
   generated against — the two must always move in lockstep.

5. **Verify** by pointing `PDF_EDITOR_OCR_WEIGHTS_DIR` at the bundle and running an
   OCR pass; a tampered or truncated file now raises `OcrWeightsError`.

## Why hashes are only checked for the bundle path

When no bundle is configured the app still pins the revision but downloads over
HTTPS without a content hash (surya provides no digest to pin against, only a
`manifest.json` file-list). Transport integrity comes from TLS; full content
pinning requires the vetted offline bundle above. This is the documented residual
until a bundle is shipped with the product.
