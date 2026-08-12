"use client";

import {
  FormEvent,
  ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
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

  function scrollTo(id: string, nextMode?: Mode) {
    if (nextMode) changeMode(nextMode);
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
    <main className="overflow-hidden bg-[#F5F1EA] text-[#181713]">
      <Navigation
        onSignIn={() => scrollTo("access", "login")}
        onTry={() => scrollTo("access", "register")}
      />

      <section className="relative px-5 pb-24 pt-32 sm:px-8 sm:pt-36 lg:pb-36 lg:pt-44">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_82%_18%,rgba(110,75,99,0.13),transparent_28rem),radial-gradient(circle_at_10%_85%,rgba(184,109,75,0.08),transparent_24rem)]" />
        <div className="relative mx-auto grid max-w-[1240px] gap-16 lg:grid-cols-[minmax(0,0.86fr)_minmax(0,1.14fr)] lg:items-center">
          <HeroCopy
            onTry={() => scrollTo("access", "register")}
            onLearn={() => scrollTo("problem")}
          />
          <DecisionPreview />
        </div>
      </section>

      <section id="problem" className="bg-[#FFFCF7] px-5 py-24 sm:px-8 lg:py-36">
        <Scene className="mx-auto max-w-[1240px]">
          <div className="grid gap-12 border-b border-[#181713]/10 pb-14 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
            <h2 className="max-w-4xl text-5xl font-semibold leading-[1] tracking-[-0.035em] sm:text-6xl">
              Your money is connected.
              <span className="mt-2 block text-[#8A8178]">Your decisions usually aren&apos;t.</span>
            </h2>
            <p className="max-w-lg text-lg leading-8 text-[#777168] lg:justify-self-end">
              Balances, transactions, goals, and recurring commitments all shape what a decision really costs.
            </p>
          </div>
          <DecisionFlow />
        </Scene>
      </section>

      <section id="examples" className="bg-[#F0E9E1] px-5 py-24 sm:px-8 lg:py-36">
        <Scene className="mx-auto max-w-[1240px]">
          <DecisionExamples />
        </Scene>
      </section>

      <section className="bg-[#1B1A18] px-5 py-24 text-[#F5F1EA] sm:px-8 lg:py-36">
        <Scene className="mx-auto max-w-[1240px]">
          <div className="space-y-12 lg:space-y-14">
            <AskIntro />
            <AnalysisPreview />
          </div>
        </Scene>
      </section>

      <section className="bg-[#FFFCF7] px-5 py-24 sm:px-8 lg:py-36">
        <Scene className="mx-auto max-w-[1240px]">
          <div className="grid gap-16 lg:grid-cols-[1.05fr_0.95fr] lg:items-start">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Discero principle</p>
              <h2 className="mt-5 max-w-3xl text-5xl font-semibold leading-[1] tracking-[-0.035em] sm:text-6xl">
                Calculations first.
                <span className="block text-[#B86D4B]">Explanation second.</span>
              </h2>
              <p className="mt-6 max-w-lg text-lg leading-8 text-[#777168]">Discero applies deterministic financial analysis, then explains the result in plain language.</p>
            </div>
            <Stagger className="divide-y divide-[#181713]/10 border-y border-[#181713]/10">
              <TrustRow number="01" title="Grounded inputs" detail="Balances, transactions, goals, and recurring commitments provide the inputs." />
              <TrustRow number="02" title="Visible confidence" detail="Confidence appears when the available data supports it." />
              <TrustRow number="03" title="Clear consequences" detail="Cash, goal, and runway effects are shown before you commit." />
            </Stagger>
          </div>
        </Scene>
      </section>

      <section id="access" className="bg-[#E9DDD3] px-5 py-16 sm:px-8 lg:py-20">
        <Scene className="mx-auto grid max-w-[1240px] gap-10 lg:grid-cols-[0.92fr_1.08fr] lg:items-start lg:gap-12">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Before the commitment</p>
            <h2 className="mt-4 text-5xl font-semibold leading-[1] tracking-[-0.035em] sm:text-6xl">Discern before you decide.</h2>
            <p className="mt-5 max-w-lg text-lg leading-8 text-[#777168]">Understand what a commitment could change before you make it.</p>
          </div>
          <AuthenticationCard
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
          />
        </Scene>
      </section>

      <footer className="border-t border-[#181713]/10 bg-[#F5F1EA] px-5 py-8 sm:px-8">
        <div className="mx-auto flex max-w-[1240px] flex-col gap-3 text-sm text-[#777168] sm:flex-row sm:items-center sm:justify-between">
          <p className="font-semibold text-[#181713]">Discero</p>
          <p>Financial analysis is informational and is not financial advice.</p>
        </div>
      </footer>
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

