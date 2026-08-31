"use client";

import {
  FormEvent,
  ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import {
  AnimatePresence,
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
} from "framer-motion";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, session } from "./lib/api";

type Mode = "login" | "register";

const ease = [0.22, 1, 0.36, 1] as const;

export default function HomePage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [error, setError] = useState("");
  const [authOpen, setAuthOpen] = useState(false);

  useEffect(() => {
    async function validateSession() {
      const sessionNotice = session.consumeNotice();
      if (sessionNotice) setError(sessionNotice);

      const token = session.getToken();
      if (!token) {
        await Promise.resolve();
        setCheckingSession(false);
        return;
      }

      try {
        await api.getMe();
        router.replace("/dashboard");
      } catch {
        session.clear();
        setError(session.consumeNotice());
        setCheckingSession(false);
      }
    }

    void validateSession();
  }, [router]);

  useEffect(() => {
    if (!authOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [authOpen]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedEmail = email.trim().toLowerCase();

    if (!normalizedEmail) {
      setError("Enter your email address.");
      return;
    }
    if (password.length < 8) {
      setError("Password must contain at least 8 characters.");
      return;
    }
    if (mode === "register" && password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      if (mode === "register") await api.createUser(normalizedEmail, password);
      const auth = await api.login(normalizedEmail, password);
      session.save(auth);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  function changeMode(nextMode: Mode) {
    setMode(nextMode);
    setPassword("");
    setConfirmPassword("");
    setError("");
  }

  function openAuth(nextMode: Mode) {
    changeMode(nextMode);
    setAuthOpen(true);
  }

  function closeAuth() {
    setAuthOpen(false);
  }

  function scrollToId(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  }

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#F5F1EA] text-[#181713]">
        <div className="text-center">
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-[#6E4B63] border-t-transparent" />
          <p className="mt-4 text-sm text-[#777168]">Checking your session...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="relative bg-[#F5F1EA] text-[#181713]">
      <Navigation onSignIn={() => openAuth("login")} onTry={() => openAuth("register")} />

      <Hero onTry={() => openAuth("register")} onLearn={() => scrollToId("financial-state")} />
      <FinancialState />
      <DecisionRipple />
      <Receipt />
      <DecisionBreadth />
      <AskDiscero />
      <DecisionsOverTime />
      <FinalCTA onTry={() => openAuth("register")} onSignIn={() => openAuth("login")} />
      <Footer />

      <AnimatePresence>
        {authOpen && (
          <AuthOverlay
            mode={mode}
            email={email}
            password={password}
            confirmPassword={confirmPassword}
            loading={loading}
            error={error}
            onModeChange={changeMode}
            onEmailChange={setEmail}
            onPasswordChange={setPassword}
            onConfirmPasswordChange={setConfirmPassword}
            onSubmit={handleSubmit}
            onClose={closeAuth}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function Navigation({ onSignIn, onTry }: { onSignIn: () => void; onTry: () => void }) {
  return (
    <nav className="fixed inset-x-0 top-0 z-50 border-b border-[#181713]/[0.07] bg-[#F5F1EA]/90 px-5 backdrop-blur-xl sm:px-8">
      <div className="mx-auto flex h-20 max-w-[1240px] items-center justify-between">
        <span className="text-lg font-semibold">Discero</span>
        <div className="flex items-center gap-1 sm:gap-2">
          <button type="button" onClick={onSignIn} className="discero-button-tertiary rounded-full px-3 py-2.5 text-sm font-semibold transition sm:px-4">Sign in</button>
          <button type="button" onClick={onTry} className="discero-button-primary rounded-full px-4 py-2.5 text-sm font-semibold transition sm:px-5">Try Discero</button>
        </div>
      </div>
    </nav>
  );
}

function Hero({ onTry, onLearn }: { onTry: () => void; onLearn: () => void }) {
  return (
    <section className="relative overflow-hidden px-5 pb-16 pt-32 sm:px-8 sm:pt-40 lg:pb-20 lg:pt-44">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_82%_10%,rgba(110,75,99,0.16),transparent_28rem),radial-gradient(circle_at_8%_70%,rgba(184,109,75,0.12),transparent_26rem)]" />
      <div className="relative mx-auto grid max-w-[1240px] items-center gap-14 text-center lg:grid-cols-[1.05fr_0.95fr] lg:gap-16 lg:text-left">
        <HeroCopy onTry={onTry} onLearn={onLearn} />
        <HeroDecisionCard />
      </div>
      <HeroTransitionCue onClick={onLearn} />
    </section>
  );
}

function HeroTransitionCue({ onClick }: { onClick: () => void }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.button
      type="button"
      onClick={onClick}
      initial={reduceMotion ? false : { opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.5, delay: reduceMotion ? 0 : 0.95, ease }}
      className="relative mx-auto mt-12 flex flex-col items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-[#8A8178] transition hover:text-[#6E4B63] lg:mt-14"
    >
      See the math behind the number
      <span aria-hidden="true">&darr;</span>
    </motion.button>
  );
}

function HeroCopy({ onTry, onLearn }: { onTry: () => void; onLearn: () => void }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      animate="visible"
      variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.13 } } }}
    >
      <HeroItem>
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-[#181713]">Discero</p>
        <p className="mt-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Financial decision intelligence</p>
      </HeroItem>
      <HeroItem>
        <h1 className="mx-auto mt-6 max-w-3xl text-[clamp(3.1rem,7vw,6.2rem)] font-semibold leading-[0.96] tracking-[-0.01em] lg:mx-0">
          Discern before you decide.
        </h1>
      </HeroItem>
      <HeroItem>
        <p className="mx-auto mt-8 max-w-xl text-lg leading-8 text-[#777168] sm:text-xl lg:mx-0">
          See how a financial decision could affect your cash, goals, and financial resilience before you commit.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row lg:justify-start">
          <button type="button" onClick={onTry} className="discero-button-primary rounded-full px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">Try Discero</button>
          <button type="button" onClick={onLearn} className="discero-button-secondary rounded-full border px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">See how it works</button>
        </div>
      </HeroItem>
    </motion.div>
  );
}

