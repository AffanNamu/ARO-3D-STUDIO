import { z } from "zod";

const schema = z.object({
  apiUrl: z.string().url("NEXT_PUBLIC_API_URL must be a URL"),
  supabaseUrl: z.string().url("NEXT_PUBLIC_SUPABASE_URL must be a URL"),
  supabaseAnonKey: z.string().min(20, "NEXT_PUBLIC_SUPABASE_ANON_KEY is missing"),
});

export type PublicEnv = z.infer<typeof schema>;

/** Validate the public configuration. Next.js only inlines `process.env.NEXT_PUBLIC_*` when it is written out in full, hence the explicit reads. */
export function readEnv(
  raw: Record<string, string | undefined> = {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  },
): { ok: true; env: PublicEnv } | { ok: false; problems: string[] } {
  const parsed = schema.safeParse({
    apiUrl: raw.NEXT_PUBLIC_API_URL?.replace(/\/+$/, ""),
    supabaseUrl: raw.NEXT_PUBLIC_SUPABASE_URL?.replace(/\/+$/, ""),
    supabaseAnonKey: raw.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  });
  if (parsed.success) return { ok: true, env: parsed.data };
  return { ok: false, problems: parsed.error.issues.map((i) => i.message) };
}
