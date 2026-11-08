"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { readEnv } from "@/lib/env";
import { supabase } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const env = readEnv();

  useEffect(() => {
    if (!env.ok) return;
    void supabase().auth.getSession().then(({ data }) => { if (data.session) router.replace("/"); });
  }, [env.ok, router]);

  if (!env.ok) {
    return <main className="auth"><div className="panel err"><h1>Not configured</h1><p>{env.problems.join(" ")}</p><p className="note">Copy .env.example to .env.local and fill in the three public values.</p></div></main>;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setMessage(null);
    const auth = supabase().auth;
    const { error: err } = mode === "in" ? await auth.signInWithPassword({ email, password }) : await auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
    setBusy(false);
    if (err) { setError(err.message); return; }
    if (mode === "up") { setMessage("Check your email to confirm the account, then sign in."); setMode("in"); return; }
    router.replace("/");
  }

  async function magic() {
    setBusy(true); setError(null); setMessage(null);
    const { error: err } = await supabase().auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
    setBusy(false);
    if (err) setError(err.message); else setMessage("A sign-in link is on its way to your email.");
  }

  return (
    <main className="auth">
      <form className="panel stack" onSubmit={submit}>
        <h1>ARO 3D AI Studio</h1>
        <p className="note">{mode === "in" ? "Sign in to turn images into 3D models." : "Create your account."}</p>
        <div><label htmlFor="email">Email</label><input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label htmlFor="password">Password</label><input id="password" type="password" required minLength={8} autoComplete={mode === "in" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        {error && <div className="err" role="alert">{error}</div>}
        {message && <div className="note" role="status">{message}</div>}
        <button className="primary" disabled={busy} type="submit">{mode === "in" ? "Sign in" : "Create account"}</button>
        <button type="button" disabled={busy || !email} onClick={magic}>Email me a sign-in link</button>
        <button type="button" onClick={() => setMode(mode === "in" ? "up" : "in")}>{mode === "in" ? "I need an account" : "I already have an account"}</button>
      </form>
    </main>
  );
}
