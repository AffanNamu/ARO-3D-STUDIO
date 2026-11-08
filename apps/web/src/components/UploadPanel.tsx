"use client";
import { useEffect, useRef, useState } from "react";

export const ACCEPT = ["image/png", "image/jpeg", "image/webp"];

/** Client-side checks are a courtesy (fast feedback); the server validates the file's content again. */
export function checkFile(file: File, maxMb: number): string | null {
  if (!ACCEPT.includes(file.type)) return "Choose a PNG, JPG or WebP image.";
  if (file.size > maxMb * 1_000_000) return `The image is ${(file.size / 1e6).toFixed(1)} MB; the limit is ${maxMb} MB.`;
  return null;
}

export default function UploadPanel({ maxMb, disabled, onFile }: { maxMb: number; disabled?: boolean; onFile: (f: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [name, setName] = useState<string>("");
  const [problem, setProblem] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function take(file: File | undefined) {
    if (!file) return;
    const p = checkFile(file, maxMb);
    setProblem(p);
    if (p) { onFile(null); return; }
    setPreview(URL.createObjectURL(file));
    setName(file.name);
    onFile(file);
  }

  return (
    <div>
      <div
        className={`drop${over ? " active" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) take(e.dataTransfer.files[0]); }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {preview && <img src={preview} alt={`Preview of ${name}`} />}
        <div>{preview ? name : "Drop an image here"}</div>
        <button type="button" disabled={disabled} onClick={() => input.current?.click()} style={{ marginTop: 8 }}>Choose image</button>
        <input ref={input} className="sr" type="file" accept={ACCEPT.join(",")} aria-label="Image file" disabled={disabled} onChange={(e) => take(e.target.files?.[0])} />
      </div>
      {problem && <div className="err" role="alert" style={{ marginTop: 8 }}>{problem}</div>}
      <p className="note">One subject on a clear background works best. PNG, JPG or WebP up to {maxMb} MB.</p>
    </div>
  );
}