function HeroCopy({ onTry, onLearn }: { onTry: () => void; onLearn: () => void }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : "hidden"}
      animate="visible"
      variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.13 } } }}
    >
      <HeroItem><p className="text-lg font-semibold uppercase tracking-[0.12em] text-[#181713]">Discero</p><p className="mt-2 text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Financial decision intelligence</p></HeroItem>
      <HeroItem><h1 style={{ wordSpacing: "0.14em" }} className="mt-6 max-w-3xl text-[clamp(3.7rem,7.2vw,6.7rem)] font-semibold leading-[0.9] tracking-[0em]">Discern before you decide.</h1></HeroItem>
      <HeroItem>
        <p className="mt-8 max-w-xl text-lg leading-8 text-[#777168] sm:text-xl">See how a financial decision could affect your cash, goals, and financial resilience before you commit.</p>
        <div className="mt-9 flex flex-col gap-3 sm:flex-row">
          <button type="button" onClick={onTry} className="discero-button-primary rounded-full px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">Try Discero</button>
          <button type="button" onClick={onLearn} className="discero-button-secondary rounded-full border px-6 py-3.5 text-sm font-semibold transition hover:-translate-y-0.5">See how it works</button>
        </div>
      </HeroItem>
    </motion.div>
  );
}

function DecisionPreview() {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, x: 42, scale: 0.96 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.62, delay: reduceMotion ? 0 : 0.38, ease }}
      className="relative mx-auto w-full max-w-[620px]"
    >
      <div className="absolute -inset-10 -z-10 bg-[radial-gradient(circle,rgba(110,75,99,0.16),transparent_65%)]" />
      <div className="overflow-hidden rounded-[18px] bg-[#FFFCF7] shadow-[0_32px_90px_rgba(50,37,43,0.16)] ring-1 ring-[#181713]/10">
        <div className="flex items-center justify-between border-b border-[#181713]/10 px-5 py-4 sm:px-7">
          <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-[#B75C50]" /><span className="h-2 w-2 rounded-full bg-[#C59A52]" /><span className="h-2 w-2 rounded-full bg-[#58715A]" /></div>
          <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#968D84]">Decision / 01</span>
        </div>
        <div className="p-5 sm:p-8">
          <motion.p initial={reduceMotion ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduceMotion ? 0 : 0.42, delay: reduceMotion ? 0 : 0.58, ease }} className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8A8178]">Decision analysis</motion.p>
          <motion.h2 initial={reduceMotion ? false : { opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: reduceMotion ? 0 : 0.48, delay: reduceMotion ? 0 : 0.66, ease }} className="mt-4 text-2xl font-semibold tracking-[-0.025em] sm:text-3xl">Can I afford a $2,000 laptop?</motion.h2>
          <motion.div initial={reduceMotion ? false : { opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: reduceMotion ? 0 : 0.42, delay: reduceMotion ? 0 : 0.76, ease }} className="mt-7 flex items-center justify-between border-y border-[#58715A]/25 bg-[#EEF1EB] px-1 py-4 sm:px-2">
            <div><p className="text-xs text-[#687868]">Result</p><p className="mt-1 text-xl font-semibold text-[#4E6A51]">Affordable</p></div>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#58715A] text-white">✓</span>
          </motion.div>
          <motion.div initial={reduceMotion ? false : "hidden"} animate="visible" variants={{ hidden: {}, visible: { transition: { delayChildren: reduceMotion ? 0 : 0.82, staggerChildren: reduceMotion ? 0 : 0.09 } } }} className="mt-4 divide-y divide-[#181713]/10">
            <ResultRow label="Safe to spend">
              <AnimatedValue value={27406} format={money} delay={0.05} />
              <span className="mx-1.5 text-[#B86D4B]">→</span>
              <AnimatedValue value={25406} format={money} delay={0.14} />
            </ResultRow>
            <ResultRow label="Goals"><span className="text-[#58715A]">Unaffected</span></ResultRow>
            <ResultRow label="Runway"><AnimatedValue value={8.3} format={(value) => `${value.toFixed(1)} months`} /></ResultRow>
            <ResultRow label="Confidence"><span className="text-[#6E4B63]"><AnimatedValue value={94} format={(value) => `${Math.round(value)}%`} /></span></ResultRow>
          </motion.div>
          <motion.p initial={reduceMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reduceMotion ? 0 : 0.4, delay: reduceMotion ? 0 : 1.15 }} className="mt-5 text-xs text-[#938A81]">Based on current balances, recurring commitments, and active goals.</motion.p>
        </div>
      </div>
    </motion.div>
  );
}

