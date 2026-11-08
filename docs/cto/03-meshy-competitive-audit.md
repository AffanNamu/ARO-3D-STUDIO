# 03 · Meshy AI competitive audit (Phase 1)

Audit date: 2026-11-08 · Benchmark: <https://www.meshy.ai/> · Status: **PASS for the documentation and API audit; NOT STARTED for the product-experience audit and for any quality comparison.**

## What was read, and what was not

This version replaces a first draft that relied on search summaries. After the sandbox network was widened (owner-approved), the following were **read at the source on 2026-11-08** (evidence grade **G**):

* Meshy's published **OpenAPI 3.1 file** (`docs.meshy.ai/openapi.yaml`, 88 operations over 54 paths, 14 tags);
* the API documentation text (`docs.meshy.ai/llms-full.txt`, 1.2 MB: pricing, models, task lifecycle, processing times, rate limits, retention, rigging, animation, plug-ins, changelog, deprecations);
* the animation library reference table;
* the public pricing page (`www.meshy.ai/pricing`).

**Not done:** the web app itself (Workspace, 3D Agent, mobile app, community library) was not used; no Meshy account was accessed; no model output was generated or judged; the terms of service were not read beyond the licence lines quoted below; Creative Lab and Text-to-Motion are documented outside the OpenAPI file and were read only through the pricing and docs text. **Nothing here is a quality comparison.**

## 1. API surface (G)

Tags: Text to 3D, Image to 3D, Multi-Image to 3D, Retexture, Remesh, Convert, Resize, UV Unwrap, Rigging, Animation, Text to Image, Image to Image, 3D Print, Account. Every task endpoint has create, list, retrieve, delete and a **server-sent-events stream**. Account endpoints: `GET /v1/balance`, `GET /v1/usage/tasks`. Base URL `https://api.meshy.ai/openapi`; bearer API keys; the docs warn not to call it from browser JavaScript. Tasks run asynchronously: `PENDING`, `IN_PROGRESS`, `SUCCEEDED`, `FAILED` (credits refunded on failure; `CANCELED` only for Creative Lab); results by polling, SSE or webhook. **Generated assets are retained for 3 days** on non-Enterprise plans.

## 2. Generation (G)

| Endpoint | Key inputs |
|---|---|
| `POST /v2/text-to-3d` | `mode` preview (geometry) or refine (texture); `prompt` up to 800 characters, `negative_prompt`, `texture_prompt`, `texture_image_url`, `art_style` (realistic), `seed`, `pose_mode` (a-pose, t-pose), `texture_resolution` 2k/4k/8k, `geometry_resolution`, `moderation` |
| `POST /v1/image-to-3d` | `image_url` (URL or data URI) or `input_task_id`; `ai_model`, `model_type` (standard or smart-topology), `topology` (triangle or quad), `target_polycount` 100 to 300,000, `should_texture`, `enable_pbr`, `texture_model`, `texture_resolution`, `geometry_resolution` standard/2k/4k, `image_enhancement`, `remove_lighting`, `pose_mode`, `auto_size`, `origin_at`, `target_formats` (no `seed` parameter here; only text-to-3D has one) |
| `POST /v1/multi-image-to-3d` | **1 to 4** images (a third-party claim of 8 is wrong), same controls; 4K geometry not supported here |
| `POST /v1/retexture` | a GLB (`model_url`) or earlier task; exactly one style source: `text_style_prompt`, `image_style_url` or 1 to 4 `multiview_image_urls`; `art_style` realistic/cartoon; `enable_original_uv`; `enable_pbr`; 2K/4K/8K |
| `POST /v1/remesh` | topology triangle or quad, `target_polycount`, resize options, `convert_format_only` |
| `POST /v1/uv-unwrap`, `/v1/resize`, `/v1/convert` | UV layout for a GLB (high-poly must be remeshed first); real-world size by height, longest side or `auto_size`; format conversion |
| `POST /v1/rigging` | biped or quadruped skeleton, `height_meters`; **models above 380,000 triangles are rejected** |
| `POST /v1/animations` | library `action_id`, or up to 10 `action_ids` merged into one file (one clip each); or a generated motion clip |
| Text-to-image, image-to-image | concept images, including multi-view images "optimized for 3D creation" |
| 3D Print | printability analysis, repair, auto split, multi-colour print, relief (photo to bas-relief GLB/STL plus a 16-bit depth map, added 5 Nov 2026) |

