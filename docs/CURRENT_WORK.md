# Current work

Updated: 2026-08-05.

## Integrated scope

Since the previous audit, FinSight has added:

- Persisted recurring items (`RecurringItem`) with a dedicated CRUD API and UI, alongside the existing algorithmic recurring detection
- Savings-goal contribution/withdrawal history (`GoalContribution`) replacing direct balance edits
- Safe-to-Spend calculation combining liquid balances, upcoming recurring obligations, essential spending, and a safety reserve
- Major Purchase Simulator and Scenario Comparison built on Safe-to-Spend
- Financial Stress Testing built on Safe-to-Spend, modeling an emergency expense, temporary income loss, delayed paycheck, or recurring bill increase
- A `/decisions` frontend route surfacing all four decision-intelligence features
- Two additional Alembic revisions (`8adb0528864c` recurring items, `146ccae6e522` goal contributions); Financial Stress Testing required no migration

Secure password recovery, email verification, hardened Plaid synchronization, and fully month-specific budgets — described below — were integrated earlier and remain unchanged.

## Recurring items

- `RecurringItem` rows are unique per user/normalized-merchant and carry frequency, next/last payment, `suggested`/`active` status, confidence score, and price-change percent/warning.
- `POST /users/{user_id}/recurring-items` rejects an empty merchant/normalized-merchant and returns 409 on a duplicate normalized merchant for the same user.
- `PATCH .../recurring-items/{item_id}` applies partial updates to category, amount, frequency, next payment, and status.
- Only `active` items with `next_payment` inside the requested horizon count as Safe-to-Spend obligations.
- The `/recurring` page shows both algorithmically detected payments (`summary/recurring`) and the persisted item list.

## Savings-goal contribution history

- `SavingsGoal.saved_cents` is derived: it is the running signed sum of that goal's `GoalContribution` rows, not a directly editable field.
- `POST/PATCH/DELETE .../goals/{goal_id}/contributions/...` each recompute the goal's projected balance and reject the change with a 422 if it would go negative; update excludes the contribution being edited when recomputing.
- Creating a goal with a nonzero opening `saved_cents` writes a synthetic "Opening balance" deposit contribution.
- The `/goals` page exposes contribution/withdrawal entry and a per-goal history list.

## Safe-to-Spend, Major Purchase Simulator, Scenario Comparison

- Safe-to-Spend liquid balance comes from active Plaid accounts of type `depository`/`cash`, preferring available balance and falling back to current balance with a warning; obligations come from active `RecurringItem` rows due within the horizon (1–90 days, default 30).
- Status is `safe`, `limited` (within 10% of liquid balance or under $100, whichever is greater), or `negative`; confidence blends obligation confidence (or a 70.0 default with no obligations) with whether a liquid balance exists.
- Major Purchase Simulator runs Safe-to-Spend as of the purchase inputs and classifies the purchase `affordable`, `caution` (over a 75%-of-safe-to-spend ceiling), or `not_affordable` (exceeds safe-to-spend); it rejects a purchase date before the calculation date or beyond the horizon with a 422.
- Scenario Comparison runs two simulations and ranks them by affordability status, then shortfall, then remaining safe-to-spend, then impact percent, then cost, returning the recommended option (or `tie`) with a generated explanation.
- The `/decisions` page covers single-purchase, comparison, and stress-test modes.

## Financial Stress Testing

- `POST /users/{user_id}/financial-stress-test` runs a Safe-to-Spend calculation as of the stress event and subtracts a user-entered `stress_amount_cents` impact for one of four scenario types: `emergency_expense`, `temporary_income_loss`, `delayed_paycheck`, `recurring_bill_increase`.
- `temporary_income_loss` and `delayed_paycheck` require `duration_days` (1–365); the endpoint returns 422 if it is missing for those two scenarios and ignores it for the other two.
- Risk level is deterministic and integer-cents based: `critical` when safe-to-spend before the event is zero/negative or the event produces a shortfall; `strained` when the impact exceeds half of safe-to-spend before the event (rounded) without a shortfall; otherwise `resilient`.
- Confidence score starts from the underlying Safe-to-Spend confidence and, only for the two duration-required scenarios, subtracts 0.3 points per duration day up to a 30-point cap, floored at 0.
- Estimated recovery days equals the entered duration for the two duration-required scenarios regardless of risk level; for the other two scenarios it is 0 when there is no shortfall and not determinable (`null`) when there is.
- The event date must fall on or after the calculation date and within the Safe-to-Spend horizon's `through_date`, or the endpoint returns 422; `scenario_name` is trimmed and rejected if blank.
- Explanation and recommendation text is generated from these deterministic values only — it does not forecast or guarantee an actual recovery timeline.
- The `/decisions` page's third mode ("Financial stress test") exposes all four scenarios, conditionally shows the duration field, and reuses the same safety-reserve/essential-spending/horizon inputs as the other two modes.

