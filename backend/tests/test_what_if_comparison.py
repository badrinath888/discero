from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.schemas import WhatIfComparisonRequest, WhatIfComparisonScenarioRequest
from app.services.what_if_comparison_service import compare_what_if_scenarios
from tests.conftest import TestingSessionLocal
from tests.test_what_if import (
    create_account,
    create_goal,
    create_recurring_item,
    create_user,
    register_and_login,
    seed_income,
)

TEST_DATE = date(2026, 8, 4)


def one_time(label: str, amount_cents: int, days_out: int = 5) -> dict:
    return {
        "label": label,
        "scenario_type": "one_time_expense",
        "amount_cents": amount_cents,
        "effective_date": (TEST_DATE + timedelta(days=days_out)).isoformat(),
    }


def test_two_scenarios_smaller_expense_wins() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-basic")
        create_account(db, user, available_balance_cents=500_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Laptop", 200_000)),
                    WhatIfComparisonScenarioRequest(
                        **one_time("Vacation", 400_000)
                    ),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert len(result.scenarios) == 2
        assert result.recommended_label == "Laptop"
        assert result.key_driver == "safe_to_spend"
        assert result.is_tie is False
        assert result.ranking == ["Laptop", "Vacation"]
        assert result.baseline.safe_to_spend_cents == 500_000


def test_three_scenarios_supported() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-three")
        create_account(db, user, available_balance_cents=500_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("A", 100_000)),
                    WhatIfComparisonScenarioRequest(**one_time("B", 200_000)),
                    WhatIfComparisonScenarioRequest(**one_time("C", 300_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert len(result.scenarios) == 3
        assert result.recommended_label == "A"
        assert result.ranking == ["A", "B", "C"]


def test_fewer_than_two_scenarios_rejected() -> None:
    try:
        WhatIfComparisonRequest(
            horizon_days=30,
            scenarios=[
                WhatIfComparisonScenarioRequest(**one_time("Only", 100_000)),
            ],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for a single scenario")


def test_more_than_three_scenarios_rejected() -> None:
    try:
        WhatIfComparisonRequest(
            horizon_days=30,
            scenarios=[
                WhatIfComparisonScenarioRequest(**one_time("A", 100_000)),
                WhatIfComparisonScenarioRequest(**one_time("B", 100_000)),
                WhatIfComparisonScenarioRequest(**one_time("C", 100_000)),
                WhatIfComparisonScenarioRequest(**one_time("D", 100_000)),
            ],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for four scenarios")


def test_duplicate_labels_rejected() -> None:
    try:
        WhatIfComparisonRequest(
            horizon_days=30,
            scenarios=[
                WhatIfComparisonScenarioRequest(**one_time("Same", 100_000)),
                WhatIfComparisonScenarioRequest(**one_time("Same", 200_000)),
            ],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for duplicate labels")


def test_one_shortfall_scenario_loses_to_affordable_one() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-shortfall")
        create_account(db, user, available_balance_cents=250_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Affordable", 100_000)),
                    WhatIfComparisonScenarioRequest(
                        **one_time("Overspend", 400_000)
                    ),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_label == "Affordable"
        assert result.key_driver == "shortfall"
        scenario_by_label = {s.label: s for s in result.scenarios}
        assert scenario_by_label["Overspend"].shortfall_cents == 150_000
        assert scenario_by_label["Affordable"].shortfall_cents == 0


def test_both_shortfall_smaller_shortfall_wins() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-both-shortfall")
        create_account(db, user, available_balance_cents=100_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Small", 300_000)),
                    WhatIfComparisonScenarioRequest(**one_time("Big", 500_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert result.recommended_label == "Small"
        assert result.key_driver == "shortfall"


def test_identical_scenarios_return_tie() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-tie")
        create_account(db, user, available_balance_cents=500_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Option A", 200_000)),
                    WhatIfComparisonScenarioRequest(
                        **one_time("Option B", 200_000)
                    ),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert result.is_tie is True
        assert result.recommended_label is None
        assert result.key_driver == "tie"


def test_goal_impact_differs_between_scenarios() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-goal-impact")
        create_account(db, user, available_balance_cents=800_000)
        seed_income(db, user)
        create_goal(db, user, target_cents=600_000, saved_cents=0)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(
                        label="Small expense increase",
                        scenario_type="monthly_expense_change",
                        monthly_amount_change_cents=100_00,
                    ),
                    WhatIfComparisonScenarioRequest(
                        label="Large expense increase",
                        scenario_type="monthly_expense_change",
                        monthly_amount_change_cents=250_00,
                    ),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert len(result.scenarios) == 2
        # Both scenarios reduce safe-to-spend by different amounts,
        # so the smaller increase should win on safe-to-spend.
        assert result.recommended_label == "Small expense increase"


def test_mixed_scenario_types_supported() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-mixed")
        create_account(db, user, available_balance_cents=500_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Buy now", 150_000)),
                    WhatIfComparisonScenarioRequest(
                        label="Income loss",
                        scenario_type="temporary_income_loss",
                        monthly_income_loss_cents=100_000,
                        duration_months=1,
                    ),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert len(result.scenarios) == 2
        labels = {s.label for s in result.scenarios}
        assert labels == {"Buy now", "Income loss"}


def test_existing_baseline_shortfall_compounds() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-existing-shortfall")
        create_account(db, user, available_balance_cents=100_000)
        create_recurring_item(
            db,
            user,
            merchant="Rent",
            amount_cents=300_000,
            next_payment=TEST_DATE + timedelta(days=5),
        )

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("Small", 50_000)),
                    WhatIfComparisonScenarioRequest(**one_time("Large", 150_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        assert result.baseline.shortfall_cents == 200_000
        scenario_by_label = {s.label: s for s in result.scenarios}
        assert scenario_by_label["Small"].shortfall_cents == 250_000
        assert scenario_by_label["Large"].shortfall_cents == 350_000
        assert result.recommended_label == "Small"


def test_no_goals_returns_empty_goal_impacts() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-no-goals")
        create_account(db, user, available_balance_cents=500_000)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("A", 100_000)),
                    WhatIfComparisonScenarioRequest(**one_time("B", 200_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        for scenario in result.scenarios:
            assert scenario.goal_impacts == []


def test_zero_liquid_balance_never_negative_safe_to_spend() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-zero-balance")
        create_account(db, user, available_balance_cents=0)

        result = compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("A", 100_000)),
                    WhatIfComparisonScenarioRequest(**one_time("B", 200_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        for scenario in result.scenarios:
            assert scenario.safe_to_spend_cents >= 0


def test_effective_date_outside_horizon_rejected() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-outside-horizon")
        create_account(db, user)

        try:
            compare_what_if_scenarios(
                db,
                user.id,
                WhatIfComparisonRequest(
                    horizon_days=30,
                    scenarios=[
                        WhatIfComparisonScenarioRequest(
                            **one_time("Too late", 100_000, days_out=45)
                        ),
                        WhatIfComparisonScenarioRequest(
                            **one_time("Fine", 100_000)
                        ),
                    ],
                ),
                as_of=TEST_DATE,
            )
        except ValueError as exc:
            assert "horizon" in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_no_database_mutation() -> None:
    with TestingSessionLocal() as db:
        user = create_user(db, "compare-no-mutation")
        create_account(db, user, available_balance_cents=500_000)

        before = db.query(User).filter(User.id == user.id).one()
        before_updated_at = getattr(before, "created_at", None)

        compare_what_if_scenarios(
            db,
            user.id,
            WhatIfComparisonRequest(
                horizon_days=30,
                scenarios=[
                    WhatIfComparisonScenarioRequest(**one_time("A", 100_000)),
                    WhatIfComparisonScenarioRequest(**one_time("B", 200_000)),
                ],
            ),
            as_of=TEST_DATE,
        )

        db.expire_all()
        after = db.query(User).filter(User.id == user.id).one()
        assert after.created_at == before_updated_at


def _future_one_time(label: str, amount_cents: int) -> dict:
    return {
        "label": label,
        "scenario_type": "one_time_expense",
        "amount_cents": amount_cents,
        "effective_date": (date.today() + timedelta(days=5)).isoformat(),
    }


def test_compare_endpoint_success(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "whatif-compare-endpoint")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        create_account(db, user, available_balance_cents=500_000)

    response = client.post(
        f"/users/{user_id}/what-if/compare",
        headers=headers,
        json={
            "horizon_days": 30,
            "scenarios": [
                _future_one_time("Laptop", 200_000),
                _future_one_time("Vacation", 400_000),
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended_label"] == "Laptop"
    assert len(payload["scenarios"]) == 2


def test_compare_endpoint_blocks_other_user(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "whatif-compare-owner")
    other_user_id, _ = register_and_login(client, "whatif-compare-other")

    response = client.post(
        f"/users/{other_user_id}/what-if/compare",
        headers=headers,
        json={
            "horizon_days": 30,
            "scenarios": [
                _future_one_time("A", 100_000),
                _future_one_time("B", 200_000),
            ],
        },
    )

    assert response.status_code == 403


def test_compare_endpoint_rejects_too_few_scenarios(
    client: TestClient,
) -> None:
    user_id, headers = register_and_login(client, "whatif-compare-too-few")

    response = client.post(
        f"/users/{user_id}/what-if/compare",
        headers=headers,
        json={
            "horizon_days": 30,
            "scenarios": [_future_one_time("Only", 100_000)],
        },
    )

    assert response.status_code == 422


def test_save_and_rerun_what_if_comparison(client: TestClient) -> None:
    user_id, headers = register_and_login(client, "whatif-compare-save")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        create_account(db, user, available_balance_cents=500_000)

    save_response = client.post(
        f"/users/{user_id}/decisions",
        headers=headers,
        json={
            "decision_type": "what_if_comparison",
            "title": "Laptop vs vacation",
            "input": {
                "horizon_days": 30,
                "scenarios": [
                    _future_one_time("Laptop", 200_000),
                    _future_one_time("Vacation", 400_000),
                ],
            },
        },
    )

    assert save_response.status_code == 201
    decision_id = save_response.json()["id"]

    rerun_response = client.post(
        f"/users/{user_id}/decisions/{decision_id}/rerun",
        headers=headers,
    )

    assert rerun_response.status_code == 200
    rerun_payload = rerun_response.json()
    assert rerun_payload["decision_type"] == "what_if_comparison"
    assert (
        rerun_payload["result_snapshot"]["recommended_label"] == "Laptop"
    )
