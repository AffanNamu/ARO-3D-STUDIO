# Image → 3D pipeline

1. **Upload** (`POST /projects/{id}/sources`): content sniffed (PNG/JPEG/WebP), size ≤ `ARO_MAX_UPLOAD_MB`, pixels ≤ `ARO_MAX_IMAGE_PIXELS`, min side 64 px, fully decoded (corruption), EXIF orientation read, alpha/transparency measured, quality metrics computed, stored as `<sha256>.<ext>`.
2. **Quality report** (advisory only): sharpness (variance of Laplacian), contrast, brightness, clipping → warnings and a 0–1 score. Nothing here blocks generation.
3. **Analysis** (`imaging/analysis.py`): background type (transparent/uniform/complex), foreground bbox/fraction, framing, aspect. **No object category is invented**: with no classifier registered, `classification` is `null` and the asset category you chose drives "recommended mode".
4. **Preprocessing** (`imaging/preprocess.py`): orientation correction → background analysis → background removal (existing alpha → rembg if installed → classical border-colour matte for uniform backgrounds → none) → crop → fit to a square at `foreground_ratio` → composite on 50 % grey → normalised float32 model input. Preview endpoint: `…/preprocessed.png`.
5. **Generation job** — see [generation-architecture](../architecture/generation-architecture.md).

### Matting honesty

The classical matte is a real algorithm (border-colour estimate, connected-to-border background, hole preservation) that works for plain/studio backgrounds. It is **not** a segmentation model; cluttered backgrounds need rembg or a transparent cut-out (the UI says so).

### Known limitation of single-image reconstruction

Hidden sides are invented by the model. Use the cleanest side/three-quarter view; expect to repair and re-model (wheel/axle metadata in particular is supplied by the artist).
