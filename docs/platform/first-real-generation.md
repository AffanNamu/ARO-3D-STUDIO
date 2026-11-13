# First real generation, then ARO vs Meshy: the owner's checklist

Written 2026-11-13. Do the parts in order; each ends with a check that must say PASS before you move on. Nothing here asks you to share a
password or key with anyone: secrets go only into your private env file. What you send back is always safe output (no secrets, no URLs).

| Part | What it proves | Time | Cost |
|---|---|---|---|
| A. Your computer | the tools run | 15 min | $0 |
| B. Licence decision (testing) | you may run TripoSG | 15 min reading | $0 |
| C. Cloudflare R2 | files can be stored | 15 min | $0 (free tier; Cloudflare may ask for a card to enable R2) |
| D. RunPod endpoint | the GPU worker image builds and answers | 30-90 min (mostly waiting for the build) | small: build and image storage per RunPod's page |
| E. **First real generation** | **a real AI model made a validated 3D model** | 10-20 min | a few cents of GPU |
| F. The full app (Supabase + web) | the model appears in ARO 3D AI Studio | 45 min | $0 (Supabase free plan) |
| G. ARO vs Meshy | which is better, measured and judged blind | 30 min per image | a few cents per image (+ your Meshy credits) |

Google Cloud is not used anywhere here.

## A. Your computer (once)

Python 3.10+, git, and (for part F) Node.js 20+.

```
git clone https://github.com/AffanNamu/ARO-3D-STUDIO.git
cd ARO-3D-STUDIO
git checkout claude/zen-johnson-je3dzk
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-cloud.txt
python -m aro_cloud.doctor --help    # CHECK: prints usage
```

Create your private settings file OUTSIDE the repository: `~/aro-secrets/aro.env` (Windows: `C:\Users\<you>\aro-secrets\aro.env`).
One `NAME=value` per line. You fill it in as you go. On macOS/Linux: `chmod 600 ~/aro-secrets/aro.env`.

```
ARO_ENV=development
ARO_ALLOWED_ORIGINS=http://localhost:3000
```

## B. Licence decision for testing

TripoSG's weights are MIT, but its model code carries two Tencent licences (correction of 2026-11-13, details in
`docs/platform/runpod-worker.md`): not valid in the EU, UK or South Korea; Tencent's Acceptable Use Policy applies; its outputs may not be
used to improve other AI models; above 1M monthly users you need Tencent's licence. **Testing from Nigeria is inside their territory.**

Read: `https://github.com/VAST-AI-Research/TripoSG/blob/main/triposg/LICENSE`, the header of
`triposg/models/transformers/triposg_transformer.py` in the same repository, and the weights card `https://huggingface.co/VAST-AI/TripoSG`.
If you accept them for testing, you will set `ARO_VERIFIED_MODEL_LICENSES=triposg` on the RunPod endpoint (part D). Public launch is a
separate decision for later (block EU/UK/South Korea and add the Tencent terms to your terms of use, or switch engine).

## C. Cloudflare R2 (where the images and models are stored)

1. Cloudflare dashboard, **R2 Object Storage** (enable it; it may ask for a payment method; the free tier is 10 GB). Note your **Account ID**.
2. **Create bucket**: name `aro-dev`, location Automatic. Leave public access OFF (no r2.dev URL, no custom domain).
3. **Manage R2 API Tokens** > **Create API token**: permission **Object Read & Write**, apply to **specific bucket** `aro-dev`. Copy the
   **Access Key ID** and **Secret Access Key** (shown once) into your file, not anywhere else.
4. Bucket `aro-dev` > Settings > **CORS policy**:
   ```json
   [{"AllowedOrigins": ["http://localhost:3000"], "AllowedMethods": ["GET"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600}]
   ```
5. Add to your file:
   ```
   ARO_R2_ACCOUNT_ID=<account id>
   ARO_R2_BUCKET=aro-dev
   ARO_R2_ACCESS_KEY_ID=<access key id>
   ARO_R2_SECRET_ACCESS_KEY=<secret access key>
   ```
6. **CHECK:** `python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env r2 --origin http://localhost:3000` must end `RESULT: PASS`
   (write/read, signed download and upload links, bucket private, CORS). Send me the output.

## D. RunPod endpoint (the GPU)

1. Settings: two-factor authentication ON. Billing: auto-pay OFF; keep the balance you are willing to spend.
2. Settings > **API Keys** > create a key (read/write). Put it in your file as `ARO_RUNPOD_API_KEY=...`.
3. **Serverless** > **New Endpoint** > **Import Git Repository** > `AffanNamu/ARO-3D-STUDIO`, branch `claude/zen-johnson-je3dzk`,
   Dockerfile path `worker/runpod/Dockerfile` (build context: repository root).
4. Settings (names may differ slightly):

   | Setting | Value | Why |
   |---|---|---|
   | GPU | a 24 GB class (e.g. RTX A5000 / RTX 4090 / L4) | TripoSG needs ~8 GB; cheapest adequate tier |
   | Max workers | 1 | caps spending while testing |
   | Active (min) workers | 0 | nothing runs (or bills) while idle |
   | Idle timeout | 5-30 s | the GPU stops soon after a job |
   | Execution timeout | 900 s | hard stop per job |
   | Container disk | 30 GB | image + model weights |
   | FlashBoot | on (if offered) | faster cold starts |

5. Environment variables on the endpoint (none is secret):
   ```
   ARO_VERIFIED_MODEL_LICENSES=triposg
   ARO_WORKER_ALLOWED_HOSTS=<your account id>.r2.cloudflarestorage.com
   ```
   Do NOT set `ARO_WORKER_ALLOW_TEST_DOUBLE`, `ARO_WORKER_EVALUATION_MODE` or `ARO_WORKER_ALLOW_INSECURE_URLS`.
