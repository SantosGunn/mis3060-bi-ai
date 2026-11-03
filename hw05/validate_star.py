"""
HW05 - Validate the Wildcat Capital star schema.

Checks, using pandas only and without modifying any CSV:
  1. Row and column counts against the counts published in the assignment
  2. Primary keys: no nulls, no duplicates
  3. Foreign keys: every non-null value exists in the referenced dimension,
     including dimension-to-dimension keys (dim_client -> dim_advisor,
     dim_security -> dim_benchmark)
  4. fact_transactions[security_id]: blanks that are legitimate (cash
     movements and fee debits) are reported separately from blanks on
     security trades and from non-null values that do not match dim_security
  5. Fact dates: every value parses and exists in dim_date[date]
  6. Grain: each fact table is unique at its stated grain
  7. Measures: the arithmetic behind the additivity notes in star_design.md
     (fee = aum_basis x bps / 12, alpha = return - benchmark, amounts positive)

Paths are resolved relative to this file, so it can be run from anywhere.
Results are printed and written to validation_results.md next to this script.
The script exits with code 1 if any check FAILs.
"""

from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_PATH = SCRIPT_DIR / "validation_results.md"

# Expected (rows, columns) from the HW05 assignment's Data table
EXPECTED_SHAPE = {
    "dim_advisor": (25, 7),
    "dim_benchmark": (8, 4),
    "dim_client": (2_500, 14),
    "dim_date": (1_827, 12),
    "dim_security": (500, 8),
    "fact_fees": (122_197, 8),
    "fact_portfolio_snapshot": (129_547, 14),
    "fact_transactions": (298_572, 10),
}

PRIMARY_KEYS = {
    "dim_advisor": "advisor_id",
    "dim_benchmark": "benchmark_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
    "fact_transactions": "txn_id",
}