function HeroDecisionCard() {
  const reduceMotion = useReducedMotion();
  const rowVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.32, ease } },
  };
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      animate="visible"
      variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.16, delayChildren: reduceMotion ? 0 : 0.3 } } }}
      className="relative mx-auto w-full max-w-[380px] rounded-2xl border border-[#181713]/10 bg-[#FFFCF7] p-6 shadow-[0_8px_24px_rgba(71,48,64,0.06)] lg:mx-0"
    >
      <IllustrativeBadge />

      <motion.div variants={rowVariants} className="mt-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Safe to spend</p>
        <p className="mt-2 text-3xl font-semibold tracking-[-0.02em] tabular-nums">$32,475</p>
      </motion.div>

      <motion.div variants={rowVariants} className="mt-4 flex items-center justify-between border-t border-[#181713]/8 pt-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Decision</p>
          <p className="mt-1 text-sm font-semibold">Laptop</p>
        </div>
        <p className="text-sm font-semibold text-[#B75C50]">&minus;$2,000</p>
      </motion.div>

      <motion.div variants={rowVariants} className="mt-4 flex items-center justify-between border-t border-[#181713]/8 pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Remaining</p>
        <p className="text-2xl font-semibold tracking-[-0.02em] tabular-nums text-[#6E4B63]">$30,475</p>
      </motion.div>

      <motion.div variants={rowVariants} className="mt-5 flex flex-wrap items-center gap-2 border-t border-[#181713]/8 pt-4">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#58715A]/30 bg-[#EEF1EB] px-3 py-1.5 text-xs font-semibold text-[#4E6A51]">
          <span aria-hidden="true">&#10003;</span> Goals protected
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#58715A]/30 bg-[#EEF1EB] px-3 py-1.5 text-xs font-semibold text-[#4E6A51]">
          Affordable
        </span>
        <span className="text-xs text-[#8A8178]">94% confidence</span>
      </motion.div>
    </motion.div>
  );
}

function IllustrativeBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[#181713]/12 bg-[#F8F4EE] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">
      Illustrative example
    </span>
  );
}

