"use client";

import {
  FormEvent,
  ReactNode,
  useEffect,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { api, session } from "./lib/api";

type Mode = "login" | "register";

export default function HomePage() {
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] =
    useState("");
  const [loading, setLoading] = useState(false);
  const [checkingSession, setCheckingSession] =
    useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function validateSession() {
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
        setCheckingSession(false);
      }
    }

    void validateSession();
  }, [router]);

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    const normalizedEmail =
      email.trim().toLowerCase();

    if (!normalizedEmail) {
      setError("Enter your email address.");
      return;
    }

    if (password.length < 8) {
      setError(
        "Password must contain at least 8 characters."
      );
      return;
    }

    if (
      mode === "register" &&
      password !== confirmPassword
    ) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      if (mode === "register") {
        await api.createUser(
          normalizedEmail,
          password
        );
      }

      const auth = await api.login(
        normalizedEmail,
        password
      );

      session.save(auth);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Authentication failed"
      );
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

  function scrollToProduct() {
    document
      .getElementById("product")
      ?.scrollIntoView({
        behavior: "smooth",
      });
  }

  function scrollToAccess(nextMode: Mode) {
    changeMode(nextMode);

    document
      .getElementById("access")
      ?.scrollIntoView({
        behavior: "smooth",
      });
  }

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#f5f1e8] text-[#13231d]">
        <div className="text-center">
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-[#167c5a] border-t-transparent" />

          <p className="mt-4 text-sm text-[#66746e]">
            Checking your session...
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="overflow-hidden bg-[#f5f1e8] text-[#14241e]">
      <Navigation
        onSignIn={() => scrollToAccess("login")}
        onRegister={() =>
          scrollToAccess("register")
        }
      />

      <section className="relative px-5 pb-20 pt-28 sm:px-8 lg:pb-28 lg:pt-36">
        <div className="pointer-events-none absolute -left-24 top-20 h-72 w-72 rounded-full bg-[#d5f7a7]/55 blur-3xl" />
        <div className="pointer-events-none absolute -right-20 top-28 h-80 w-80 rounded-full bg-[#9debd5]/45 blur-3xl" />

        <div className="relative mx-auto grid max-w-7xl gap-16 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Personal finance intelligence
            </p>

            <h1 className="mt-5 max-w-3xl text-[52px] font-semibold leading-[0.98] tracking-[-0.065em] text-[#10211b] sm:text-[68px] lg:text-[78px]">
              Know where your money went.
              <span className="mt-2 block text-[#167c5a]">
                See where it goes next.
              </span>
            </h1>

            <p className="mt-7 max-w-xl text-lg leading-8 text-[#5d6d66]">
              FinSight connects your financial
              activity, explains your spending,
              tracks your progress, and forecasts
              what comes next.
            </p>

            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={() =>
                  scrollToAccess("register")
                }
                className="rounded-full bg-[#14241e] px-6 py-3.5 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-[#20352d]"
              >
                Start exploring
              </button>

              <button
                type="button"
                onClick={scrollToProduct}
                className="rounded-full border border-[#14241e]/15 bg-white/55 px-6 py-3.5 text-sm font-semibold text-[#14241e] transition hover:-translate-y-0.5 hover:bg-white"
              >
                See the product
              </button>
            </div>

            <div className="mt-9 flex flex-wrap gap-x-6 gap-y-3 text-sm text-[#6c7974]">
              <span className="flex items-center gap-2">
                <CheckIcon />
                Secure authentication
              </span>

              <span className="flex items-center gap-2">
                <CheckIcon />
                Plaid Sandbox integration
              </span>

              <span className="flex items-center gap-2">
                <CheckIcon />
                Intelligent forecasting
              </span>
            </div>
          </div>

          <HeroProductPreview />
        </div>
      </section>

      <section className="border-y border-[#14241e]/10 bg-[#ede8dc] px-5 py-6 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-10 gap-y-4 text-xs font-semibold uppercase tracking-[0.16em] text-[#758079]">
          <span>FastAPI</span>
          <span>Next.js</span>
          <span>PostgreSQL-ready</span>
          <span>Plaid</span>
          <span>JWT Security</span>
          <span>Financial Intelligence</span>
        </div>
      </section>

      <section
        id="product"
        className="bg-[#14241e] px-5 py-24 text-white sm:px-8 lg:py-32"
      >
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#76dfbd]">
              One connected financial workspace
            </p>

            <h2 className="mt-5 text-4xl font-semibold leading-tight tracking-[-0.045em] sm:text-6xl">
              Everything you need to understand
              today and prepare for tomorrow.
            </h2>
          </div>

          <div className="mt-16 grid gap-px overflow-hidden rounded-[28px] border border-white/10 bg-white/10 lg:grid-cols-3">
            <FeaturePanel
              number="01"
              title="See the full picture"
              description="Bring CSV activity and connected accounts into one clear financial workspace."
              icon={<AccountsIcon />}
            />

            <FeaturePanel
              number="02"
              title="Understand your habits"
              description="Explore spending categories, recurring bills, monthly trends, and personalized insights."
              icon={<InsightIcon />}
            />

            <FeaturePanel
              number="03"
              title="Plan what comes next"
              description="Track budgets and savings goals while forecasting your expected month-end balance."
              icon={<ForecastIcon />}
            />
          </div>
        </div>
      </section>

      <section className="px-5 py-24 sm:px-8 lg:py-32">
        <div className="mx-auto max-w-7xl">
          <div className="text-center">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              How FinSight works
            </p>

            <h2 className="mx-auto mt-5 max-w-3xl text-4xl font-semibold tracking-[-0.045em] sm:text-6xl">
              From scattered transactions to
              financial clarity.
            </h2>
          </div>

          <div className="mt-16 grid gap-8 lg:grid-cols-3">
            <ProcessStep
              number="1"
              title="Bring in your activity"
              description="Upload a transaction CSV or connect Sandbox financial accounts through Plaid."
            />

            <ProcessStep
              number="2"
              title="Let FinSight organize it"
              description="Transactions are categorized, recurring patterns are detected, and financial summaries are calculated."
            />

            <ProcessStep
              number="3"
              title="Make better decisions"
              description="Review insights, monitor budgets, grow your goals, and prepare for upcoming cash-flow changes."
            />
          </div>
        </div>
      </section>

      <section className="bg-[#dff6c7] px-5 py-24 sm:px-8 lg:py-32">
        <div className="mx-auto grid max-w-7xl gap-16 lg:grid-cols-2 lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Spending intelligence
            </p>

            <h2 className="mt-5 text-4xl font-semibold tracking-[-0.05em] sm:text-6xl">
              Your transactions should tell you
              something useful.
            </h2>

            <p className="mt-6 max-w-xl text-lg leading-8 text-[#53675d]">
              FinSight turns raw activity into
              understandable categories, trends,
              recurring patterns, and monthly
              observations.
            </p>

            <div className="mt-9 space-y-5">
              <Benefit
                title="Automatic categorization"
                description="Organize spending into meaningful financial categories."
              />

              <Benefit
                title="Recurring-payment detection"
                description="Identify subscriptions and expected bills before they arrive."
              />

              <Benefit
                title="Monthly comparisons"
                description="See how income and spending change over time."
              />
            </div>
          </div>

          <SpendingPreview />
        </div>
      </section>

      <section className="bg-[#f5f1e8] px-5 py-24 sm:px-8 lg:py-32">
        <div className="mx-auto grid max-w-7xl gap-16 lg:grid-cols-2 lg:items-center">
          <ForecastPreview />

          <div className="lg:pl-12">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Forward-looking finance
            </p>

            <h2 className="mt-5 text-4xl font-semibold tracking-[-0.05em] sm:text-6xl">
              Don’t just review the past.
              Prepare for what is next.
            </h2>

            <p className="mt-6 max-w-xl text-lg leading-8 text-[#5d6d66]">
              FinSight combines available balances,
              income pace, and predicted recurring
              bills to estimate your position at the
              end of the month.
            </p>

            <div className="mt-9 grid gap-4 sm:grid-cols-2">
              <SmallFeature
                title="Cash-flow forecast"
                description="Estimate your month-end balance."
              />

              <SmallFeature
                title="Low-balance warnings"
                description="Spot financial pressure earlier."
              />

              <SmallFeature
                title="Upcoming bills"
                description="See expected recurring payments."
              />

              <SmallFeature
                title="Savings progress"
                description="Track goals across milestones."
              />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[#f0b8a8] px-5 py-24 sm:px-8 lg:py-32">
        <div className="mx-auto grid max-w-7xl gap-14 lg:grid-cols-[0.8fr_1.2fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#713729]">
              Built with security in mind
            </p>

            <h2 className="mt-5 text-4xl font-semibold tracking-[-0.05em] text-[#351d17] sm:text-6xl">
              Financial clarity without treating
              security as an afterthought.
            </h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <SecurityCard
              title="Protected authentication"
              description="Passwords are hashed using Argon2 and sessions use signed JWT access tokens."
            />

            <SecurityCard
              title="Encrypted provider tokens"
              description="Sensitive Plaid access tokens are encrypted before being stored."
            />

            <SecurityCard
              title="User-level isolation"
              description="Financial resources are scoped to the authenticated user."
            />

            <SecurityCard
              title="Controlled integrations"
              description="Plaid Sandbox supports secure financial account testing and synchronization."
            />
          </div>
        </div>
      </section>

      <section
        id="access"
        className="bg-[#14241e] px-5 py-24 text-white sm:px-8 lg:py-32"
      >
        <div className="mx-auto grid max-w-7xl gap-14 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#76dfbd]">
              Your financial workspace
            </p>

            <h2 className="mt-5 max-w-2xl text-4xl font-semibold tracking-[-0.05em] sm:text-6xl">
              Make your money easier to understand.
            </h2>

            <p className="mt-6 max-w-xl text-lg leading-8 text-[#aebbb5]">
              Create an account to explore the full
              FinSight experience, or sign in to
              continue where you left off.
            </p>

            <div className="mt-10 grid gap-4 sm:grid-cols-3">
              <AccessStat
                value="8"
                label="Financial tools"
              />

              <AccessStat
                value="111"
                label="Backend tests"
              />

              <AccessStat
                value="1"
                label="Connected workspace"
              />
            </div>
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
            onConfirmPasswordChange={
              setConfirmPassword
            }
            onSubmit={handleSubmit}
          />
        </div>
      </section>

      <footer className="border-t border-[#14241e]/10 bg-[#f5f1e8] px-5 py-10 sm:px-8">
        <div className="mx-auto flex max-w-7xl flex-col gap-8 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <BrandMark />

            <div>
              <p className="font-semibold">
                FinSight
              </p>

              <p className="text-xs text-[#728078]">
                Personal finance intelligence
              </p>
            </div>
          </div>

          <p className="max-w-xl text-sm leading-6 text-[#728078]">
            FinSight is an educational portfolio
            project. Forecasts and insights are
            estimates and are not financial advice.
          </p>

          <p className="text-sm text-[#728078]">
            Built by Badrinath T
          </p>
        </div>
      </footer>
    </main>
  );
}

