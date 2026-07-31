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
  const [contributions, setContributions] = useState<
    Record<number, string>
  >({});
  const [withdrawals, setWithdrawals] = useState<
    Record<number, string>
  >({});
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

        const data = await api.getSavingsGoals(id);

        setUserId(id);
        setGoals(data);
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
        }),
        { target: 0, saved: 0 }
      ),
    [goals]
  );

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

    const amount = Number(contributions[goal.id]);
    const contributionCents = Math.round(amount * 100);

    if (!Number.isFinite(contributionCents) || contributionCents <= 0) {
      setError("Enter a valid contribution greater than $0.");
      setMessage("");
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        goal.id,
        {
          saved_cents: goal.saved_cents + contributionCents,
        }
      );

      setGoals((current) =>
        current.map((item) =>
          item.id === updated.id ? updated : item
        )
      );

      setContributions((current) => ({
        ...current,
        [goal.id]: "",
      }));

      setMessage(`${formatCents(contributionCents)} added.`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to add contribution"
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

    const targetCents = Math.round(
      Number(editTargetAmount) * 100
    );

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
      const updated = await api.updateSavingsGoal(
        userId,
        goal.id,
        {
          name: editName.trim(),
          target_cents: targetCents,
          target_date: editTargetDate || null,
        }
      );

      setGoals((current) =>
        current.map((item) =>
          item.id === updated.id ? updated : item
        )
      );

      cancelEditing();
      setMessage("Savings goal updated.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to update savings goal"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function withdrawFunds(goal: SavingsGoal) {
    if (!userId) return;

    const amount = Number(withdrawals[goal.id]);
    const withdrawalCents = Math.round(amount * 100);

    if (
      !Number.isFinite(withdrawalCents) ||
      withdrawalCents <= 0
    ) {
      setError("Enter a valid withdrawal greater than $0.");
      setMessage("");
      return;
    }

    if (withdrawalCents > goal.saved_cents) {
      setError(
        "Withdrawal cannot exceed the amount currently saved."
      );
      setMessage("");
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      const updated = await api.updateSavingsGoal(
        userId,
        goal.id,
        {
          saved_cents: goal.saved_cents - withdrawalCents,
        }
      );

      setGoals((current) =>
        current.map((item) =>
          item.id === updated.id ? updated : item
        )
      );

      setWithdrawals((current) => ({
        ...current,
        [goal.id]: "",
      }));

      setMessage(`${formatCents(withdrawalCents)} withdrawn.`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to withdraw funds"
      );
    } finally {
      setBusyId(null);
    }
  }

  async function deleteGoal(goal: SavingsGoal) {
    if (
      !userId ||
      !window.confirm(`Delete "${goal.name}"?`)
    ) {
      return;
    }

    setBusyId(goal.id);
    setError("");
    setMessage("");

    try {
      await api.deleteSavingsGoal(userId, goal.id);

      setGoals((current) =>
        current.filter((item) => item.id !== goal.id)
      );

      setMessage("Savings goal deleted.");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to delete savings goal"
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#050d18] text-white">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: `
            radial-gradient(circle at 10% 5%, rgba(16,185,129,0.18), transparent 28%),
            radial-gradient(circle at 88% 15%, rgba(14,165,233,0.12), transparent 25%),
            linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px)
          `,
          backgroundSize:
            "auto, auto, 42px 42px, 42px 42px",
        }}
      />

      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-[#050d18]/20 to-[#050d18]" />

      <AppSidebar />

      <div className="relative px-5 pb-10 pt-20 sm:px-8 lg:ml-72 lg:px-10 lg:pt-8">
        <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-6 rounded-3xl border border-white/10 bg-white/[0.05] p-6 shadow-2xl shadow-black/30 backdrop-blur-xl sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="inline-flex rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-300">
              Financial milestones
            </div>

            <h1 className="mt-4 text-3xl font-bold sm:text-4xl">
              Savings goals
            </h1>

            <p className="mt-2 text-sm text-slate-400">
              Create goals, add contributions, and track progress.
            </p>
          </div>

        </header>

        <section className="mt-6 grid gap-4 sm:grid-cols-3">
          <SummaryCard
            label="Total goal amount"
            value={formatCents(totals.target)}
          />
          <SummaryCard
            label="Total saved"
            value={formatCents(totals.saved)}
          />
          <SummaryCard
            label="Remaining"
            value={formatCents(
              Math.max(totals.target - totals.saved, 0)
            )}
          />
        </section>

        <section className="mt-6 rounded-3xl border border-white/10 bg-white/[0.06] p-6">
          <h2 className="text-lg font-semibold">
            Create a savings goal
          </h2>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Goal name"
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
            />

            <input
              type="number"
              min="0.01"
              step="0.01"
              value={targetAmount}
              onChange={(event) =>
                setTargetAmount(event.target.value)
              }
              placeholder="Target amount"
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
            />

            <input
              type="number"
              min="0"
              step="0.01"
              value={savedAmount}
              onChange={(event) =>
                setSavedAmount(event.target.value)
              }
              placeholder="Already saved"
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
            />

            <input
              type="date"
              value={targetDate}
              onChange={(event) =>
                setTargetDate(event.target.value)
              }
              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
            />
          </div>

          <button
            type="button"
            onClick={createGoal}
            disabled={creating}
            className="mt-4 rounded-xl bg-emerald-400 px-5 py-3 font-semibold text-slate-950 transition hover:bg-emerald-300 disabled:opacity-50"
          >
            {creating ? "Creating..." : "Create goal"}
          </button>
        </section>

        {message && (
          <div className="mt-5 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300">
            {message}
          </div>
        )}

        {error && (
          <div className="mt-5 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        {loading ? (
          <div className="mt-6 flex min-h-72 items-center justify-center">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
          </div>
        ) : (
          <section className="mt-6 grid gap-4 md:grid-cols-2">
            {goals.map((goal) => {
              const percentage = Math.min(
                goal.progress_percent,
                100
              );

              return (
                <article
                  key={goal.id}
                  className="rounded-3xl border border-white/10 bg-white/[0.06] p-6 shadow-xl shadow-black/20"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      {editingId === goal.id ? (
                        <div className="grid gap-3">
                          <input
                            value={editName}
                            onChange={(event) =>
                              setEditName(event.target.value)
                            }
                            className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
                          />

                          <div className="grid gap-3 sm:grid-cols-2">
                            <input
                              type="number"
                              min="0.01"
                              step="0.01"
                              value={editTargetAmount}
                              onChange={(event) =>
                                setEditTargetAmount(
                                  event.target.value
                                )
                              }
                              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
                            />

                            <input
                              type="date"
                              value={editTargetDate}
                              onChange={(event) =>
                                setEditTargetDate(
                                  event.target.value
                                )
                              }
                              className="rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
                            />
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() =>
                                saveGoalChanges(goal)
                              }
                              disabled={busyId === goal.id}
                              className="rounded-xl bg-emerald-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-emerald-300 disabled:opacity-50"
                            >
                              Save changes
                            </button>

                            <button
                              type="button"
                              onClick={cancelEditing}
                              disabled={busyId === goal.id}
                              className="rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300 transition hover:bg-white/10 disabled:opacity-50"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <h2 className="text-lg font-semibold">
                            {goal.name}
                          </h2>

                          <p className="mt-1 text-xs text-slate-500">
                            {goal.target_date
                              ? `Target ${new Date(
                                  `${goal.target_date}T00:00:00`
                                ).toLocaleDateString("en-US")}`
                              : "No target date"}
                          </p>

                          <button
                            type="button"
                            onClick={() => startEditing(goal)}
                            className="mt-3 text-xs font-medium text-cyan-300 transition hover:text-cyan-200"
                          >
                            Edit goal
                          </button>
                        </>
                      )}
                    </div>

                    <span
                      className={`rounded-full px-3 py-1 text-xs font-medium ${
                        goal.status === "completed"
                          ? "bg-emerald-400/10 text-emerald-300"
                          : goal.status === "overdue"
                          ? "bg-rose-400/10 text-rose-300"
                          : "bg-cyan-400/10 text-cyan-300"
                      }`}
                    >
                      {goal.status}
                    </span>
                  </div>

                  <div className="mt-5 flex justify-between text-sm">
                    <span className="text-slate-400">
                      {formatCents(goal.saved_cents)} saved
                    </span>
                    <span className="text-slate-400">
                      {formatCents(goal.target_cents)} target
                    </span>
                  </div>

                  <div className="mt-3 h-3 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full rounded-full bg-emerald-400 transition-all"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>

                  <div className="mt-3 flex justify-between text-xs">
                    <span className="text-emerald-300">
                      {goal.progress_percent}% complete
                    </span>
                    <span className="text-slate-500">
                      {formatCents(goal.remaining_cents)} remaining
                    </span>
                  </div>

                  <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_auto]">
                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={contributions[goal.id] ?? ""}
                      onChange={(event) =>
                        setContributions((current) => ({
                          ...current,
                          [goal.id]: event.target.value,
                        }))
                      }
                      placeholder="Add contribution"
                      className="min-w-0 rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-emerald-400"
                    />

                    <button
                      type="button"
                      onClick={() => addContribution(goal)}
                      disabled={busyId === goal.id}
                      className="rounded-xl bg-emerald-400 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-emerald-300 disabled:opacity-50"
                    >
                      Add funds
                    </button>

                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      max={goal.saved_cents / 100}
                      value={withdrawals[goal.id] ?? ""}
                      onChange={(event) =>
                        setWithdrawals((current) => ({
                          ...current,
                          [goal.id]: event.target.value,
                        }))
                      }
                      placeholder="Withdraw amount"
                      disabled={goal.saved_cents === 0}
                      className="min-w-0 rounded-xl border border-white/10 bg-slate-950/70 px-4 py-3 text-sm outline-none focus:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
                    />

                    <button
                      type="button"
                      onClick={() => withdrawFunds(goal)}
                      disabled={
                        busyId === goal.id ||
                        goal.saved_cents === 0
                      }
                      className="rounded-xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm font-medium text-amber-300 transition hover:bg-amber-400/20 disabled:opacity-50"
                    >
                      Withdraw
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => deleteGoal(goal)}
                    disabled={busyId === goal.id}
                    className="mt-3 w-full rounded-xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm font-medium text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50"
                  >
                    Delete goal
                  </button>
                </article>
              );
            })}

            {goals.length === 0 && (
              <div className="col-span-full rounded-3xl border border-dashed border-white/10 px-6 py-16 text-center text-sm text-slate-500">
                No savings goals yet.
              </div>
            )}
          </section>
        )}
        </div>
      </div>
    </main>
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
    <div className="rounded-3xl border border-white/10 bg-white/[0.06] p-5">
      <p className="text-sm text-slate-400">{label}</p>
      <p className="mt-3 text-xl font-bold text-emerald-300">
        {value}
      </p>
    </div>
  );
}