function FinancialState() {
  return (
    <section id="financial-state" className="bg-[#FFFCF7] px-5 pb-24 pt-14 sm:px-8 sm:pt-16 lg:pb-32 lg:pt-20">
      <Scene className="mx-auto max-w-[1240px]">
        <div className="grid gap-10 border-b border-[#181713]/10 pb-14 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">How Discero gets there</p>
              <IllustrativeBadge />
            </div>
            <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-5xl lg:text-6xl">
              Every number has a receipt.
            </h2>
          </div>
          <p className="max-w-lg text-lg leading-8 text-[#777168] lg:justify-self-end">
            Discero shows the financial inputs behind the amount — not just the answer.
          </p>
        </div>
        <FinancialReceipt />
      </Scene>
    </section>
  );
}

function FinancialReceipt() {
  const reduceMotion = useReducedMotion();
  const rowVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.32, ease } },
  };
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      whileInView="visible"
      viewport={{ once: true, amount: 0.3, margin: "-5% 0px" }}
      variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.12 } } }}
      className="mt-16 lg:ml-[8%] lg:w-[64%]"
    >
      <div className="rounded-2xl border border-[#181713]/10 bg-[#FFFCF7] p-7 shadow-[0_10px_32px_rgba(71,48,64,0.06)] sm:p-9">
        <motion.div variants={rowVariants} className="flex items-baseline justify-between gap-4">
          <span className="text-sm text-[#777168]">Liquid cash</span>
          <span className="text-base font-semibold tabular-nums">$26,500</span>
        </motion.div>
        <motion.div variants={rowVariants} className="mt-4 flex items-baseline justify-between gap-4">
          <span className="text-sm text-[#777168]">Expected income</span>
          <span className="text-base font-semibold tabular-nums text-[#58715A]">+$8,125</span>
        </motion.div>
        <motion.div variants={rowVariants} className="mt-4 flex items-baseline justify-between gap-4">
          <span className="text-sm text-[#777168]">Upcoming obligations</span>
          <span className="text-base font-semibold tabular-nums text-[#B75C50]">&minus;$2,150</span>
        </motion.div>

        <motion.div variants={rowVariants} className="my-6 border-t border-[#181713]/15" />

        <motion.div variants={rowVariants} className="flex items-baseline justify-between gap-4">
          <span className="text-sm font-semibold uppercase tracking-[0.1em] text-[#6E4B63]">Safe to spend</span>
          <span className="text-3xl font-semibold tracking-[-0.02em] tabular-nums text-[#6E4B63] sm:text-4xl">
            <AnimatedValue value={32475} format={money} />
          </span>
        </motion.div>

        <motion.div variants={rowVariants} className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-[#181713]/10 pt-5 text-sm text-[#777168]">
          <span>Goals protected</span>
          <span>Runway 8.3 months</span>
        </motion.div>
      </div>

      <p className="mt-4 text-xs text-[#8A8178]">Deterministic calculation</p>
    </motion.div>
  );
}

function DecisionRipple() {
  const reduceMotion = useReducedMotion();
  return (
    <div id="decision-ripple">
      {!reduceMotion && (
        <div className="hidden md:block">
          <DecisionRippleScroll />
        </div>
      )}
      <div className={reduceMotion ? "block" : "block md:hidden"}>
        <DecisionRippleSimple />
      </div>
    </div>
  );
}

