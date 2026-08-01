"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";
import {
  PlaidLinkOnSuccess,
  usePlaidLink,
} from "react-plaid-link";
import { api } from "../lib/api";

type ConnectBankButtonProps = {
  userId: number;
  onConnected: () => void | Promise<void>;
};

export default function ConnectBankButton({
  userId,
  onConnected,
}: ConnectBankButtonProps) {
  const [linkToken, setLinkToken] =
    useState<string | null>(null);
  const [loading, setLoading] =
    useState(false);
  const [connecting, setConnecting] =
    useState(false);
  const [error, setError] = useState("");

  const onSuccess = useCallback<PlaidLinkOnSuccess>(
    async (publicToken, metadata) => {
      if (!publicToken) {
        setError(
          "Plaid did not return a valid public token."
        );
        return;
      }

      setConnecting(true);
      setError("");

      try {
        await api.exchangePlaidToken(
          userId,
          publicToken,
          metadata.institution?.institution_id ??
            null,
          metadata.institution?.name ?? null
        );

        setLinkToken(null);
        await onConnected();
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to connect bank account"
        );
      } finally {
        setConnecting(false);
      }
    },
    [userId, onConnected]
  );

  const {
    open,
    ready,
    error: plaidError,
  } = usePlaidLink({
    token: linkToken,
    onSuccess,
    onExit: (exitError) => {
      if (!exitError) return;

      setError(
        exitError.display_message ||
          exitError.error_message ||
          "Plaid Link closed unexpectedly"
      );
    },
  });

  useEffect(() => {
    if (!linkToken || !ready) return;

    open();
  }, [linkToken, ready, open]);

  async function startConnection() {
    setLoading(true);
    setError("");

    try {
      const response =
        await api.createPlaidLinkToken(userId);

      setLinkToken(response.link_token);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to start bank connection"
      );
    } finally {
      setLoading(false);
    }
  }

  const displayedError =
    error ||
    (plaidError
      ? "Unable to load Plaid Link"
      : "");

  return (
    <div>
      <button
        type="button"
        onClick={startConnection}
        disabled={loading || connecting}
        className="rounded-xl bg-[#45d7a4] px-5 py-3 text-sm font-semibold text-slate-950 shadow-lg shadow-emerald-500/20 transition hover:bg-[#5de3b3] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {connecting
          ? "Connecting account..."
          : loading
            ? "Preparing secure connection..."
            : "Connect bank"}
      </button>

      {displayedError && (
        <p className="mt-3 text-sm text-rose-300">
          {displayedError}
        </p>
      )}
    </div>
  );
}