function ResultRow({ label, children }: { label: string; children: ReactNode }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div variants={{ hidden: { opacity: 0, x: 24 }, visible: { opacity: 1, x: 0, transition: { duration: reduceMotion ? 0 : 0.42, ease } } }} className="flex items-center justify-between gap-4 py-4">
      <span className="text-sm text-[#777168]">{label}</span>
      <span className="text-right text-sm font-semibold sm:text-base">{children}</span>
    </motion.div>
  );
}

function DecisionFlow() {
  const reduceMotion = useReducedMotion();
  const sources = [
    { icon: "◒", label: "Accounts", detail: "$27,406 available" },
    { icon: "↕", label: "Transactions", detail: "$2,000 evaluated" },
    { icon: "◎", label: "Goals", detail: "68% funded" },
    { icon: "↻", label: "Recurring commitments", detail: "Included in analysis" },
  ];
  const signalPaths = [
    { path: "M 300 54 C 386 54 398 126 476 160", x: [300, 365, 420, 476], y: [54, 70, 124, 160] },
    { path: "M 300 120 C 388 120 414 146 476 160", x: [300, 370, 425, 476], y: [120, 124, 146, 160] },
    { path: "M 300 200 C 388 200 414 174 476 160", x: [300, 370, 425, 476], y: [200, 196, 174, 160] },
    { path: "M 300 266 C 386 266 398 194 476 160", x: [300, 365, 420, 476], y: [266, 250, 196, 160] },
  ];
  return (
    <motion.div initial={reduceMotion ? false : "hidden"} whileInView="visible" viewport={{ once: false, amount: 0.25, margin: "-5% 0px" }} className="relative mt-16 grid gap-10 lg:min-h-[320px] lg:grid-cols-[0.34fr_0.25fr_0.41fr] lg:items-center lg:gap-0">
      <svg aria-hidden="true" viewBox="0 0 1000 320" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 hidden h-full w-full overflow-visible lg:block">
        {signalPaths.map((signal, index) => (
          <g key={signal.path}>
            <motion.path d={signal.path} fill="none" stroke={index % 2 === 0 ? "#B86D4B" : "#6E4B63"} strokeOpacity="0.32" strokeWidth="1" vectorEffect="non-scaling-stroke" variants={{ hidden: { pathLength: 0, opacity: 0 }, visible: { pathLength: 1, opacity: 1, transition: { pathLength: { duration: reduceMotion ? 0 : 0.42, delay: reduceMotion ? 0 : 0.3 + index * 0.06, ease }, opacity: { duration: reduceMotion ? 0 : 0.18, delay: reduceMotion ? 0 : 0.3 + index * 0.06 } } } }} />
            <motion.circle r="3.2" fill={index % 2 === 0 ? "#B86D4B" : "#6E4B63"} variants={{ hidden: { opacity: 0, cx: signal.x[0], cy: signal.y[0] }, visible: { opacity: [0, 1, 1, 0], cx: signal.x, cy: signal.y, transition: { duration: reduceMotion ? 0 : 0.46, delay: reduceMotion ? 0 : 0.42 + index * 0.06, ease } } }} />
          </g>
        ))}
        <motion.path d="M 548 160 C 566 160 576 148 592 148" fill="none" stroke="#B86D4B" strokeOpacity="0.4" strokeWidth="1" vectorEffect="non-scaling-stroke" variants={{ hidden: { pathLength: 0, opacity: 0 }, visible: { pathLength: 1, opacity: 1, transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 1.08, ease } } }} />
        <motion.circle r="3" fill="#B86D4B" variants={{ hidden: { opacity: 0, cx: 548, cy: 160 }, visible: { opacity: [0, 1, 1, 0], cx: [548, 566, 580, 592], cy: [160, 158, 151, 148], transition: { duration: reduceMotion ? 0 : 0.34, delay: reduceMotion ? 0 : 1.12, ease } } }} />
      </svg>

      <div className="relative z-10 grid grid-cols-2 gap-x-7 gap-y-8 lg:grid-cols-1 lg:gap-y-6">
        {sources.map((source, index) => (
          <motion.div
            key={source.label}
            variants={{ hidden: { opacity: 0, x: -18 }, visible: { opacity: 1, x: 0, transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : index * 0.08, ease } } }}
            whileHover={reduceMotion ? undefined : { x: 4 }}
            className="group relative pl-4"
          >
            <motion.span variants={{ hidden: { scaleY: 0 }, visible: { scaleY: 1, transition: { duration: reduceMotion ? 0 : 0.26, delay: reduceMotion ? 0 : index * 0.08 + 0.1, ease } } }} className="absolute inset-y-1 left-0 w-px origin-top bg-[#B86D4B]/55" />
            <div className="flex items-start gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#6E4B63]/10 text-xs font-semibold text-[#6E4B63]">{source.icon}</span>
              <div><p className="font-semibold">{source.label}</p><p className="mt-1 text-xs text-[#8A8178] tabular-nums">{source.detail}</p></div>
            </div>
          </motion.div>
        ))}
      </div>

      <MobileSignal delay={0.42} />
      <motion.div
        variants={{
          hidden: { opacity: 0, scale: 0.9, boxShadow: "0 0 0 0 rgba(110,75,99,0)" },
          visible: { opacity: 1, scale: [0.9, 1, 1.045, 1], boxShadow: ["0 0 0 0 rgba(110,75,99,0)", "0 0 0 0 rgba(110,75,99,0)", "0 0 0 18px rgba(110,75,99,0.11)", "0 0 0 0 rgba(110,75,99,0)"], transition: { duration: reduceMotion ? 0 : 0.48, delay: reduceMotion ? 0 : 0.72, ease } },
        }}
        className="relative z-10 mx-auto flex aspect-square w-40 flex-col items-center justify-center rounded-full bg-[#FFFCF7] text-center shadow-[0_18px_48px_rgba(71,48,64,0.10)] ring-1 ring-[#6E4B63]/20"
      >
        <span className="absolute inset-3 rounded-full border border-[#6E4B63]/10" />
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Discero</p>
        <p className="mt-2 max-w-[110px] text-xl font-semibold leading-tight tracking-[-0.025em]">Decision analysis</p>
        <div className="relative mt-3 h-4 w-full text-[10px] font-medium text-[#777168]">
          <motion.p variants={{ hidden: { opacity: 0 }, visible: { opacity: reduceMotion ? 0 : [0, 1, 1, 0], transition: { duration: reduceMotion ? 0 : 0.44, delay: reduceMotion ? 0 : 0.74 } } }} className="absolute inset-0">Analyzing signals</motion.p>
          <motion.p variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { duration: reduceMotion ? 0 : 0.2, delay: reduceMotion ? 0 : 1.16 } } }} className="absolute inset-0 text-[#58715A]">Analysis complete</motion.p>
        </div>
      </motion.div>

      <MobileSignal delay={1.08} />
      <motion.div variants={{ hidden: { opacity: 0, x: 24 }, visible: { opacity: 1, x: 0, transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 1.14, ease } } }} className="relative z-10 border-y border-[#181713]/12 bg-[#F0E9E1]/35 px-5 py-6 sm:px-6">
        <motion.p variants={{ hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 1.18, ease } } }} className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Decision impact</motion.p>
        <motion.p variants={{ hidden: { opacity: 0, y: 14 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.26, delay: reduceMotion ? 0 : 1.2, ease } } }} className="mt-4 text-[clamp(2.8rem,5vw,4.5rem)] font-semibold leading-none tracking-[-0.035em] text-[#6E4B63] tabular-nums">+<AnimatedValue value={1026} format={money} delay={0.62} duration={0.82} once={false} /></motion.p>
        <motion.p variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { duration: reduceMotion ? 0 : 0.22, delay: reduceMotion ? 0 : 1.25 } } }} className="mt-2 text-sm text-[#777168]">More cash buffer by waiting</motion.p>
        <div className="mt-5 divide-y divide-[#181713]/10 border-t border-[#181713]/10">
          {[
            ["Goals", "Unaffected"],
            ["Runway", "No material change"],
          ].map(([label, value], index) => (
            <motion.div key={label} variants={{ hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.22, delay: reduceMotion ? 0 : 1.16 + index * 0.1, ease } } }} className="flex items-center justify-between gap-4 py-3 text-sm">
              <span className="text-[#777168]">{label}</span><span className="font-semibold text-[#181713]">{value}</span>
            </motion.div>
          ))}
        </div>
      </motion.div>
    </motion.div>
  );
}

