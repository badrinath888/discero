"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarDays,
  Edit3,
  Flag,
  Plus,
  Target,
  Trash2,
  WalletCards,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import ConfirmationModal from "../components/ConfirmationModal";
import Toast from "../components/Toast";
import {
  EmptyState,
  PageError,
  PageLoading,
} from "../components/PageFeedback";
import {
  AnimatedNumber,
  PageReveal,
  Reveal,
} from "../components/PremiumMotion";
import {
  api,
  formatCents,
  SavingsGoal,
  session,
} from "../lib/api";

type DrawerMode = "create" | "edit" | "fund";

type GoalFormState = {
  name: string;
  targetAmount: string;
  savedAmount: string;
  targetDate: string;
};

const EMPTY_FORM: GoalFormState = {
  name: "",
  targetAmount: "",
  savedAmount: "",
  targetDate: "",
};

export default function GoalsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [drawerMode, setDrawerMode] = useState<DrawerMode | null>(null);
  const [activeGoalId, setActiveGoalId] = useState<number | null>(null);
  const [form, setForm] = useState<GoalFormState>(EMPTY_FORM);
  const [contribution, setContribution] = useState("");
  const [withdrawal, setWithdrawal] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [pendingDeleteGoal, setPendingDeleteGoal] =
    useState<SavingsGoal | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    async function initialize() {
      const id = session.getUserId();
      const token = session.getToken();

      if (!id || !token) {
        session.clear();
        router.replace("/");
        return;
      }

      try {
        const user = await api.getMe();

        if (user.id !== id) {
          session.clear();
          router.replace("/");
          return;
        }

        setUserId(id);
        setGoals(await api.getSavingsGoals(id));
      } catch (err) {
        if (!session.getToken()) {
          router.replace("/");
          return;
        }

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load savings goals"
        );
      } finally {
        setLoading(false);
      }
    }

    void initialize();
  }, [router]);

  const totals = useMemo(
    () =>
      goals.reduce(
        (current, goal) => ({
          target: current.target + goal.target_cents,
          saved: current.saved + goal.saved_cents,
          completed:
            current.completed + (goal.status === "completed" ? 1 : 0),
        }),
        { target: 0, saved: 0, completed: 0 }
      ),
    [goals]
  );

  const overallProgress =
    totals.target > 0
      ? Math.min(Math.round((totals.saved / totals.target) * 100), 100)
      : 0;

  const activeGoal =
    goals.find((goal) => goal.id === activeGoalId) ?? null;

  function openCreateDrawer() {
    setDrawerMode("create");
    setActiveGoalId(null);
    setForm(EMPTY_FORM);
    setContribution("");
    setWithdrawal("");
    setError("");
    setMessage("");
  }

  function openEditDrawer(goal: SavingsGoal) {
    setDrawerMode("edit");
    setActiveGoalId(goal.id);
    setForm({
      name: goal.name,
      targetAmount: String(goal.target_cents / 100),
      savedAmount: String(goal.saved_cents / 100),
      targetDate: goal.target_date || "",
    });
    setContribution("");
    setWithdrawal("");
    setError("");
    setMessage("");
  }

  function openFundDrawer(goal: SavingsGoal) {
    setDrawerMode("fund");
    setActiveGoalId(goal.id);
    setContribution("");
    setWithdrawal("");
    setError("");
    setMessage("");
  }

  function closeDrawer() {
    setDrawerMode(null);
    setActiveGoalId(null);
    setForm(EMPTY_FORM);
    setContribution("");
    setWithdrawal("");
  }

  async function createGoal() {
    const targetCents = Math.round(Number(form.targetAmount) * 100);
    const savedCents = form.savedAmount
      ? Math.round(Number(form.savedAmount) * 100)
      : 0;

    if (
      !userId ||
      !form.name.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0 ||
      !Number.isFinite(savedCents) ||
      savedCents < 0
    ) {
      setError("Enter a valid goal name and target amount.");
      setMessage("");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const created = await api.createSavingsGoal(userId, {
        name: form.name.trim(),
        target_cents: targetCents,
        saved_cents: savedCents,
        target_date: form.targetDate || null,
      });

      setGoals((current) => [created, ...current]);
      setMessage("Savings goal created successfully.");
      closeDrawer();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create savings goal"
      );
    } finally {
      setBusy(false);
    }
  }

  async function saveGoalChanges() {
    if (!userId || !activeGoal) return;

    const targetCents = Math.round(Number(form.targetAmount) * 100);

    if (
      !form.name.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0
    ) {
      setError("Enter a valid goal name and target amount.");
      setMessage("");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        activeGoal.id,
        {
          name: form.name.trim(),
          target_cents: targetCents,
          target_date: form.targetDate || null,
        }
      );

      setGoals((current) =>
        current.map((goal) =>
          goal.id === updated.id ? updated : goal
        )
      );
      setMessage("Savings goal updated.");
      closeDrawer();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to update savings goal"
      );
    } finally {
      setBusy(false);
    }
  }

  async function addContribution() {
    if (!userId || !activeGoal) return;

    const contributionCents = Math.round(Number(contribution) * 100);

    if (!Number.isFinite(contributionCents) || contributionCents <= 0) {
      setError("Enter a valid contribution greater than $0.");
      setMessage("");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        activeGoal.id,
        {
          saved_cents: activeGoal.saved_cents + contributionCents,
        }
      );

      setGoals((current) =>
        current.map((goal) =>
          goal.id === updated.id ? updated : goal
        )
      );
      setContribution("");
      setMessage(`${formatCents(contributionCents)} added.`);
      closeDrawer();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to add contribution"
      );
    } finally {
      setBusy(false);
    }
  }

  async function withdrawFunds() {
    if (!userId || !activeGoal) return;

    const withdrawalCents = Math.round(Number(withdrawal) * 100);

    if (!Number.isFinite(withdrawalCents) || withdrawalCents <= 0) {
      setError("Enter a valid withdrawal greater than $0.");
      setMessage("");
      return;
    }

    if (withdrawalCents > activeGoal.saved_cents) {
      setError("Withdrawal cannot exceed the amount currently saved.");
      setMessage("");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        activeGoal.id,
        {
          saved_cents: activeGoal.saved_cents - withdrawalCents,
        }
      );

      setGoals((current) =>
        current.map((goal) =>
          goal.id === updated.id ? updated : goal
        )
      );
      setWithdrawal("");
      setMessage(`${formatCents(withdrawalCents)} withdrawn.`);
      closeDrawer();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to withdraw funds"
      );
    } finally {
      setBusy(false);
    }
  }

  function deleteGoal(goal: SavingsGoal) {
    if (busyId !== null || busy) return;

    setPendingDeleteGoal(goal);
  }

  async function confirmDeleteGoal() {
    if (!userId || !pendingDeleteGoal || busyId !== null) return;

    const goal = pendingDeleteGoal;

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      await api.deleteSavingsGoal(userId, goal.id);
      setGoals((current) =>
        current.filter((item) => item.id !== goal.id)
      );
      setPendingDeleteGoal(null);
      setMessage("Savings goal deleted.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to delete savings goal"
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="min-h-screen bg-[#f5f1e8] text-[#14241e]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#14241e]/10 pb-7 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
                  Financial milestones
                </p>

                <h1 className="mt-2 text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Goals
                </h1>

                <p className="mt-3 max-w-2xl text-sm leading-6 text-[#66746e]">
                  Plan meaningful milestones, contribute over time, and
                  understand exactly what remains.
                </p>
              </div>

              <button
                type="button"
                onClick={openCreateDrawer}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-[#14241e] px-5 text-sm font-semibold text-white transition hover:-translate-y-0.5 hover:bg-[#20352d]"
              >
                <Plus className="h-4 w-4" />
                Create goal
              </button>
            </header>
          </Reveal>

          {error && (
            <div className="mt-5">
              <PageError message={error} />
            </div>
          )}

          <Reveal delay={0.06}>
            <section className="mt-6 grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
              <article className="premium-hover relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                <div className="pointer-events-none absolute -right-16 -top-16 h-52 w-52 rounded-full bg-[#76dfbd]/15 blur-3xl" />

                <div className="relative">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                    Total saved
                  </p>

                  <AnimatedNumber
                    value={totals.saved}
                    format={formatCents}
                    className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                  />

                  <p className="mt-3 text-sm text-white/55">
                    {formatCents(
                      Math.max(totals.target - totals.saved, 0)
                    )}{" "}
                    remaining across all active goals
                  </p>

                  <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                    <GoalMetric
                      label="Target"
                      value={formatCents(totals.target)}
                      tone="neutral"
                    />
                    <GoalMetric
                      label="Progress"
                      value={`${overallProgress}%`}
                      tone="positive"
                    />
                    <GoalMetric
                      label="Completed"
                      value={`${totals.completed} of ${goals.length}`}
                      tone="neutral"
                    />
                  </div>
                </div>
              </article>

              <article className="premium-hover rounded-[30px] bg-[#f7e8b5] p-7 sm:p-8">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8b6518]">
                      Overall progress
                    </p>
                    <AnimatedNumber
                      value={overallProgress}
                      format={(value) => `${value}%`}
                      className="mt-4 block text-5xl font-semibold tracking-[-0.05em]"
                    />
                  </div>

                  <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#14241e] text-[#f7e8b5]">
                    <Target className="h-5 w-5" />
                  </span>
                </div>

                <div className="mt-8 h-2 overflow-hidden rounded-full bg-[#14241e]/10">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${overallProgress}%` }}
                    transition={{
                      duration: 0.55,
                      ease: [0.22, 1, 0.36, 1],
                    }}
                    className="h-full rounded-full bg-[#167c5a]"
                  />
                </div>

                <p className="mt-4 text-sm leading-6 text-[#6b5d39]">
                  Your portfolio includes {goals.length} goal
                  {goals.length === 1 ? "" : "s"} and{" "}
                  {totals.completed} completed milestone
                  {totals.completed === 1 ? "" : "s"}.
                </p>
              </article>
            </section>
          </Reveal>

          {loading ? (
            <div className="mt-8">
              <PageLoading message="Loading savings goals..." />
            </div>
          ) : goals.length === 0 ? (
            <div className="mt-8">
              <EmptyState
                title="No savings goals yet"
                description="Create your first milestone to begin tracking progress."
                actionLabel="Create first goal"
                onAction={openCreateDrawer}
              />
            </div>
          ) : (
            <Reveal>
              <section className="mt-8 overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
                <header className="grid gap-3 border-b border-[#14241e]/10 bg-[#faf8f3] px-5 py-4 text-xs font-semibold uppercase tracking-[0.12em] text-[#7a8780] md:grid-cols-[minmax(220px,1.4fr)_150px_minmax(220px,1fr)_150px_160px] md:items-center">
                  <span>Goal</span>
                  <span>Saved</span>
                  <span>Progress</span>
                  <span>Timeline</span>
                  <span />
                </header>

                <div className="divide-y divide-[#14241e]/8">
                  {goals.map((goal) => (
                    <GoalRow
                      key={goal.id}
                      goal={goal}
                      busy={busyId === goal.id}
                      onFund={() => openFundDrawer(goal)}
                      onEdit={() => openEditDrawer(goal)}
                      onDelete={() => deleteGoal(goal)}
                    />
                  ))}
                </div>
              </section>
            </Reveal>
          )}
        </PageReveal>
      </div>

      <AnimatePresence>
        {drawerMode && (
          <GoalDrawer
            mode={drawerMode}
            goal={activeGoal}
            form={form}
            contribution={contribution}
            withdrawal={withdrawal}
            busy={busy}
            onFormChange={setForm}
            onContributionChange={setContribution}
            onWithdrawalChange={setWithdrawal}
            onClose={closeDrawer}
            onCreate={createGoal}
            onSave={saveGoalChanges}
            onAdd={addContribution}
            onWithdraw={withdrawFunds}
          />
        )}
      </AnimatePresence>

      <Toast
        message={message}
        type="success"
        onClose={() => setMessage("")}
      />

      <AnimatePresence>
        {pendingDeleteGoal && (
          <ConfirmationModal
            eyebrow="Confirm deletion"
            title={`Delete "${pendingDeleteGoal.name}"?`}
            description="This savings goal and its recorded progress will be permanently removed from FinSight."
            cancelLabel="Keep goal"
            confirmLabel="Delete permanently"
            busyLabel="Deleting..."
            busy={busyId === pendingDeleteGoal.id}
            icon={<Trash2 className="h-5 w-5" />}
            onCancel={() => {
              if (busyId === null) {
                setPendingDeleteGoal(null);
              }
            }}
            onConfirm={() => void confirmDeleteGoal()}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function GoalMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "neutral";
}) {
  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p
        className={`mt-2 text-lg font-semibold ${
          tone === "positive" ? "text-[#83dcb9]" : "text-white"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function GoalRow({
  goal,
  busy,
  onFund,
  onEdit,
  onDelete,
}: {
  goal: SavingsGoal;
  busy: boolean;
  onFund: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const percentage = Math.min(goal.progress_percent, 100);

  const statusClass =
    goal.status === "completed"
      ? "bg-[#edf5ee] text-[#167c5a]"
      : goal.status === "overdue"
        ? "bg-[#f8ddd5] text-[#923f32]"
        : "bg-[#f1eee7] text-[#52635b]";

  return (
    <motion.article
      layout
      whileHover={
        reduceMotion
          ? undefined
          : { x: 3, backgroundColor: "#fbfaf6" }
      }
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
      className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(220px,1.4fr)_150px_minmax(220px,1fr)_150px_160px] md:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
          <Flag className="h-4 w-4" />
        </span>

        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{goal.name}</p>
          <span
            className={`mt-1 inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold capitalize ${statusClass}`}
          >
            {goal.status}
          </span>
        </div>
      </div>

      <div>
        <p className="text-sm font-semibold">
          {formatCents(goal.saved_cents)}
        </p>
        <p className="mt-1 text-xs text-[#87928d]">
          of {formatCents(goal.target_cents)}
        </p>
      </div>

      <div>
        <div className="h-2 overflow-hidden rounded-full bg-[#14241e]/8">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percentage}%` }}
            transition={{
              duration: reduceMotion ? 0 : 0.5,
              ease: [0.22, 1, 0.36, 1],
            }}
            className="h-full rounded-full bg-[#167c5a]"
          />
        </div>

        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-[#7b8781]">
          <span>{goal.progress_percent}% complete</span>
          <span>{formatCents(goal.remaining_cents)} left</span>
        </div>
      </div>

      <div>
        <p className="text-sm font-medium">
          {goal.target_date
            ? new Date(
                `${goal.target_date}T00:00:00`
              ).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })
            : "No deadline"}
        </p>
        <p className="mt-1 text-xs text-[#87928d]">
          {goal.target_date ? "Target date" : "Flexible timeline"}
        </p>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onFund}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#14241e] px-3 text-sm font-semibold text-white"
        >
          <WalletCards className="h-4 w-4" />
          Funds
        </button>

        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit ${goal.name}`}
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#14241e]/10 bg-white transition hover:bg-[#f7f4ed]"
        >
          <Edit3 className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`Delete ${goal.name}`}
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#c56755]/20 bg-[#f8ddd5] text-[#923f32] disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </motion.article>
  );
}

function GoalDrawer({
  mode,
  goal,
  form,
  contribution,
  withdrawal,
  busy,
  onFormChange,
  onContributionChange,
  onWithdrawalChange,
  onClose,
  onCreate,
  onSave,
  onAdd,
  onWithdraw,
}: {
  mode: DrawerMode;
  goal: SavingsGoal | null;
  form: GoalFormState;
  contribution: string;
  withdrawal: string;
  busy: boolean;
  onFormChange: (value: GoalFormState) => void;
  onContributionChange: (value: string) => void;
  onWithdrawalChange: (value: string) => void;
  onClose: () => void;
  onCreate: () => void;
  onSave: () => void;
  onAdd: () => void;
  onWithdraw: () => void;
}) {
  const reduceMotion = useReducedMotion();

  const title =
    mode === "create"
      ? "Create goal"
      : mode === "edit"
        ? "Edit goal"
        : "Manage funds";

  return (
    <motion.div
      className="fixed inset-0 z-50"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.2 }}
    >
      <motion.button
        type="button"
        aria-label="Close goal panel"
        onClick={onClose}
        className="absolute inset-0 bg-[#14241e]/35 backdrop-blur-[2px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />

      <motion.aside
        initial={reduceMotion ? false : { x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{
          duration: reduceMotion ? 0 : 0.32,
          ease: [0.22, 1, 0.36, 1],
        }}
        className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col bg-[#fdfcf8] shadow-2xl"
      >
        <header className="flex items-start justify-between border-b border-[#14241e]/10 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#167c5a]">
              Goal workspace
            </p>
            <h2 className="mt-2 text-xl font-semibold">{title}</h2>
            {goal && (
              <p className="mt-1 text-sm text-[#728078]">{goal.name}</p>
            )}
          </div>

          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {mode === "fund" && goal ? (
            <div className="space-y-7">
              <div className="rounded-2xl bg-[#edf5ee] p-5">
                <p className="text-xs uppercase tracking-[0.1em] text-[#728078]">
                  Currently saved
                </p>
                <p className="mt-2 text-3xl font-semibold">
                  {formatCents(goal.saved_cents)}
                </p>
                <p className="mt-2 text-sm text-[#66746e]">
                  {formatCents(goal.remaining_cents)} remaining
                </p>
              </div>

              <div>
                <label className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                  Add contribution
                </label>
                <div className="relative mt-2">
                  <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#728078]">
                    $
                  </span>
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={contribution}
                    onChange={(event) =>
                      onContributionChange(event.target.value)
                    }
                    placeholder="0.00"
                    className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-white pl-8 pr-4 text-lg font-semibold outline-none focus:border-[#167c5a]"
                  />
                </div>

                <button
                  type="button"
                  onClick={onAdd}
                  disabled={busy}
                  className="mt-3 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-[#14241e] text-sm font-semibold text-white disabled:opacity-50"
                >
                  <ArrowUpRight className="h-4 w-4" />
                  {busy ? "Working..." : "Add funds"}
                </button>
              </div>

              <div className="border-t border-[#14241e]/10 pt-7">
                <label className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                  Withdraw funds
                </label>
                <div className="relative mt-2">
                  <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[#728078]">
                    $
                  </span>
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    max={goal.saved_cents / 100}
                    value={withdrawal}
                    onChange={(event) =>
                      onWithdrawalChange(event.target.value)
                    }
                    placeholder="0.00"
                    disabled={goal.saved_cents === 0}
                    className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-white pl-8 pr-4 text-lg font-semibold outline-none focus:border-[#a87b20] disabled:opacity-50"
                  />
                </div>

                <button
                  type="button"
                  onClick={onWithdraw}
                  disabled={busy || goal.saved_cents === 0}
                  className="mt-3 inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-[#a87b20]/20 bg-[#f7e8b5] text-sm font-semibold text-[#8b6518] disabled:opacity-50"
                >
                  <ArrowDownRight className="h-4 w-4" />
                  {busy ? "Working..." : "Withdraw"}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                  Goal name
                </span>
                <input
                  value={form.name}
                  onChange={(event) =>
                    onFormChange({
                      ...form,
                      name: event.target.value,
                    })
                  }
                  placeholder="Emergency fund"
                  autoFocus
                  className="mt-2 h-12 w-full rounded-xl border border-[#14241e]/10 bg-white px-4 text-sm outline-none focus:border-[#167c5a]"
                />
              </label>

              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                  Target amount
                </span>
                <input
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={form.targetAmount}
                  onChange={(event) =>
                    onFormChange({
                      ...form,
                      targetAmount: event.target.value,
                    })
                  }
                  placeholder="10000"
                  className="mt-2 h-12 w-full rounded-xl border border-[#14241e]/10 bg-white px-4 text-sm outline-none focus:border-[#167c5a]"
                />
              </label>

              {mode === "create" && (
                <label className="block">
                  <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                    Already saved
                  </span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={form.savedAmount}
                    onChange={(event) =>
                      onFormChange({
                        ...form,
                        savedAmount: event.target.value,
                      })
                    }
                    placeholder="0"
                    className="mt-2 h-12 w-full rounded-xl border border-[#14241e]/10 bg-white px-4 text-sm outline-none focus:border-[#167c5a]"
                  />
                </label>
              )}

              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[#728078]">
                  Target date
                </span>
                <div className="relative mt-2">
                  <CalendarDays className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#728078]" />
                  <input
                    type="date"
                    value={form.targetDate}
                    onChange={(event) =>
                      onFormChange({
                        ...form,
                        targetDate: event.target.value,
                      })
                    }
                    className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-white pl-11 pr-4 text-sm outline-none focus:border-[#167c5a]"
                  />
                </div>
              </label>
            </div>
          )}
        </div>

        {mode !== "fund" && (
          <footer className="border-t border-[#14241e]/10 p-6">
            <button
              type="button"
              onClick={mode === "create" ? onCreate : onSave}
              disabled={busy}
              className="h-11 w-full rounded-xl bg-[#14241e] text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:opacity-50"
            >
              {busy
                ? "Saving..."
                : mode === "create"
                  ? "Create goal"
                  : "Save changes"}
            </button>
          </footer>
        )}
      </motion.aside>
    </motion.div>
  );
}