6. Wait for the build. **This image has never been built**: if the build fails, copy the build log's last ~80 lines to me and I fix it.
7. Copy the **Endpoint ID** into your file: `ARO_RUNPOD_ENDPOINT_ID=...`
8. **CHECK:** `python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env runpod` must end `RESULT: PASS`. It only calls the free health
   route; it starts no GPU.

## E. First real generation (the milestone)

```
python -m aro_cloud.smoke --env-file ~/aro-secrets/aro.env --image truck.png \
    --preset STANDARD --category heavy_truck --length 6.9 --timeout 2400 --keep --out evidence.json
```

* The first run includes a cold start: RunPod downloads the image (it is large: the model weights are inside) and loads the model. It can
  take 10-30 minutes; `--timeout 2400` allows for that. Later runs on a warm or cached worker take a few minutes at most.
* **CHECK:** the output ends with `"status": "PASS"` and `"ai_inference": true`. That is only printed when the worker reports a real
  (non-test-double) engine AND the downloaded model passed the output checks.
* `--keep` saves the model next to you as `smoke-<id>.glb`. Open it in any glTF viewer to look at it now; part F shows it in ARO.
* Send me `evidence.json` (no secrets, no URLs). If it says FAIL, send it anyway: the `reason` line tells me what to fix.

## F. The full app: generate and view inside ARO 3D AI Studio

1. **Supabase** (free plan): new project `aro-dev`, region near you, generated database password saved in your password manager.
   * Project URL and the anon/publishable key: Project Settings > API.
   * Connection string: **Connect** > **Session pooler** (port 5432); replace `[YOUR-PASSWORD]` locally.
   * Authentication > Providers > Email: on; for this test turn **Confirm email** off. URL configuration: Site URL `http://localhost:3000`.
   * Add to your file: `ARO_DATABASE_URL=...` and `ARO_SUPABASE_URL=https://<ref>.supabase.co`.
2. Create the tables and check:
   ```
   python -m aro_cloud.migrate --env-file ~/aro-secrets/aro.env
   python -m aro_cloud.doctor  --env-file ~/aro-secrets/aro.env supabase      # CHECK: RESULT: PASS
   ```
   If it says "no public keys", your project signs tokens with the legacy shared secret: add `ARO_SUPABASE_JWT_SECRET=` (Project Settings >
   API > JWT settings) to your file and run the check again. If it says the TLS certificate could not be verified, download the project's
   CA certificate (Project Settings > Database > SSL) and add `ARO_DATABASE_CA_FILE=<path>`.
3. Record your licence decision in the database (the platform refuses unverified models):
   ```
   python -m aro_cloud.admin --env-file ~/aro-secrets/aro.env verify-model --model triposg --verified-by "Your Name" \
       --weights-licence "MIT weights; Tencent Hunyuan DiT + FlashVDM community licences in the code" --attest-licence-read
   python -m aro_cloud.admin --env-file ~/aro-secrets/aro.env enable-model --model triposg
   ```
4. Add a local API token to your file (any 32+ random characters; generate with
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`): `ARO_INTERNAL_TOKEN=...`, and `ARO_RUN_RECONCILER_THREAD=1`.
5. **CHECK everything at once:** `python -m aro_cloud.doctor --env-file ~/aro-secrets/aro.env all` (RESULT: PASS).
6. Start the API (terminal 1): `python -m aro_cloud --env-file ~/aro-secrets/aro.env` (listens on http://127.0.0.1:8080 only).
7. Start the web app (terminal 2):
   ```
   cd apps/web
   cp .env.example .env.local     # set NEXT_PUBLIC_API_URL=http://localhost:8080 and the Supabase URL + anon key (public values)
   npm ci
   npm run dev                    # http://localhost:3000
   ```
8. Open http://localhost:3000, **create your account**, then give yourself credits (terminal 3):
   `python -m aro_cloud.admin --env-file ~/aro-secrets/aro.env grant-credits --email <your email> --amount 100 --note "owner test"`
9. Reload the page, upload the truck, Category **Heavy truck**, Quality **Standard**, Real length **6.9**, **Generate**.
   **CHECK:** the progress reaches Ready and the truck opens in the viewer (no "Test output" label). Send me a screenshot.

## G. ARO vs Meshy: measured, then judged blind

1. In Meshy, run **Image to 3D** with the SAME image. Use its current best model with texture ON, and write down the model name and
   settings. Download the **GLB**.
2. From the ARO app (or `smoke-<id>.glb` from part E), save ARO's GLB as `aro.glb`; save Meshy's as `meshy.glb`.
3. Compare:
   ```
   python -m aro_studio.quality.compare --reference truck.png --category heavy_truck \
       --model ARO=aro.glb --model Meshy=meshy.glb --out compare_truck --blind
   ```
4. Open `compare_truck/comparison.png` **before** `key.json`. Write down which model (A or B) is better for shape, for colours/texture
   and for game use, and why. Only then open `key.json`.
5. Send me `comparison.md`, `comparison.png` and your blind notes. Repeat with 3-5 more images (a car, a bus, a building) for a fair
   picture: one image is an anecdote.

What the numbers mean and do not mean is written at the bottom of `comparison.md`. Meshy's terms of use apply to its outputs: use them for
this comparison, not to train any model.

## What I need from you, and what I never need

Send: doctor outputs, `evidence.json`, build logs (last ~80 lines), screenshots, the `compare_*` files and your blind notes.
Never send: passwords, API keys, the database connection string, R2 secret keys, or signed URLs.
