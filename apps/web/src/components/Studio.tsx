"use client";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useJob } from "@/hooks/useJob";
import { useSession } from "@/hooks/useSession";
import { createApi, describeError, type Asset, type AssetDetail, type GenerationRequest, type Job, type Me, type Preset } from "@/lib/api";
import { readEnv } from "@/lib/env";
import { isTerminal, newIdempotencyKey } from "@/lib/jobs";
import { randomSeed } from "@/lib/model";
import { supabase } from "@/lib/supabase";
import Activity from "./Activity";
import AssetPanel from "./AssetPanel";
import CreatePanel, { type CreateInput } from "./CreatePanel";
import CreditsPanel from "./CreditsPanel";
import JobProgress from "./JobProgress";
import Library from "./Library";

const Viewer = dynamic(() => import("./Viewer"), {
  ssr: false,
  loading: () => (
    <div className="viewer">
      <div className="viewer-loading">Loading the viewer…</div>
    </div>
  ),
});

type SideTab = "models" | "activity" | "credits";

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
  const [query, setQuery] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [glbUrl, setGlbUrl] = useState<string | null>(null);
  const [tab, setTab] = useState<SideTab>("models");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [tick, setTick] = useState(0); // bumps when credits may have changed
  const keyRef = useRef<{ sig: string; key: string } | null>(null);
  const booted = useRef(false);
  const openedFor = useRef<string | null>(null);
  const queryRef = useRef("");

  useEffect(() => {
    if (session === null) router.replace("/login");
  }, [session, router]);

  const loadAssets = useCallback(
    async (q: string) => {
      if (!api) return [];
      const a = await api.listAssets(q.trim() || undefined);
      if (queryRef.current === q) setAssets(a.items);
      return a.items;
    },
    [api],
  );

  const refresh = useCallback(async () => {
    if (!api) return;
    try {
      const [m, j] = await Promise.all([api.me(), api.listGenerations(20)]);
      setMe(m);
      setJobs(j.items);
      setTick((t) => t + 1);
      await loadAssets(queryRef.current);
    } catch (e) {
      setProblem(describeError(e));
    }
  }, [api, loadAssets]);

  const openAsset = useCallback(
    async (assetId: string) => {
      if (!api) return;
      try {
        const d = await api.getAsset(assetId);
        const f = await api.fileUrl(assetId, d.current_version ?? 1, "glb");
        setDetail(d);
        setGlbUrl(f.url);
      } catch (e) {
        setProblem(describeError(e));
      }
    },
    [api],
  );

  // first load: resume a running generation if there is one, otherwise show the newest model
  useEffect(() => {
    if (!session || !api || booted.current) return;
    booted.current = true;
    void (async () => {
      try {
        const [m, j, a] = await Promise.all([api.me(), api.listGenerations(20), api.listAssets()]);
        setMe(m);
        setJobs(j.items);
        setAssets(a.items);
        const running = j.items.find((x) => !isTerminal(x.state));
        if (running) setJobId(running.job_id);
        const newest = a.items[0];
        if (newest) await openAsset(newest.asset_id);
      } catch (e) {
        setProblem(describeError(e));
      }
    })();
  }, [session, api, openAsset]);

  // search as you type
  useEffect(() => {
    queryRef.current = query;
    if (!booted.current) return;
    const t = setTimeout(() => void loadAssets(query).catch(() => undefined), 250);
    return () => clearTimeout(t);
  }, [query, loadAssets]);

  const { job, error: pollError } = useJob(api, jobId);
  useEffect(() => {
    if (!job || !isTerminal(job.state)) return;
    void refresh();
    if (job.state === "completed" && job.result && openedFor.current !== job.job_id) {
      openedFor.current = job.job_id;
      setTab("models");
      void openAsset(job.result.asset_id);
    }
  }, [job, refresh, openAsset]);

  if (!env.ok)
    return (
      <main className="center">
        <div className="panel err">
          <h1>Not configured</h1>
          <p>{env.problems.join(" ")}</p>
        </div>
      </main>
    );
  if (session === undefined)
    return (
      <main className="center">
        <p className="muted">Loading…</p>
      </main>
    );
  if (session === null || !api) return null;

  const running = jobs.filter((j) => !isTerminal(j.state)).length;
  const price = me?.price.image_to_3d ?? 0;
  const atLimit = !!me && running >= me.limits.max_active_jobs;
  const blocked = atLimit ? `You already have ${running} generation${running === 1 ? "" : "s"} running. Wait for one to finish, or cancel it.` : null;
  const canGenerate = !!me && !busy && !atLimit && me.credits.balance >= price && me.engines.length > 0;

  async function submit(body: GenerationRequest) {
    if (!api) return;
    const sig = JSON.stringify(body);
    if (keyRef.current?.sig !== sig) keyRef.current = { sig, key: newIdempotencyKey() }; // a retry of the SAME request reuses its key: no double charge
    const created = await api.createGeneration(body, keyRef.current.key);
    keyRef.current = null;
    openedFor.current = null;
    setJobId(created.job_id);
    setTab("activity");
    void refresh();
  }

  async function generate(input: CreateInput) {
    if (!api) return;
    setBusy(true);
    setProblem(null);
    try {
      const up = await api.uploadImage(input.file);
      await submit({
        kind: "image_to_3d",
        upload_id: up.upload_id,
        name: input.name.slice(0, 120),
        engine: input.engine,
        settings: { preset: input.preset, category: input.category, target_faces: input.faces, texture_resolution: input.texture, ...(input.lengthM !== undefined ? { length_m: input.lengthM } : {}) },
      });
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  async function variation(d: AssetDetail) {
    const uploadId = d.metadata.upload_id;
    const s = d.model?.settings;
    const engine = d.model?.engine && me?.engines.includes(d.model.engine) ? d.model.engine : me?.engines[0];
    if (!uploadId || !s || !engine) return;
    setBusy(true);
    setProblem(null);
    try {
      const tex = s.texture_resolution === 512 || s.texture_resolution === 2048 ? s.texture_resolution : 1024;
      await submit({
        kind: "image_to_3d",
        upload_id: uploadId,
        name: `${d.name} (variation)`.slice(0, 120),
        engine,
        settings: {
          preset: (s.preset as Preset | undefined) ?? "STANDARD",
          category: s.category ?? d.category,
          target_faces: s.target_faces ?? 24000,
          texture_resolution: tex,
          ...(s.length_m ? { length_m: s.length_m } : {}),
          seed: randomSeed(),
        },
      });
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!jobId || !api) return;
    try {
      await api.cancelGeneration(jobId);
    } catch (e) {
      setProblem(describeError(e));
    }
  }

  function openJob(j: Job) {
    if (!isTerminal(j.state)) setJobId(j.job_id);
    else if (j.result) void openAsset(j.result.asset_id);
  }

  const testMode = !!me?.engines.includes("fake");
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          ARO 3D AI Studio
        </div>
        <div className="topbar-right">
          {me && (
            <button type="button" className="pill" onClick={() => setTab("credits")} title="Credits you can spend now">
              <strong>{me.credits.balance}</strong> credits{me.credits.reserved ? ` · ${me.credits.reserved} in use` : ""}
            </button>
          )}
          {me?.email && <span className="muted email">{me.email}</span>}
          <button type="button" onClick={() => void supabase().auth.signOut().then(() => router.replace("/login"))}>
            Sign out
          </button>
        </div>
      </header>
      {testMode && (
        <div className="banner" role="status">
          Development mode: the model on this server is a test double, not AI. Every image produces the same placeholder shape.
        </div>
      )}

      <div className="workspace">
        <aside className="col-left">
          <CreatePanel me={me} busy={busy} blocked={blocked} problem={problem} onGenerate={(i) => void generate(i)} />
          {job && <JobProgress job={job} error={pollError} onCancel={() => void cancel()} onDismiss={() => setJobId(null)} />}
        </aside>

        <main className="col-main">
          <Viewer url={glbUrl} name={detail?.name} testOutput={detail?.model?.ai_inference === false} />
          {detail && (
            <AssetPanel
              api={api}
              detail={detail}
              price={price}
              canGenerate={canGenerate}
              formats={me?.limits.export_formats ?? []}
              onRenamed={(d) => {
                setDetail(d);
                void loadAssets(queryRef.current);
              }}
              onDeleted={(assetId) => {
                setDetail(null);
                setGlbUrl(null);
                setAssets((list) => list.filter((a) => a.asset_id !== assetId));
              }}
              onVariation={(d) => void variation(d)}
            />
          )}
        </main>

        <aside className="col-right panel">
          <div className="tabs" role="tablist" aria-label="Your work">
            {(["models", "activity", "credits"] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
                {t === "models" ? "My models" : t === "activity" ? "Activity" : "Credits"}
              </button>
            ))}
          </div>
          {tab === "models" && <Library api={api} assets={assets} query={query} onQuery={setQuery} selectedId={detail?.asset_id ?? null} onOpen={(a) => void openAsset(a.asset_id)} />}
          {tab === "activity" && <Activity jobs={jobs} activeId={jobId} onOpen={openJob} />}
          {tab === "credits" && <CreditsPanel api={api} me={me} refreshKey={tick} />}
        </aside>
      </div>
    </div>
  );
}
