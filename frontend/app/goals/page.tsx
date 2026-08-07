"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowDownRight,
  ArrowUpRight,
  AlertTriangle,
  CalendarDays,
  Edit3,
  Flag,
  History,
  Plus,
  Save,
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
  CardSkeleton,
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
  GoalContribution,
  GoalConflictDetection,
  GoalContributionType,
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

type ContributionFormState = {
  amount: string;
  contributionType: GoalContributionType;
  contributedOn: string;
  note: string;
};

const today = () => new Date().toISOString().slice(0, 10);

const EMPTY_GOAL_FORM: GoalFormState = {
  name: "",
  targetAmount: "",
  savedAmount: "",
  targetDate: "",
};

const EMPTY_CONTRIBUTION_FORM: ContributionFormState = {
  amount: "",
  contributionType: "deposit",
  contributedOn: today(),
  note: "",
};

function formatDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function GoalsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [monthlyCapacity, setMonthlyCapacity] = useState("");
  const [conflictAnalysis, setConflictAnalysis] =
    useState<GoalConflictDetection | null>(null);
  const [conflictLoading, setConflictLoading] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode | null>(null);
  const [activeGoalId, setActiveGoalId] = useState<number | null>(null);
  const [goalForm, setGoalForm] =
    useState<GoalFormState>(EMPTY_GOAL_FORM);
  const [contributionForm, setContributionForm] =
    useState<ContributionFormState>(EMPTY_CONTRIBUTION_FORM);
  const [contributions, setContributions] = useState<GoalContribution[]>([]);
  const [editingContributionId, setEditingContributionId] =
    useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [pendingDeleteGoal, setPendingDeleteGoal] =
    useState<SavingsGoal | null>(null);
  const [pendingDeleteContribution, setPendingDeleteContribution] =
    useState<GoalContribution | null>(null);
  const [error, setError] = useState("");
const [message, setMessage] = useState("");

