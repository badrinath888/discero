"use client";

import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import Link from "next/link";

import AuthFlowCard, {
  buttonClass,
  FlowMessage,
  inputClass,
} from "../components/AuthFlowCard";
import { api } from "../lib/api";


export default function VerifyEmailPage() {
  const [token] = useState(() =>
    typeof window === "undefined"
      ? ""
      : new URLSearchParams(window.location.search).get("token") ?? ""
  );
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(Boolean(token));
  const [resending, setResending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(
    token ? "" : "This email verification link is invalid or expired."
  );

  useEffect(() => {
    if (!token) return;

    api.verifyEmail(token)
      .then((result) => setMessage(result.message))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Unable to verify email")
      )
      .finally(() => setLoading(false));
  }, [token]);

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setResending(true);
    setError("");
    setMessage("");
    try {
      const result = await api.resendVerification(email.trim().toLowerCase());
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resend verification");
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthFlowCard
      eyebrow="Email verification"
      title="Verify your email"
      description="Verification links are single-use and expire after 24 hours."
    >
      {loading && <FlowMessage>Verifying your email...</FlowMessage>}
      {!loading && message && <FlowMessage>{message}</FlowMessage>}
      {!loading && error && <FlowMessage error>{error}</FlowMessage>}

      {!loading && (
        <form onSubmit={resend} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-xs font-medium text-[#66746e]">Need a new link?</span>
            <input
              required
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={inputClass}
            />
          </label>
          <button disabled={resending} className={buttonClass} type="submit">
            {resending ? "Sending..." : "Resend verification"}
          </button>
        </form>
      )}

      <Link href="/" className="mt-5 block text-center text-sm font-semibold text-[#167c5a]">
        Continue to sign in
      </Link>
    </AuthFlowCard>
  );
}
