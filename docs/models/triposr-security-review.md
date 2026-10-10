# TripoSR model-loading and checkpoint security review

Reviewed 2026-10-10 against upstream commit `107cefdc244c39106fa830359024f6a2f1c78871` (files hashed in `engines/locks/triposr.json`). Scope: how weights are fetched, deserialised and wired into code.

## Findings in upstream `TSR.from_pretrained` (tsr/system.py) and its dependencies

| # | Finding (file) | Risk | Mitigation in this repository |
|---|---|---|---|
| 1 | `hf_hub_download(repo_id, filename)` with **no `revision`** (system.py) | Weights follow a mutable `main`: silent upstream change, account takeover or typosquat = different model/licence/pickle with no review | `weights.py` downloads only `lock.weights.revision` (40-hex) and refuses any other repo id (`test_resolve_refuses_other_repositories…`). The adapter never calls `from_pretrained`. |
| 2 | `torch.load(weight_path, map_location="cpu")` with no `weights_only` (system.py) | `.ckpt` is a **pickle**: loading a poisoned file executes arbitrary code on older torch defaults | SHA-256 + size verified **before** deserialising; `torch.load(..., weights_only=True)` always; **no fallback** to the unsafe mode on failure (`test_unsafe_pickle_failure_is_not_retried…`); `torch >= 2.6.0` enforced because `weights_only=True` itself had a published RCE bypass in earlier releases (CVE-2025-32434, as recalled by the author — verify against the torch advisory). |
| 3 | `find_class(cfg.*_cls)` = `importlib.import_module(<string from config.yaml>)` (utils.py) | A tampered config imports/executes any installed module path | `config.yaml` checksum-verified first; every `*_cls` value must start with `tsr.` (`validate_config_classes`, tested with `os.system`, `builtins.eval`, `subprocess.Popen`, nested keys). |
| 4 | `DINOSingleImageTokenizer.configure` calls `hf_hub_download("facebook/dino-vitb16", "config.json")` **every time the model is built** (tokenizers/image.py) | Hidden unpinned network fetch, needs the Hub even with local weights; JSON data (not pickle) but still an integrity/availability dependency | Lock records its revision + SHA-256; construction runs with that module's `hf_hub_download` replaced by a function that serves only the verified pinned file and **raises on any other download** (`test_unpinned_download_attempt…`). |
| 5 | `Pillow==10.1.0`, `transformers==4.35.0`, `trimesh==4.0.5` pinned by upstream | Old versions with published CVEs may be pulled in the AI image | `requirements-triposr.txt` does not copy those pins blindly; the Studio's own closure is `pip-audit`-ed in CI. **Not yet verified**: that `transformers==4.35.0` works with `torch>=2.6` (to be confirmed on the first GPU run; if it does not, move to a newer `transformers` and re-pin). |

## Residual risk (be explicit)

* `weights_only=True` with `torch>=2.6` removes the known pickle code-execution paths but is still a pickle parser. The strongest option is to convert the verified checkpoint to **safetensors** once, in a throw-away sandbox, record that file's hash as the new pin, and load only that. Not done: it needs the real file.
* A checksum proves the file is the one **you pinned**, not that it is benign. The pin step (`scripts/pin_triposr_weights.py`) therefore also cross-checks the Hub-reported LFS hash, records the Hub licence tag, and requires a human to review the diff before committing.
* Config/class allow-listing relies on the `tsr` checkout being the audited commit (pinned in the Dockerfile; verify `git -C TripoSR rev-parse HEAD`).
* `tsr` itself is third-party code executing in the Studio process; run the AI image with the least privilege available (non-root user is already the default; add `--read-only`/seccomp on your host if possible).
* Dependencies compiled from git (`torchmcubes`) are fetched unpinned by `requirements-triposr.txt`; pin a commit when you first build it.

## What the tests prove (and do not)

`tests/test_weights_security.py` uses minimal stand-ins for torch/tsr/omegaconf that **record call order and arguments**. They prove: files are verified before any parse; `weights_only=True` is passed; tampering of the checkpoint, config or aux file prevents deserialisation; unpinned downloads and foreign repos are refused; an incomplete lock keeps the engine closed. They prove **nothing** about model quality or that inference runs.
