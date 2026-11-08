"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError, type Api, type Job } from "@/lib/api";
import { isTerminal } from "@/lib/jobs";

export const POLL_MS = 2500;

/** Poll a generation until it ends. Transient errors back off; auth and not-found errors stop the polling and are reported. */
export function useJob(api: Api | null, jobId: string | null, initial?: Job | null, pollMs: number = POLL_MS) {
  const [job, setJob] = useState<Job | null>(initial ?? null);
  const [error, setError] = useState<ApiError | null>(null);
  const failures = useRef(0);

  useEffect(() => {
    setJob(initial ?? null);
    setError(null);
    failures.current = 0;
    if (!api || !jobId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const tick = async () => {
      try {
        const j = await api.getGeneration(jobId);
        if (stopped) return;
        failures.current = 0;
        setError(null);
        setJob(j);
        if (!isTerminal(j.state)) timer = setTimeout(tick, pollMs);
      } catch (e) {
        if (stopped) return;
        const err = e instanceof ApiError ? e : new ApiError(0, "network", "The server could not be reached.");
        setError(err);
        if (err.status === 401 || err.status === 404) return;
        failures.current += 1;
        timer = setTimeout(tick, Math.min(30_000, pollMs * 2 ** failures.current));
      }
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, jobId, pollMs]);

  return { job, error };
}
