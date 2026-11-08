"use client";
import { useEffect, useState } from "react";
import type { ApiError, Job } from "@/lib/api";
import { STAGES, elapsedSeconds, formatDuration, isTerminal, stageIndex } from "@/lib/jobs";

export default function JobProgress({ job, error, onCancel }: { job: Job; error: ApiError | null; onCancel: () => void }) {
  const [now, setNow] = useState(() => Date.now());
  const ended = isTerminal(job.state);
  useEffect(() => {
    if (ended) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [ended]);

  const at = stageIndex(job.state);
  const secs = elapsedSeconds(job.created_at, ended && job.finished_at ? Date.parse(job.finished_at) : now);

  return (
    <section className="panel stack" aria-live="polite" aria-label="Generation progress">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <h2>{job.name}</h2>
        <span className="pill">{formatDuration(secs)}</span>
      </div>
      <div className="steps">
        {STAGES.map((s, i) => (
          <div key={s.id} className={`step${job.state === "completed" || i < at ? " done" : i === at ? " now" : ""}`}>{s.label}</div>
        ))}
      </div>
      {job.state === "failed" && (
        <div className="err" role="alert">
          <strong>This generation did not finish.</strong>
          <div>{job.error?.message ?? "Something went wrong."}</div>
          <div className="note">Your credits were returned.</div>
        </div>
      )}
      {job.state === "cancelled" && <div className="note">Cancelled. Your credits were returned.</div>}
      {!ended && <div className="note">{job.cancel_requested ? "Cancelling…" : (job.status_message ?? "Working…")}{job.attempt > 1 ? ` (attempt ${job.attempt})` : ""}</div>}
      {!ended && secs > 60 && job.state === "initializing" && <div className="note">A cold GPU can take a few minutes to wake up the first time.</div>}
      {error && !ended && <div className="note" role="status">Having trouble reaching the server ({error.message}). Still trying…</div>}
      {!ended && <button type="button" disabled={job.cancel_requested || job.state === "validating_output" || job.state === "uploading"} onClick={onCancel}>Cancel</button>}
    </section>
  );
}
