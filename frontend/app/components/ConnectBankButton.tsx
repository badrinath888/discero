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
        className="discero-button-primary rounded-xl px-5 py-3 text-sm font-semibold transition disabled:cursor-not-allowed"
      >
        {connecting
          ? "Connecting account..."
          : loading
            ? "Preparing secure connection..."
            : "Connect bank"}
      </button>

      {displayedError && (
        <p className="mt-3 text-sm text-[#A25543]">
          {displayedError}
        </p>
      )}
    </div>
  );
}
