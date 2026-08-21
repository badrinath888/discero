"use client";

import { useEffect, useState } from "react";
import { api, DataFreshness } from "../lib/api";

export default function DataFreshnessNote({ userId }: { userId: number }) {
  const [data, setData] = useState<DataFreshness | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .getDataFreshness(userId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      // A compact, secondary note -- a failure here must never affect
      // the deterministic result above it, so it silently stays
      // hidden rather than showing an error.
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (data === null || data.freshness_status === "unavailable") return null;

  return (
    <p
      data-testid="data-freshness-note"
      className="text-[11px] leading-5 text-[#8a978f]"
    >
      {data.notices.join(" ")}
    </p>
  );
}