function MobileSignal({ delay }: { delay: number }) {
  const reduceMotion = useReducedMotion();
  return (
    <div className="relative mx-auto h-11 w-8 lg:hidden">
      <motion.span variants={{ hidden: { scaleY: 0 }, visible: { scaleY: 1, transition: { duration: reduceMotion ? 0 : 0.36, delay: reduceMotion ? 0 : delay, ease } } }} className="absolute bottom-0 left-1/2 top-0 w-px origin-top -rotate-6 bg-[#B86D4B]/55" />
      <motion.span variants={{ hidden: { opacity: 0, y: 0 }, visible: { opacity: [0, 1, 1, 0], y: 38, x: -4, transition: { duration: reduceMotion ? 0 : 0.38, delay: reduceMotion ? 0 : delay + 0.04, ease } } }} className="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 rounded-full bg-[#B86D4B]" />
    </div>
  );
}

function DecisionExamples() {
  return (
    <div className="border-t border-[#181713]/15">
      <Scene className="grid gap-10 border-b border-[#181713]/15 py-14 lg:grid-cols-[0.78fr_1.22fr] lg:items-center">
        <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Decision comparison</p><h3 className="mt-5 text-3xl font-semibold leading-[1.1] tracking-[-0.025em] sm:text-4xl">Would waiting create more breathing room?</h3></div>
        <div className="grid grid-cols-2 border-y border-[#181713]/15">
          <CompareColumn label="Buy now" value={25406} detail="Available buffer" muted />
          <CompareColumn label="Wait until October" value={26432} detail="+$1,026 buffer" />
        </div>
      </Scene>
      <div className="grid border-b border-[#181713]/15 lg:grid-cols-[1.2fr_0.8fr]">
        <Scene className="border-b border-[#181713]/15 py-14 lg:border-b-0 lg:border-r lg:pr-14">
          <div className="grid gap-8 sm:grid-cols-[1fr_auto] sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6E4B63]">Goal impact</p><h3 className="mt-5 max-w-xl text-3xl font-semibold leading-[1.1] tracking-[-0.025em] sm:text-4xl">Will this purchase delay something more important?</h3></div><span className="w-fit border border-[#58715A]/30 px-3 py-1.5 text-xs font-semibold text-[#58715A]">No change</span></div>
          <div className="mt-12"><div className="flex justify-between text-sm"><span className="font-semibold">Emergency fund</span><span className="text-[#6E4B63]"><AnimatedValue value={68} format={(value) => `${Math.round(value)}%`} /></span></div><div className="mt-4 h-2 bg-[#FFFCF7]"><ProgressLine /></div><p className="mt-4 text-sm text-[#777168]">Projected progress remains unchanged.</p></div>
        </Scene>
        <Scene className="py-14 lg:pl-14">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#B86D4B]">Financial runway</p><h3 className="mt-5 text-3xl font-semibold leading-[1.1] tracking-[-0.025em] sm:text-4xl">How long could my cash support me if income stopped?</h3>
          <p className="mt-12 text-[clamp(4rem,8vw,7rem)] font-semibold leading-none tracking-[-0.035em] text-[#6E4B63] tabular-nums"><AnimatedValue value={8.3} format={(value) => value.toFixed(1)} /></p>
          <p className="mt-2 text-xl text-[#777168]">months after the purchase</p>
        </Scene>
      </div>
    </div>
  );
}