function DecisionRippleScroll() {
  const sectionRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ["start start", "end end"] });

  const stage = (progress: number, from: number, to: number, start: number, end: number) => {
    const t = Math.min(1, Math.max(0, (progress - start) / (end - start)));
    return from + t * (to - from);
  };

  const hintOpacity = useTransform(scrollYProgress, (v) => stage(v, 1, 0, 0, 0.08));
  const railScale = scrollYProgress;

  const questionOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.05, 0.12));
  const questionY = useTransform(scrollYProgress, (v) => stage(v, 16, 0, 0.05, 0.12));

  const topLabelOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0, 0.05));

  const laptopOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.12, 0.2));
  const laptopY = useTransform(scrollYProgress, (v) => stage(v, 12, 0, 0.12, 0.2));

  const arrowDownOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.2, 0.26));

  const resultOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.22, 0.28));
  const resultValue = useTransform(scrollYProgress, (v) => stage(v, 32475, 30475, 0.24, 0.46));
  const resultDisplay = useTransform(resultValue, money);

  const equationScale = useTransform(scrollYProgress, (v) => stage(v, 1, 0.82, 0.46, 0.56));
  const equationY = useTransform(scrollYProgress, (v) => stage(v, 0, -32, 0.46, 0.56));

  const chipsRowOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.5, 0.56));
  const chip1Y = useTransform(scrollYProgress, (v) => stage(v, 14, 0, 0.5, 0.56));
  const chip2Y = useTransform(scrollYProgress, (v) => stage(v, 14, 0, 0.54, 0.6));
  const chip3Y = useTransform(scrollYProgress, (v) => stage(v, 14, 0, 0.58, 0.64));

  const verdictOpacity = useTransform(scrollYProgress, (v) => stage(v, 0, 1, 0.68, 0.8));
  const verdictScale = useTransform(scrollYProgress, (v) => stage(v, 0.92, 1, 0.68, 0.8));
  const confidenceValue = useTransform(scrollYProgress, (v) => stage(v, 0, 94, 0.72, 0.92));
  const confidenceDisplay = useTransform(confidenceValue, (value) => `${Math.round(value)}%`);

  return (
    <section ref={sectionRef} className="relative h-[440vh] bg-[#FFFCF7]">
      <div className="sticky top-0 flex h-[100svh] flex-col items-center justify-center overflow-hidden px-5 sm:px-8">
        <motion.div
          aria-hidden="true"
          style={{ scaleY: railScale }}
          className="absolute left-6 top-1/2 hidden h-40 w-px origin-top -translate-y-1/2 bg-[#6E4B63]/30 lg:block"
        />

        <div className="mx-auto w-full max-w-[760px] text-center">
          <IllustrativeBadge />

          <motion.h2 style={{ opacity: questionOpacity, y: questionY }} className="mt-6 text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
            Can I afford a $2,000 laptop?
          </motion.h2>

          <div className="relative mt-12">
            <motion.div style={{ scale: equationScale, y: equationY }}>
              <motion.p style={{ opacity: topLabelOpacity }} className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8A8178]">
                Current safe-to-spend
              </motion.p>
              <p className="mt-3 text-[clamp(2.6rem,7vw,4.6rem)] font-semibold tracking-[-0.02em] tabular-nums">$32,475</p>

              <motion.div style={{ opacity: laptopOpacity, y: laptopY }} className="mt-6 flex items-center justify-center gap-2 text-lg font-semibold text-[#B75C50]">
                <span aria-hidden="true">&darr;</span>
                <span>Laptop &minus;$2,000</span>
              </motion.div>

              <motion.span style={{ opacity: arrowDownOpacity }} aria-hidden="true" className="mt-4 block text-[#8A8178]">
                &darr;
              </motion.span>

              <motion.div style={{ opacity: resultOpacity }} className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Safe-to-spend after this decision</p>
                <motion.p className="mt-3 text-[clamp(2.6rem,7vw,4.6rem)] font-semibold tracking-[-0.02em] tabular-nums text-[#6E4B63]">
                  {resultDisplay}
                </motion.p>
              </motion.div>
            </motion.div>

            <motion.div style={{ opacity: chipsRowOpacity }} className="mt-10 grid grid-cols-3 gap-4 border-t border-[#181713]/10 pt-8 sm:gap-8">
              <motion.div style={{ y: chip1Y }}>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8A8178]">Goals</p>
                <p className="mt-2 text-sm font-semibold text-[#58715A] sm:text-base">Protected</p>
              </motion.div>
              <motion.div style={{ y: chip2Y }}>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8A8178]">Runway</p>
                <p className="mt-2 text-sm font-semibold sm:text-base">8.3 months</p>
              </motion.div>
              <motion.div style={{ y: chip3Y }}>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8A8178]">Obligations</p>
                <p className="mt-2 text-sm font-semibold text-[#58715A] sm:text-base">Covered</p>
              </motion.div>
            </motion.div>

            <motion.div style={{ opacity: verdictOpacity, scale: verdictScale }} className="mt-10">
              <span className="inline-flex items-center gap-2 rounded-full border border-[#58715A]/30 bg-[#EEF1EB] px-5 py-2.5 text-sm font-semibold text-[#4E6A51]">
                <span aria-hidden="true">&#10003;</span> Affordable
              </span>
              <p className="mt-3 text-sm text-[#777168]">
                <motion.span>{confidenceDisplay}</motion.span> confidence
              </p>
            </motion.div>
          </div>

          <motion.p style={{ opacity: hintOpacity }} className="mt-14 text-xs font-semibold uppercase tracking-[0.16em] text-[#8A8178]">
            Scroll to continue
          </motion.p>
        </div>
      </div>
    </section>
  );
}

