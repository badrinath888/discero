"use client";

import { ReactNode, useEffect, useId } from "react";
import { motion, useReducedMotion } from "framer-motion";

type ConfirmationModalProps = {
  eyebrow: string;
  title: string;
  description: string;
  cancelLabel: string;
  confirmLabel: string;
  busyLabel: string;
  busy: boolean;
  icon: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function ConfirmationModal({
  eyebrow,
  title,
  description,
  cancelLabel,
  confirmLabel,
  busyLabel,
  busy,
  icon,
  onCancel,
  onConfirm,
}: ConfirmationModalProps) {
  const reduceMotion = useReducedMotion();
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        onCancel();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [busy, onCancel]);

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center px-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.18 }}
    >
      <button
        type="button"
        aria-label="Close confirmation"
        onClick={onCancel}
        disabled={busy}
        className="absolute inset-0 bg-[#14241e]/45 backdrop-blur-[3px]"
      />

      <motion.section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        initial={
          reduceMotion
            ? false
            : { opacity: 0, scale: 0.96, y: 16 }
        }
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 16 }}
        transition={{
          duration: reduceMotion ? 0 : 0.22,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="relative w-full max-w-md rounded-[28px] border border-[#14241e]/10 bg-[#fdfcf8] p-6 shadow-[0_30px_90px_rgba(20,36,30,0.28)] sm:p-7"
      >
        <div className="flex items-start gap-4">
          <span
            aria-hidden="true"
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f6e6e1] text-[#a64b3d]"
          >
            {icon}
          </span>

          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#a64b3d]">
              {eyebrow}
            </p>

            <h2
              id={titleId}
              className="mt-2 text-2xl font-semibold tracking-[-0.04em]"
            >
              {title}
            </h2>
          </div>
        </div>

        <p
          id={descriptionId}
          className="mt-5 text-sm leading-6 text-[#66746e]"
        >
          {description}
        </p>

        <div className="mt-7 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="min-h-11 rounded-full border border-[#14241e]/10 bg-white px-5 text-sm font-semibold transition hover:bg-[#f5f1e8] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cancelLabel}
          </button>

          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="inline-flex min-h-11 items-center justify-center rounded-full bg-[#a64b3d] px-5 text-sm font-semibold text-white transition hover:bg-[#8f3f33] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? busyLabel : confirmLabel}
          </button>
        </div>
      </motion.section>
    </motion.div>
  );
}
