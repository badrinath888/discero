"use client";

import type { FormEvent } from "react";
import { useState } from "react";
import Link from "next/link";

import AuthFlowCard, {
  buttonClass,
  FlowMessage,
  inputClass,
} from "../components/AuthFlowCard";
import { api } from "../lib/api";


export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    setError("");

    try {
      const result = await api.forgotPassword(email.trim().toLowerCase());
      setMessage(result.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to request a reset link");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFlowCard
      eyebrow="Account recovery"
      title="Forgot your password?"
      description="Enter your email and we’ll send a secure reset link if it matches an account."
    >
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="text-xs font-medium text-[#66746e]">Email address</span>
          <input
            required
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={inputClass}
          />
        </label>
        {message && <FlowMessage>{message}</FlowMessage>}
        {error && <FlowMessage error>{error}</FlowMessage>}
        <button disabled={loading} className={buttonClass} type="submit">
          {loading ? "Sending..." : "Send reset link"}
        </button>
      </form>
      <Link href="/" className="mt-5 block text-center text-sm font-semibold text-[#167c5a]">
        Back to sign in
      </Link>
    </AuthFlowCard>
  );
}
