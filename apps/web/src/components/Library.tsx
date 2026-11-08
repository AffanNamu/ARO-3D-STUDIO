"use client";
import { useEffect, useState } from "react";
import type { Api, Asset } from "@/lib/api";

function Card({ api, asset, selected, onOpen }: { api: Api; asset: Asset; selected: boolean; onOpen: (a: Asset) => void }) {
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void api.fileUrl(asset.asset_id, asset.current_version ?? 1, "thumbnail").then((f) => { if (live) setThumb(f.url); }).catch(() => undefined);
    return () => { live = false; };
  }, [api, asset.asset_id, asset.current_version]);

  return (
    <button type="button" className={`card${selected ? " sel" : ""}`} onClick={() => onOpen(asset)} aria-label={`Open ${asset.name}`}>
      <div className="thumb">{/* eslint-disable-next-line @next/next/no-img-element */}{thumb ? <img src={thumb} alt="" /> : "3D"}</div>
      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{asset.name}</div>
      <div className="note">{asset.triangles ? `${asset.triangles.toLocaleString()} tris` : "—"}{asset.ai_inference === false ? " · test output" : ""}</div>
    </button>
  );
}

export default function Library({ api, assets, selectedId, onOpen }: { api: Api; assets: Asset[]; selectedId: string | null; onOpen: (a: Asset) => void }) {
  if (assets.length === 0) return <p className="note">Your finished models will appear here.</p>;
  return <div className="lib">{assets.map((a) => <Card key={a.asset_id} api={api} asset={a} selected={a.asset_id === selectedId} onOpen={onOpen} />)}</div>;
}