function AskIntro() {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div initial={reduceMotion ? false : "hidden"} whileInView="visible" viewport={{ once: false, amount: 0.25, margin: "-5% 0px" }} variants={{ hidden: {}, visible: {} }} className="max-w-2xl">
      <motion.p variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.26, ease } } }} className="text-xs font-semibold uppercase tracking-[0.18em] text-[#C89A78]">Ask Discero</motion.p>
      <motion.h2 variants={{ hidden: { opacity: 0, y: 30 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.32, delay: reduceMotion ? 0 : 0.06, ease } } }} className="mt-5 text-4xl font-semibold leading-[1.05] tracking-[0em] sm:text-5xl">Ask a question.<span className="block">See the consequence.</span></motion.h2>
      <motion.p variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.28, delay: reduceMotion ? 0 : 0.14, ease } } }} className="mt-5 max-w-lg text-lg leading-8 text-[#AAA39A]">Ask about a financial choice. Discero evaluates the effects that matter.</motion.p>
    </motion.div>
  );
}

function AnalysisPreview() {
  const reduceMotion = useReducedMotion();
  const question = "Should I buy this now or wait until October?".split(" ");
  const checks = [
    { icon: "$", label: "Cash position" },
    { icon: "◎", label: "Goal impact" },
    { icon: "◷", label: "Timing" },
  ];
  return (
    <motion.div initial={reduceMotion ? false : "hidden"} whileInView="visible" viewport={{ once: false, amount: 0.25, margin: "-5% 0px" }} className="relative border-y border-white/15 bg-white/[0.025] px-5 py-8 sm:px-8 lg:px-10 lg:py-10">
      <div className="grid gap-6 border-b border-white/10 pb-8 sm:grid-cols-[1fr_auto] sm:items-end">
        <div>
          <motion.p variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 0.03, ease } } }} className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8F8981]">Your question</motion.p>
          <h3 style={{ wordSpacing: "normal" }} className="mt-4 max-w-4xl text-3xl font-semibold leading-[1.1] tracking-[-0.025em] sm:text-4xl lg:text-5xl">
            {question.map((word, index) => (
              <span key={`${word}-${index}`}>
                <motion.span variants={{ hidden: { opacity: 0, y: 16, filter: "blur(4px)" }, visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: reduceMotion ? 0 : 0.22, delay: reduceMotion ? 0 : 0.05 + index * 0.03, ease } } }} className="inline-block">{word}</motion.span>
                {index < question.length - 1 ? " " : null}
              </span>
            ))}
          </h3>
        </div>
        <motion.span variants={{ hidden: { opacity: 0, scale: 0.8 }, visible: { opacity: 1, scale: 1, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 0.43, ease } } }} className="flex h-11 w-11 items-center justify-center justify-self-end rounded-full border border-[#C89A78]/35 text-lg text-[#C89A78]">→</motion.span>
      </div>

      <motion.div variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.26, delay: reduceMotion ? 0 : 0.48, ease } } }} className="mt-8">
        <div className="relative h-5 text-sm font-medium">
          <motion.p variants={{ hidden: { opacity: 0 }, visible: { opacity: reduceMotion ? 0 : [1, 1, 0], transition: { duration: reduceMotion ? 0 : 0.52, delay: reduceMotion ? 0 : 0.48 } } }} className="absolute inset-0 text-[#C8C1B8]">Analyzing your financial position...</motion.p>
          <motion.p variants={{ hidden: { opacity: 0 }, visible: { opacity: 1, transition: { duration: reduceMotion ? 0 : 0.22, delay: reduceMotion ? 0 : 1.02 } } }} className="absolute inset-0 text-[#91A990]">Analysis complete</motion.p>
        </div>
        <div className="relative mt-6 grid gap-5 sm:grid-cols-3 sm:gap-8">
          <span className="absolute bottom-5 left-5 top-5 w-px bg-white/10 sm:bottom-auto sm:left-5 sm:right-5 sm:top-5 sm:h-px sm:w-auto" />
          <motion.span variants={{ hidden: { scaleY: 0 }, visible: { scaleY: 1, transition: { duration: reduceMotion ? 0 : 0.5, delay: reduceMotion ? 0 : 0.5, ease } } }} className="absolute bottom-5 left-5 top-5 w-px origin-top bg-[#C89A78] sm:hidden" />
          <motion.span variants={{ hidden: { scaleX: 0 }, visible: { scaleX: 1, transition: { duration: reduceMotion ? 0 : 0.5, delay: reduceMotion ? 0 : 0.5, ease } } }} className="absolute left-5 right-5 top-5 hidden h-px origin-left bg-[#C89A78] sm:block" />
          {checks.map((check, index) => (
            <motion.div key={check.label} variants={{ hidden: { opacity: 0, y: 12 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 0.54 + index * 0.2, ease } } }} className={`relative z-10 flex items-center gap-3 sm:flex-col ${index === 0 ? "sm:items-start" : index === 1 ? "sm:items-center" : "sm:items-end"}`}>
              <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[#91A990]/30 bg-[#1B1A18] text-sm text-[#91A990]"><motion.span variants={{ hidden: { opacity: 1 }, visible: { opacity: reduceMotion ? 0 : [1, 1, 0], transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 0.64 + index * 0.2 } } }}>{check.icon}</motion.span><motion.span variants={{ hidden: { opacity: 0, scale: 0.7 }, visible: { opacity: 1, scale: [0.7, 1.12, 1], transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 0.64 + index * 0.2 } } }} className="absolute inset-0 flex items-center justify-center">✓</motion.span></span>
              <div className={index === 1 ? "sm:text-center" : index === 2 ? "sm:text-right" : ""}><span className="text-sm font-semibold text-[#F5F1EA]">{check.label}</span><span className="mt-1 block text-[10px] uppercase tracking-[0.16em] text-[#8F8981]">Complete</span></div>
            </motion.div>
          ))}
        </div>
      </motion.div>

      <div className="mt-10 grid gap-8 border-t border-white/10 pt-8 lg:grid-cols-[0.9fr_1.1fr] lg:items-end">
        <motion.div variants={{ hidden: { opacity: 0, y: 22 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 0.98, ease } } }} className="relative pl-5">
          <span className="absolute bottom-1 left-0 top-1 w-px bg-[#D3A963]" />
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#AAA39A]">Recommendation</p>
          <motion.p variants={{ hidden: { opacity: 0, scale: 0.9 }, visible: { opacity: 1, scale: [0.9, 1.04, 1], transition: { duration: reduceMotion ? 0 : 0.3, delay: reduceMotion ? 0 : 1.02, ease } } }} className="mt-3 text-6xl font-semibold leading-none tracking-[0em] text-[#D3A963] sm:text-7xl">Wait</motion.p>
        </motion.div>
        <div className="grid grid-cols-2 gap-5 sm:gap-8">
          <motion.div variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 1.06, ease } } }} className="border-l border-white/10 pl-4 sm:pl-6">
            <p className="text-3xl font-semibold tracking-[-0.025em] text-[#91A990] tabular-nums sm:text-4xl">+<AnimatedValue value={1026} format={money} delay={0.62} duration={0.84} once={false} /></p>
            <p className="mt-2 text-sm text-[#AAA39A]">More cash buffer</p>
          </motion.div>
          <motion.div variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.24, delay: reduceMotion ? 0 : 1.24, ease } } }} className="border-l border-white/10 pl-4 sm:pl-6">
            <p className="text-3xl font-semibold tracking-[-0.025em] text-[#F5F1EA] sm:text-4xl">No change</p>
            <p className="mt-2 text-sm text-[#AAA39A]">Goal impact</p>
          </motion.div>
        </div>
      </div>

      <motion.div variants={{ hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0, transition: { duration: reduceMotion ? 0 : 0.25, delay: reduceMotion ? 0 : 1.25, ease } } }} className="mt-8 text-[11px] text-[#8F8981]"><p><span className="font-semibold uppercase tracking-[0.18em]">Discero analysis</span><span className="ml-2 text-[#AAA39A]">Based on current balances, goals, and recurring commitments.</span></p></motion.div>
    </motion.div>
  );
}