function DecisionRippleSimple() {
  return (
    <section className="bg-[#FFFCF7] px-5 py-20 sm:px-8">
      <Scene className="mx-auto max-w-[640px] text-center">
        <IllustrativeBadge />
        <h2 className="mt-6 text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">Can I afford a $2,000 laptop?</h2>

        <div className="mt-10">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Current safe-to-spend</p>
          <p className="mt-3 text-4xl font-semibold tracking-[-0.02em] tabular-nums sm:text-5xl">$32,475</p>
          <p className="mt-5 text-lg font-semibold text-[#B75C50]">&darr; Laptop &minus;$2,000</p>
          <p className="mt-5 text-xs font-semibold uppercase tracking-[0.16em] text-[#8A8178]">Safe-to-spend after this decision</p>
          <p className="mt-3 text-4xl font-semibold tracking-[-0.02em] tabular-nums text-[#6E4B63] sm:text-5xl">$30,475</p>
        </div>

        <Stagger className="mt-10 grid grid-cols-3 gap-4 border-t border-[#181713]/10 pt-8">
          <RippleChip label="Goals" value="Protected" sage />
          <RippleChip label="Runway" value="8.3 months" />
          <RippleChip label="Obligations" value="Covered" sage />
        </Stagger>

        <div className="mt-10">
          <span className="inline-flex items-center gap-2 rounded-full border border-[#58715A]/30 bg-[#EEF1EB] px-5 py-2.5 text-sm font-semibold text-[#4E6A51]">
            <span aria-hidden="true">&#10003;</span> Affordable
          </span>
          <p className="mt-3 text-sm text-[#777168]">94% confidence</p>
        </div>
      </Scene>
    </section>
  );
}

function RippleChip({ label, value, sage = false }: { label: string; value: string; sage?: boolean }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div variants={{ hidden: { opacity: 0, y: 14 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.32, ease } } }}>
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#8A8178]">{label}</p>
      <p className={`mt-2 text-sm font-semibold sm:text-base ${sage ? "text-[#58715A]" : "text-[#181713]"}`}>{value}</p>
    </motion.div>
  );
}

function Receipt() {
  const rows: { label: string; value: string; sign?: "plus" | "minus" }[] = [
    { label: "Cash available", value: "$26,500" },
    { label: "Projected income", value: "$9,800", sign: "plus" },
    { label: "Known obligations", value: "$2,150", sign: "minus" },
    { label: "Protection / reserve", value: "$1,675", sign: "minus" },
  ];

  return (
    <section className="bg-[#F0E9E1] px-5 py-24 sm:px-8 lg:py-32">
      <Scene className="mx-auto max-w-[1240px]">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:items-start">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Discero principle</p>
            <h2 className="mt-5 max-w-lg text-4xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-5xl">
              Every recommendation has a receipt.
            </h2>
            <p className="mt-6 max-w-md text-lg leading-8 text-[#777168]">
              See what the decision is based on. Discero applies deterministic financial analysis, then explains the result in plain language.
            </p>
          </div>

          <Stagger className="divide-y divide-[#181713]/15 border-y border-[#181713]/15">
            {rows.map((row) => (
              <ReceiptRow key={row.label} {...row} />
            ))}
            <ReceiptRow label="Safe-to-spend" value="$32,475" strong />
            <ReceiptRow label="Decision · Laptop" value="$2,000" sign="minus" />
            <ReceiptRow label="Remaining room" value="$30,475" strong accent />
          </Stagger>
        </div>
      </Scene>
    </section>
  );
}