# (child table, child column, parent table, parent column)
# Date keys are handled separately in check_dates().
FOREIGN_KEYS = [
    ("dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    ("dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_fees", "client_id", "dim_client", "client_id"),
    ("fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    ("fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_transactions", "client_id", "dim_client", "client_id"),
    ("fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_transactions", "security_id", "dim_security", "security_id"),
]

# Transaction types that involve a security and therefore need security_id.
# Every other type (Deposit, Withdrawal, Advisory Fee) is a cash movement
# and is expected to have a blank security_id.
SECURITY_TXN_TYPES = {"Buy", "Sell", "Dividend"}

DATE_KEYS = [
    ("fact_fees", "fee_date"),
    ("fact_portfolio_snapshot", "snapshot_date"),
    ("fact_transactions", "txn_date"),
]

# Natural grain of each fact table (the surrogate PK is checked separately)
GRAIN = {
    "fact_fees": ["client_id", "fee_date"],
    "fact_portfolio_snapshot": ["client_id", "snapshot_date"],
    "fact_transactions": ["txn_id"],
}

results = []  # rows of (section, check, status, detail)


def record(section, check, passed, detail="", status=None):
    status = status or ("PASS" if passed else "FAIL")
    results.append((section, check, status, detail))
    print(f"[{status}] {section}: {check}" + (f" - {detail}" if detail else ""))


def load_tables():
    tables = {}
    for name in EXPECTED_SHAPE:
        path = DATA_DIR / f"{name}.csv"
        if not path.exists():
            sys.exit(f"Missing file: {path}")
        # zip_code is text (leading zeros); everything else uses pandas defaults
        dtype = {"zip_code": str} if name == "dim_client" else None
        tables[name] = pd.read_csv(path, dtype=dtype)
    return tables


def check_shapes(tables):
    for name, (exp_rows, exp_cols) in EXPECTED_SHAPE.items():
        rows, cols = tables[name].shape
        record(
            "Row counts",
            name,
            (rows, cols) == (exp_rows, exp_cols),
            f"{rows:,} rows x {cols} cols (expected {exp_rows:,} x {exp_cols})",
        )


def check_primary_keys(tables):
    for name, pk in PRIMARY_KEYS.items():
        col = tables[name][pk]
        nulls = int(col.isna().sum())
        dups = int(col.duplicated().sum())
        record(
            "Primary keys",
            f"{name}[{pk}]",
            nulls == 0 and dups == 0,
            f"{nulls:,} nulls, {dups:,} duplicates, {col.nunique():,} distinct",
        )


def check_foreign_keys(tables):
    for child, ccol, parent, pcol in FOREIGN_KEYS:
        values = tables[child][ccol]
        parent_keys = set(tables[parent][pcol].dropna())
        nulls = int(values.isna().sum())
        present = values.dropna()
        orphans = present[~present.isin(parent_keys)]
        label = f"{child}[{ccol}] -> {parent}[{pcol}]"

        if child == "fact_transactions" and ccol == "security_id":
            # Nulls are judged by check_security_nulls(); here only orphans count
            record(
                "Foreign keys",
                label,
                orphans.empty,
                f"{len(orphans):,} non-null values not in {parent} "
                f"({nulls:,} blanks checked separately below)",
            )
        else:
            sample = sorted(orphans.unique())[:10]
            record(
                "Foreign keys",
                label,
                nulls == 0 and orphans.empty,
                f"{nulls:,} nulls, {len(orphans):,} orphan rows"
                + (f", e.g. {sample}" if sample else ""),
            )


def check_security_nulls(tables):
    txn = tables["fact_transactions"]
    is_null = txn["security_id"].isna()
    needs_security = txn["txn_type"].isin(SECURITY_TXN_TYPES)

    legit = int((is_null & ~needs_security).sum())
    missing = int((is_null & needs_security).sum())
    unexpected = int((~is_null & ~needs_security).sum())

    by_type = (
        txn[is_null]["txn_type"].value_counts().sort_index().to_dict()
    )
    record(
        "security_id blanks",
        "Legitimate blanks (cash / fee rows)",
        True,
        f"{legit:,} rows; blanks by txn_type: {by_type}",
        status="INFO",
    )
    record(
        "security_id blanks",
        "Blank security_id on Buy/Sell/Dividend",
        missing == 0,
        f"{missing:,} rows",
    )
    record(
        "security_id blanks",
        "security_id filled on cash / fee rows",
        unexpected == 0,
        f"{unexpected:,} rows",
    )


def check_dates(tables):
    dim_date = tables["dim_date"]
    calendar = pd.to_datetime(dim_date["date"], format="%Y-%m-%d", errors="coerce")
    bad_calendar = int(calendar.isna().sum())
    record(
        "Dates",
        "dim_date[date] parses and is unique",
        bad_calendar == 0 and not calendar.duplicated().any(),
        f"{bad_calendar:,} unparseable, {int(calendar.duplicated().sum()):,} duplicates, "
        f"range {calendar.min():%Y-%m-%d} to {calendar.max():%Y-%m-%d}",
    )
    calendar_set = set(calendar.dropna())

    # Mark as date table needs one row per day with no gaps
    gaps = int((calendar.sort_values().diff().dropna() != pd.Timedelta(days=1)).sum())
    record(
        "Dates",
        "dim_date[date] is contiguous (one row per day)",
        gaps == 0,
        f"{gaps:,} gaps",
    )

    for table, col in DATE_KEYS:
        raw = tables[table][col]
        parsed = pd.to_datetime(raw, format="%Y-%m-%d", errors="coerce")
        nulls = int(raw.isna().sum())
        unparseable = int((parsed.isna() & raw.notna()).sum())
        missing = parsed.dropna()[~parsed.dropna().isin(calendar_set)]
        record(
            "Dates",
            f"{table}[{col}] -> dim_date[date]",
            nulls == 0 and unparseable == 0 and missing.empty,
            f"{nulls:,} nulls, {unparseable:,} unparseable, "
            f"{len(missing):,} not in dim_date; "
            f"range {parsed.min():%Y-%m-%d} to {parsed.max():%Y-%m-%d}",
        )

    # Show that fact dates do NOT match dim_date[date_id] (they are dates, not ids)
    sample = tables["fact_fees"]["fee_date"].iloc[0]
    record(
        "Dates",
        "Fact dates are calendar dates, not date_id integers",
        True,
        f"e.g. fact_fees[fee_date] = {sample!r}; dim_date[date_id] is an integer "
        f"{dim_date['date_id'].min()}..{dim_date['date_id'].max()}",
        status="INFO",
    )

    # Snapshots are dated the 1st, so month-end flags in dim_date never select one
    month_ends = set(calendar[dim_date["is_month_end"] == 1])
    snap = pd.to_datetime(tables["fact_portfolio_snapshot"]["snapshot_date"], errors="coerce")
    record(
        "Dates",
        "fact_portfolio_snapshot rows on a dim_date[is_month_end] = 1 date",
        True,
        f"{int(snap.isin(month_ends).sum()):,} rows",
        status="INFO",
    )

    # client_since is a descriptive attribute; report how much falls outside the calendar
    since = pd.to_datetime(tables["dim_client"]["client_since"], errors="coerce")
    outside = int((~since.isin(calendar_set)).sum())
    record(
        "Dates",
        "dim_client[client_since] outside dim_date (attribute, not a relationship)",
        True,
        f"{outside:,} of {len(since):,} clients; earliest {since.min():%Y-%m-%d}",
        status="INFO",
    )


def check_grain(tables):
    for table, cols in GRAIN.items():
        dups = int(tables[table].duplicated(subset=cols).sum())
        record(
            "Grain",
            f"{table} unique on ({', '.join(cols)})",
            dups == 0,
            f"{dups:,} duplicate rows",
        )

    # Monthly facts should all be dated the first of a month
    for table, col in [("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date")]:
        days = pd.to_datetime(tables[table][col], errors="coerce").dt.day
        not_first = int((days != 1).sum())
        record(
            "Grain",
            f"{table}[{col}] is always the 1st of the month",
            not_first == 0,
            f"{not_first:,} rows on another day",
        )

    # Snapshot year/month must agree with snapshot_date
    snap = tables["fact_portfolio_snapshot"]
    snap_dates = pd.to_datetime(snap["snapshot_date"], errors="coerce")
    mismatch = int(((snap_dates.dt.year != snap["year"]) | (snap_dates.dt.month != snap["month"])).sum())
    record(
        "Grain",
        "fact_portfolio_snapshot year/month agree with snapshot_date",
        mismatch == 0,
        f"{mismatch:,} mismatched rows",
    )

    # Transactions have no natural key besides txn_id; report exact duplicates as info
    txn = tables["fact_transactions"]
    exact = int(txn.duplicated(subset=[c for c in txn.columns if c != "txn_id"]).sum())
    record(
        "Grain",
        "fact_transactions rows identical apart from txn_id",
        True,
        f"{exact:,} rows",
        status="INFO",
    )


def check_advisor_paths(tables):
    """Does each fact's advisor_id agree with the client's advisor in dim_client?

    Informational: explains why only one advisor path is kept active in Power BI.
    """
    client_advisor = tables["dim_client"].set_index("client_id")["advisor_id"]
    for table in GRAIN:
        fact = tables[table]
        mapped = fact["client_id"].map(client_advisor)
        differ = int((mapped != fact["advisor_id"]).sum())
        record(
            "Advisor paths",
            f"{table}[advisor_id] differs from dim_client[advisor_id]",
            True,
            f"{differ:,} of {len(fact):,} rows",
            status="INFO",
        )

    txn = tables["fact_transactions"]
    post = txn[txn["is_post_departure_txn"] == 1]
    record(
        "Advisor paths",
        "fact_transactions flagged is_post_departure_txn",
        True,
        f"{len(post):,} rows across {post['advisor_id'].nunique()} advisors; "
        "each is still attributed to that advisor_id",
        status="INFO",
    )


def check_measures(tables):
    """Arithmetic that the additivity classifications in star_design.md rely on."""
    fees = tables["fact_fees"]
    expected = fees["aum_basis"] * fees["bps_charged"] / 10_000 / 12
    off = int(((expected - fees["amount"]).abs() > 0.01).sum())
    record(
        "Measures",
        "fact_fees amount = aum_basis x bps_charged / 10,000 / 12 (monthly fee on an annual rate)",
        off == 0,
        f"{off:,} rows off by more than $0.01",
    )

    snap = tables["fact_portfolio_snapshot"]
    merged = fees.merge(
        snap, left_on=["client_id", "fee_date"], right_on=["client_id", "snapshot_date"], how="left"
    )
    off = int((~((merged["aum_basis"] - merged["aum"]).abs() <= 0.01)).sum())
    record(
        "Measures",
        "fact_fees aum_basis = fact_portfolio_snapshot aum for the same client and month",
        off == 0,
        f"{off:,} rows differ or have no matching snapshot",
    )

    off = int(((snap["return_ytd"] - snap["benchmark_return_ytd"] - snap["active_alpha_ytd"]).abs() > 1e-5).sum())
    record(
        "Measures",
        "active_alpha_ytd = return_ytd - benchmark_return_ytd",
        off == 0,
        f"{off:,} rows off by more than 0.00001",
    )

    suspect = snap[snap["is_return_suspect"] == 1]["return_ytd"]
    record(
        "Measures",
        "return_ytd on rows flagged is_return_suspect",
        True,
        f"{len(suspect):,} rows; range {suspect.min():.4f} to {suspect.max():.4f}",
        status="INFO",
    )

    txn = tables["fact_transactions"]
    negative = int((txn["amount"] < 0).sum()) + int((fees["amount"] < 0).sum())
    record(
        "Measures",
        "fact_transactions and fact_fees amounts are all non-negative (direction is in txn_type)",
        negative == 0,
        f"{negative:,} negative amounts",
    )

    trades = txn[txn["txn_type"].isin(SECURITY_TXN_TYPES)]
    off = int(((trades["shares"] * trades["price"] - trades["amount"]).abs() > 0.01).sum())
    record(
        "Measures",
        "Buy/Sell/Dividend amount = shares x price",
        off == 0,
        f"{off:,} of {len(trades):,} rows off by more than $0.01",
    )

    cash = txn[~txn["txn_type"].isin(SECURITY_TXN_TYPES)]
    filled = int(cash["shares"].notna().sum() + cash["price"].notna().sum())
    record(
        "Measures",
        "shares and price are blank on cash / fee rows",
        filled == 0,
        f"{filled:,} filled values",
    )

    txn_fees = txn.loc[txn["txn_type"] == "Advisory Fee", "amount"].sum()
    record(
        "Measures",
        "fact_transactions Advisory Fee total vs fact_fees total",
        True,
        f"${txn_fees:,.2f} vs ${fees['amount'].sum():,.2f}; different sources, do not add or swap",
        status="INFO",
    )


def write_markdown():
    counts = {s: sum(1 for r in results if r[2] == s) for s in ("PASS", "FAIL", "INFO")}
    lines = [
        "# HW05 Validation Results",
        "",
        f"Generated by `validate_star.py` on {datetime.now():%Y-%m-%d %H:%M:%S}.",
        f"Data folder: `{DATA_DIR.relative_to(SCRIPT_DIR).as_posix()}/` (read only, not modified).",
        "",
        f"**Summary:** {counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['INFO']} INFO",
        "",
    ]
    section = None
    for sec, check, status, detail in results:
        if sec != section:
            section = sec
            lines += ["", f"## {sec}", "", "| Check | Result | Detail |", "|---|---|---|"]
        detail = detail.replace("|", "\\|")
        lines.append(f"| {check} | {status} | {detail} |")
    lines.append("")
    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")
    return counts


def main():
    tables = load_tables()
    check_shapes(tables)
    check_primary_keys(tables)
    check_foreign_keys(tables)
    check_security_nulls(tables)
    check_dates(tables)
    check_grain(tables)
    check_advisor_paths(tables)
    check_measures(tables)
    counts = write_markdown()
    print(
        f"\n{counts['PASS']} PASS, {counts['FAIL']} FAIL, {counts['INFO']} INFO. "
        f"Results written to {RESULTS_PATH}"
    )
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