useEffect(() => {
  if (!error) return;

  const timeout = window.setTimeout(() => {
    setError("");
  }, 8000);

  return () => window.clearTimeout(timeout);
}, [error]);

  const activeGoal =
    goals.find((goal) => goal.id === activeGoalId) ?? null;

  const loadGoals = useCallback(async (id: number) => {
    const result = await api.getSavingsGoals(id);
    setGoals(result);
    return result;
  }, []);

  const loadContributions = useCallback(
    async (id: number, goalId: number) => {
      setHistoryLoading(true);

      try {
        const result = await api.getGoalContributions(id, goalId);
        setContributions(result);
      } finally {
        setHistoryLoading(false);
      }
    },
    []
  );

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
        await loadGoals(id);
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
  }, [loadGoals, router]);

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

  function resetContributionForm() {
    setContributionForm({
      ...EMPTY_CONTRIBUTION_FORM,
      contributedOn: today(),
    });
    setEditingContributionId(null);
  }

  function closeDrawer() {
    if (busy) return;

    setDrawerMode(null);
    setActiveGoalId(null);
    setGoalForm(EMPTY_GOAL_FORM);
    setContributions([]);
    resetContributionForm();
  }

  function openCreateDrawer() {
    setDrawerMode("create");
    setActiveGoalId(null);
    setGoalForm(EMPTY_GOAL_FORM);
    setContributions([]);
    resetContributionForm();
    setError("");
  }

  function openEditDrawer(goal: SavingsGoal) {
    setDrawerMode("edit");
    setActiveGoalId(goal.id);
    setGoalForm({
      name: goal.name,
      targetAmount: String(goal.target_cents / 100),
      savedAmount: "",
      targetDate: goal.target_date || "",
    });
    setContributions([]);
    resetContributionForm();
    setError("");
  }

  async function openFundDrawer(goal: SavingsGoal) {
    if (!userId) return;

    setDrawerMode("fund");
    setActiveGoalId(goal.id);
    setGoalForm(EMPTY_GOAL_FORM);
    resetContributionForm();
    setError("");

    try {
      await loadContributions(userId, goal.id);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to load contribution history"
      );
    }
  }

  async function analyzeGoalConflicts() {
    if (!userId) return;

    const capacityCents = Math.round(Number(monthlyCapacity) * 100);

    if (
      !monthlyCapacity.trim() ||
      !Number.isFinite(capacityCents) ||
      capacityCents < 0
    ) {
      setError("Enter a valid monthly savings capacity.");
      return;
    }

    setConflictLoading(true);
    setError("");

    try {
      const result = await api.detectGoalConflicts(userId, {
        monthly_savings_capacity_cents: capacityCents,
      });

      setConflictAnalysis(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to analyze goal conflicts"
      );
    } finally {
      setConflictLoading(false);
    }
  }

  async function createGoal() {
    if (!userId) return;

    const targetCents = Math.round(Number(goalForm.targetAmount) * 100);
    const savedCents = goalForm.savedAmount
      ? Math.round(Number(goalForm.savedAmount) * 100)
      : 0;

    if (
      !goalForm.name.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0 ||
      !Number.isFinite(savedCents) ||
      savedCents < 0
    ) {
      setError("Enter a valid goal name and target amount.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const created = await api.createSavingsGoal(userId, {
        name: goalForm.name.trim(),
        target_cents: targetCents,
        saved_cents: savedCents,
        target_date: goalForm.targetDate || null,
      });

      setGoals((current) => [created, ...current]);
      setMessage("Savings goal created successfully.");
      setDrawerMode(null);
      setGoalForm(EMPTY_GOAL_FORM);
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

    const targetCents = Math.round(Number(goalForm.targetAmount) * 100);

    if (
      !goalForm.name.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0
    ) {
      setError("Enter a valid goal name and target amount.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        activeGoal.id,
        {
          name: goalForm.name.trim(),
          target_cents: targetCents,
          target_date: goalForm.targetDate || null,
        }
      );

      setGoals((current) =>
        current.map((goal) => (goal.id === updated.id ? updated : goal))
      );
      setMessage("Savings goal updated.");
      setDrawerMode(null);
      setActiveGoalId(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to update savings goal"
      );
    } finally {
      setBusy(false);
    }
  }

  async function refreshFundData() {
    if (!userId || !activeGoalId) return;

    await Promise.all([
      loadGoals(userId),
      loadContributions(userId, activeGoalId),
    ]);
  }

  async function saveContribution() {
    if (!userId || !activeGoal) return;

    const amountCents = Math.round(
      Number(contributionForm.amount) * 100
    );

    if (!Number.isFinite(amountCents) || amountCents <= 0) {
      setError("Enter a valid amount greater than $0.");
      return;
    }

    if (
      contributionForm.contributionType === "withdrawal" &&
      !editingContributionId &&
      amountCents > activeGoal.saved_cents
    ) {
      setError("Withdrawal cannot exceed the amount currently saved.");
      return;
    }

    if (!contributionForm.contributedOn) {
      setError("Choose a contribution date.");
      return;
    }

    setBusy(true);
    setError("");

    try {
      const payload = {
        amount_cents: amountCents,
        contribution_type: contributionForm.contributionType,
        contributed_on: contributionForm.contributedOn,
        note: contributionForm.note.trim() || null,
      };

      if (editingContributionId) {
        await api.updateGoalContribution(
          userId,
          activeGoal.id,
          editingContributionId,
          payload
        );
        setMessage("Contribution updated.");
      } else {
        await api.createGoalContribution(
          userId,
          activeGoal.id,
          payload
        );
        setMessage(
          contributionForm.contributionType === "deposit"
            ? `${formatCents(amountCents)} deposited.`
            : `${formatCents(amountCents)} withdrawn.`
        );
      }

      resetContributionForm();

      try {
        await refreshFundData();
      } catch {
        // The contribution itself was saved successfully; only the
        // follow-up list refresh failed, so keep the success message
        // instead of contradicting it with an error.
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to save contribution"
      );
    } finally {
      setBusy(false);
    }
  }

  function editContribution(item: GoalContribution) {
    setEditingContributionId(item.id);
    setContributionForm({
      amount: String(item.amount_cents / 100),
      contributionType: item.contribution_type,
      contributedOn: item.contributed_on,
      note: item.note || "",
    });
    setError("");
  }

  function requestDeleteContribution(item: GoalContribution) {
    if (busy) return;
    setPendingDeleteContribution(item);
  }

  async function confirmDeleteContribution() {
    if (
      !userId ||
      !activeGoal ||
      !pendingDeleteContribution ||
      busy
    ) {
      return;
    }

    setBusy(true);
    setError("");

    try {
      await api.deleteGoalContribution(
        userId,
        activeGoal.id,
        pendingDeleteContribution.id
      );
      setPendingDeleteContribution(null);
      resetContributionForm();
      setMessage("Contribution deleted.");

      try {
        await refreshFundData();
      } catch {
        // The deletion itself succeeded; only the follow-up list
        // refresh failed, so keep the success message instead of
        // contradicting it with an error.
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete contribution"
      );
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteGoal() {
    if (!userId || !pendingDeleteGoal || busyId !== null) return;

    const goal = pendingDeleteGoal;
    setBusyId(goal.id);
    setError("");

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
                  Build meaningful milestones and track every deposit and
                  withdrawal in one place.
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

          {error && !drawerMode && (
  <div className="mt-5">
    <PageError
      message={error}
      onRetry={userId ? () => void loadGoals(userId) : undefined}
    />
  </div>
)}

          {loading ? (
            <div className="mt-6">
              <CardSkeleton count={2} />
            </div>
          ) : (
          <Reveal delay={0.06}>
            <section className="mt-6 grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
              <article className="relative overflow-hidden rounded-[30px] bg-[#14241e] p-7 text-white shadow-[0_24px_70px_rgba(20,36,30,0.18)] sm:p-9">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#83dcb9]">
                  Total saved
                </p>
                <AnimatedNumber
                  value={totals.saved}
                  format={formatCents}
                  className="mt-4 block text-5xl font-semibold tracking-[-0.06em] sm:text-6xl"
                />
                <p className="mt-3 text-sm text-white/55">
                  {formatCents(Math.max(totals.target - totals.saved, 0))}{" "}
                  remaining across all goals
                </p>

                <div className="mt-10 grid gap-px overflow-hidden rounded-2xl bg-white/10 sm:grid-cols-3">
                  <Metric label="Target" value={formatCents(totals.target)} />
                  <Metric label="Progress" value={`${overallProgress}%`} />
                  <Metric
                    label="Completed"
                    value={`${totals.completed} of ${goals.length}`}
                  />
                </div>
              </article>

              <article className="rounded-[30px] bg-[#f7e8b5] p-7 sm:p-8">
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
                    className="h-full rounded-full bg-[#167c5a]"
                  />
                </div>
              </article>
            </section>
          </Reveal>
          )}

          <Reveal delay={0.1}>
            <GoalConflictPanel
              monthlyCapacity={monthlyCapacity}
              analysis={conflictAnalysis}
              loading={conflictLoading}
              disabled={loading || goals.length === 0}
              onCapacityChange={setMonthlyCapacity}
              onAnalyze={() => void analyzeGoalConflicts()}
            />
          </Reveal>

          {loading ? (
            <div className="mt-8">
              <PageLoading message="Loading savings goals..." />
            </div>
          ) : goals.length === 0 ? (
            error ? null : (
            <div className="mt-8">
              <EmptyState
                title="No savings goals yet"
                description="Create your first milestone to begin tracking progress."
                actionLabel="Create first goal"
                onAction={openCreateDrawer}
              />
            </div>
            )
          ) : (
            <Reveal>
              <section className="mt-8 overflow-hidden rounded-[24px] border border-[#14241e]/10 bg-white">
                <div className="divide-y divide-[#14241e]/8">
                  {goals.map((goal) => (
                    <GoalRow
                      key={goal.id}
                      goal={goal}
                      busy={busyId === goal.id}
                      onFund={() => void openFundDrawer(goal)}
                      onEdit={() => openEditDrawer(goal)}
                      onDelete={() => setPendingDeleteGoal(goal)}
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
          <DrawerShell onClose={closeDrawer}>
  {error && (
    <div className="mb-5">
      <PageError
        message={error}
        onRetry={
          drawerMode === "fund" && activeGoal
            ? () => void openFundDrawer(activeGoal)
            : undefined
        }
      />
    </div>
  )}

  {drawerMode === "create" && (
              <GoalEditor
                title="Create a savings goal"
                description="Set a target and optionally record an opening balance."
                form={goalForm}
                showOpeningBalance
                busy={busy}
                onChange={setGoalForm}
                onSubmit={() => void createGoal()}
                submitLabel="Create goal"
              />
            )}

            {drawerMode === "edit" && activeGoal && (
              <GoalEditor
                title="Edit savings goal"
                description="Update the milestone details without changing its recorded balance."
                form={goalForm}
                showOpeningBalance={false}
                busy={busy}
                onChange={setGoalForm}
                onSubmit={() => void saveGoalChanges()}
                submitLabel="Save changes"
              />
            )}

            {drawerMode === "fund" && activeGoal && (
              <FundManager
                goal={activeGoal}
                form={contributionForm}
                contributions={contributions}
                editingId={editingContributionId}
                loading={historyLoading}
                busy={busy}
                onFormChange={setContributionForm}
                onSave={() => void saveContribution()}
                onCancelEdit={resetContributionForm}
                onEdit={editContribution}
                onDelete={requestDeleteContribution}
              />
            )}
          </DrawerShell>
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
            description="This goal and its complete contribution history will be permanently removed."
            cancelLabel="Keep goal"
            confirmLabel="Delete permanently"
            busyLabel="Deleting..."
            busy={busyId === pendingDeleteGoal.id}
            icon={<Trash2 className="h-5 w-5" />}
            onCancel={() => setPendingDeleteGoal(null)}
            onConfirm={() => void confirmDeleteGoal()}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pendingDeleteContribution && (
          <ConfirmationModal
            eyebrow="Confirm deletion"
            title="Delete this contribution?"
            description="The goal balance will be recalculated automatically."
            cancelLabel="Keep record"
            confirmLabel="Delete record"
            busyLabel="Deleting..."
            busy={busy}
            icon={<Trash2 className="h-5 w-5" />}
            onCancel={() => setPendingDeleteContribution(null)}
            onConfirm={() => void confirmDeleteContribution()}
          />
        )}
      </AnimatePresence>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/[0.045] p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/35">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
    </div>
  );
}

function GoalConflictPanel({
  monthlyCapacity,
  analysis,
  loading,
  disabled,
  onCapacityChange,
  onAnalyze,
}: {
  monthlyCapacity: string;
  analysis: GoalConflictDetection | null;
  loading: boolean;
  disabled: boolean;
  onCapacityChange: (value: string) => void;
  onAnalyze: () => void;
}) {
  return (
    <section className="mt-8 rounded-[30px] border border-[#14241e]/10 bg-white p-6">
      <div className="flex items-center gap-3">
        <AlertTriangle className="h-5 w-5 text-[#8b6518]" />
        <h2 className="text-2xl font-semibold">Goal conflict check</h2>
      </div>

      <p className="mt-3 text-sm text-[#66746e]">
        Compare your monthly savings capacity against every active goal.
      </p>

      <div className="mt-5 grid gap-4 lg:grid-cols-[320px_1fr]">
        <div>
          <Field label="Monthly savings capacity">
            <input
              type="number"
              min="0"
              step="0.01"
              value={monthlyCapacity}
              onChange={(event) => onCapacityChange(event.target.value)}
              className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
              placeholder="1000.00"
              disabled={disabled || loading}
            />
          </Field>

          <button
            type="button"
            onClick={onAnalyze}
            disabled={disabled || loading}
            className="mt-4 min-h-11 w-full rounded-2xl bg-[#14241e] px-5 text-sm font-semibold text-white disabled:opacity-50"
          >
            {loading ? "Analyzing..." : "Analyze goal conflicts"}
          </button>
        </div>

        <div className="rounded-2xl bg-[#f5f1e8] p-5">
          {!analysis ? (
            <p className="text-sm text-[#66746e]">
              {disabled
                ? "Create a savings goal before running the analysis."
                : "Run the analysis to see goal risk and monthly shortfalls."}
            </p>
          ) : (
            <>
              <p className="text-lg font-semibold capitalize">
                {analysis.conflict_status.replaceAll("_", " ")}
              </p>
              <p className="mt-2 text-sm leading-6 text-[#66746e]">
                {analysis.explanation}
              </p>

              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <SummaryCard
                  label="Capacity"
                  value={formatCents(
                    analysis.monthly_savings_capacity_cents
                  )}
                />
                <SummaryCard
                  label="Required"
                  value={formatCents(
                    analysis.total_required_monthly_cents
                  )}
                />
                <SummaryCard
                  label="Shortfall"
                  value={formatCents(analysis.monthly_shortfall_cents)}
                />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
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
  const percentage = Math.min(goal.progress_percent, 100);

  return (
    <motion.article
      layout
      className="grid gap-4 px-5 py-5 md:grid-cols-[minmax(220px,1.35fr)_160px_minmax(220px,1fr)_170px] md:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#edf5ee] text-[#167c5a]">
          <Flag className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{goal.name}</p>
          <p className="mt-1 text-xs capitalize text-[#87928d]">
            {goal.status}
          </p>
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
            className="h-full rounded-full bg-[#167c5a]"
          />
        </div>
        <div className="mt-2 flex justify-between gap-3 text-xs text-[#7b8781]">
          <span>{goal.progress_percent}% complete</span>
          <span>{formatCents(goal.remaining_cents)} left</span>
        </div>
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
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#14241e]/10"
        >
          <Edit3 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`Delete ${goal.name}`}
          className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#f8ddd5] text-[#923f32] disabled:opacity-50"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </motion.article>
  );
}

function DrawerShell({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <>
      <motion.button
        type="button"
        aria-label="Close drawer"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 z-40 bg-[#14241e]/35 backdrop-blur-sm"
      />
      <motion.aside
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", stiffness: 300, damping: 32 }}
        className="fixed inset-y-0 right-0 z-50 w-full overflow-y-auto bg-[#fbfaf6] shadow-2xl sm:max-w-xl"
      >
        <div className="sticky top-0 z-10 flex justify-end bg-[#fbfaf6] p-5">
          <button
            type="button"
            onClick={onClose}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#14241e]/10 bg-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-6 pb-10 sm:px-8">{children}</div>
      </motion.aside>
    </>
  );
}

function GoalEditor({
  title,
  description,
  form,
  showOpeningBalance,
  busy,
  onChange,
  onSubmit,
  submitLabel,
}: {
  title: string;
  description: string;
  form: GoalFormState;
  showOpeningBalance: boolean;
  busy: boolean;
  onChange: (value: GoalFormState) => void;
  onSubmit: () => void;
  submitLabel: string;
}) {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
        Goal details
      </p>
      <h2 className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
        {title}
      </h2>
      <p className="mt-3 text-sm leading-6 text-[#66746e]">
        {description}
      </p>

      <div className="mt-8 space-y-5">
        <Field label="Goal name">
          <input
            value={form.name}
            onChange={(event) =>
              onChange({ ...form, name: event.target.value })
            }
            className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
            placeholder="Emergency fund"
          />
        </Field>

        <Field label="Target amount">
          <input
            type="number"
            min="0"
            step="0.01"
            value={form.targetAmount}
            onChange={(event) =>
              onChange({ ...form, targetAmount: event.target.value })
            }
            className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
            placeholder="10000"
          />
        </Field>

        {showOpeningBalance && (
          <Field label="Opening balance">
            <input
              type="number"
              min="0"
              step="0.01"
              value={form.savedAmount}
              onChange={(event) =>
                onChange({ ...form, savedAmount: event.target.value })
              }
              className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
              placeholder="0"
            />
          </Field>
        )}

        <Field label="Target date">
          <input
            type="date"
            value={form.targetDate}
            onChange={(event) =>
              onChange({ ...form, targetDate: event.target.value })
            }
            className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
          />
        </Field>

        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[#14241e] px-5 text-sm font-semibold text-white disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {busy ? "Saving..." : submitLabel}
        </button>
      </div>
    </section>
  );
}

function FundManager({
  goal,
  form,
  contributions,
  editingId,
  loading,
  busy,
  onFormChange,
  onSave,
  onCancelEdit,
  onEdit,
  onDelete,
}: {
  goal: SavingsGoal;
  form: ContributionFormState;
  contributions: GoalContribution[];
  editingId: number | null;
  loading: boolean;
  busy: boolean;
  onFormChange: (value: ContributionFormState) => void;
  onSave: () => void;
  onCancelEdit: () => void;
  onEdit: (item: GoalContribution) => void;
  onDelete: (item: GoalContribution) => void;
}) {
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#167c5a]">
        Manage funds
      </p>
      <h2 className="mt-2 break-words text-3xl font-semibold tracking-[-0.04em]">
        {goal.name}
      </h2>

      <div className="mt-6 grid grid-cols-2 gap-3">
        <SummaryCard label="Saved" value={formatCents(goal.saved_cents)} />
        <SummaryCard
          label="Remaining"
          value={formatCents(goal.remaining_cents)}
        />
      </div>

      <div className="mt-8 rounded-[24px] border border-[#14241e]/10 bg-white p-5">
        <div className="grid grid-cols-2 gap-2 rounded-2xl bg-[#f1eee7] p-1">
          {(["deposit", "withdrawal"] as GoalContributionType[]).map(
            (type) => (
              <button
                key={type}
                type="button"
                onClick={() =>
                  onFormChange({ ...form, contributionType: type })
                }
                className={`rounded-xl px-3 py-2.5 text-sm font-semibold capitalize ${
                  form.contributionType === type
                    ? "bg-[#14241e] text-white"
                    : "text-[#66746e]"
                }`}
              >
                {type}
              </button>
            )
          )}
        </div>

        <div className="mt-5 space-y-4">
          <Field label="Amount">
            <input
              type="number"
              min="0"
              step="0.01"
              value={form.amount}
              onChange={(event) =>
                onFormChange({ ...form, amount: event.target.value })
              }
              className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
              placeholder="100.00"
            />
          </Field>

          <Field label="Date">
            <input
              type="date"
              value={form.contributedOn}
              onChange={(event) =>
                onFormChange({
                  ...form,
                  contributedOn: event.target.value,
                })
              }
              className="h-12 w-full rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
            />
          </Field>

          <Field label="Note">
            <textarea
              value={form.note}
              onChange={(event) =>
                onFormChange({ ...form, note: event.target.value })
              }
              className="min-h-24 w-full resize-none rounded-xl border border-[#14241e]/10 bg-[#fbfaf7] px-4 py-3 text-sm outline-none transition focus:border-[#167c5a] focus:bg-white"
              placeholder="Optional note"
              maxLength={255}
            />
          </Field>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSave}
              disabled={busy}
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-2xl bg-[#14241e] px-4 text-sm font-semibold text-white disabled:opacity-50"
            >
              {form.contributionType === "deposit" ? (
                <ArrowUpRight className="h-4 w-4" />
              ) : (
                <ArrowDownRight className="h-4 w-4" />
              )}
              {busy
                ? "Saving..."
                : editingId
                  ? "Update record"
                  : `Add ${form.contributionType}`}
            </button>

            {editingId && (
              <button
                type="button"
                onClick={onCancelEdit}
                disabled={busy}
                className="rounded-2xl border border-[#14241e]/10 px-4 text-sm font-semibold"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-[#167c5a]" />
          <h3 className="text-lg font-semibold">Contribution history</h3>
        </div>

        {loading ? (
          <div className="mt-4">
            <PageLoading message="Loading contribution history..." />
          </div>
        ) : contributions.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-[#14241e]/15 p-6 text-center text-sm text-[#66746e]">
            No contribution history yet.
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {contributions.map((item) => (
              <ContributionRow
                key={item.id}
                item={item}
                busy={busy}
                onEdit={() => onEdit(item)}
                onDelete={() => onDelete(item)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function ContributionRow({
  item,
  busy,
  onEdit,
  onDelete,
}: {
  item: GoalContribution;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const isWithdrawal = item.contribution_type === "withdrawal";

  return (
    <article className="rounded-2xl border border-[#14241e]/10 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
              isWithdrawal
                ? "bg-[#f8ddd5] text-[#923f32]"
                : "bg-[#edf5ee] text-[#167c5a]"
            }`}
          >
            {isWithdrawal ? (
              <ArrowDownRight className="h-4 w-4" />
            ) : (
              <ArrowUpRight className="h-4 w-4" />
            )}
          </span>

          <div className="min-w-0">
            <p
              className={`text-sm font-semibold ${
                isWithdrawal ? "text-[#923f32]" : "text-[#167c5a]"
              }`}
            >
              {isWithdrawal ? "−" : "+"}
              {formatCents(item.amount_cents)}
            </p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-[#7b8781]">
              <CalendarDays className="h-3.5 w-3.5" />
              {formatDate(item.contributed_on)}
            </p>
            {item.note && (
              <p className="mt-2 break-words text-sm text-[#66746e]">
                {item.note}
              </p>
            )}
          </div>
        </div>

        <div className="flex gap-1">
          <button
            type="button"
            onClick={onEdit}
            disabled={busy}
            aria-label="Edit contribution"
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#14241e]/10 disabled:opacity-50"
          >
            <Edit3 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            aria-label="Delete contribution"
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#f8ddd5] text-[#923f32] disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </article>
  );
}

function SummaryCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-2xl bg-[#14241e] p-4 text-white">
      <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/45">
        {label}
      </p>
      <p className="mt-2 text-lg font-semibold">{value}</p>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-[#66746e]">
        {label}
      </span>
      {children}
    </label>
  );
}