Outputs (G): model formats `glb, fbx, gltf, usdz, obj, mtl, vox, blend, stl, 3mf` and `pre_remeshed_glb`; texture maps `base_color, metallic, roughness, normal, emission, metallic_roughness`; thumbnails; `consumed_credits` on every task. Rigged output as FBX or GLB (skeleton templates, default Mixamo, for humanoids).

**Animation library:** action IDs run from 0 to 696 (about 655 rows parsed from the reference table; categories DailyActions, WalkAndRun, Fighting, BodyMovements, Dancing, Idle). Third-party figures of "500+" or "678" are inconsistent with the official table.

## 3. Models (G, docs.meshy.ai/api/models.md and deprecations page)

Geometry: `meshy-7.1` (`latest`; dense detail, 890,226 faces in the doc example; `geometry_resolution` 2k or 4k up to about 10 million faces and 490 MB), `meshy-6`, `meshy-6-lite` (about 30,000 faces, quarter of the cost), Smart Topology `meshy-t2` and `meshy-t2.5` (clean triangle meshes at a set face count; t2 up to 15,000, t2.5 up to 30,000). Texture models: `meshy-7` (PBR to 8K, 1 to 4 reference images), `meshy-n1` (2K base colour, stylised and game assets), `meshy-6` (adds an emission map), `meshy-6-lite`. Lifecycle: `meshy-5` **retired** 10 Oct 2026, `meshy-7` deprecated 18 Sep 2026, `meshy-t1` and `lowpoly` retire 30 Nov 2026. Meshy's own guidance maps projects to model pairs (hero asset: 7.1 + 7; game character: t2.5 + n1; many props: t2 + n1; drafts: 6-lite).

## 4. Pricing, speed and limits (G)

Credits per request (meshy-7.1 / meshy-6; lite and Smart Topology in brackets): Text-to-3D preview 20 [5]; Image-to-3D mesh only 20 [5], with 2K textures 30 [15], 8K 35 [20]; Ultra geometry +5; text refine and retexture 10 (15 at 8K); remesh 5; UV unwrap 5; convert 1; resize 1; rigging 5; animation 3 per action; text-to-motion 10 (prime) or 3 (swift); text-to-image 3 to 9; 3D print 10 to 20 (analysis free).

Plans (`www.meshy.ai/pricing`): Free $0 (100 credits per month, 1 concurrent task, models under CC BY 4.0); Pro $20 per month (1,000 credits, 10 concurrent tasks); Premium $40 (3,000 credits, 30 concurrent); Ultra $100 (8,000 credits, 100 concurrent); Studio and Enterprise for teams. All paid plans: private licence with commercial use and output ownership. Credits reset monthly; purchased credits do not expire; **failed generations are not charged**.

Derived price (arithmetic on the figures above): one credit is $0.02 on Pro, about $0.0133 on Premium and $0.0125 on Ultra, so a textured meshy-7.1 image-to-3D task (30 credits) costs about **$0.60 on Pro, $0.40 on Premium, $0.375 on Ultra**. The web-app credit table differs slightly from the API table (for example 25 credits for Ultra 2K image-to-3D).

Median task times, September 2026 production traffic (G): image-to-3D meshy-7.1 mesh only 75 s, with 2K textures 2 min, 8K 3.5 min; meshy-6 2 to 4 min; meshy-t2 4 s mesh only and 60 s textured; PBR adds 30 to 60 s; text-to-3D preview 75 s and refine 80 s; retexture 55 s (2K) to 2.5 min (8K); remesh 2 min; UV unwrap 35 s; rigging 40 s; animation 15 s; convert 7 s.

