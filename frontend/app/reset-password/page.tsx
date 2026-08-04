"use client";

import type { FormEvent } from "react";
import { useState } from "react";
import Link from "next/link";

import AuthFlowCard, {
  buttonClass,
  FlowMessage,
  inputClass,
} from "../components/AuthFlowCard";
import { api, session } from "../lib/api";


export default function ResetPasswordPage() {
  const [token] = useState(() =>
    typeof window === "undefined"
      ? ""
      : new URLSearchParams(window.location.search).get("token") ?? ""
  );
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) {
      setError("This password reset link is invalid or expired.");
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setMessage("");
    setError("");
    try {
      const result = await api.resetPassword(token, password);
      session.clear();
      setMessage(result.message);
      setPassword("");
      setConfirmation("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reset password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFlowCard
      eyebrow="Account recovery"
      title="Choose a new password"
      description="Use at least 8 characters. Completing this reset signs out every existing session."
    >
      <form onSubmit={submit} className="space-y-4">
        <PasswordInput label="New password" value={password} onChange={setPassword} />
        <PasswordInput label="Confirm new password" value={confirmation} onChange={setConfirmation} />
        {message && <FlowMessage>{message}</FlowMessage>}
        {error && <FlowMessage error>{error}</FlowMessage>}
        <button disabled={loading} className={buttonClass} type="submit">
          {loading ? "Resetting..." : "Reset password"}
        </button>
      </form>
      <Link href="/" className="mt-5 block text-center text-sm font-semibold text-[#167c5a]">
        Back to sign in
      </Link>
    </AuthFlowCard>
  );
}

function PasswordInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-[#66746e]">{label}</span>
      <input
        required
        minLength={8}
        maxLength={128}
        type="password"
        autoComplete="new-password"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    </label>
  );
}
