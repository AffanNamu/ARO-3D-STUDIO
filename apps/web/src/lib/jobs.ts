export const TERMINAL = ["completed", "failed", "cancelled"] as const;

/** The stages a user sees, in order. Several internal states map to one stage. */
export const STAGES = [
  { id: "queued", label: "Queued", states: ["created", "validating", "queued"] },
  { id: "starting", label: "Starting a GPU", states: ["initializing"] },
  { id: "generating", label: "Generating", states: ["generating", "processing"] },
  { id: "checking", label: "Checking & saving", states: ["validating_output", "uploading"] },
  { id: "done", label: "Ready", states: ["completed"] },
] as const;

export function isTerminal(state: string): boolean {
  return (TERMINAL as readonly string[]).includes(state);
}

/** Index of the stage a state belongs to, or -1 for failed/cancelled/unknown. */
export function stageIndex(state: string): number {
  return STAGES.findIndex((s) => (s.states as readonly string[]).includes(state));
}

export function elapsedSeconds(startIso: string | null | undefined, now: number = Date.now()): number {
  if (!startIso) return 0;
  const t = Date.parse(startIso);
  return Number.isFinite(t) ? Math.max(0, Math.round((now - t) / 1000)) : 0;
}

export function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/** A fresh key for each NEW generation. Reuse it only to retry the same request after a network error. */
export function newIdempotencyKey(): string {
  return `gen-${crypto.randomUUID()}`;
}
