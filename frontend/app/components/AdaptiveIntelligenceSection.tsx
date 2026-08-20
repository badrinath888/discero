"use client";

import { useEffect, useState } from "react";
import { api, DecisionAdaptiveIntelligence } from "../lib/api";

export default function AdaptiveIntelligenceSection({
  userId,
}: {
  userId: number;
}) {
  const [data, setData] = useState<DecisionAdaptiveIntelligence | null>(
    null
  );

  useEffect(() => {
    let cancelled = false;

    api
      .getDecisionAdaptiveIntelligence(userId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      // Historical context is a secondary, restrained section -- a
      // failure here must never affect the deterministic result above
      // it, so it silently stays hidden rather than showing an error.
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (data === null || data.status === "insufficient_data") return null;

  return (
    <div
      data-testid="adaptive-intelligence-section"
      className="rounded-2xl border border-[#181713]/10 bg-[#F8F4EE] px-4 py-3.5"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#6E4B63]">
        Your decision history
      </p>
      <p className="mt-1.5 text-xs leading-5 text-[#5F5751]">
        {data.narrative}
      </p>
      <p className="mt-1.5 text-[11px] leading-5 text-[#8a978f]">
        Historical context only -- it does not change the calculation
        above.
      </p>
    </div>
  );
}
