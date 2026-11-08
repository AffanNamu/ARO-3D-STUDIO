import { z } from "zod";

const credits = z.object({ balance: z.number(), reserved: z.number() });

const me = z.object({
  user_id: z.string(),
  email: z.string().nullable(),
  new_user: z.boolean(),
  credits,
  price: z.object({ image_to_3d: z.number() }),
  engines: z.array(z.string()),
  limits: z.object({ max_upload_mb: z.number(), min_image_side: z.number(), max_active_jobs: z.number(), target_faces: z.array(z.number()) }),
});

const upload = z.object({
  upload_id: z.string(),
  content_type: z.string(),
  bytes: z.number(),
  width: z.number(),
  height: z.number(),
  has_alpha: z.boolean(),
  warnings: z.array(z.string()).default([]),
});

const job = z.object({
  job_id: z.string(),
  name: z.string(),
  engine: z.string().nullable(),
  state: z.string(),
  progress: z.number(),
  status_message: z.string().nullable(),
  error: z.object({ code: z.string().nullable(), message: z.string().nullable() }).nullable(),
  attempt: z.number(),
  cancel_requested: z.boolean(),
  credits: z.object({ reserved: z.number(), captured: z.number() }),
  created_at: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  result: z.object({ asset_id: z.string(), version_id: z.string().nullable() }).nullable(),
});

const asset = z.object({
  asset_id: z.string(),
  name: z.string(),
  category: z.string(),
  created_at: z.string().nullable(),
  current_version: z.number().nullable(),
  triangles: z.number().nullable(),
  has_uv: z.boolean().nullable(),
  engine: z.string().nullable(),
  ai_inference: z.boolean().nullable(),
});

const fileUrl = z.object({ url: z.string().url(), expires_at: z.string(), content_type: z.string(), filename: z.string() });

export type Me = z.infer<typeof me>;
export type Upload = z.infer<typeof upload>;
export type Job = z.infer<typeof job>;
export type Asset = z.infer<typeof asset>;
export type FileUrl = z.infer<typeof fileUrl>;

export type GenerationRequest = {
  kind: "image_to_3d";
  upload_id: string;
  name: string;
  engine?: string;
  settings: { preset: "DRAFT" | "STANDARD" | "HIGH"; category: string; target_faces: number; texture_resolution: 512 | 1024 | 2048; length_m?: number; seed?: number };
};

/** The server's error envelope: {"error": {"code", "message", "recommended_action", "details"}}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public recommendedAction?: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Options = { baseUrl: string; getToken: () => Promise<string | null>; fetchImpl?: typeof fetch };

export function createApi({ baseUrl, getToken, fetchImpl }: Options) {
  const doFetch: typeof fetch = (...a) => (fetchImpl ?? fetch)(...a);

  async function call<T>(schema: z.ZodType<T>, path: string, init: RequestInit = {}, extra: Record<string, string> = {}): Promise<T> {
    const token = await getToken();
    if (!token) throw new ApiError(401, "unauthorized", "Sign in to continue.");
    let res: Response;
    try {
      res = await doFetch(`${baseUrl}${path}`, { ...init, headers: { ...(init.headers as Record<string, string>), Authorization: `Bearer ${token}`, ...extra } });
    } catch {
      throw new ApiError(0, "network", "The server could not be reached.", "Check your connection and try again.");
    }
    if (!res.ok) throw await toError(res);
    const body: unknown = await res.json();
    const parsed = schema.safeParse(body);
    if (!parsed.success) throw new ApiError(res.status, "bad_response", "The server answered in an unexpected format.");
    return parsed.data;
  }

  return {
    me: () => call(me, "/v1/me"),
    uploadImage: (file: Blob) => call(upload, "/v1/uploads", { method: "POST", body: file }, { "Content-Type": file.type }),
    createGeneration: (body: GenerationRequest, idempotencyKey: string) =>
      call(job, "/v1/generations", { method: "POST", body: JSON.stringify(body) }, { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }),
    getGeneration: (id: string) => call(job, `/v1/generations/${encodeURIComponent(id)}`),
    cancelGeneration: (id: string) => call(job, `/v1/generations/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    listAssets: () => call(z.object({ items: z.array(asset) }), "/v1/assets?limit=60"),
    fileUrl: (assetId: string, version: number, role: "glb" | "thumbnail" | "raw_mesh") =>
      call(fileUrl, `/v1/assets/${encodeURIComponent(assetId)}/versions/${version}/files/${role}`),
  };
}

export type Api = ReturnType<typeof createApi>;

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string; recommended_action?: string; details?: Record<string, unknown> } };
    const e = body.error;
    if (e) return new ApiError(res.status, e.code ?? "error", e.message ?? "The request failed.", e.recommended_action, e.details);
  } catch {
    /* not JSON */
  }
  return new ApiError(res.status, "error", `The request failed (HTTP ${res.status}).`);
}
