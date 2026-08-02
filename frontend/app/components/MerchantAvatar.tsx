"use client";

import {
  Coffee,
  Film,
  Music2,
  ShoppingBag,
  ShoppingCart,
  Store,
  Utensils,
} from "lucide-react";

type MerchantAvatarProps = {
  merchant: string;
  category?: string | null;
  size?: "sm" | "md";
};

const MERCHANT_STYLES: Array<{
  matches: string[];
  label: string;
  className: string;
}> = [
  { matches: ["spotify"], label: "S", className: "bg-[#1DB954] text-white" },
  { matches: ["netflix"], label: "N", className: "bg-[#E50914] text-white" },
  { matches: ["amazon", "amzn"], label: "a", className: "bg-[#232F3E] text-white" },
  { matches: ["apple", "itunes"], label: "", className: "bg-black text-white" },
  { matches: ["uber"], label: "U", className: "bg-black text-white" },
  { matches: ["starbucks"], label: "S", className: "bg-[#00754A] text-white" },
  { matches: ["walmart"], label: "W", className: "bg-[#0071CE] text-white" },
  { matches: ["target"], label: "◎", className: "bg-[#CC0000] text-white" },
  { matches: ["youtube"], label: "▶", className: "bg-[#FF0000] text-white" },
  { matches: ["hulu"], label: "h", className: "bg-[#1CE783] text-[#102217]" },
  { matches: ["disney"], label: "D+", className: "bg-[#113CCF] text-white" },
];

function initials(value: string) {
  const words = value
    .replace(/[^a-zA-Z0-9 ]/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();

  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}

function CategoryIcon({ category }: { category?: string | null }) {
  const normalized = category?.toLowerCase() ?? "";

  if (normalized.includes("dining")) return <Utensils className="h-4 w-4" />;
  if (normalized.includes("grocer")) return <ShoppingCart className="h-4 w-4" />;
  if (normalized.includes("shopping")) return <ShoppingBag className="h-4 w-4" />;
  if (normalized.includes("coffee")) return <Coffee className="h-4 w-4" />;
  if (normalized.includes("entertainment")) return <Film className="h-4 w-4" />;
  if (normalized.includes("subscription")) return <Music2 className="h-4 w-4" />;

  return <Store className="h-4 w-4" />;
}

export default function MerchantAvatar({
  merchant,
  category,
  size = "md",
}: MerchantAvatarProps) {
  const normalized = merchant.toLowerCase();
  const known = MERCHANT_STYLES.find(({ matches }) =>
    matches.some((match) => normalized.includes(match))
  );

  const dimensions =
    size === "sm"
      ? "h-9 w-9 rounded-xl text-xs"
      : "h-11 w-11 rounded-2xl text-sm";

  if (known) {
    return (
      <span
        aria-label={`${merchant} merchant mark`}
        className={`flex shrink-0 items-center justify-center font-bold shadow-sm ${dimensions} ${known.className}`}
      >
        {known.label}
      </span>
    );
  }

  const fallback = initials(merchant);

  return (
    <span
      aria-label={`${merchant} merchant`}
      className={`flex shrink-0 items-center justify-center border border-[#14241e]/8 bg-[#edf5ee] font-semibold text-[#167c5a] ${dimensions}`}
    >
      {fallback === "?" ? <CategoryIcon category={category} /> : fallback}
    </span>
  );
}
