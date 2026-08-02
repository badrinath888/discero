"use client";

import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "framer-motion";
import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useRef,
} from "react";

type MotionProps = {
  children: ReactNode;
  className?: string;
  delay?: number;
};

const staggerContext = createContext(false);

export function PageReveal({
  children,
  className = "",
}: Omit<MotionProps, "delay">) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: reduceMotion ? 0 : 0.55,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function Reveal({
  children,
  className = "",
  delay = 0,
}: MotionProps) {
  const reduceMotion = useReducedMotion();
  const insideStagger = useContext(staggerContext);

  if (insideStagger) {
    return (
      <motion.div
        variants={{
          hidden: { opacity: 0, y: 14, scale: 0.99 },
          visible: {
            opacity: 1,
            y: 0,
            scale: 1,
            transition: {
              duration: reduceMotion ? 0 : 0.48,
              ease: [0.22, 1, 0.36, 1],
            },
          },
        }}
        className={className}
      >
        {children}
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 14, scale: 0.99 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, amount: 0.12 }}
      transition={{
        duration: reduceMotion ? 0 : 0.48,
        delay: reduceMotion ? 0 : delay,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function Stagger({
  children,
  className = "",
}: Omit<MotionProps, "delay">) {
  const reduceMotion = useReducedMotion();

  return (
    <staggerContext.Provider value>
      <motion.div
        initial={reduceMotion ? false : "hidden"}
        whileInView="visible"
        viewport={{ once: true, amount: 0.08 }}
        variants={{
          hidden: {},
          visible: {
            transition: {
              staggerChildren: reduceMotion ? 0 : 0.08,
              delayChildren: reduceMotion ? 0 : 0.05,
            },
          },
        }}
        className={className}
      >
        {children}
      </motion.div>
    </staggerContext.Provider>
  );
}

export function HoverLift({
  children,
  className = "",
}: Omit<MotionProps, "delay">) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.div
      whileHover={
        reduceMotion
          ? undefined
          : {
              y: -3,
              transition: {
                duration: 0.22,
                ease: [0.22, 1, 0.36, 1],
              },
            }
      }
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function AnimatedNumber({
  value,
  format,
  className = "",
  duration = 0.8,
}: {
  value: number;
  format: (value: number) => string;
  className?: string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.5 });
  const reduceMotion = useReducedMotion();
  const progress = useMotionValue(reduceMotion ? value : 0);
  const display = useTransform(progress, (latest) =>
    format(Math.round(latest))
  );

  useEffect(() => {
    if (!inView) return;

    if (reduceMotion) {
      progress.set(value);
      return;
    }

    const controls = animate(progress, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
    });

    return controls.stop;
  }, [duration, inView, progress, reduceMotion, value]);

  return (
    <motion.span ref={ref} className={className}>
      {display}
    </motion.span>
  );
}