function ReceiptRow({
  label,
  value,
  sign,
  strong = false,
  accent = false,
}: {
  label: string;
  value: string;
  sign?: "plus" | "minus";
  strong?: boolean;
  accent?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, x: 24 }, visible: { opacity: 1, x: 0, transition: { duration: reduceMotion ? 0 : 0.4, ease } } }}
      className="flex items-center justify-between gap-4 py-5"
    >
      <span className={`text-sm sm:text-base ${strong ? "font-semibold text-[#181713]" : "text-[#777168]"}`}>{label}</span>
      <span className={`text-right text-sm font-semibold tabular-nums sm:text-base ${accent ? "text-[#6E4B63]" : "text-[#181713]"}`}>
        {sign === "minus" ? "− " : sign === "plus" ? "+ " : ""}
        {value}
      </span>
    </motion.div>
  );
}

function DecisionBreadth() {
  const steps = [
    { label: "Laptop purchase", detail: "A single upfront decision." },
    { label: "Buy now vs. wait", detail: "Compare timing, not just cost." },
    { label: "Income interruption", detail: "Model a paycheck that pauses." },
    { label: "Multi-step plan", detail: "Sequence several decisions together." },
  ];

  return (
    <section className="bg-[#FFFCF7] px-5 py-24 sm:px-8 lg:py-32">
      <Scene className="mx-auto max-w-[1240px]">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Beyond one decision</p>
          <h2 className="mt-5 text-4xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-5xl">
            The same analysis scales with the decision.
          </h2>
        </div>

        <Stagger className="mt-14 grid gap-8 border-t border-[#181713]/10 pt-10 sm:grid-cols-2 lg:grid-cols-4 lg:gap-0 lg:divide-x lg:divide-[#181713]/10">
          {steps.map((step, index) => (
            <BreadthStep key={step.label} index={index} {...step} />
          ))}
        </Stagger>
      </Scene>
    </section>
  );
}

function BreadthStep({ index, label, detail }: { index: number; label: string; detail: string }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.4, ease } } }}
      className="lg:px-8 lg:first:pl-0"
    >
      <span className="text-xs font-semibold text-[#B86D4B] tabular-nums">0{index + 1}</span>
      <p className="mt-3 text-lg font-semibold tracking-[-0.01em]">{label}</p>
      <p className="mt-2 text-sm leading-6 text-[#777168]">{detail}</p>
    </motion.div>
  );
}

function AskDiscero() {
  return (
    <section className="bg-[#1B1A18] px-5 py-24 text-[#F5F1EA] sm:px-8 lg:py-32">
      <Scene className="mx-auto max-w-[1240px]">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#C89A78]">Ask Discero</p>
          <h2 className="mt-5 text-4xl font-semibold leading-[1.05] tracking-[0em] sm:text-5xl">
            Ask a question.
            <span className="block">See the consequence.</span>
          </h2>
        </div>

        <AskSequence />

        <p className="mt-10 max-w-xl text-sm text-[#AAA39A]">Calculated from financial data. Explained in plain language.</p>
      </Scene>
    </section>
  );
}

function AskSequence() {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      whileInView="visible"
      viewport={{ once: true, amount: 0.25, margin: "-5% 0px" }}
      className="relative mt-14 border-y border-white/15 bg-white/[0.025] px-5 py-8 sm:px-8 lg:px-10 lg:py-10"
    >
      <motion.p
        variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.3, ease } } }}
        className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8F8981]"
      >
        Your question
      </motion.p>
      <motion.h3
        variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.34, delay: reduceMotion ? 0 : 0.05, ease } } }}
        className="mt-4 text-2xl font-semibold tracking-[-0.02em] sm:text-3xl"
      >
        How much can I safely spend right now?
      </motion.h3>

      <motion.p
        variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 0.4 } } }}
        className="mt-6 text-sm font-medium text-[#91A990]"
      >
        Deterministic analysis complete
      </motion.p>

      <motion.p
        variants={{ hidden: { opacity: 0, y: 14 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.36, delay: reduceMotion ? 0 : 0.5, ease } } }}
        className="mt-4 text-[clamp(2.6rem,6vw,4.2rem)] font-semibold leading-none tracking-[-0.03em] tabular-nums text-[#D3A963]"
      >
        $32,475
      </motion.p>

      <motion.p
        variants={{ hidden: { opacity: 0, y: 14 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.36, delay: reduceMotion ? 0 : 0.62, ease } } }}
        className="mt-6 max-w-2xl border-t border-white/10 pt-6 text-base leading-7 text-[#D8D2C8]"
      >
        Based on your current cash, expected income, and known obligations, this is what you can spend without affecting your goals or runway.
      </motion.p>
    </motion.div>
  );
}