## Authentication recovery

- Reset and verification tokens use 256-bit URL-safe values.
- Only SHA-256 token hashes are stored.
- Password reset atomically consumes the token, updates the Argon2 password hash, increments `token_version`, and invalidates all older JWTs.
- Forgot-password and resend-verification responses do not reveal account existence or verification state.
- Registration and email changes issue verification links.
- Unverified users may continue to log in.
- Production console delivery is prohibited; production email can use configured SMTP or Resend HTTPS delivery.
- Resend uses the official Python SDK, requires `RESEND_API_KEY`, and sends from `EMAIL_FROM`.
- Provider-failure logs omit exception details, reset/verification links and tokens, API keys, and SMTP passwords.

## Monthly budgets

- Budgets are uniquely stored by user, category, and canonical `YYYY-MM` month.
- List, upsert, delete, copy, and progress operations are selected-month scoped.
- Copy preserves existing target categories by default and supports explicit overwrite through the API.
- Progress uses negative transactions from the selected month and reports spent, signed remaining, percent used, overage, and overspent status.
- No budget migration was required because the original schema already supports monthly records.

## Plaid synchronization

- Manual synchronization tracks `idle`, `syncing`, `succeeded`, `failed`, and reconnect-required lifecycle states.
- Last attempted and last successful synchronization timestamps are persisted separately.
- One conditional database update atomically acquires synchronization ownership.
- Active claims remain protected with 409 responses.
- Claims at least 15 minutes old may be atomically reclaimed.
- Transaction mutations and final cursor updates commit atomically per institution.
- Failed synchronization preserves the previous valid cursor and successful-sync timestamp.
- Repeated provider responses remain idempotent.
- Removed provider transactions are handled safely.
- Disconnect remains provider-first and owner-scoped.
- The Accounts page exposes Sync Now, status, last-sync information, reconnect notices, and safe disconnect confirmation.

## Potential Duplicates

- The transaction search endpoint accepts a `duplicates_only` filter that correlates transactions by same user/date/amount and normalized merchant-or-description identity, returning every group member with totals.
- Seven focused backend tests cover the omitted/false no-op case, grouping/totals, blank-merchant fallback, self-match exclusion, merchant-over-description preference, user isolation, and combination with existing filters.
- The Transactions page toggle reuses existing selection, bulk delete, confirmation, and Undo behavior; a frontend test confirms bulk actions stay compatible with the toggle enabled.
- This is implemented and verified, not in-progress; see the corrected [ROADMAP.md](ROADMAP.md).

## Validation baseline

Current verified result:

- Backend: 275 tests (`pytest -q`)
- Frontend: 32 tests across 5 files (`npm run test:run`)
  - 10 Transactions
  - 5 authentication recovery
  - 2 Budgets
  - 6 Accounts/Plaid
  - 9 Decisions (3 Scenario Comparison, 6 Financial Stress Testing)
- Frontend lint and production build must pass.
- Alembic must report one head:
  `146ccae6e522`

## Known limitations

- Recovery and resend endpoints do not yet have shared datastore-backed rate limiting.
- Production SMTP/Resend delivery requires environment-specific configuration, a verified sender, and smoke testing.
- Email verification is advisory rather than an authorization gate.
- Pending negative transactions count toward budget spending.
- Budget category matching is exact and case-sensitive.
- Arbitrary budget source-month copy and overwrite are API-only.
- Plaid synchronization remains synchronous and covers all connected institutions for the user.
- A crashed Plaid request can delay another sync for up to 15 minutes.
- Safe-to-Spend obligations come only from `RecurringItem` rows; budgets and one-off manual obligations are not yet included even though the `SafeToSpendObligationOut.source` schema already allows `budget`/`manual` values.
- Recurring items are created manually or promoted from a detected suggestion; there is no automatic promotion job.
- There is no live Plaid, PostgreSQL concurrency, browser E2E, or production smoke suite.
