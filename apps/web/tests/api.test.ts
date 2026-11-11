import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "@/lib/api";

const job = {
  job_id: "j1", name: "Car", engine: "triposg", state: "queued", progress: 0.05, status_message: null, error: null, attempt: 1,
  cancel_requested: false, credits: { reserved: 10, captured: 0 }, created_at: null, started_at: null, finished_at: null, result: null,
};
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function api(fetchImpl: typeof fetch, token: string | null = "tok") {
  return createApi({ baseUrl: "https://api.test", getToken: async () => token, fetchImpl });
}

describe("api client", () => {
  it("sends the bearer token and the idempotency key, and parses the job", async () => {
    const f = vi.fn(async () => json(job, 201));
    const out = await api(f as never).createGeneration(
      { kind: "image_to_3d", upload_id: "u1", name: "Car", engine: "triposg", settings: { preset: "DRAFT", category: "car", target_faces: 24000, texture_resolution: 1024 } },
      "gen-key-12345",
    );
    expect(out.job_id).toBe("j1");
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    const h = init.headers as Record<string, string>;
    expect(url).toBe("https://api.test/v1/generations");
    expect(h.Authorization).toBe("Bearer tok");
    expect(h["Idempotency-Key"]).toBe("gen-key-12345");
    expect(JSON.parse(init.body as string).settings.preset).toBe("DRAFT");
  });

  it("uploads the file itself with its own content type", async () => {
    const f = vi.fn(async () => json({ upload_id: "u1", content_type: "image/png", bytes: 3, width: 512, height: 512, has_alpha: false, warnings: [] }, 201));
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" });
    await api(f as never).uploadImage(blob);
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("image/png");
    expect(init.body).toBe(blob);
  });

  it("turns the server's error envelope into an ApiError", async () => {
    const f = async () => json({ error: { code: "insufficient_credits", message: "A generation costs 10 credits and you have 3.", recommended_action: "Add credits to continue.", details: { price: 10, balance: 3 } } }, 402);
    await expect(api(f as never).me()).rejects.toMatchObject({ status: 402, code: "insufficient_credits", recommendedAction: "Add credits to continue.", details: { price: 10, balance: 3 } });
  });

  it("does not call the server without a token", async () => {
    const f = vi.fn();
    await expect(api(f as never, null).me()).rejects.toMatchObject({ status: 401 });
    expect(f).not.toHaveBeenCalled();
  });

  it("reports a network failure as a retryable error, and a malformed answer as bad_response", async () => {
    await expect(api((async () => { throw new TypeError("fetch failed"); }) as never).me()).rejects.toMatchObject({ code: "network", status: 0 });
    await expect(api((async () => json({ unexpected: true })) as never).getGeneration("j1")).rejects.toMatchObject({ code: "bad_response" });
  });

  it("falls back to a generic message when an error body is not JSON", async () => {
    const e = await api((async () => new Response("<html>bad gateway</html>", { status: 502 })) as never).me().catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e.status).toBe(502);
    expect(e.message).toContain("502");
  });

  it("handles an empty answer for delete, and builds the export and search paths", async () => {
    const f = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (String(url).includes("/exports/")) return json({ url: "https://store.test/x", expires_at: "2026-01-01T00:00:00Z", content_type: "application/zip", filename: "Car_obj.zip" });
      return json({ items: [] });
    });
    const a = api(f as never);
    await expect(a.deleteAsset("a/1")).resolves.toBeUndefined();
    expect((await a.exportUrl("a1", 2, "obj")).filename).toBe("Car_obj.zip");
    await a.listAssets("red & blue");
    const urls = f.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(["https://api.test/v1/assets/a%2F1", "https://api.test/v1/assets/a1/versions/2/exports/obj", "https://api.test/v1/assets?limit=60&q=red%20%26%20blue"]);
  });

  it("encodes ids in paths", async () => {
    const f = vi.fn(async () => json(job));
    await api(f as never).getGeneration("a/b?c");
    expect((f.mock.calls[0] as unknown as [string])[0]).toBe("https://api.test/v1/generations/a%2Fb%3Fc");
  });
});
