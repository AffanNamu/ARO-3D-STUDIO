import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useJob } from "@/hooks/useJob";
import { ApiError, type Api, type Job } from "@/lib/api";

const job = (state: string): Job => ({
  job_id: "j1", name: "Car", engine: "triposg", state, progress: 0, status_message: null, error: null, attempt: 1, cancel_requested: false,
  credits: { reserved: 10, captured: 0 }, created_at: null, started_at: null, finished_at: null, result: null,
});
const asApi = (getGeneration: unknown) => ({ getGeneration }) as unknown as Api;
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));
const FAST = 15; // poll interval for tests

describe("useJob", () => {
  it("polls until the job ends and then stops", async () => {
    const states = ["queued", "generating", "completed"];
    const getGeneration = vi.fn(async () => job(states.shift() ?? "completed"));
    const api = asApi(getGeneration);
    const { result } = renderHook(() => useJob(api, "j1", null, FAST));
    await waitFor(() => expect(result.current.job?.state).toBe("completed"));
    await pause(120);
    expect(getGeneration).toHaveBeenCalledTimes(3);
  });

  it("backs off on network errors and recovers", async () => {
    let n = 0;
    const getGeneration = vi.fn(async () => {
      n += 1;
      if (n <= 2) throw new ApiError(0, "network", "down");
      return job("generating");
    });
    const api = asApi(getGeneration);
    const { result } = renderHook(() => useJob(api, "j1", null, FAST));
    await waitFor(() => expect(result.current.error?.code).toBe("network"));
    await waitFor(() => expect(result.current.job?.state).toBe("generating"));
    expect(result.current.error).toBeNull();
  });

  it("stops polling for good on 404", async () => {
    const getGeneration = vi.fn(async () => { throw new ApiError(404, "job_not_found", "gone"); });
    const api = asApi(getGeneration);
    const { result } = renderHook(() => useJob(api, "j1", null, FAST));
    await waitFor(() => expect(result.current.error?.status).toBe(404));
    await pause(150);
    expect(getGeneration).toHaveBeenCalledTimes(1);
  });

  it("stops polling when the component goes away", async () => {
    const getGeneration = vi.fn(async () => job("generating"));
    const api = asApi(getGeneration);
    const { unmount } = renderHook(() => useJob(api, "j1", null, FAST));
    await waitFor(() => expect(getGeneration).toHaveBeenCalled());
    unmount();
    const seen = getGeneration.mock.calls.length;
    await pause(120);
    expect(getGeneration.mock.calls.length).toBeLessThanOrEqual(seen + 1);
  });

  it("does nothing without a job id", async () => {
    const getGeneration = vi.fn();
    const api = asApi(getGeneration);
    renderHook(() => useJob(api, null, null, FAST));
    await pause(80);
    expect(getGeneration).not.toHaveBeenCalled();
  });
});