Limits: 20 requests per second on every plan (Enterprise 100); concurrent tasks Pro 10, Premium 30, Ultra 100, Studio 60; higher plans start sooner; HTTP 429 with `Retry-After`.

## 5. Ecosystem (G)

Official plug-ins and a "DCC Bridge" for Blender, Unreal Engine, Unity, Maya, Godot and 3ds Max; an MCP server for AI agents; an API playground; a conversational "3D Agent" on paid plans; a mobile app; a community model library; Creative Lab generators for physical products (keychains, figures, lamps and others). Meshy ships changes **every few days**: the changelog has entries dated 26 Oct, 30 Oct, 2 Nov, 3 Nov and 5 Nov 2026, including a new model-pairing parameter, a new API and model retirements.

## 6. Corrections to the first draft

| First draft (search summary) | Official source says |
|---|---|
| Multi-image: 1 to 4 (official) or 2 to 8 (third party) | 1 to 4 only |
| Animation library "500+", "678" or "696" | IDs 0 to 696; about 655 parsed rows |
| Remesh cost unknown | 5 credits |
| Rigging and animation prices unknown | rigging 5; animation 3 per action; text-to-motion 3 or 10 |
| Meshy 7 "released 10 Aug 2026" (blog) | deprecation page: `meshy-7` deprecated 18 Sep 2026, `meshy-7.1` active, `latest` is 7.1; release dates not stated there |
| Plans unsettled | Free, Pro $20, Premium $40, Ultra $100 as read on the pricing page |

## 7. What this means for ARO

1. **The bar is wide and moving.** Meshy covers generation, retexture, remesh, UV, rigging, animation, 3D-print repair, plug-ins and an API; models are replaced within months. Matching the breadth needs a staged plan; matching the pace needs a small number of well-chosen model providers behind one contract (ADR-5).
2. **Cost to beat:** about $0.60 per textured generation on Pro, $0.375 on Ultra. ARO's estimated cost per successful job is far lower (see `04-architecture.md`), but cost is not the product.
3. **Speed to match:** about 2 to 3 minutes median for a textured image-to-3D. ARO's GPU step may be seconds but the CPU preparation measured about 100 to 150 s; both are on the same order.
4. **Credit rules to copy:** failed jobs refunded, credits reserved then captured, balance and per-task usage endpoints, per-plan concurrency.
5. **Retention rule to decide:** Meshy keeps outputs 3 days on non-Enterprise plans; ARO must choose its own policy (matrix H10).
6. **Licence posture to decide:** Meshy gives Free-plan outputs CC BY 4.0 and paid plans a private licence; ARO has not chosen.
7. **Where ARO can differentiate (hypotheses):** automatic LOD0-3 and collision meshes, a 50-rule production validation report, a Unity package with a verifier, Blender-verified FBX/USD, per-version provenance saying which steps were AI. Meshy's spec has no LOD or collision endpoint; that does not prove its web app lacks them.

## 8. Sources (all read on 2026-11-08)

[OpenAPI](https://docs.meshy.ai/openapi.yaml) · [API pricing](https://docs.meshy.ai/api/pricing.md) · [Models](https://docs.meshy.ai/api/models.md) · [Deprecations](https://docs.meshy.ai/api/deprecations.md) · [Changelog](https://docs.meshy.ai/api/changelog.md) · [Full docs text](https://docs.meshy.ai/llms-full.txt) · [Animation library](https://docs.meshy.ai/en/api/animation-library) · [Pricing page](https://www.meshy.ai/pricing).

## 9. To finish the audit

Use the web app on the owner's account (the owner must do this; credentials must not be shared) to record: the Workspace tools and editing features, the 3D Agent flow, mobile capture, the community library and its licence terms, and the terms of service for generated content. Then run the benchmark inputs (see `06-roadmap.md`) and record credits, time and outputs.
