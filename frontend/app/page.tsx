"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, session } from "./lib/api";

type Mode = "login" | "register";

export default function HomePage() {
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function validateSession() {
      const token = session.getToken();

      if (!token) {
        await Promise.resolve();
        setCheckingSession(false);
        return;
      }

      try {
        await api.getMe();
        router.replace("/dashboard");
      } catch {
        session.clear();
        setCheckingSession(false);
      }
    }

    void validateSession();
  }, [router]);

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    const normalizedEmail = email.trim().toLowerCase();

    if (!normalizedEmail) {
      setError("Enter your email address.");
      return;
    }

    if (password.length < 8) {
      setError("Password must contain at least 8 characters.");
      return;
    }

    if (
      mode === "register" &&
      password !== confirmPassword
    ) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      if (mode === "register") {
        await api.createUser(normalizedEmail, password);
      }

      const auth = await api.login(
        normalizedEmail,
        password
      );

      session.save(auth);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Authentication failed"
      );
    } finally {
      setLoading(false);
    }
  }

  function changeMode(nextMode: Mode) {
    setMode(nextMode);
    setPassword("");
    setConfirmPassword("");
    setError("");
  }

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#050d18] text-white">
        <div className="text-center">
          <div className="mx-auto h-9 w-9 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />

          <p className="mt-4 text-sm text-slate-400">
            Checking your session...
          </p>
        </div>
      </main>
    );
  }

  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#050d18] px-5 py-10 text-white"
      style={{
        backgroundImage: `
          radial-gradient(circle at 12% 10%, rgba(16,185,129,0.22), transparent 30%),
          radial-gradient(circle at 88% 18%, rgba(14,165,233,0.16), transparent 28%),
          linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
        `,
        backgroundSize:
          "auto, auto, 42px 42px, 42px 42px",
      }}
    >
      <div className="relative mx-auto flex min-h-[calc(100vh-5rem)] max-w-6xl items-center">
        <div className="grid w-full gap-10 lg:grid-cols-2 lg:items-center">
          <section>
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Personal finance intelligence
            </div>

            <h1 className="mt-6 text-5xl font-bold tracking-tight">
              See your money clearly with
              <span className="block bg-gradient-to-r from-emerald-300 to-cyan-300 bg-clip-text text-transparent">
                FinSight
              </span>
            </h1>

            <p className="mt-6 max-w-xl leading-7 text-slate-400">
              Analyze spending, manage budgets, identify recurring
              payments, and monitor your financial health securely.
            </p>
          </section>

          <section className="rounded-3xl border border-white/10 bg-white/[0.07] p-7 shadow-2xl shadow-black/30 backdrop-blur-xl">
            <div className="grid grid-cols-2 rounded-xl border border-white/10 bg-slate-950/60 p-1">
              <button
                type="button"
                onClick={() => changeMode("login")}
                className={`rounded-lg px-4 py-2.5 text-sm font-medium ${
                  mode === "login"
                    ? "bg-emerald-400 text-slate-950"
                    : "text-slate-400"
                }`}
              >
                Sign in
              </button>

              <button
                type="button"
                onClick={() => changeMode("register")}
                className={`rounded-lg px-4 py-2.5 text-sm font-medium ${
                  mode === "register"
                    ? "bg-emerald-400 text-slate-950"
                    : "text-slate-400"
                }`}
              >
                Create account
              </button>
            </div>

            <h2 className="mt-7 text-2xl font-bold">
              {mode === "login"
                ? "Welcome back"
                : "Create your account"}
            </h2>

            <form
              onSubmit={handleSubmit}
              className="mt-6 space-y-5"
            >
              <input
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) =>
                  setEmail(event.target.value)
                }
                placeholder="Email address"
                className="w-full rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 outline-none focus:border-emerald-400"
              />

              <input
                type="password"
                autoComplete={
                  mode === "login"
                    ? "current-password"
                    : "new-password"
                }
                value={password}
                onChange={(event) =>
                  setPassword(event.target.value)
                }
                placeholder="Password"
                className="w-full rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 outline-none focus:border-emerald-400"
              />

              {mode === "register" && (
                <input
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) =>
                    setConfirmPassword(event.target.value)
                  }
                  placeholder="Confirm password"
                  className="w-full rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 outline-none focus:border-emerald-400"
                />
              )}

              {error && (
                <div className="rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-xl bg-emerald-400 px-5 py-3 font-semibold text-slate-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading
                  ? "Please wait..."
                  : mode === "login"
                    ? "Sign in"
                    : "Create account"}
              </button>
            </form>
          </section>
        </div>
      </div>
    </main>
  );
}
