from app.ingestion import parse_csv


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_parses_clean_file():
    data = _csv(
        "date,description,amount\n"
        "2026-01-05,Whole Foods,-52.10\n"
        "2026-01-06,ACME Payroll,2000.00\n"
    )
    result = parse_csv(data)
    assert result.ok_count == 2
    assert result.error_count == 0

    groceries = result.transactions[0]
    assert groceries.amount_cents == -5210
    assert groceries.category == "Groceries"
    assert result.transactions[1].category == "Income"


def test_column_aliases_work():
    # 'transaction date' / 'memo' / 'value' should all be recognized
    data = _csv("Transaction Date,Memo,Value\n01/05/2026,Netflix,-15.99\n")
    result = parse_csv(data)
    assert result.ok_count == 1
    assert result.transactions[0].amount_cents == -1599
    assert result.transactions[0].category == "Subscriptions"


def test_bad_rows_are_collected_not_fatal():
    data = _csv(
        "date,description,amount\n"
        "2026-01-05,Good Row,-10.00\n"
        "not-a-date,Bad Date,-5.00\n"
        "2026-01-07,Bad Amount,xyz\n"
        "2026-01-08,Another Good,-1.00\n"
    )
    result = parse_csv(data)
    assert result.ok_count == 2          # the two good rows still import
    assert result.error_count == 2       # two bad rows reported, not dropped silently
    assert result.errors[0].row_number == 2
    assert result.errors[1].row_number == 3


def test_accounting_negatives_and_currency_symbols():
    data = _csv('date,description,amount\n2026-02-01,Refund,"(1,234.56)"\n')
    result = parse_csv(data)
    assert result.ok_count == 1
    assert result.transactions[0].amount_cents == -123456


def test_empty_file_reports_error():
    result = parse_csv(_csv(""))
    assert result.ok_count == 0
    assert result.error_count == 1


def test_missing_amount_column():
    data = _csv("date,description\n2026-01-05,No Amount Here\n")
    result = parse_csv(data)
    assert result.error_count == 1
    assert "amount" in result.errors[0].message
