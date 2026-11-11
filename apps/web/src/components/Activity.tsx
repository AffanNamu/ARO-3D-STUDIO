"use client";
import type { Job } from "@/lib/api";
import { isTerminal } from "@/lib/jobs";

const LABEL: Record<string, string> = { completed: "Ready", failed: "Failed", cancelled: "Cancelled" };

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function Activity({ jobs, activeId, onOpen }: { jobs: Job[]; activeId: string | null; onOpen: (j: Job) => void }) {
  if (jobs.length === 0) return <p className="muted">Every generation you start is listed here, with what it cost.</p>;
  return (
    <ul className="activity">
      {jobs.map((j) => {
        const running = !isTerminal(j.state);
        const openable = running || (j.state === "completed" && !!j.result);
        return (
          <li key={j.job_id}>
            <button type="button" disabled={!openable} aria-current={j.job_id === activeId} onClick={() => onOpen(j)}>
              <span className="activity-name">{j.name}</span>
              <span className={`tag ${j.state === "completed" ? "good" : j.state === "failed" ? "bad" : running ? "live" : "mid"}`}>{running ? "In progress" : (LABEL[j.state] ?? j.state)}</span>
              <span className="muted small">
                {when(j.created_at)} · {j.state === "completed" ? `${j.credits.captured} credits` : running ? `${j.credits.reserved} credits held` : "not charged"}
              </span>
              {j.state === "failed" && j.error?.message && <span className="muted small clamp">{j.error.message}</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