function Navigation({
  onSignIn,
  onRegister,
}: {
  onSignIn: () => void;
  onRegister: () => void;
}) {
  return (
    <nav className="fixed inset-x-0 top-0 z-50 border-b border-[#14241e]/10 bg-[#f5f1e8]/90 px-5 backdrop-blur-xl sm:px-8">
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between">
        <div className="flex items-center gap-3">
          <BrandMark />

          <span className="text-lg font-semibold tracking-[-0.02em]">
            FinSight
          </span>
        </div>

        <div className="hidden items-center gap-8 text-sm font-medium text-[#66746e] md:flex">
          <a
            href="#product"
            className="transition hover:text-[#14241e]"
          >
            Product
          </a>

          <a
            href="#access"
            className="transition hover:text-[#14241e]"
          >
            Get started
          </a>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSignIn}
            className="rounded-full px-4 py-2.5 text-sm font-semibold text-[#14241e] transition hover:bg-white/70"
          >
            Sign in
          </button>

          <button
            type="button"
            onClick={onRegister}
            className="rounded-full bg-[#14241e] px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-[#20352d]"
          >
            Create account
          </button>
        </div>
      </div>
    </nav>
  );
}

function BrandMark() {
  return (
    <span className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-[#167c5a] text-sm font-bold text-white">
      F
    </span>
  );
}

function HeroProductPreview() {
  return (
    <div className="relative mx-auto w-full max-w-2xl">
      <div className="absolute -left-5 top-24 z-20 hidden rounded-2xl bg-[#f0b8a8] p-4 shadow-2xl shadow-black/10 sm:block">
        <p className="text-xs font-medium text-[#713729]">
          Spending this month
        </p>

        <p className="mt-1 text-xl font-semibold text-[#351d17]">
          Down 12%
        </p>
      </div>

      <div className="absolute -right-5 bottom-20 z-20 hidden rounded-2xl bg-[#d5f7a7] p-4 shadow-2xl shadow-black/10 sm:block">
        <p className="text-xs font-medium text-[#41651c]">
          Savings goal
        </p>

        <p className="mt-1 text-xl font-semibold text-[#243d0d]">
          68% complete
        </p>
      </div>

      <div className="rotate-[1.5deg] rounded-[30px] border border-[#14241e]/10 bg-[#14241e] p-3 shadow-[0_35px_100px_rgba(20,36,30,0.28)]">
        <div className="overflow-hidden rounded-[22px] bg-[#0d141e]">
          <div className="flex h-12 items-center gap-2 border-b border-white/[0.08] px-5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#f0b8a8]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#f5d66f]" />
            <span className="h-2.5 w-2.5 rounded-full bg-[#76dfbd]" />

            <div className="ml-4 h-5 flex-1 rounded-full bg-white/[0.05]" />
          </div>

          <div className="grid min-h-[470px] grid-cols-[72px_1fr] sm:grid-cols-[150px_1fr]">
            <div className="border-r border-white/[0.08] p-4">
              <div className="h-8 w-8 rounded-lg bg-[#45d7a4]" />

              <div className="mt-8 space-y-4">
                {Array.from({ length: 6 }).map(
                  (_, index) => (
                    <div
                      key={index}
                      className={`h-2.5 rounded-full ${
                        index === 0
                          ? "bg-[#45d7a4]/50"
                          : "bg-white/[0.07]"
                      }`}
                    />
                  )
                )}
              </div>
            </div>

            <div className="min-w-0 p-5 sm:p-7">
              <p className="text-xs uppercase tracking-[0.14em] text-slate-600">
                July 2026
              </p>

              <h3 className="mt-2 text-xl font-semibold text-white">
                Financial overview
              </h3>

              <div className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-white/[0.08]">
                <PreviewMetric
                  label="Income"
                  value="$7,850"
                  accent
                />

                <PreviewMetric
                  label="Spending"
                  value="$4,280"
                />

                <PreviewMetric
                  label="Net balance"
                  value="$3,570"
                />

                <PreviewMetric
                  label="Forecast"
                  value="$4,130"
                  accent
                />
              </div>

              <div className="mt-5 rounded-xl border border-white/[0.08] bg-white/[0.025] p-5">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-slate-200">
                    Spending by category
                  </p>

                  <p className="text-xs text-slate-600">
                    42 transactions
                  </p>
                </div>

                <div className="mt-6 space-y-4">
                  <ChartRow
                    label="Housing"
                    value="$1,500"
                    width="82%"
                  />

                  <ChartRow
                    label="Groceries"
                    value="$620"
                    width="54%"
                  />

                  <ChartRow
                    label="Transport"
                    value="$410"
                    width="38%"
                  />

                  <ChartRow
                    label="Dining"
                    value="$285"
                    width="27%"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviewMetric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="bg-[#111925] p-4">
      <p className="text-[10px] uppercase tracking-[0.12em] text-slate-600">
        {label}
      </p>

      <p
        className={`mt-2 text-base font-semibold ${
          accent
            ? "text-[#45d7a4]"
            : "text-slate-200"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ChartRow({
  label,
  value,
  width,
}: {
  label: string;
  value: string;
  width: string;
}) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">
          {label}
        </span>

        <span className="text-slate-500">
          {value}
        </span>
      </div>

      <div className="mt-2 h-1 rounded-full bg-white/[0.06]">
        <div
          className="h-full rounded-full bg-[#45d7a4]"
          style={{ width }}
        />
      </div>
    </div>
  );
}

function FeaturePanel({
  number,
  title,
  description,
  icon,
}: {
  number: string;
  title: string;
  description: string;
  icon: ReactNode;
}) {
  return (
    <article className="bg-[#192d25] p-8 sm:p-10">
      <div className="flex items-start justify-between">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#76dfbd]/10 text-[#76dfbd]">
          {icon}
        </span>

        <span className="text-xs text-white/30">
          {number}
        </span>
      </div>

      <h3 className="mt-10 text-2xl font-semibold tracking-[-0.03em]">
        {title}
      </h3>

      <p className="mt-4 leading-7 text-[#aebbb5]">
        {description}
      </p>
    </article>
  );
}

function ProcessStep({
  number,
  title,
  description,
}: {
  number: string;
  title: string;
  description: string;
}) {
  return (
    <article className="border-t border-[#14241e]/15 pt-6">
      <span className="text-sm font-semibold text-[#167c5a]">
        0{number}
      </span>

      <h3 className="mt-6 text-2xl font-semibold tracking-[-0.03em]">
        {title}
      </h3>

      <p className="mt-4 leading-7 text-[#66746e]">
        {description}
      </p>
    </article>
  );
}

function Benefit({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex gap-4">
      <span className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#167c5a] text-white">
        <CheckIcon light />
      </span>

      <div>
        <p className="font-semibold">{title}</p>

        <p className="mt-1 text-sm leading-6 text-[#63736a]">
          {description}
        </p>
      </div>
    </div>
  );
}

function SpendingPreview() {
  return (
    <div className="rounded-[30px] bg-[#14241e] p-6 shadow-[0_35px_90px_rgba(20,36,30,0.22)] sm:p-8">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.14em] text-slate-600">
            Spending analysis
          </p>

          <p className="mt-2 text-2xl font-semibold text-white">
            $4,280 this month
          </p>
        </div>

        <span className="rounded-full bg-[#45d7a4]/10 px-3 py-1 text-xs font-medium text-[#45d7a4]">
          12% lower
        </span>
      </div>

      <div className="mt-10 space-y-6">
        <LargeChartRow
          label="Housing"
          amount="$1,500"
          width="84%"
        />

        <LargeChartRow
          label="Groceries"
          amount="$620"
          width="58%"
        />

        <LargeChartRow
          label="Transport"
          amount="$410"
          width="43%"
        />

        <LargeChartRow
          label="Dining"
          amount="$285"
          width="31%"
        />
      </div>

      <div className="mt-10 border-t border-white/[0.08] pt-6">
        <p className="text-xs uppercase tracking-[0.14em] text-slate-600">
          FinSight observation
        </p>

        <p className="mt-3 leading-7 text-slate-300">
          Dining spending is down compared with last
          month, while grocery spending remains
          within your planned budget.
        </p>
      </div>
    </div>
  );
}

function LargeChartRow({
  label,
  amount,
  width,
}: {
  label: string;
  amount: string;
  width: string;
}) {
  return (
    <div>
      <div className="flex justify-between">
        <span className="text-sm text-slate-300">
          {label}
        </span>

        <span className="text-sm font-medium text-white">
          {amount}
        </span>
      </div>

      <div className="mt-3 h-2 rounded-full bg-white/[0.07]">
        <div
          className="h-full rounded-full bg-[#45d7a4]"
          style={{ width }}
        />
      </div>
    </div>
  );
}

function ForecastPreview() {
  return (
    <div className="rounded-[30px] border border-[#14241e]/10 bg-white p-6 shadow-[0_30px_90px_rgba(20,36,30,0.12)] sm:p-8">
      <p className="text-xs uppercase tracking-[0.14em] text-[#87928d]">
        Month-end forecast
      </p>

      <div className="mt-4 flex items-end justify-between gap-6">
        <p className="text-4xl font-semibold tracking-[-0.05em]">
          $4,130
        </p>

        <span className="rounded-full bg-[#dff6c7] px-3 py-1 text-xs font-medium text-[#41651c]">
          On track
        </span>
      </div>

      <div className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-[#14241e]/10">
        <LightMetric
          label="Available cash"
          value="$3,240"
        />

        <LightMetric
          label="Expected income"
          value="$2,100"
        />

        <LightMetric
          label="Upcoming bills"
          value="-$1,210"
        />

        <LightMetric
          label="Days remaining"
          value="14"
        />
      </div>

      <div className="mt-8">
        <p className="text-sm font-semibold">
          Upcoming activity
        </p>

        <div className="mt-4 divide-y divide-[#14241e]/10">
          <ForecastRow
            merchant="Rent"
            date="Aug 1"
            amount="-$1,500"
          />

          <ForecastRow
            merchant="Spotify"
            date="Aug 4"
            amount="-$11.99"
          />

          <ForecastRow
            merchant="Paycheck"
            date="Aug 8"
            amount="+$2,100"
            positive
          />
        </div>
      </div>
    </div>
  );
}

function LightMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="bg-[#f7f4ed] p-4">
      <p className="text-xs text-[#87928d]">
        {label}
      </p>

      <p className="mt-2 font-semibold">
        {value}
      </p>
    </div>
  );
}

function ForecastRow({
  merchant,
  date,
  amount,
  positive = false,
}: {
  merchant: string;
  date: string;
  amount: string;
  positive?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-4">
      <div>
        <p className="text-sm font-medium">
          {merchant}
        </p>

        <p className="mt-1 text-xs text-[#87928d]">
          Expected {date}
        </p>
      </div>

      <p
        className={`text-sm font-semibold ${
          positive
            ? "text-[#167c5a]"
            : "text-[#9b4b3b]"
        }`}
      >
        {amount}
      </p>
    </div>
  );
}

function SmallFeature({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <article className="border-t border-[#14241e]/15 pt-4">
      <p className="font-semibold">{title}</p>

      <p className="mt-2 text-sm leading-6 text-[#66746e]">
        {description}
      </p>
    </article>
  );
}

function SecurityCard({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <article className="rounded-2xl border border-[#351d17]/10 bg-[#f9d9d0]/60 p-6">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#713729] text-white">
        <LockIcon />
      </span>

      <h3 className="mt-6 text-lg font-semibold text-[#351d17]">
        {title}
      </h3>

      <p className="mt-3 text-sm leading-6 text-[#714e44]">
        {description}
      </p>
    </article>
  );
}

function AccessStat({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  return (
    <div className="border-t border-white/15 pt-4">
      <p className="text-3xl font-semibold text-[#76dfbd]">
        {value}
      </p>

      <p className="mt-1 text-sm text-[#aebbb5]">
        {label}
      </p>
    </div>
  );
}

function AuthenticationCard({
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
  onConfirmPasswordChange: (
    value: string
  ) => void;
  onSubmit: (
    event: FormEvent<HTMLFormElement>
  ) => void;
}) {
  return (
    <section className="rounded-[28px] bg-white p-6 text-[#14241e] shadow-[0_30px_90px_rgba(0,0,0,0.2)] sm:p-8">
      <div className="grid grid-cols-2 rounded-full bg-[#f1eee7] p-1">
        <button
          type="button"
          onClick={() => onModeChange("login")}
          className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${
            mode === "login"
              ? "bg-[#14241e] text-white"
              : "text-[#66746e]"
          }`}
        >
          Sign in
        </button>

        <button
          type="button"
          onClick={() =>
            onModeChange("register")
          }
          className={`rounded-full px-4 py-2.5 text-sm font-semibold transition ${
            mode === "register"
              ? "bg-[#14241e] text-white"
              : "text-[#66746e]"
          }`}
        >
          Create account
        </button>
      </div>

      <h3 className="mt-7 text-2xl font-semibold tracking-[-0.03em]">
        {mode === "login"
          ? "Welcome back"
          : "Start with FinSight"}
      </h3>

      <p className="mt-2 text-sm leading-6 text-[#728078]">
        {mode === "login"
          ? "Sign in to continue to your financial workspace."
          : "Create an account and begin exploring your financial data."}
      </p>

      <form
        onSubmit={onSubmit}
        className="mt-7 space-y-4"
      >
        <label className="block">
          <span className="text-xs font-medium text-[#66746e]">
            Email address
          </span>

          <input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) =>
              onEmailChange(event.target.value)
            }
            placeholder="you@example.com"
            className="mt-2 w-full rounded-xl border border-[#14241e]/12 bg-[#f7f4ed] px-4 py-3 text-sm outline-none transition placeholder:text-[#9aa39f] focus:border-[#167c5a]"
          />
        </label>

        <label className="block">
          <span className="text-xs font-medium text-[#66746e]">
            Password
          </span>

          <input
            type="password"
            autoComplete={
              mode === "login"
                ? "current-password"
                : "new-password"
            }
            value={password}
            onChange={(event) =>
              onPasswordChange(event.target.value)
            }
            placeholder="Minimum 8 characters"
            className="mt-2 w-full rounded-xl border border-[#14241e]/12 bg-[#f7f4ed] px-4 py-3 text-sm outline-none transition placeholder:text-[#9aa39f] focus:border-[#167c5a]"
          />
        </label>

        {mode === "register" && (
          <label className="block">
            <span className="text-xs font-medium text-[#66746e]">
              Confirm password
            </span>

            <input
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) =>
                onConfirmPasswordChange(
                  event.target.value
                )
              }
              placeholder="Repeat your password"
              className="mt-2 w-full rounded-xl border border-[#14241e]/12 bg-[#f7f4ed] px-4 py-3 text-sm outline-none transition placeholder:text-[#9aa39f] focus:border-[#167c5a]"
            />
          </label>
        )}

        {error && (
          <div className="rounded-xl border border-[#bc5b47]/20 bg-[#f0b8a8]/30 px-4 py-3 text-sm text-[#873d2f]">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-full bg-[#167c5a] px-5 py-3.5 text-sm font-semibold text-white transition hover:bg-[#116847] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading
            ? "Please wait..."
            : mode === "login"
              ? "Sign in to FinSight"
              : "Create my account"}
        </button>
      </form>
    </section>
  );
}

function CheckIcon({
  light = false,
}: {
  light?: boolean;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 20 20"
      fill="none"
      className="h-4 w-4"
    >
      <path
        d="m5 10 3 3 7-7"
        stroke={light ? "white" : "#167c5a"}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function AccountsIcon() {
  return <SimpleIcon path="M4 6h16v12H4zM4 10h16M8 14h3" />;
}

function InsightIcon() {
  return <SimpleIcon path="M5 18V9m7 9V5m7 13v-6M3 21h18" />;
}

function ForecastIcon() {
  return <SimpleIcon path="m4 17 6-6 4 4 6-8m-5 0h5v5" />;
}

function LockIcon() {
  return <SimpleIcon path="M7 10V7a5 5 0 0 1 10 0v3M5 10h14v11H5z" />;
}

function SimpleIcon({
  path,
}: {
  path: string;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
    >
      <path d={path} />
    </svg>
  );
}
