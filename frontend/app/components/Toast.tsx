"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, CircleAlert, X } from "lucide-react";

export type ToastType = "success" | "error";

type ToastProps = {
  message: string;
  type: ToastType;
  onClose: () => void;
};

export default function Toast({
  message,
  type,
  onClose,
}: ToastProps) {
  const reduceMotion = useReducedMotion();
  const isSuccess = type === "success";

  return (
    <AnimatePresence>
      {message && (
        <motion.div
          role={isSuccess ? "status" : "alert"}
          aria-live={isSuccess ? "polite" : "assertive"}
          initial={
            reduceMotion
              ? false
              : { opacity: 0, y: -14, scale: 0.97 }
          }
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -10, scale: 0.97 }}
          transition={{
            duration: reduceMotion ? 0 : 0.2,
            ease: [0.22, 1, 0.36, 1],
          }}
          className={`fixed right-4 top-20 z-[70] flex w-[calc(100%-2rem)] max-w-sm items-start gap-3 rounded-2xl border px-4 py-3.5 shadow-[0_20px_55px_rgba(20,36,30,0.22)] sm:right-6 sm:top-6 ${
            isSuccess
              ? "border-[#167c5a]/25 bg-[#edf7f0] text-[#0f5f43]"
              : "border-[#a64b3d]/25 bg-[#fff3ef] text-[#8f3f33]"
          }`}
        >
          <span
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-white ${
              isSuccess ? "bg-[#167c5a]" : "bg-[#a64b3d]"
            }`}
          >
            {isSuccess ? (
              <Check className="h-4 w-4" />
            ) : (
              <CircleAlert className="h-4 w-4" />
            )}
          </span>

          <p className="min-w-0 flex-1 text-sm font-semibold leading-6">
            {message}
          </p>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close notification"
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition hover:bg-black/[0.06]"
          >
            <X className="h-4 w-4" />
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
