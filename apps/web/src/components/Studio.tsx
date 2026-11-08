"use client";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useJob } from "@/hooks/useJob";
import { useSession } from "@/hooks/useSession";
import { ApiError, createApi, type Asset, type GenerationRequest, type Me } from "@/lib/api";
import { readEnv } from "@/lib/env";
import { isTerminal, newIdempotencyKey } from "@/lib/jobs";
import { supabase } from "@/lib/supabase";
import JobProgress from "./JobProgress";
import Library from "./Library";
import UploadPanel from "./UploadPanel";

const Viewer = dynamic(() => import("./Viewer"), { ssr: false, loading: () => <div className="viewer"><div className="empty">Loading the viewer…</div></div> });

const CATEGORIES = [["car", "Car"], ["suv", "SUV"], ["pickup", "Pickup"], ["bus", "Bus"], ["light_truck", "Light truck"], ["medium_truck", "Medium truck"], ["heavy_truck", "Heavy truck"], ["building", "Building"], ["prop", "Prop"], ["furniture", "Furniture"], ["household_object", "Household object"], ["other", "Other"]] as const;

function describe(e: unknown): string {
  if (e instanceof ApiError) return e.recommendedAction ? `${e.message} ${e.recommendedAction}` : e.message;
  return "Something went wrong. Please try again.";
}