function DecisionsOverTime() {
  const stages = [
    { label: "Plan", detail: "Model the decision before committing." },
    { label: "Act", detail: "Move forward with confidence." },
    { label: "Review", detail: "See how the outcome played out." },
    { label: "Learn", detail: "Future recommendations get sharper." },
  ];

  return (
    <section className="bg-[#F0E9E1] px-5 py-24 sm:px-8 lg:py-32">
      <Scene className="mx-auto max-w-[1240px]">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Decisions over time</p>
          <h2 className="mt-5 text-4xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-5xl">
            Every decision sharpens the next one.
          </h2>
        </div>

        <div className="relative mt-14">
          <div aria-hidden="true" className="pointer-events-none absolute left-[1.125rem] top-0 bottom-0 w-px bg-[#6E4B63]/25 lg:hidden" />
          <div aria-hidden="true" className="pointer-events-none absolute left-[12.5%] right-[12.5%] top-[1.125rem] hidden h-px bg-[#6E4B63]/25 lg:block" />
          <Stagger className="relative grid grid-cols-1 gap-8 lg:grid-cols-4 lg:gap-6">
            {stages.map((stage, index) => (
              <LifecycleStage key={stage.label} index={index} {...stage} />
            ))}
          </Stagger>
        </div>
      </Scene>
    </section>
  );
}

function LifecycleStage({ index, label, detail }: { index: number; label: string; detail: string }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.36, ease } } }}
      className="relative flex items-start gap-4 lg:flex-col lg:items-center lg:gap-0 lg:text-center"
    >
      <span className="relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-[#6E4B63]/30 bg-[#F0E9E1] text-xs font-semibold text-[#6E4B63]">
        {index + 1}
      </span>
      <div className="lg:mt-4">
        <p className="text-lg font-semibold tracking-[-0.01em]">{label}</p>
        <p className="mt-1 text-sm leading-6 text-[#777168] lg:mt-2">{detail}</p>
      </div>
    </motion.div>
  );
}

