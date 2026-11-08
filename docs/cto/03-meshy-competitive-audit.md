# 03 · Meshy AI competitive audit (Phase 1)

Audit date: 2026-11-08 · Benchmark: <https://www.meshy.ai/> · Status: **PARTIAL**.

## Read this first: how reliable this audit is

The sandbox's network policy blocked `www.meshy.ai`, `docs.meshy.ai` and `help.meshy.ai` (HTTP 403 from the session proxy), and the request to widen the policy could not be shown to the owner (mobile app too old). **No Meshy page was opened by the audit.** Everything below comes from web-search summaries that cite Meshy's own documentation, plus third-party sites. Each claim carries a grade:

* **S**: a search summary quoting an official Meshy page (docs, help centre, pricing). Likely right; not read at source.
* **T**: a third-party site only. Treat as unverified; several conflict with the official pages.

No claim was tested by using the product. Nothing here is a benchmark result. The competitive matrix ([`competitive-matrix.md`](competitive-matrix.md)) carries the same grades per capability and a test prevents anything from being graded above S.

To finish the audit properly: allow `www.meshy.ai`, `docs.meshy.ai` and `help.meshy.ai` for a session (newer app or claude.ai on a computer), or paste/export the Meshy documentation pages named in section 9.

## 1. Product map

Meshy's documentation describes a **Workspace 3.0** organised into six modules: **Image, 3D Model, 3D Printing, Animate, Scene, Video** (S, `docs.meshy.ai/en`). The help centre lists four core generation capabilities, two of them beta, plus texture editing, an API, auto-resizing, customisable polygon settings and a **library of downloadable community models** (S, help article 9991738). I could not see which four are core.

## 2. Capabilities (what Meshy publicly offers)

| Capability | Evidence |
|---|---|
| Text-to-3D with a **preview** stage and a separate **refine/texture** stage | S: pricing and API pages list both and price them separately |
| Image-to-3D | S |
| Multi-image-to-3D: official changelog says **1 to 4** input images; a third-party guide says 2 to 8 (conflict) | S / T |
| Retexture an existing model (launched June 2025; 10 credits per task) | S: changelog and pricing |
| UV unwrap, text-to-image and image-to-image API tags | S: OpenAPI tag list |
| Remesh with a target polycount, triangle or quad topology | S for the parameters; remesh task deletion endpoints exist |
| Auto-rigging and animation (launched 10 June 2025); humanoid and quadruped scope and a motion library of several hundred clips (figures 500+, 678, 696 conflict) | S for launch; T for scope and size |
| 3D printing module; multi-colour print task (10 credits); STL and 3MF export | S |
| Exports: GLB, FBX, OBJ, STL, USDZ, 3MF | S |
| Integrations: official plug-ins and a "DCC Bridge" for Blender, Unity, Unreal Engine, Maya "and more"; an MCP server for AI agents | S (docs overview) |
| Asynchronous REST API with bearer API keys and a published OpenAPI specification | S |

Generation parameters seen on the Image-to-3D page (S): `ai_model`, `should_texture` (default true), `enable_pbr` (only with texturing, default false), `should_remesh` (default false for meshy-6, true for others), `topology` (`triangle` default, `quad`), `target_polycount`, `is_a_t_pose`, `pose_mode` (one example `a-pose`), `geometry_resolution` (`2k`); adaptive polycount levels 1 to 4 on the newest page. `symmetry_mode` was not found. Documentation versions disagree with each other on some of these.

## 3. Models and versions

* Meshy 6: preview 16 Oct 2025, general availability 18 Jan 2026 (S/T). `meshy-6-lite` is listed as active; `meshy-5` is deprecated (S, deprecations page).
* Meshy 7: released 10 Aug 2026, announced 12 Aug (T, one blog). `meshy-7` is **deprecated since 18 Sep 2026**; `meshy-7.1` is **active** and `latest` resolves to it (S, deprecations page). The Ultra mode parameter is deprecated and equals `geometry_resolution: "2k"` (S); a blog's "4K" description conflicts.
* Meshy N1, T1, T2 appear in pricing notes (S) without enough context to describe them.

