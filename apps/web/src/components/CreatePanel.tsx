"use client";
import { useState } from "react";
import type { Me, Preset } from "@/lib/api";
import { CATEGORIES, engineLabel } from "@/lib/model";
import UploadPanel from "./UploadPanel";

export type CreateInput = {
  file: File;
  name: string;
  engine: string;
  preset: Preset;
  category: string;
  faces: number;
  texture: 512 | 1024 | 2048;
  lengthM?: number;
};

export default function CreatePanel({ me, busy, blocked, problem, onGenerate }: { me: Me | null; busy: boolean; blocked: string | null; problem: string | null; onGenerate: (input: CreateInput) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("car");
  const [preset, setPreset] = useState<Preset>("STANDARD");
  const [faces, setFaces] = useState(24000);
  const [texture, setTexture] = useState<512 | 1024 | 2048>(1024);
  const [length, setLength] = useState("");
  const [engine, setEngine] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);

  const engines = me?.engines ?? [];
  const chosen = engine && engines.includes(engine) ? engine : (engines[0] ?? null);
  const price = me?.price.image_to_3d ?? 0;
  const lengthN = length.trim() === "" ? undefined : Number(length);
  const lengthBad = lengthN !== undefined && !(lengthN > 0 && lengthN <= 60);
  const poor = !!me && me.credits.balance < price;
  const noEngine = !!me && engines.length === 0;
  const disabled = !file || busy || !!blocked || poor || noEngine || lengthBad || !chosen;

  return (
    <section className="panel stack" aria-label="Create a model">
      <h2>Image to 3D</h2>
      <UploadPanel
        maxMb={me?.limits.max_upload_mb ?? 10}
        disabled={busy}
        onFile={(f) => {
          setFile(f);
          if (f && !name) setName(f.name.replace(/\.[^.]+$/, "").slice(0, 120));
        }}
      />
      <div>
        <label htmlFor="name">Name</label>
        <input id="name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="row">
        <div>
          <label htmlFor="cat">Category</label>
          <select id="cat" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="preset">Quality</label>
          <select id="preset" value={preset} onChange={(e) => setPreset(e.target.value as Preset)}>
            <option value="DRAFT">Draft · fastest</option>
            <option value="STANDARD">Standard</option>
            <option value="HIGH">High · slowest</option>
          </select>
        </div>
      </div>
      <div>
        <label htmlFor="len">Real length in metres (optional)</label>
        <input id="len" inputMode="decimal" placeholder="e.g. 4.5 — gives the model its true size" value={length} aria-invalid={lengthBad} onChange={(e) => setLength(e.target.value)} />
        {lengthBad && <div className="field-err">Enter a length between 0 and 60 metres.</div>}
      </div>
      <button type="button" className="link" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
        {advanced ? "Hide" : "Show"} advanced settings
      </button>
      {advanced && (
        <div className="row">
          <div>
            <label htmlFor="faces">Triangle budget</label>
            <input id="faces" type="number" min={2000} max={25000} step={1000} value={faces} onChange={(e) => setFaces(Math.max(2000, Math.min(25000, Number(e.target.value) || 24000)))} />
          </div>
          <div>
            <label htmlFor="tex">Texture size</label>
            <select id="tex" value={texture} onChange={(e) => setTexture(Number(e.target.value) as 512 | 1024 | 2048)}>
              <option value={512}>512 px</option>
              <option value={1024}>1024 px</option>
              <option value={2048}>2048 px</option>
            </select>
          </div>
          {engines.length > 1 && (
            <div>
              <label htmlFor="engine">AI model</label>
              <select id="engine" value={chosen ?? ""} onChange={(e) => setEngine(e.target.value)}>
                {engines.map((e) => (
                  <option key={e} value={e}>
                    {engineLabel(e)}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
      {problem && (
        <div className="err" role="alert">
          {problem}
        </div>
      )}
      {noEngine && (
        <div className="notice" role="status">
          No AI model is switched on for this server yet. The administrator has to verify a model&apos;s licence and enable it first.
        </div>
      )}
      <button
        className="primary"
        type="button"
        disabled={disabled}
        onClick={() => file && chosen && onGenerate({ file, name: name.trim() || file.name.replace(/\.[^.]+$/, "") || "Untitled", engine: chosen, preset, category, faces, texture, lengthM: lengthN })}
      >
        {busy ? "Starting…" : `Generate${price ? ` · ${price} credits` : ""}`}
      </button>
      {blocked && <p className="muted small">{blocked}</p>}
      {poor && !noEngine && (
        <p className="muted small">
          You need {price} credits to generate and have {me?.credits.balance}.
        </p>
      )}
      <p className="muted small">Credits are held while the model is made, and returned if it fails or you cancel.</p>
    </section>
  );
}