export default function Studio() {
  const router = useRouter();
  const session = useSession();
  const env = readEnv();
  const api = useMemo(
    () => (env.ok ? createApi({ baseUrl: env.env.apiUrl, getToken: async () => (await supabase().auth.getSession()).data.session?.access_token ?? null }) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [env.ok],
  );

  const [me, setMe] = useState<Me | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("car");
  const [preset, setPreset] = useState<"DRAFT" | "STANDARD" | "HIGH">("STANDARD");
  const [faces, setFaces] = useState(24000);
  const [texture, setTexture] = useState<512 | 1024 | 2048>(1024);
  const [length, setLength] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [view, setView] = useState<{ assetId: string; url: string; filename: string } | null>(null);
  const keyRef = useRef<{ sig: string; key: string } | null>(null);

  useEffect(() => { if (session === null) router.replace("/login"); }, [session, router]);

  const refresh = useCallback(async () => {
    if (!api) return;
    try {
      const [m, a] = await Promise.all([api.me(), api.listAssets()]);
      setMe(m);
      setAssets(a.items);
    } catch (e) {
      setProblem(describe(e));
    }
  }, [api]);
  useEffect(() => { if (session && api) void refresh(); }, [session, api, refresh]);

  const open = useCallback(async (assetId: string, version: number) => {
    if (!api) return;
    try {
      const f = await api.fileUrl(assetId, version, "glb");
      setView({ assetId, url: f.url, filename: f.filename });
    } catch (e) {
      setProblem(describe(e));
    }
  }, [api]);

  const { job, error: pollError } = useJob(api, jobId);
  const openedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!job || !isTerminal(job.state)) return;
    void refresh();
    if (job.state === "completed" && job.result && openedFor.current !== job.job_id) {
      openedFor.current = job.job_id;
      void open(job.result.asset_id, 1);
    }
  }, [job, refresh, open]);

  if (!env.ok) return <main className="shell"><div className="panel err"><h1>Not configured</h1><p>{env.problems.join(" ")}</p></div></main>;
  if (session === undefined) return <main className="shell"><p className="note">Loading…</p></main>;
  if (session === null || !api) return null;

  const active = !!job && !isTerminal(job.state);
  const price = me?.price.image_to_3d ?? 0;
  const canGenerate = !!file && !busy && !active && (me ? me.credits.balance >= price : true);

  async function generate() {
    if (!file || !api) return;
    setBusy(true);
    setProblem(null);
    try {
      const up = await api.uploadImage(file);
      const lenN = length.trim() === "" ? undefined : Number(length);
      if (lenN !== undefined && !(lenN > 0 && lenN <= 60)) throw new ApiError(422, "invalid_length", "Length must be between 0 and 60 metres.");
      const body: GenerationRequest = {
        kind: "image_to_3d",
        upload_id: up.upload_id,
        name: (name.trim() || file.name.replace(/\.[^.]+$/, "") || "Untitled").slice(0, 120),
        settings: { preset, category, target_faces: faces, texture_resolution: texture, ...(lenN !== undefined ? { length_m: lenN } : {}) },
      };
      const sig = JSON.stringify(body);
      if (keyRef.current?.sig !== sig) keyRef.current = { sig, key: newIdempotencyKey() }; // a retry of the SAME request reuses its key: no double charge
      const created = await api.createGeneration(body, keyRef.current.key);
      keyRef.current = null;
      openedFor.current = null;
      setView(null);
      setJobId(created.job_id);
      void refresh();
    } catch (e) {
      setProblem(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!jobId || !api) return;
    try { await api.cancelGeneration(jobId); } catch (e) { setProblem(describe(e)); }
  }

  return (
    <main className="shell">
      <header className="top">
        <div className="brand">ARO 3D AI Studio</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {me && <span className="pill" title="Credits you can spend now">{me.credits.balance} credits{me.credits.reserved ? ` (${me.credits.reserved} in use)` : ""}</span>}
          {me?.email && <span className="note">{me.email}</span>}
          <button type="button" onClick={() => void supabase().auth.signOut().then(() => router.replace("/login"))}>Sign out</button>
        </div>
      </header>

      <div className="grid">
        <div className="stack">
          <section className="panel stack" aria-label="New model">
            <h2>New model</h2>
            <UploadPanel maxMb={me?.limits.max_upload_mb ?? 10} disabled={busy || active} onFile={(f) => { setFile(f); if (f && !name) setName(f.name.replace(/\.[^.]+$/, "")); }} />
            <div><label htmlFor="name">Name</label><input id="name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></div>
            <div className="row">
              <div><label htmlFor="cat">Category</label><select id="cat" value={category} onChange={(e) => setCategory(e.target.value)}>{CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
              <div><label htmlFor="preset">Quality</label><select id="preset" value={preset} onChange={(e) => setPreset(e.target.value as typeof preset)}><option value="DRAFT">Draft (fastest)</option><option value="STANDARD">Standard</option><option value="HIGH">High (slowest)</option></select></div>
            </div>
            <div className="row">
              <div><label htmlFor="faces">Triangle budget</label><input id="faces" type="number" min={2000} max={25000} step={1000} value={faces} onChange={(e) => setFaces(Math.max(2000, Math.min(25000, Number(e.target.value) || 24000)))} /></div>
              <div><label htmlFor="tex">Texture size</label><select id="tex" value={texture} onChange={(e) => setTexture(Number(e.target.value) as typeof texture)}><option value={512}>512</option><option value={1024}>1024</option><option value={2048}>2048</option></select></div>
            </div>
            <div><label htmlFor="len">Real length in metres (optional, sets true scale)</label><input id="len" inputMode="decimal" placeholder="e.g. 4.5" value={length} onChange={(e) => setLength(e.target.value)} /></div>
            {problem && <div className="err" role="alert">{problem}</div>}
            <button className="primary" type="button" disabled={!canGenerate} onClick={() => void generate()}>{busy ? "Starting…" : `Generate${price ? ` · ${price} credits` : ""}`}</button>
            {me && me.credits.balance < price && <p className="note">You need {price} credits to generate. You have {me.credits.balance}.</p>}
            <p className="note">Credits are held while the model is made and returned if it fails.</p>
          </section>
          {job && <JobProgress job={job} error={pollError} onCancel={() => void cancel()} />}
        </div>

        <div className="stack">
          <Viewer url={view?.url ?? null} filename={view?.filename} />
          <section className="panel" aria-label="Library">
            <h2>Your library</h2>
            <Library api={api} assets={assets} selectedId={view?.assetId ?? null} onOpen={(a) => void open(a.asset_id, a.current_version ?? 1)} />
          </section>
        </div>
      </div>
    </main>
  );
}
