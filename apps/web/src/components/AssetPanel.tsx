"use client";
import { useEffect, useState } from "react";
import { describeError, type Api, type AssetDetail } from "@/lib/api";
import { CHECK_LABELS, categoryLabel, engineLabel, formatBytes, formatSize } from "@/lib/model";

type Tab = "details" | "checks" | "download";

const DOWNLOADS: ReadonlyArray<{ id: string; label: string; note: string; kind: "file" | "export" }> = [
  { id: "glb", label: "GLB", note: "Game-ready: all detail levels + collision", kind: "file" },
  { id: "obj", label: "OBJ", note: "Zip with material and texture", kind: "export" },
  { id: "stl", label: "STL", note: "Geometry only, for 3D printing", kind: "export" },
  { id: "ply", label: "PLY", note: "Geometry with vertex colours", kind: "export" },
  { id: "raw_mesh", label: "Raw GLB", note: "The model's untouched output", kind: "file" },
];

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default function AssetPanel({
  api,
  detail,
  price,
  canGenerate,
  formats,
  onRenamed,
  onDeleted,
  onVariation,
}: {
  api: Api;
  detail: AssetDetail;
  price: number;
  canGenerate: boolean;
  formats: string[];
  onRenamed: (d: AssetDetail) => void;
  onDeleted: (assetId: string) => void;
  onVariation: (d: AssetDetail) => void;
}) {
  const [tab, setTab] = useState<Tab>("details");
  const [name, setName] = useState(detail.name);
  const [reference, setReference] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showIssues, setShowIssues] = useState(false);
  const m = detail.model;
  const uploadId = detail.metadata.upload_id ?? null;

  useEffect(() => {
    setName(detail.name);
    setProblem(null);
    setConfirmDelete(false);
    setShowIssues(false);
  }, [detail.asset_id, detail.name]);

  useEffect(() => {
    let live = true;
    setReference(null);
    if (uploadId)
      void api
        .uploadLink(uploadId)
        .then((l) => {
          if (live) setReference(l.url);
        })
        .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [api, uploadId]);

  async function rename() {
    const next = name.trim();
    if (!next || next === detail.name) {
      setName(detail.name);
      return;
    }
    setBusy("rename");
    try {
      onRenamed(await api.renameAsset(detail.asset_id, next));
    } catch (e) {
      setProblem(describeError(e));
      setName(detail.name);
    } finally {
      setBusy(null);
    }
  }

  async function download(id: string, kind: "file" | "export") {
    setBusy(id);
    setProblem(null);
    try {
      const version = m?.version ?? 1;
      const f = kind === "file" ? await api.fileUrl(detail.asset_id, version, id as "glb" | "raw_mesh") : await api.exportUrl(detail.asset_id, version, id);
      const a = document.createElement("a");
      a.href = f.url;
      a.download = f.filename;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("delete");
    try {
      await api.deleteAsset(detail.asset_id);
      onDeleted(detail.asset_id);
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setBusy(null);
    }
  }

  const checks = m?.checks ?? null;
  const available = DOWNLOADS.filter((d) => (d.kind === "export" ? formats.includes(d.id) : (m?.files ?? []).some((f) => f.role === d.id)));
  return (
    <section className="panel asset" aria-label="Model details">
      <header className="asset-head">
        <input
          className="title-input"
          aria-label="Model name"
          value={name}
          maxLength={120}
          disabled={busy === "rename"}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => void rename()}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setName(detail.name);
          }}
        />
        <div className="tabs" role="tablist" aria-label="Model sections">
          {(["details", "checks", "download"] as const).map((t) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {t === "details" ? "Details" : t === "checks" ? "Game-ready checks" : "Download"}
            </button>
          ))}
        </div>
      </header>
      {problem && (
        <div className="err" role="alert">
          {problem}
        </div>
      )}

      {tab === "details" && (
        <div className="asset-body">
          <dl className="facts">
            <Fact label="Category">{categoryLabel(detail.category)}</Fact>
            <Fact label="Made with">
              {engineLabel(m?.engine)}
              {m?.ai_inference === false && m.engine !== "fake" && <span className="tag warn">not AI</span>}
            </Fact>
            <Fact label="Quality">{m?.settings.preset ? m.settings.preset.charAt(0) + m.settings.preset.slice(1).toLowerCase() : "—"}</Fact>
            <Fact label="Triangles">{m?.triangles?.toLocaleString() ?? "—"}</Fact>
            <Fact label="Size (W × H × L)">{formatSize(m?.extents_m) ?? "—"}</Fact>
            <Fact label="Texture">{m?.has_uv ? `${m.settings.texture_resolution ?? "—"} px, UV mapped` : "None"}</Fact>
            <Fact label="Created">{detail.created_at ? new Date(detail.created_at).toLocaleString() : "—"}</Fact>
            <Fact label="File size">{formatBytes(m?.bytes)}</Fact>
          </dl>
          {reference && (
            <figure className="reference">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={reference} alt="The image this model was made from" />
              <figcaption>Reference image</figcaption>
            </figure>
          )}
          <div className="actions">
            <button type="button" disabled={!canGenerate || !uploadId} onClick={() => onVariation(detail)} title="Generate again from the same image with a different seed">
              Make a variation{price ? ` · ${price} credits` : ""}
            </button>
            {!confirmDelete ? (
              <button type="button" className="danger-ghost" onClick={() => setConfirmDelete(true)}>
                Delete
              </button>
            ) : (
              <>
                <button type="button" className="danger" disabled={busy === "delete"} onClick={() => void remove()}>
                  Delete this model
                </button>
                <button type="button" onClick={() => setConfirmDelete(false)}>
                  Keep it
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {tab === "checks" && (
        <div className="asset-body">
          {!checks ? (
            <p className="muted">No check report was recorded for this model.</p>
          ) : (
            <>
              <div className="score">
                <div className="score-num">{checks.overall != null ? `${Math.round(checks.overall)}%` : "—"}</div>
                <div>
                  <strong>{checks.status === "PRODUCTION_READY" || checks.status === "APPROVED" ? "Passed every automatic check" : "Needs review before it goes into a game"}</strong>
                  <p className="muted">
                    Checked automatically after generation: {checks.critical_failures ?? 0} critical and {checks.major_failures ?? 0} major issues.
                  </p>
                </div>
              </div>
              <ul className="bars">
                {checks.categories
                  .filter((c) => c.applicable !== false)
                  .map((c) => (
                    <li key={c.id}>
                      <span>{CHECK_LABELS[c.id] ?? c.id}</span>
                      <div className="bar" role="img" aria-label={`${CHECK_LABELS[c.id] ?? c.id}: ${Math.round(c.score ?? 0)} percent`}>
                        <i style={{ width: `${Math.max(0, Math.min(100, c.score ?? 0))}%` }} data-level={(c.score ?? 0) >= 90 ? "good" : (c.score ?? 0) >= 60 ? "mid" : "bad"} />
                      </div>
                      <b>{Math.round(c.score ?? 0)}%</b>
                    </li>
                  ))}
              </ul>
              {m && m.lods.length > 0 && (
                <p className="muted">
                  Detail levels: {m.lods.map((l) => `LOD${l.level} ${l.triangles.toLocaleString()}`).join(" · ")} triangles
                  {m.collision_triangles ? ` · collision mesh ${m.collision_triangles.toLocaleString()}` : ""}
                </p>
              )}
              {checks.problems.length > 0 && (
                <>
                  <button type="button" onClick={() => setShowIssues(!showIssues)} aria-expanded={showIssues}>
                    {showIssues ? "Hide" : "Show"} {checks.problems.length} issue{checks.problems.length === 1 ? "" : "s"}
                  </button>
                  {showIssues && (
                    <ul className="issues">
                      {checks.problems.map((p, i) => (
                        <li key={`${p.id ?? "x"}-${i}`}>
                          <span className={`tag ${p.severity === "critical" ? "bad" : p.status === "warning" ? "warn" : "mid"}`}>{p.severity ?? p.status}</span>
                          <div>
                            <strong>{p.title}</strong>
                            <div className="muted">{p.message}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </>
          )}
        </div>
      )}

      {tab === "download" && (
        <div className="asset-body">
          <ul className="downloads">
            {available.map((d) => (
              <li key={d.id}>
                <div>
                  <strong>{d.label}</strong>
                  <div className="muted">{d.note}</div>
                </div>
                <button type="button" disabled={busy !== null} onClick={() => void download(d.id, d.kind)}>
                  {busy === d.id ? "Preparing…" : "Download"}
                </button>
              </li>
            ))}
          </ul>
          <p className="muted">FBX, USDZ and .blend are not available yet. Units are metres.</p>
        </div>
      )}
    </section>
  );
}
