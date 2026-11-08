import { describe, expect, it } from "vitest";
import { elapsedSeconds, formatDuration, isTerminal, newIdempotencyKey, stageIndex } from "@/lib/jobs";

describe("job helpers", () => {
  it("knows which states are final", () => {
    for (const s of ["completed", "failed", "cancelled"]) expect(isTerminal(s)).toBe(true);
    for (const s of ["created", "queued", "initializing", "generating", "validating_output", "uploading"]) expect(isTerminal(s)).toBe(false);
  });
  it("maps internal states onto the five stages a user sees", () => {
    expect(stageIndex("queued")).toBe(0);
    expect(stageIndex("initializing")).toBe(1);
    expect(stageIndex("generating")).toBe(2);
    expect(stageIndex("processing")).toBe(2);
    expect(stageIndex("uploading")).toBe(3);
    expect(stageIndex("completed")).toBe(4);
    expect(stageIndex("failed")).toBe(-1);
  });
  it("formats durations", () => {
    expect(formatDuration(7)).toBe("7s");
    expect(formatDuration(125)).toBe("2m 05s");
  });
  it("measures elapsed time from a timestamp and survives garbage", () => {
    expect(elapsedSeconds("2026-01-01T00:00:00Z", Date.parse("2026-01-01T00:01:30Z"))).toBe(90);
    expect(elapsedSeconds(null)).toBe(0);
    expect(elapsedSeconds("nonsense")).toBe(0);
  });
  it("makes a fresh, well-formed idempotency key each time (8-128 characters)", () => {
    const a = newIdempotencyKey();
    const b = newIdempotencyKey();
    expect(a).not.toBe(b);
    expect(a).toMatch(/^gen-[0-9a-f-]{36}$/);
  });
});