function AuthenticationCard({ mode, email, password, confirmPassword, loading, error, onModeChange, onEmailChange, onPasswordChange, onConfirmPasswordChange, onSubmit }: { mode: Mode; email: string; password: string; confirmPassword: string; loading: boolean; error: string; onModeChange: (mode: Mode) => void; onEmailChange: (value: string) => void; onPasswordChange: (value: string) => void; onConfirmPasswordChange: (value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void }) {
  return (
    <section className="bg-[#FFFCF7] p-6 shadow-[0_24px_70px_rgba(60,43,35,0.10)] ring-1 ring-[#181713]/10 sm:p-7">
      <div className="grid grid-cols-2 border border-[#181713]/10 p-1">
        {(["login", "register"] as Mode[]).map((item) => <button key={item} type="button" onClick={() => onModeChange(item)} className={`px-4 py-2.5 text-sm font-semibold transition ${mode === item ? "bg-[#1B1A18] text-white" : "text-[#777168]"}`}>{item === "login" ? "Sign in" : "Create account"}</button>)}
      </div>
      <h3 className="mt-5 text-2xl font-semibold tracking-[-0.025em]">{mode === "login" ? "Welcome back" : "Try Discero"}</h3>
      <p className="mt-2 text-sm leading-6 text-[#777168]">{mode === "login" ? "Sign in to continue your decision analysis." : "Create an account to evaluate financial decisions."}</p>
      <form onSubmit={onSubmit} className="mt-5 space-y-3">
        <AuthInput label="Email address" type="email" autoComplete="email" value={email} placeholder="you@example.com" onChange={onEmailChange} />
        <AuthInput label="Password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} placeholder="Minimum 8 characters" onChange={onPasswordChange} />
        <div className="flex min-h-[4.5rem] items-center justify-end">
          {mode === "register" ? <div className="w-full"><AuthInput label="Confirm password" type="password" autoComplete="new-password" value={confirmPassword} placeholder="Repeat your password" onChange={onConfirmPasswordChange} /></div> : <Link href="/forgot-password" className="text-sm font-semibold text-[#6E4B63]">Forgot password?</Link>}
        </div>
        {error && <div role="alert" className="border border-[#B75C50]/25 bg-[#F6E5E0] px-4 py-3 text-sm text-[#96493F]">{error}</div>}
        <button type="submit" disabled={loading} className="discero-button-primary w-full rounded-full px-5 py-3.5 text-sm font-semibold transition disabled:cursor-not-allowed">{loading ? "Please wait..." : mode === "login" ? "Sign in to Discero" : "Create my account"}</button>
      </form>
    </section>
  );
}

function AuthInput({ label, onChange, ...props }: { label: string; type: string; autoComplete: string; value: string; placeholder: string; onChange: (value: string) => void }) {
  return <label className="block"><span className="text-xs font-medium text-[#706961]">{label}</span><input {...props} onChange={(event) => onChange(event.target.value)} className="mt-2 w-full border border-[#181713]/10 bg-[#F8F4EE] px-4 py-3 text-sm outline-none transition placeholder:text-[#A49D95] focus:border-[#6E4B63] focus:ring-2 focus:ring-[#6E4B63]/15" /></label>;
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
  return <motion.div initial={reduceMotion ? false : { opacity: 0, y: 64, scale: 0.985 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={{ once: true, amount: 0.13 }} transition={{ duration: reduceMotion ? 0 : 0.72, ease }} className={className}>{children}</motion.div>;
}

function Stagger({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduceMotion = useReducedMotion();
  return <motion.div initial={reduceMotion ? false : "hidden"} whileInView="visible" viewport={{ once: true, amount: 0.2 }} variants={{ hidden: {}, visible: { transition: { staggerChildren: reduceMotion ? 0 : 0.12 } } }} className={className}>{children}</motion.div>;
}

function TrustRow({ number, title, detail }: { number: string; title: string; detail: string }) {
  const reduceMotion = useReducedMotion();
  return <motion.div variants={{ hidden: { opacity: 0, x: 38 }, visible: { opacity: 1, x: 0, transition: { duration: reduceMotion ? 0 : 0.52, ease } } }} className="grid gap-3 py-7 sm:grid-cols-[48px_160px_1fr]"><span className="text-xs font-semibold text-[#B86D4B] tabular-nums">{number}</span><h3 className="font-semibold">{title}</h3><p className="text-sm leading-6 text-[#777168]">{detail}</p></motion.div>;
}

function HeroItem({ children }: { children: ReactNode }) {
  const reduceMotion = useReducedMotion();
  return <motion.div variants={{ hidden: { opacity: 0, y: 34, filter: "blur(7px)" }, visible: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: reduceMotion ? 0 : 0.55, ease } } }}>{children}</motion.div>;
}

function CompareColumn({ label, value, detail, muted = false }: { label: string; value: number; detail: string; muted?: boolean }) {
  return <div className={`py-8 ${muted ? "border-r border-[#181713]/15 pr-5" : "pl-5"}`}><p className="text-xs font-medium text-[#777168]">{label}</p><p className={`mt-5 text-3xl font-semibold tracking-[-0.035em] tabular-nums sm:text-5xl ${muted ? "text-[#777168]" : "text-[#6E4B63]"}`}><AnimatedValue value={value} format={money} /></p><p className="mt-3 text-sm text-[#8A8178]">{detail}</p></div>;
}

function ProgressLine() {
  const reduceMotion = useReducedMotion();
  return <motion.div initial={reduceMotion ? false : { scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: reduceMotion ? 0 : 0.9, ease }} className="h-full w-[68%] origin-left bg-[#58715A]" />;
}

function money(value: number) {
  return `$${Math.round(value).toLocaleString("en-US")}`;
}
