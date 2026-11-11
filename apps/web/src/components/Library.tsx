"use client";
import { useEffect, useState } from "react";
import type { Api, Asset } from "@/lib/api";

function Card({ api, asset, selected, onOpen }: { api: Api; asset: Asset; selected: boolean; onOpen: (a: Asset) => void }) {
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void api
      .fileUrl(asset.asset_id, asset.current_version ?? 1, "thumbnail")
      .then((f) => {
        if (live) setThumb(f.url);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [api, asset.asset_id, asset.current_version]);

  return (
    <button type="button" className="card" aria-current={selected} onClick={() => onOpen(asset)} aria-label={`Open ${asset.name}`}>
      <div className="thumb">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {thumb ? <img src={thumb} alt="" loading="lazy" /> : <span aria-hidden="true">3D</span>}
        {asset.ai_inference === false && <span className="tag warn corner">test</span>}
      </div>
      <div className="card-name">{asset.name}</div>
      <div className="muted small">{asset.triangles ? `${asset.triangles.toLocaleString()} triangles` : "—"}</div>
    </button>
  );
}

export default function Library({
  api,
  assets,
  query,
  onQuery,
  selectedId,
  onOpen,
}: {
  api: Api;
  assets: Asset[];
  query: string;
  onQuery: (q: string) => void;
  selectedId: string | null;
  onOpen: (a: Asset) => void;
}) {
  return (
    <div className="stack">
      <input type="search" placeholder="Search your models" aria-label="Search your models" value={query} onChange={(e) => onQuery(e.target.value)} />
      {assets.length === 0 ? (
        <p className="muted">{query ? "No model matches that search." : "Your finished models will appear here."}</p>
      ) : (
        <div className="lib">
          {assets.map((a) => (
            <Card key={a.asset_id} api={api} asset={a} selected={a.asset_id === selectedId} onOpen={onOpen} />
          ))}
        </div>
      )}
    </div>
  );
}