function FinalCTA({ onTry, onSignIn }: { onTry: () => void; onSignIn: () => void }) {
  return (
    <section className="bg-[#F5F1EA] px-5 py-28 text-center sm:px-8 lg:py-36">
      <Scene className="mx-auto max-w-[720px]">
        <h2 className="text-4xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-5xl lg:text-6xl">
          See what your next decision means.
        </h2>
        <p className="mx-auto mt-5 max-w-md text-lg leading-8 text-[#777168]">
          See how a decision changes your numbers, before you make it.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <button type="button" onClick={onTry} className="discero-button-primary rounded-full px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">Try Discero</button>
          <button type="button" onClick={onSignIn} className="discero-button-secondary rounded-full border px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">Sign in</button>
        </div>
      </Scene>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[#181713]/10 bg-[#F5F1EA] px-5 py-8 sm:px-8">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-3 text-sm text-[#777168] sm:flex-row sm:items-center sm:justify-between">
        <p className="font-semibold text-[#181713]">Discero</p>
        <p>Financial analysis is informational and is not financial advice.</p>
      </div>
    </footer>
  );
}

function AuthOverlay({
  mode,
  email,
  password,
  confirmPassword,
  loading,
  error,
  onModeChange,
  onEmailChange,
  onPasswordChange,
  onConfirmPasswordChange,
  onSubmit,
  onClose,
}: {
  mode: Mode;
  email: string;
  password: string;
  confirmPassword: string;
  loading: boolean;
  error: string;
  onModeChange: (mode: Mode) => void;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const titleId = useId();

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <motion.div
      className="fixed inset-0 z-[60] flex items-center justify-center px-4 py-8"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
    >
      <button
        type="button"
        aria-label="Close sign in"
        onClick={onClose}
        className="absolute inset-0 bg-[#181713]/45 backdrop-blur-[3px]"
      />

      <motion.section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        initial={reduceMotion ? false : { opacity: 0, scale: 0.97, y: 14 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: 14 }}
        transition={{ duration: reduceMotion ? 0 : 0.24, ease }}
        className="relative w-full max-w-md bg-[#FFFCF7] p-6 shadow-[0_30px_90px_rgba(60,43,35,0.22)] ring-1 ring-[#181713]/10 sm:p-8"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="absolute right-5 top-5 flex h-8 w-8 items-center justify-center rounded-full text-[#777168] transition hover:bg-[#181713]/5 hover:text-[#181713]"
        >
          &#10005;
        </button>

        <Link href="/" onClick={onClose} className="text-sm font-semibold">Discero</Link>

        <div className="mt-6 grid grid-cols-2 border border-[#181713]/10 p-1">
          {(["login", "register"] as Mode[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onModeChange(item)}
              className={`px-4 py-2.5 text-sm font-semibold transition ${mode === item ? "bg-[var(--brand)] text-white" : "text-[#777168] hover:text-[#181713]"}`}
            >
              {item === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <h2 id={titleId} className="mt-5 text-2xl font-semibold tracking-[-0.02em]">
          {mode === "login" ? "Welcome back" : "Try Discero"}
        </h2>
        <p className="mt-2 text-sm leading-6 text-[#777168]">
          {mode === "login" ? "Sign in to continue your decision analysis." : "Create an account to evaluate financial decisions."}
        </p>

        <form onSubmit={onSubmit} className="mt-5 space-y-3">
          <AuthInput label="Email address" type="email" autoComplete="email" value={email} placeholder="you@example.com" onChange={onEmailChange} />
          <AuthInput
            label="Password"
            type="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            placeholder="Minimum 8 characters"
            onChange={onPasswordChange}
          />
          <div className="flex min-h-[4.5rem] items-center justify-end">
            {mode === "register" ? (
              <div className="w-full">
                <AuthInput label="Confirm password" type="password" autoComplete="new-password" value={confirmPassword} placeholder="Repeat your password" onChange={onConfirmPasswordChange} />
              </div>
            ) : (
              <Link href="/forgot-password" onClick={onClose} className="text-sm font-semibold text-[#6E4B63]">Forgot password?</Link>
            )}
          </div>
          {error && <div role="alert" className="border border-[#B75C50]/25 bg-[#F6E5E0] px-4 py-3 text-sm text-[#96493F]">{error}</div>}
          <button type="submit" disabled={loading} className="discero-button-primary w-full rounded-full px-5 py-3.5 text-sm font-semibold transition disabled:cursor-not-allowed">
            {loading ? "Please wait..." : mode === "login" ? "Sign in to Discero" : "Create my account"}
          </button>
        </form>
      </motion.section>
    </motion.div>
  );
}

function AuthInput({ label, onChange, ...props }: { label: string; type: string; autoComplete: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-[#706961]">{label}</span>
      <input
        {...props}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 w-full border border-[#181713]/10 bg-[#F8F4EE] px-4 py-3 text-sm outline-none transition placeholder:text-[#A49D95] focus:border-[#6E4B63] focus:ring-2 focus:ring-[#6E4B63]/15"
      />
    </label>
  );
}

function AnimatedValue({ value, format, delay = 0, duration = 0.82, once = true }: { value: number; format: (value: number) => string; delay?: number; duration?: number; once?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once, amount: 0.65 });
  const reduceMotion = useReducedMotion();
  const progress = useMotionValue(reduceMotion ? value : 0);
  const display = useTransform(progress, format);

  useEffect(() => {
    if (!inView) {
      if (!once && !reduceMotion) progress.set(0);
      return;
    }
    if (reduceMotion) {
      progress.set(value);
      return;
    }
    const controls = animate(progress, value, { duration, delay, ease });
    return controls.stop;
  }, [delay, duration, inView, once, progress, reduceMotion, value]);

  return <motion.span ref={ref} className="tabular-nums">{display}</motion.span>;
}

function Scene({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 64, scale: 0.985 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true, amount: 0.13 }}
      transition={{ duration: reduceMotion ? 0 : 0.72, ease }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function Stagger({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      whileInView="visible"
      viewport={{ once: true, amount: 0.2 }}
      variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.12 } } }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

function HeroItem({ children }: { children: ReactNode }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div variants={{ hidden: { opacity: 0, y: 34, filter: "blur(7px)" }, visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: reduceMotion ? 0 : 0.55, ease } } }}>
      {children}
    </motion.div>
  );
}

function money(value: number) {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}
