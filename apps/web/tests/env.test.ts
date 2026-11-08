import { describe, expect, it } from "vitest";
import { readEnv } from "@/lib/env";

const good = { NEXT_PUBLIC_API_URL: "https://api.example.com/", NEXT_PUBLIC_SUPABASE_URL: "https://abc.supabase.co", NEXT_PUBLIC_SUPABASE_ANON_KEY: "x".repeat(40) };

describe("readEnv", () => {
  it("accepts a complete configuration and trims trailing slashes", () => {
    const r = readEnv(good);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.env.apiUrl).toBe("https://api.example.com");
  });
  it("names every missing value", () => {
    const r = readEnv({});
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.problems.length).toBe(3);
  });
  it("rejects a value that is not a URL", () => {
    expect(readEnv({ ...good, NEXT_PUBLIC_API_URL: "not a url" }).ok).toBe(false);
  });
});
