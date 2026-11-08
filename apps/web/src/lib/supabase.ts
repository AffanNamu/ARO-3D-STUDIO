import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { readEnv } from "./env";

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient {
  if (client) return client;
  const e = readEnv();
  if (!e.ok) throw new Error("Configuration problem: " + e.problems.join("; "));
  client = createClient(e.env.supabaseUrl, e.env.supabaseAnonKey, { auth: { persistSession: true, autoRefreshToken: true } });
  return client;
}
