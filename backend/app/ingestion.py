"""CSV ingestion pipeline.

Takes raw CSV bytes from an upload and turns them into clean Transaction rows.
Design choices that matter for a recruiter reading this:
  - We never trust the file. Every row is validated; bad rows are collected and
    reported, not silently dropped and not allowed to crash the whole upload.
  - Money is parsed to integer cents at this boundary (see app.money).
  - Categorization happens here so stored rows are query-ready.

Expected columns (case-insensitive, flexible aliases):
  date        | posted_on | transaction date
  description | name      | memo
  amount
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime

from app.categorization import categorize
from app.money import MoneyParseError, parse_to_cents

DATE_COLUMNS = ("date", "posted_on", "transaction date", "posted date")
DESC_COLUMNS = ("description", "name", "memo", "details")
AMOUNT_COLUMNS = ("amount", "amount_cents", "value")

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%m-%Y")


@dataclass
class ParsedTransaction:
    posted_on: date
    description: str
    amount_cents: int
    category: str


@dataclass
class RowError:
    row_number: int  # 1-based, matching what a human sees in a spreadsheet
    message: str


@dataclass
class IngestResult:
    transactions: list[ParsedTransaction] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return len(self.transactions)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def _find(row: dict[str, str], candidates: tuple[str, ...]) -> str | None:
    lowered = {k.lower().strip(): v for k, v in row.items() if k}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    return None


def _parse_date(raw: str) -> date:
    s = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {raw!r}")


_MAX_DESCRIPTION_LENGTH = 512


def parse_csv(raw_bytes: bytes) -> IngestResult:
    """Parse CSV bytes into an IngestResult (good rows + per-row errors)."""
    result = IngestResult()

    try:
        text = raw_bytes.decode("utf-8-sig")  # tolerate Excel BOM
    except UnicodeDecodeError:
        result.errors.append(
            RowError(0, "file is not valid UTF-8 text")
        )
        return result

    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        result.errors.append(RowError(0, "file is empty or has no header row"))
        return result

    for i, row in enumerate(reader, start=1):
        try:
            raw_date = _find(row, DATE_COLUMNS)
            raw_desc = _find(row, DESC_COLUMNS)
            raw_amount = _find(row, AMOUNT_COLUMNS)

            if raw_date is None:
                raise ValueError("missing a date column")
            if raw_amount is None:
                raise ValueError("missing an amount column")

            description = (raw_desc or "").strip() or "(no description)"
            description = description[:_MAX_DESCRIPTION_LENGTH]
            posted_on = _parse_date(raw_date)
            amount_cents = parse_to_cents(raw_amount)

            result.transactions.append(
                ParsedTransaction(
                    posted_on=posted_on,
                    description=description,
                    amount_cents=amount_cents,
                    category=categorize(description),
                )
            )
        except (ValueError, MoneyParseError) as exc:
            result.errors.append(RowError(row_number=i, message=str(exc)))

    return result
