"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppSidebar from "../components/AppSidebar";
import {
  api,
  formatCents,
  SavingsGoal,
  session,
} from "../lib/api";

export default function GoalsPage() {
  const router = useRouter();

  const [userId, setUserId] = useState<number | null>(null);
  const [goals, setGoals] = useState<SavingsGoal[]>([]);
  const [name, setName] = useState("");
  const [targetAmount, setTargetAmount] = useState("");
  const [savedAmount, setSavedAmount] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [contributions, setContributions] = useState<Record<number, string>>({});
  const [withdrawals, setWithdrawals] = useState<Record<number, string>>({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editTargetAmount, setEditTargetAmount] = useState("");
  const [editTargetDate, setEditTargetDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
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

  async function createGoal() {
    const targetCents = Math.round(Number(targetAmount) * 100);
    const savedCents = savedAmount
      ? Math.round(Number(savedAmount) * 100)
      : 0;

    if (
      !userId ||
      !name.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0 ||
      !Number.isFinite(savedCents) ||
      savedCents < 0
    ) {
      setError("Enter a valid goal name and target amount.");
      setMessage("");
      return;
    }

    setCreating(true);
    setError("");
    setMessage("");

    try {
      const created = await api.createSavingsGoal(userId, {
        name: name.trim(),
        target_cents: targetCents,
        saved_cents: savedCents,
        target_date: targetDate || null,
      });

      setGoals((current) => [created, ...current]);
      setName("");
      setTargetAmount("");
      setSavedAmount("");
      setTargetDate("");
      setMessage("Savings goal created successfully.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to create savings goal"
      );
    } finally {
      setCreating(false);
    }
  }

  async function addContribution(goal: SavingsGoal) {
    if (!userId) return;

    const contributionCents = Math.round(
      Number(contributions[goal.id]) * 100
    );

    if (!Number.isFinite(contributionCents) || contributionCents <= 0) {
      setError("Enter a valid contribution greater than $0.");
      setMessage("");
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(userId, goal.id, {
        saved_cents: goal.saved_cents + contributionCents,
      });

      setGoals((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setContributions((current) => ({ ...current, [goal.id]: "" }));
      setMessage(`${formatCents(contributionCents)} added.`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to add contribution"
      );
    } finally {
      setBusyId(null);
    }
  }

  function startEditing(goal: SavingsGoal) {
    setEditingId(goal.id);
    setEditName(goal.name);
    setEditTargetAmount(String(goal.target_cents / 100));
    setEditTargetDate(goal.target_date || "");
    setError("");
    setMessage("");
  }

  function cancelEditing() {
    setEditingId(null);
    setEditName("");
    setEditTargetAmount("");
    setEditTargetDate("");
  }

  async function saveGoalChanges(goal: SavingsGoal) {
    if (!userId) return;

    const targetCents = Math.round(Number(editTargetAmount) * 100);

    if (
      !editName.trim() ||
      !Number.isFinite(targetCents) ||
      targetCents <= 0
    ) {
      setError("Enter a valid goal name and target amount.");
      setMessage("");
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(userId, goal.id, {
        name: editName.trim(),
        target_cents: targetCents,
        target_date: editTargetDate || null,
      });

      setGoals((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      cancelEditing();
      setMessage("Savings goal updated.");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to update savings goal"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function withdrawFunds(goal: SavingsGoal) {
    if (!userId) return;

    const withdrawalCents = Math.round(
      Number(withdrawals[goal.id]) * 100
    );

    if (!Number.isFinite(withdrawalCents) || withdrawalCents <= 0) {
      setError("Enter a valid withdrawal greater than $0.");
      setMessage("");
      return;
    }

    if (withdrawalCents > goal.saved_cents) {
      setError("Withdrawal cannot exceed the amount currently saved.");
      setMessage("");
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(userId, goal.id, {
        saved_cents: goal.saved_cents - withdrawalCents,
      });

      setGoals((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setWithdrawals((current) => ({ ...current, [goal.id]: "" }));
      setMessage(`${formatCents(withdrawalCents)} withdrawn.`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Unable to withdraw funds"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function deleteGoal(goal: SavingsGoal) {
    if (!userId || !window.confirm(`Delete "${goal.name}"?`)) return;

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      await api.deleteSavingsGoal(userId, goal.id);
      setGoals((current) => current.filter((item) => item.id !== goal.id));
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

      <div className="px-5 pb-14 pt-20 sm:px-8 lg:ml-64 lg:px-10 lg:pt-10">
        <div className="mx-auto max-w-7xl">
          <header>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#167c5a]">
              Financial milestones
            </p>

            <h1 className="mt-3 max-w-3xl text-4xl font-semibold leading-tight tracking-[-0.05em] sm:text-5xl">
              Turn plans into
              <span className="block text-[#167c5a]">
                visible progress.
              </span>
            </h1>

            <p className="mt-4 max-w-2xl text-sm leading-6 text-[#66746e] sm:text-base">
              Create goals, contribute over time, and see exactly how close
              you are to each milestone.
            </p>
          </header>

          <section className="mt-8 grid gap-4 md:grid-cols-3">
            <MetricCard
              label="Total saved"
              value={formatCents(totals.saved)}
              tone="green"
            />
            <MetricCard
              label="Total target"
              value={formatCents(totals.target)}
              tone="yellow"
            />
            <MetricCard
              label="Goals completed"
              value={`${totals.completed} of ${goals.length}`}
              tone="blue"
            />
          </section>

          <section className="mt-6 grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
            <div className="rounded-[30px] bg-[#14241e] p-6 text-white sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#76dfbd]">
                Overall progress
              </p>

              <div className="mt-5 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <p className="text-5xl font-semibold tracking-[-0.06em]">
                    {overallProgress}%
                  </p>
                  <p className="mt-2 text-sm text-white/65">
                    {formatCents(
                      Math.max(totals.target - totals.saved, 0)
                    )}{" "}
                    remaining across all goals
                  </p>
                </div>

                <div className="w-full max-w-sm">
                  <div className="h-3 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-[#76dfbd]"
                      style={{ width: `${overallProgress}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="rounded-[30px] border border-[#14241e]/10 bg-white p-6 sm:p-8">
              <h2 className="text-xl font-semibold">Create a goal</h2>
              <p className="mt-1 text-sm text-[#728078]">
                Add a new savings target.
              </p>

              <div className="mt-5 space-y-3">
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Goal name"
                  className="w-full rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
                />

                <div className="grid gap-3 sm:grid-cols-2">
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={targetAmount}
                    onChange={(event) => setTargetAmount(event.target.value)}
                    placeholder="Target amount"
                    className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
                  />

                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={savedAmount}
                    onChange={(event) => setSavedAmount(event.target.value)}
                    placeholder="Already saved"
                    className="rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
                  />
                </div>

                <input
                  type="date"
                  value={targetDate}
                  onChange={(event) => setTargetDate(event.target.value)}
                  className="w-full rounded-2xl border border-[#14241e]/10 bg-[#f7f4ed] px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
                />

                <button
                  type="button"
                  onClick={createGoal}
                  disabled={creating}
                  className="w-full rounded-full bg-[#14241e] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#20352d] disabled:opacity-50"
                >
                  {creating ? "Creating..." : "Create goal"}
                </button>
              </div>
            </div>
          </section>

          {(message || error) && (
            <div className="mt-6 space-y-3">
              {message && (
                <div className="rounded-2xl border border-[#167c5a]/20 bg-[#dff6c7] px-4 py-3 text-sm text-[#167c5a]">
                  {message}
                </div>
              )}

              {error && (
                <div className="rounded-2xl border border-[#c56755]/20 bg-[#f8ddd5] px-4 py-3 text-sm text-[#923f32]">
                  {error}
                </div>
              )}
            </div>
          )}

          {loading ? (
            <div className="mt-8 flex min-h-72 items-center justify-center rounded-[30px] border border-[#14241e]/10 bg-white">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#167c5a] border-t-transparent" />
            </div>
          ) : goals.length === 0 ? (
            <div className="mt-8 rounded-[30px] border border-dashed border-[#14241e]/15 bg-white px-6 py-16 text-center">
              <p className="text-lg font-semibold">No savings goals yet</p>
              <p className="mt-2 text-sm text-[#728078]">
                Create your first goal to begin tracking progress.
              </p>
            </div>
          ) : (
            <section className="mt-8 grid gap-5 md:grid-cols-2">
              {goals.map((goal, index) => (
                <GoalCard
                  key={goal.id}
                  goal={goal}
                  index={index}
                  busy={busyId === goal.id}
                  editing={editingId === goal.id}
                  contribution={contributions[goal.id] ?? ""}
                  withdrawal={withdrawals[goal.id] ?? ""}
                  editName={editName}
                  editTargetAmount={editTargetAmount}
                  editTargetDate={editTargetDate}
                  onEdit={() => startEditing(goal)}
                  onCancel={cancelEditing}
                  onSave={() => saveGoalChanges(goal)}
                  onDelete={() => deleteGoal(goal)}
                  onContributionChange={(value) =>
                    setContributions((current) => ({
                      ...current,
                      [goal.id]: value,
                    }))
                  }
                  onWithdrawalChange={(value) =>
                    setWithdrawals((current) => ({
                      ...current,
                      [goal.id]: value,
                    }))
                  }
                  onAdd={() => addContribution(goal)}
                  onWithdraw={() => withdrawFunds(goal)}
                  onEditName={setEditName}
                  onEditTargetAmount={setEditTargetAmount}
                  onEditTargetDate={setEditTargetDate}
                />
              ))}
            </section>
          )}
        </div>
      </div>
    </main>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "yellow" | "blue";
}) {
  const styles = {
    green: "bg-[#dff6c7]",
    yellow: "bg-[#f7e8b5]",
    blue: "bg-[#dceeea]",
  };

  return (
    <article className={`rounded-[26px] p-5 ${styles[tone]}`}>
      <p className="text-sm text-[#52635b]">{label}</p>
      <p className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
        {value}
      </p>
    </article>
  );
}

function GoalCard({
  goal,
  index,
  busy,
  editing,
  contribution,
  withdrawal,
  editName,
  editTargetAmount,
  editTargetDate,
  onEdit,
  onCancel,
  onSave,
  onDelete,
  onContributionChange,
  onWithdrawalChange,
  onAdd,
  onWithdraw,
  onEditName,
  onEditTargetAmount,
  onEditTargetDate,
}: {
  goal: SavingsGoal;
  index: number;
  busy: boolean;
  editing: boolean;
  contribution: string;
  withdrawal: string;
  editName: string;
  editTargetAmount: string;
  editTargetDate: string;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onDelete: () => void;
  onContributionChange: (value: string) => void;
  onWithdrawalChange: (value: string) => void;
  onAdd: () => void;
  onWithdraw: () => void;
  onEditName: (value: string) => void;
  onEditTargetAmount: (value: string) => void;
  onEditTargetDate: (value: string) => void;
}) {
  const tones = [
    "bg-white",
    "bg-[#eef6e9]",
    "bg-[#fbf0d1]",
    "bg-[#f5e4de]",
  ];

  const percentage = Math.min(goal.progress_percent, 100);

  return (
    <article
      className={`rounded-[30px] border border-[#14241e]/10 p-6 shadow-sm shadow-[#14241e]/5 ${
        tones[index % tones.length]
      }`}
    >
      {editing ? (
        <div className="space-y-3">
          <input
            value={editName}
            onChange={(event) => onEditName(event.target.value)}
            className="w-full rounded-2xl border border-[#14241e]/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={editTargetAmount}
              onChange={(event) =>
                onEditTargetAmount(event.target.value)
              }
              className="rounded-2xl border border-[#14241e]/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
            />

            <input
              type="date"
              value={editTargetDate}
              onChange={(event) => onEditTargetDate(event.target.value)}
              className="rounded-2xl border border-[#14241e]/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
            />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={onSave}
              disabled={busy}
              className="rounded-full bg-[#14241e] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              Save changes
            </button>

            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="rounded-full border border-[#14241e]/10 bg-white/70 px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.15em] text-[#7b8781]">
                {goal.target_date
                  ? `Target ${new Date(
                      `${goal.target_date}T00:00:00`
                    ).toLocaleDateString("en-US")}`
                  : "No target date"}
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em]">
                {goal.name}
              </h2>
            </div>

            <span
              className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                goal.status === "completed"
                  ? "bg-[#dff6c7] text-[#167c5a]"
                  : goal.status === "overdue"
                  ? "bg-[#f8ddd5] text-[#923f32]"
                  : "bg-white/60 text-[#52635b]"
              }`}
            >
              {goal.status}
            </span>
          </div>

          <button
            type="button"
            onClick={onEdit}
            className="mt-3 text-sm font-semibold text-[#167c5a]"
          >
            Edit goal
          </button>
        </>
      )}

      <div className="mt-6">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-sm text-[#66746e]">Saved</p>
            <p className="mt-1 text-3xl font-semibold tracking-[-0.04em]">
              {formatCents(goal.saved_cents)}
            </p>
          </div>

          <div className="text-right">
            <p className="text-sm text-[#66746e]">Target</p>
            <p className="mt-1 font-semibold">
              {formatCents(goal.target_cents)}
            </p>
          </div>
        </div>

        <div className="mt-4 h-3 overflow-hidden rounded-full bg-[#14241e]/10">
          <div
            className="h-full rounded-full bg-[#167c5a]"
            style={{ width: `${percentage}%` }}
          />
        </div>

        <div className="mt-2 flex justify-between text-xs text-[#7b8781]">
          <span>{goal.progress_percent}% complete</span>
          <span>{formatCents(goal.remaining_cents)} remaining</span>
        </div>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-[1fr_auto]">
        <input
          type="number"
          min="0.01"
          step="0.01"
          value={contribution}
          onChange={(event) =>
            onContributionChange(event.target.value)
          }
          placeholder="Add contribution"
          className="rounded-2xl border border-[#14241e]/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[#167c5a]"
        />

        <button
          type="button"
          onClick={onAdd}
          disabled={busy}
          className="rounded-full bg-[#14241e] px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          Add funds
        </button>

        <input
          type="number"
          min="0.01"
          step="0.01"
          max={goal.saved_cents / 100}
          value={withdrawal}
          onChange={(event) =>
            onWithdrawalChange(event.target.value)
          }
          placeholder="Withdraw amount"
          disabled={goal.saved_cents === 0}
          className="rounded-2xl border border-[#14241e]/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[#a87b20] disabled:opacity-50"
        />

        <button
          type="button"
          onClick={onWithdraw}
          disabled={busy || goal.saved_cents === 0}
          className="rounded-full border border-[#a87b20]/20 bg-[#f7e8b5] px-5 py-3 text-sm font-semibold text-[#8b6518] disabled:opacity-50"
        >
          Withdraw
        </button>
      </div>

      <button
        type="button"
        onClick={onDelete}
        disabled={busy}
        className="mt-3 w-full rounded-full border border-[#c56755]/20 bg-[#f8ddd5] px-5 py-3 text-sm font-semibold text-[#923f32] disabled:opacity-50"
      >
        Delete goal
      </button>
    </article>
  );
}
