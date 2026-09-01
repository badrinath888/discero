"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
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
  GoalIntelligence,
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
  const reduceMotion = useReducedMotion();

  const [userId, setUserId] = useState<number | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [monthlyCapacity, setMonthlyCapacity] = useState("");
  const [conflictAnalysis, setConflictAnalysis] =
    useState<GoalIntelligence | null>(null);
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

  const runConflictAnalysis = useCallback(
    async (id: number, capacityCents?: number) => {
      setConflictLoading(true);
      setError("");

      try {
        const result = await api.getGoalIntelligence(id, capacityCents);
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
        const loadedGoals = await loadGoals(id);

        if (loadedGoals.length > 0) {
          // No manual capacity entered yet -- let the backend estimate
          // a realistic one from recent income and obligations so the
          // panel answers "can I fund my goals?" without the user
          // having to guess a number first.
          void runConflictAnalysis(id);
        }
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
  }, [loadGoals, router, runConflictAnalysis]);

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
      ? Math.round((totals.saved / totals.target) * 100)
      : 0;
  const trajectoryPosition = Math.min(Math.max(overallProgress, 0), 100);
  const activeGoalCount = goals.length - totals.completed;

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

    const trimmedCapacity = monthlyCapacity.trim();

    if (!trimmedCapacity) {
      // Blank override -- let the backend estimate a realistic
      // capacity from recent income and obligations.
      await runConflictAnalysis(userId);
      return;
    }

    const capacityCents = Math.round(Number(monthlyCapacity) * 100);

    if (!Number.isFinite(capacityCents) || capacityCents < 0) {
      setError("Enter a valid monthly savings capacity.");
      return;
    }

    await runConflictAnalysis(userId, capacityCents);
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
    <main className="min-h-screen bg-[#F5F1EA] text-[#181713]">
      <AppSidebar />

      <div className="px-4 pb-14 pt-20 sm:px-8 lg:ml-56 lg:px-10 lg:pt-9">
        <PageReveal className="mx-auto max-w-[1500px]">
          <Reveal>
            <header className="flex flex-col gap-6 border-b border-[#181713]/10 pb-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                  Future money
                </p>
                <h1 className="mt-1 text-[32px] font-semibold tracking-[-0.03em]">
                  Savings goals
                </h1>
                <p className="mt-1 text-sm text-[#706961]">
                  Progress toward what matters next.
                </p>
              </div>

              <button
                type="button"
                onClick={openCreateDrawer}
                className="discero-button-primary inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold transition hover:-translate-y-0.5"
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
              <section className="mt-6 border-y border-[#181713]/10 bg-[#FFFCF7] px-5 py-7 sm:px-8 sm:py-8">
                <div className="grid gap-6 xl:grid-cols-[minmax(260px,0.9fr)_minmax(480px,1.25fr)] xl:items-end">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
                      Goal position
                    </p>
                    <p className="mt-3 text-sm font-medium text-[#706961]">Saved</p>
                    <AnimatedNumber
                      value={totals.saved}
                      format={formatCents}
                      duration={0.75}
                      className="mt-1 block text-5xl font-semibold leading-none tracking-[-0.06em] text-[#2F2930] [overflow-wrap:anywhere] sm:text-6xl"
                    />
                  </div>

                  <motion.dl
                    initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: reduceMotion ? 0 : 0.35, delay: reduceMotion ? 0 : 0.28 }}
                    className="grid text-sm sm:grid-cols-3 sm:divide-x sm:divide-[#181713]/10"
                  >
                    <div className="border-b border-[#181713]/10 py-2 sm:border-b-0 sm:py-0 sm:pr-5">
                      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">Target</dt>
                      <dd className="mt-1 text-lg font-semibold tabular-nums [overflow-wrap:anywhere]">{formatCents(totals.target)}</dd>
                    </div>
                    <div className="border-b border-[#181713]/10 py-2 sm:border-b-0 sm:px-5 sm:py-0">
                      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">Active goals</dt>
                      <dd className="mt-1 text-lg font-semibold tabular-nums">{activeGoalCount}</dd>
                    </div>
                    <div className="py-2 sm:py-0 sm:pl-5">
                      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#8A8178]">Funded</dt>
                      <dd className="mt-1 text-lg font-semibold tabular-nums">{overallProgress}%</dd>
                    </div>
                  </motion.dl>
                </div>

                <div className="mt-6 border-t border-[#181713]/10 pt-4" aria-label="Overall goal trajectory">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#706961]">
                    <span className="font-semibold text-[#2F2930]">Goal progress</span>
                    <span><strong className="font-semibold tabular-nums text-[#2F2930]">{formatCents(Math.max(totals.target - totals.saved, 0))}</strong> remaining</span>
                  </div>

                  <div className="mt-3 grid grid-cols-[auto_minmax(70px,1fr)_auto] items-start gap-3 text-xs font-semibold tabular-nums text-[#706961]">
                    <span>$0</span>
                    <div className="relative h-7">
                      <div className="absolute inset-x-0 top-1.5 h-px bg-[#181713]/18" />
                      <motion.div
                        initial={reduceMotion ? false : { width: 0 }}
                        animate={{ width: `${trajectoryPosition}%` }}
                        transition={{ duration: reduceMotion ? 0 : 0.65, delay: reduceMotion ? 0 : 0.42, ease: [0.22, 1, 0.36, 1] }}
                        className="absolute left-0 top-1.5 h-0.5 bg-[#6E4B63]"
                      />
                      <motion.div
                        initial={reduceMotion ? false : { left: 0, opacity: 0, scale: 0.75 }}
                        animate={{ left: `${trajectoryPosition}%`, opacity: 1, scale: 1 }}
                        transition={{ duration: reduceMotion ? 0 : 0.38, delay: reduceMotion ? 0 : 0.84, ease: [0.22, 1, 0.36, 1] }}
                        className={`absolute top-1.5 h-3.5 w-3.5 -translate-y-1/2 rounded-full border-[3px] border-[#FFFCF7] bg-[#6E4B63] shadow-[0_0_0_1px_rgba(110,75,99,0.28)] ${
                          trajectoryPosition === 0
                            ? "translate-x-0"
                            : trajectoryPosition === 100
                              ? "-translate-x-full"
                              : "-translate-x-1/2"
                        }`}
                      />
                      <motion.span
                        initial={reduceMotion ? false : { opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ duration: reduceMotion ? 0 : 0.28, delay: reduceMotion ? 0 : 1.02 }}
                        style={{ left: `${trajectoryPosition}%` }}
                        className={`absolute top-3.5 text-xs font-semibold text-[#6E4B63] ${
                          trajectoryPosition <= 8
                            ? "translate-x-0"
                            : trajectoryPosition >= 92
                              ? "-translate-x-full"
                              : "-translate-x-1/2"
                        }`}
                      >
                        {overallProgress}%
                      </motion.span>
                    </div>
                    <span className="max-w-[42vw] text-right [overflow-wrap:anywhere]">{formatCents(totals.target)}</span>
                  </div>
                </div>
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
              <section className="mt-8 overflow-hidden border-y border-[#181713]/10 bg-[#FFFCF7]">
                <div className="divide-y divide-[#181713]/8">
                  {goals.map((goal, index) => (
                    <GoalRow
                      key={goal.id}
                      goal={goal}
                      index={index}
                      intelligenceGoal={conflictAnalysis?.goals.find((item) => item.goal_id === goal.id)}
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
          <DrawerShell
            onClose={closeDrawer}
            label={
              drawerMode === "create"
                ? "Create a savings goal"
                : drawerMode === "edit"
                  ? "Edit savings goal"
                  : activeGoal
                    ? `Manage funds for ${activeGoal.name}`
                    : "Manage funds"
            }
          >
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

const GOAL_INTELLIGENCE_STATUS_STYLE: Record<string, string> = {
  on_track: "bg-[#E3EBE1] text-[#48634B]",
  ahead: "bg-[#DCEBDD] text-[#3B5A3E]",
  at_risk: "bg-[#fbeecb] text-[#8b6518]",
  conflict: "bg-[#f8ddd5] text-[#923f32]",
  not_feasible: "bg-[#f3c2b6] text-[#7a2e23]",
  completed: "bg-[#e8ecea] text-[#4b5a54]",
  no_deadline: "bg-[#e8ecea] text-[#4b5a54]",
};

function GoalConflictPanel({
  monthlyCapacity,
  analysis,
  loading,
  disabled,
  onCapacityChange,
  onAnalyze,
}: {
  monthlyCapacity: string;
  analysis: GoalIntelligence | null;
  loading: boolean;
  disabled: boolean;
  onCapacityChange: (value: string) => void;
  onAnalyze: () => void;
}) {
  const comparisonMax = analysis
    ? Math.max(analysis.total_capacity_cents, analysis.total_required_cents, 1)
    : 1;

  return (
    <section className="mt-8 border-y border-[#181713]/10 bg-[#FFFCF7] p-6 sm:p-8">
      <div className="flex items-center gap-3">
        <AlertTriangle className="h-5 w-5 text-[#8b6518]" />
        <h2 className="text-2xl font-semibold">Goal intelligence</h2>
      </div>

      <p className="mt-3 text-sm text-[#706961]">
        See which goal is most urgent, how much each needs per month, and
        whether your capacity covers them all.
      </p>

      <div className="mt-5 grid gap-4 lg:grid-cols-[320px_1fr]">
        <div>
          <Field label="Monthly savings capacity (optional)">
            <input
              type="number"
              min="0"
              step="0.01"
              value={monthlyCapacity}
              onChange={(event) => onCapacityChange(event.target.value)}
              className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
              placeholder="Estimated automatically if left blank"
              disabled={disabled || loading}
            />
          </Field>

          <button
            type="button"
            onClick={onAnalyze}
            disabled={disabled || loading}
            className="discero-button-primary mt-4 min-h-11 w-full rounded-2xl px-5 text-sm font-semibold"
          >
            {loading ? "Analyzing..." : "Re-analyze my goals"}
          </button>
        </div>

        <div className="rounded-2xl bg-[#F5F1EA] p-5">
          {!analysis ? (
            <p className="text-sm text-[#706961]">
              {disabled
                ? "Create a savings goal before running the analysis."
                : "Analyzing your goals against your recent income and obligations..."}
            </p>
          ) : (
            <>
              <p className="text-lg font-semibold capitalize">
                {analysis.conflict_status === "no_conflict"
                  ? "Goals are on track"
                  : analysis.conflict_status.replaceAll("_", " ")}
              </p>
              <p className="mt-2 text-sm leading-6 text-[#706961]">
                {analysis.explanation}
              </p>

              {analysis.warnings.length > 0 && (
                <p className="mt-2 text-xs text-[#8A8178]">
                  {analysis.warnings.join(" ")}
                </p>
              )}

              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <SummaryCard
                  label="Capacity"
                  value={formatCents(analysis.total_capacity_cents)}
                  tone="positive"
                />
                <SummaryCard
                  label="Required"
                  value={formatCents(analysis.total_required_cents)}
                  tone="neutral"
                />
                <SummaryCard
                  label={
                    analysis.total_shortfall_cents > 0
                      ? "Funding gap"
                      : "Headroom"
                  }
                  value={formatCents(
                    analysis.total_shortfall_cents > 0
                      ? analysis.total_shortfall_cents
                      : analysis.monthly_headroom_cents
                  )}
                  tone={analysis.total_shortfall_cents > 0 ? "warning" : "positive-strong"}
                />
              </div>

              <div className="mt-5 space-y-3 border-y border-[#181713]/10 py-4">
                <div className="grid grid-cols-[80px_1fr_auto] items-center gap-3 text-xs">
                  <span className="font-semibold text-[#706961]">Capacity</span>
                  <div className="h-2 overflow-hidden rounded-full bg-[#181713]/8"><motion.div initial={{ width: 0 }} animate={{ width: `${(analysis.total_capacity_cents / comparisonMax) * 100}%` }} transition={{ duration: 0.65 }} className="h-full rounded-full bg-[#58715A]" /></div>
                  <span className="font-semibold tabular-nums">{formatCents(analysis.total_capacity_cents)}</span>
                </div>
                <div className="grid grid-cols-[80px_1fr_auto] items-center gap-3 text-xs">
                  <span className="font-semibold text-[#706961]">Required</span>
                  <div className="h-2 overflow-hidden rounded-full bg-[#181713]/8"><motion.div initial={{ width: 0 }} animate={{ width: `${(analysis.total_required_cents / comparisonMax) * 100}%` }} transition={{ duration: 0.75 }} className="h-full rounded-full bg-[#B86D4B]" /></div>
                  <span className="font-semibold tabular-nums">{formatCents(analysis.total_required_cents)}</span>
                </div>
              </div>

              <RecommendationSection analysis={analysis} />
            </>
          )}
        </div>
      </div>

      {analysis && analysis.goals.length > 0 && (
        <div className="mt-6 space-y-3">
          {analysis.goals.map((goal) => (
            <article
              key={goal.goal_id}
              className={`rounded-2xl border p-4 ${
                goal.goal_id === analysis.largest_pressure_goal_id
                  ? "border-[#923f32]/30 bg-[#fdf4f1]"
                  : "border-[#181713]/10 bg-white"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {goal.urgency_rank === 1 && (
                    <span className="rounded-full bg-[#181713] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-white">
                      Most urgent
                    </span>
                  )}
                  <p className="text-sm font-semibold">{goal.name}</p>
                  {goal.goal_id === analysis.largest_pressure_goal_id && (
                    <span className="text-[11px] font-medium text-[#923f32]">
                      Largest contributor to shortfall
                    </span>
                  )}
                </div>
                <span
                  className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ${
                    GOAL_INTELLIGENCE_STATUS_STYLE[goal.status] ??
                    "bg-[#e8ecea] text-[#4b5a54]"
                  }`}
                >
                  {goal.status.replaceAll("_", " ")}
                </span>
              </div>

              <p className="mt-2 text-sm leading-6 text-[#706961]">
                {goal.explanation}
              </p>

              <div className="mt-3 grid gap-3 text-xs text-[#706961] sm:grid-cols-3 lg:grid-cols-5">
                <div>
                  <p className="uppercase tracking-[0.08em] text-[#8A8178]">
                    Required / mo
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#181713]">
                    {formatCents(goal.required_monthly_cents)}
                  </p>
                </div>
                <div>
                  <p className="uppercase tracking-[0.08em] text-[#8A8178]">
                    Monthly gap
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#181713]">
                    {formatCents(goal.monthly_gap_cents)}
                  </p>
                </div>
                <div>
                  <p className="uppercase tracking-[0.08em] text-[#8A8178]">
                    Projected delay
                  </p>
                  <p
                    className={`mt-1 text-sm font-semibold ${
                      goal.projected_delay_months
                        ? "text-[#923f32]"
                        : "text-[#181713]"
                    }`}
                  >
                    {goal.projected_delay_months === null
                      ? "—"
                      : goal.projected_delay_months === 0
                        ? "On time"
                        : `${goal.projected_delay_months} mo late`}
                  </p>
                </div>
                <div>
                  <p className="uppercase tracking-[0.08em] text-[#8A8178]">
                    Projected completion
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#181713]">
                    {goal.projected_completion_date
                      ? formatDate(goal.projected_completion_date)
                      : "—"}
                  </p>
                </div>
                <div>
                  <p className="uppercase tracking-[0.08em] text-[#8A8178]">
                    Feasible target date
                  </p>
                  <p className="mt-1 text-sm font-semibold text-[#181713]">
                    {goal.suggested_feasible_target_date
                      ? formatDate(goal.suggested_feasible_target_date)
                      : "On track"}
                  </p>
                </div>
              </div>

              {goal.recommended_action.type !== "no_change_needed" && (
                <div className="mt-3 rounded-xl bg-[#F5F1EA] p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
                    Best action
                  </p>
                  <p className="mt-1 text-xs leading-5 text-[#3f4b46]">
                    {goal.recommended_action.message}
                  </p>

                  {goal.alternative_actions[0] && (
                    <>
                      <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
                        Alternative
                      </p>
                      <p className="mt-1 text-xs leading-5 text-[#706961]">
                        {goal.alternative_actions[0].message}
                      </p>
                    </>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function RecommendationSection({ analysis }: { analysis: GoalIntelligence }) {
  if (analysis.recommendation.type === "no_change_needed") {
    return null;
  }

  return (
    <div className="mt-5">
      <p className="text-xs font-semibold uppercase tracking-[0.1em] text-[#8A8178]">
        Suggested adjustment
      </p>
      <div className="mt-2 rounded-xl border border-[#B86D4B]/25 bg-white px-4 py-3">
        <p className="text-sm leading-6 text-[#3f4b46]">
          {analysis.recommendation.message}
        </p>
        <p className="mt-1.5 text-xs text-[#8A8178]">
          Resulting gap:{" "}
          {formatCents(analysis.recommendation.resulting_monthly_gap_cents)}
        </p>
      </div>

      {analysis.recommendation_alternatives.length > 0 && (
        <div className="mt-2 space-y-2">
          {analysis.recommendation_alternatives.map((alt, index) => (
            <div
              key={`${alt.type}-${alt.goal_id ?? index}`}
              className="rounded-xl bg-white px-4 py-3 text-sm leading-6 text-[#706961]"
            >
              {alt.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function GoalRow({
  goal,
  index,
  intelligenceGoal,
  busy,
  onFund,
  onEdit,
  onDelete,
}: {
  goal: SavingsGoal;
  index: number;
  intelligenceGoal?: GoalIntelligence["goals"][number];
  busy: boolean;
  onFund: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const percentage = Math.min(goal.progress_percent, 100);
  const reduceMotion = useReducedMotion();

  return (
    <motion.article
      layout
      initial={reduceMotion ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduceMotion ? 0 : 0.36, delay: reduceMotion ? 0 : index * 0.07 }}
      className="grid gap-4 px-5 py-5 xl:grid-cols-[minmax(190px,1.2fr)_150px_minmax(200px,1fr)_170px_150px] xl:items-center"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#EDE5DE] text-[#6E4B63]">
          <Flag className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{goal.name}</p>
          <p className="mt-1 text-xs capitalize text-[#8A8178]">
            {goal.status}
          </p>
        </div>
      </div>

      <div>
        <p className="text-base font-semibold tabular-nums text-[#181713]">
          {formatCents(goal.saved_cents)}
        </p>
        <p className="mt-1 text-xs text-[#8A8178]">
          of {formatCents(goal.target_cents)}
        </p>
      </div>

      <div>
        <p className="text-sm font-medium text-[#706961]">{goal.target_date ? `Target ${formatDate(goal.target_date)}` : "No target date"}</p>
        {intelligenceGoal && <p className="mt-1 text-sm font-semibold tabular-nums text-[#2F2930]">{formatCents(intelligenceGoal.required_monthly_cents)}/month</p>}
      </div>

      <div>
        <div className="h-2 overflow-hidden rounded-full bg-[#181713]/8">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${percentage}%` }}
            className="h-full rounded-full bg-[#6E4B63]"
          />
        </div>
        <div className="mt-2 flex justify-between gap-3">
          <span className="text-xs text-[#8A8178]">{goal.progress_percent}% complete</span>
          <span className="text-sm font-semibold tabular-nums text-[#181713]">{formatCents(goal.remaining_cents)} left</span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onFund}
          className="discero-button-secondary inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-sm font-semibold transition"
        >
          <WalletCards className="h-4 w-4" />
          Funds
        </button>
        <button
          type="button"
          onClick={onEdit}
          aria-label={`Edit ${goal.name}`}
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#181713]/10"
        >
          <Edit3 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={onDelete}
          disabled={busy}
          aria-label={`Delete ${goal.name}`}
          className="discero-button-destructive flex h-10 w-10 items-center justify-center rounded-xl border disabled:opacity-50"
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
  label,
}: {
  children: React.ReactNode;
  onClose: () => void;
  label: string;
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
        className="fixed inset-0 z-40 bg-[#181713]/35 backdrop-blur-sm"
      />
      <motion.aside
        role="dialog"
        aria-modal="true"
        aria-label={label}
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
            aria-label="Close drawer"
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#181713]/10 bg-white"
          >
            <X className="h-4 w-4" aria-hidden="true" />
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
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
        Goal details
      </p>
      <h2 className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
        {title}
      </h2>
      <p className="mt-3 text-sm leading-6 text-[#706961]">
        {description}
      </p>

      <div className="mt-8 space-y-5">
        <Field label="Goal name">
          <input
            value={form.name}
            onChange={(event) =>
              onChange({ ...form, name: event.target.value })
            }
            className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
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
            className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
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
              className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
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
            className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
          />
        </Field>

        <button
          type="button"
          onClick={onSubmit}
          disabled={busy}
          className="discero-button-primary inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl px-5 text-sm font-semibold"
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
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6E4B63]">
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

      <div className="mt-8 rounded-[24px] border border-[#181713]/10 bg-white p-5">
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
                    ? "discero-segment-selected"
                    : "text-[#706961]"
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
              className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
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
              className="h-12 w-full rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
            />
          </Field>

          <Field label="Note">
            <textarea
              value={form.note}
              onChange={(event) =>
                onFormChange({ ...form, note: event.target.value })
              }
              className="min-h-24 w-full resize-none rounded-xl border border-[#181713]/10 bg-[#FFFCF7] px-4 py-3 text-sm outline-none transition focus:border-[#6E4B63] focus:bg-white"
              placeholder="Optional note"
              maxLength={255}
            />
          </Field>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSave}
              disabled={busy}
              className="discero-button-primary inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-2xl px-4 text-sm font-semibold"
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
                className="discero-button-secondary rounded-2xl border px-4 text-sm font-semibold transition"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-[#6E4B63]" />
          <h3 className="text-lg font-semibold">Contribution history</h3>
        </div>

        {loading ? (
          <div className="mt-4">
            <PageLoading message="Loading contribution history..." />
          </div>
        ) : contributions.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-[#181713]/15 p-6 text-center text-sm text-[#706961]">
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
    <article className="rounded-2xl border border-[#181713]/10 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
              isWithdrawal
                ? "bg-[#f8ddd5] text-[#923f32]"
                : "bg-[#E8EEE7] text-[#6E4B63]"
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
                isWithdrawal ? "text-[#923f32]" : "text-[#6E4B63]"
              }`}
            >
              {isWithdrawal ? "−" : "+"}
              {formatCents(item.amount_cents)}
            </p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-[#8A8178]">
              <CalendarDays className="h-3.5 w-3.5" />
              {formatDate(item.contributed_on)}
            </p>
            {item.note && (
              <p className="mt-2 break-words text-sm text-[#706961]">
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
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#181713]/10 disabled:opacity-50"
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
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "positive-strong" | "neutral" | "warning";
}) {
  const surfaceClasses =
    tone === "positive-strong"
      ? "border border-[#58715A]/30 bg-[#58715A]/[0.12]"
      : tone === "positive"
        ? "border border-[#58715A]/25 bg-[#58715A]/[0.08]"
        : tone === "warning"
          ? "border border-[#B86D4B]/30 bg-[#B86D4B]/[0.08]"
          : "border border-[#181713]/10 bg-[#FFFCF7]";
  const labelClasses =
    tone === "positive" || tone === "positive-strong"
      ? "text-[#58715A]/70"
      : tone === "warning"
        ? "text-[#B86D4B]/80"
        : "text-[#777168]";
  return (
    <div className={`rounded-2xl p-4 ${surfaceClasses}`}>
      <p className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${labelClasses}`}>
        {label}
      </p>
      <p className={`mt-2 text-lg text-[#181713] ${tone === "positive-strong" ? "font-bold" : "font-semibold"}`}>{value}</p>
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
      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.12em] text-[#706961]">
        {label}
      </span>
      {children}
    </label>
  );
}