## 4. Pricing and credits (S unless marked)

* Plans: Free (100 credits per month), Pro ($20 per month, 1,000 credits), Studio ($60), Enterprise (custom) on the pricing page. The web-app documentation lists a different individual lineup (Free, Pro, Premium, Ultra) with Studio and Enterprise for teams; third-party sites give other numbers. Treat plan prices as unsettled.
* Credits reset monthly; purchased and permanent credits do not expire. **Failed generations are not charged; cancelled tasks are refunded.**
* **Commercial use is allowed on paid plans; models made on the Free plan are licensed CC BY 4.0.**
* Credit costs: Text-to-3D preview 20 credits (Meshy-6 and low-poly) or 5 (other models); refine/texture 10 (15 at 8K); Image-to-3D with Meshy-6 20 without texture and 30 with; other models 5 and 15; retexture 10; multi-colour print 10. Rigging, animation and standalone remesh costs were not found.
* Derived (arithmetic on the S figures above, not a Meshy statement): at the Pro rate, one credit is about $0.02, so a textured Meshy-6 image-to-3D task costs roughly $0.60. ARO's all-in cost per successful generation therefore has to be comfortably below that to compete on price. A third party quotes API base costs from about $0.88 per generation (T).

## 5. Where Meshy is thin or contested (T, use with care)

A critical review calls the rigging "very basic" with no facial rigging; accuracy figures for multi-view input (80 to 90 percent) are unsourced. None of this is used as a requirement.

## 6. What this means for ARO (decisions already supported by the evidence)

1. **Credit rules to match:** failed generations free, cancelled refunded, reserve then capture. Already in the design (`04-architecture.md`, `schema.sql`).
2. **Two-stage text-to-3D (preview then refine)** is Meshy's own structure; our design (text to image, then image to 3D) fits it and lets users stop after the cheap stage.
3. **Texture as a separate, priced step** is how the market sells it; our job kinds separate `retexture` from generation.
4. **Parameters to expose first:** target polycount, topology (triangle now, quad later), PBR on/off, pose for characters, model/quality tier.
5. **Free-tier output licence (CC BY 4.0)** is a business decision for ARO to make explicitly; it is not copied by default.
6. **Not yet decidable from evidence:** exact motion-library size, plug-in capabilities, Scene and Video module scope, rigging quality. These stay "Not investigated" in the matrix.

## 7. Where ARO can differentiate (hypotheses, not claims)

LOD0-3 and collision meshes generated automatically, a 50-rule production validation report, a Unity package with a batch-mode verifier, Blender-verified FBX/USD exports and per-version provenance that says which steps were AI and which were conventional. I found no mention of these in the Meshy sources searched, which does not prove Meshy lacks them.

## 8. Sources

Official pages named by search summaries (not opened):
[docs overview](https://docs.meshy.ai/en) ·
[API changelog](https://docs.meshy.ai/api/changelog) ·
[OpenAPI spec](https://docs.meshy.ai/openapi.yaml) ·
[Image-to-3D API](https://docs.meshy.ai/api/image-to-3d.md) ·
[API pricing](https://docs.meshy.ai/en/api/pricing) ·
[web-app pricing](https://docs.meshy.ai/en/webapp/pricing) ·
[deprecations](https://docs.meshy.ai/de/api/deprecations) ·
[help: features](https://help.meshy.ai/en/articles/9991738-what-features-does-meshy-have) ·
[help: workspace](https://help.meshy.ai/en/articles/12618267-meshy-workspace-features-and-navigation) ·
[help: plans](https://help.meshy.ai/en/articles/12062933-what-are-your-prices-and-plans-offered-and-do-you-have-monthly-annual-plans).

Third-party pages were consulted only where marked T and are not cited as authority.

## 9. To complete this audit (owner or a session with network access)

Read in full: the OpenAPI spec (parameters for every endpoint), the pricing table (rigging, animation, remesh costs), the changelog, the Workspace 3.0 help article, the plug-in pages, and the terms of service for generated-content licensing. Then create a Meshy account and record, for the benchmark, the model version, settings, credits spent and time for each test input (see `06-roadmap.md`, benchmark protocol).
