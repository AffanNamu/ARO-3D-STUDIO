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
    void supabase()
      .auth.getSession()
      .then(({ data }) => {
        if (data.session) router.replace("/");
      });
  }, [env.ok, router]);

  if (!env.ok) {
    return (
      <main className="center">
        <div className="panel err">
          <h1>Not configured</h1>
          <p>{env.problems.join(" ")}</p>
          <p className="muted">Copy .env.example to .env.local and fill in the three public values.</p>
        </div>
      </main>
    );
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    const auth = supabase().auth;
    if (mode === "in") {
      const { error: err } = await auth.signInWithPassword({ email, password });
      setBusy(false);
      if (err) return setError(err.message);
      return router.replace("/");
    }
    const { data, error: err } = await auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } });
    setBusy(false);
    if (err) return setError(err.message);
    if (data.session) return router.replace("/"); // the project does not require email confirmation: you are signed in
    setMessage("Check your email to confirm the account, then sign in.");
    setMode("in");
  }

  async function magic() {
    setBusy(true);
    setError(null);
    setMessage(null);
    const { error: err } = await supabase().auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
    setBusy(false);
    if (err) setError(err.message);
    else setMessage("A sign-in link is on its way to your email.");
  }

  return (
    <main className="auth">
      <section className="auth-art" aria-label="About">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          ARO 3D AI Studio
        </div>
        <h1>Turn one image into a game-ready 3D model.</h1>
        <ul>
          <li>Upload a picture; get a textured model sized in real metres.</li>
          <li>Every model ships with four levels of detail and a collision mesh.</li>
          <li>Checked automatically before you download: GLB, OBJ, STL or PLY.</li>
        </ul>
      </section>
      <section className="auth-form">
        <form onSubmit={submit} aria-label={mode === "in" ? "Sign in" : "Create account"}>
          <h2>{mode === "in" ? "Sign in" : "Create your account"}</h2>
          <div>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label htmlFor="password">Password</label>
            <input id="password" type="password" required minLength={8} autoComplete={mode === "in" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error && (
            <div className="err" role="alert">
              {error}
            </div>
          )}
          {message && (
            <div className="notice" role="status">
              {message}
            </div>
          )}
          <button className="primary" disabled={busy} type="submit">
            {mode === "in" ? "Sign in" : "Create account"}
          </button>
          <button type="button" disabled={busy || !email} onClick={() => void magic()}>
            Email me a sign-in link
          </button>
          <button type="button" className="link" onClick={() => setMode(mode === "in" ? "up" : "in")}>
            {mode === "in" ? "I need an account" : "I already have an account"}
          </button>
        </form>
      </section>
    </main>
  );
}
