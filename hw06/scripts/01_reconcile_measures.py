#!/usr/bin/env python
"""
MIS3060 HW06 - 01_reconcile_measures.py

Independently recomputes the HW06 DAX measure library from the HW05 CSV
extracts with pandas, reconciles those values against a SEPARATELY exported
Power BI values file, and writes Part C / Part D design evidence.

Inputs (read only)
    hw05/data/dim_date.csv, dim_client.csv, fact_portfolio_snapshot.csv,
    fact_fees.csv, fact_transactions.csv
    hw06/reports/powerbi_values.csv      measure,slice,value  (exported from
                                         Power BI by hand; this script never
                                         creates, edits or repairs it)

Outputs
    hw06/reports/pandas_values.csv        measure,slice,value  (pandas only)
    hw06/reports/design_evidence.json     Part C / Part D numerical evidence
    hw06/reports/measure_reconciliation.csv
                                          only when the Power BI export is
                                          present and has valid coverage

Exit codes
    0  Power BI export present, coverage valid, every row matched
    1  Power BI export valid, but at least one row mismatched
    2  Invalid input (CSV validation or Power BI export coverage/values)
    3  Power BI export missing - reconciliation NOT completed

Run from the repo root:
    python hw06/scripts/01_reconcile_measures.py

--data-dir / --reports-dir exist only so the script can be pointed at test
fixtures; the defaults are resolved relative to this file, not the CWD.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# ----------------------------------------------------------------------------
# Paths (relative to this file, never the current working directory)
# ----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent      # hw06/scripts
HW06_DIR = SCRIPT_DIR.parent                      # hw06
REPO_ROOT = HW06_DIR.parent                       # repo root
DEFAULT_DATA_DIR = REPO_ROOT / "hw05" / "data"
DEFAULT_REPORTS_DIR = HW06_DIR / "reports"

PANDAS_VALUES_FILE = "pandas_values.csv"
POWERBI_VALUES_FILE = "powerbi_values.csv"
RECONCILIATION_FILE = "measure_reconciliation.csv"
EVIDENCE_FILE = "design_evidence.json"

EXIT_OK, EXIT_MISMATCH, EXIT_INVALID, EXIT_EXPORT_MISSING = 0, 1, 2, 3

# ----------------------------------------------------------------------------
# Input schemas
# ----------------------------------------------------------------------------
REQUIRED_COLUMNS = {
    "dim_date": ["date_id", "date", "year", "quarter", "month", "month_name",
                 "week_of_year", "day_of_week", "is_month_end", "is_quarter_end",
                 "is_year_end", "is_trading_day"],
    "dim_client": ["client_id", "first_name", "last_name", "age", "city", "state",
                   "zip_code", "risk_profile", "client_tier", "primary_account_type",
                   "initial_aum", "client_since", "advisor_id", "is_active"],
    "fact_portfolio_snapshot": ["snapshot_id", "client_id", "advisor_id", "benchmark_id",
                                "snapshot_date", "year", "month", "aum", "return_ytd",
                                "benchmark_return_ytd", "active_alpha_ytd", "cash_pct",
                                "account_type", "is_return_suspect"],
    "fact_fees": ["fee_id", "client_id", "advisor_id", "fee_date", "fee_type",
                  "aum_basis", "bps_charged", "amount"],
    "fact_transactions": ["txn_id", "client_id", "advisor_id", "security_id", "txn_date",
                          "txn_type", "shares", "price", "amount", "is_post_departure_txn"],
}
DATE_COLUMNS = {
    "dim_date": ["date"],
    "dim_client": ["client_since"],
    "fact_portfolio_snapshot": ["snapshot_date"],
    "fact_fees": ["fee_date"],
    "fact_transactions": ["txn_date"],
}
READ_DTYPES = {
    "dim_client": {"zip_code": str, "client_tier": str, "is_active": str},
}
FACT_DATE_COLUMN = {
    "fact_portfolio_snapshot": "snapshot_date",
    "fact_fees": "fee_date",
    "fact_transactions": "txn_date",
}

DEPOSIT_TYPE = "Deposit"
WITHDRAWAL_TYPE = "Withdrawal"
REQUIRED_TIERS = ["HNW", "Retail", "UHNW"]

# ----------------------------------------------------------------------------
# Measures, tolerances and slices
# ----------------------------------------------------------------------------
MEASURES: dict[str, str] = {           # measure name -> comparison kind
    "Total Fees": "currency",
    "Net Flows": "currency",
    "AUM (naive SUM)": "currency",
    "Ending AUM": "currency",
    "Ending Clients": "count",
    "Avg AUM per Client": "currency",
    "Ending AUM LY": "currency",
    "AUM YoY %": "ratio",
    "Ending AUM PM": "currency",
    "AUM MoM %": "ratio",
    "Avg Monthly AUM": "currency",
    "Fee Yield (bps)": "bps",
    "Organic Growth Rate": "ratio",
    "AUM-Weighted Alpha": "ratio",
    "Alpha Signal": "text",
    "Top 10 Client Share": "ratio",
}
ABS_TOLERANCE = {"currency": 0.01, "ratio": 0.0001, "bps": 0.0001, "count": 0.0}

# (label, dim_date[year], dim_date[month], dim_client[client_tier])
SLICES: list[tuple[str, Optional[int], Optional[int], Optional[str]]] = [
    ("Grand Total", None, None, None),
    ("Year=2020", 2020, None, None),
    ("Year=2021", 2021, None, None),
    ("Year=2022", 2022, None, None),
    ("Year=2023", 2023, None, None),
    ("Year=2024", 2024, None, None),
    ("Year=2024|Tier=HNW", 2024, None, "HNW"),
    ("Year=2024|Tier=Retail", 2024, None, "Retail"),
    ("Year=2024|Tier=UHNW", 2024, None, "UHNW"),
    ("Month=2024-12", 2024, 12, None),
]
SLICE_LABELS = [s[0] for s in SLICES]

NUMBER_PATTERN = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


class InputError(Exception):
    """Raised when input data cannot support a trustworthy calculation."""


# ----------------------------------------------------------------------------
# DAX blank semantics (BLANK is represented as None)
# ----------------------------------------------------------------------------
def dax_sum(values: pd.Series) -> Optional[float]:
    """SUM/SUMX: BLANK when there is nothing non-blank to add; 0 stays 0."""
    values = values.dropna()
    return None if values.empty else float(values.sum())


def dax_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """DIVIDE: BLANK for a blank numerator, or a blank or zero denominator."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def dax_subtract(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """a - b: BLANK only when both are BLANK; otherwise BLANK acts as 0."""
    if a is None and b is None:
        return None
    return (0.0 if a is None else a) - (0.0 if b is None else b)


def alpha_signal(alpha: Optional[float]) -> Optional[str]:
    if alpha is None:
        return None
    if alpha >= 0.02:
        return "Outperforming"
    if alpha <= -0.02:
        return "Lagging"
    return "In line"


# ----------------------------------------------------------------------------
# Loading and validation
# ----------------------------------------------------------------------------
@dataclass
class Model:
    dim_date: pd.DataFrame
    cal_dates: pd.Series          # sorted dim_date[date]
    cal_set: frozenset
    dim_client: pd.DataFrame
    snap: pd.DataFrame            # enriched with client_tier, is_active, cal_year, in_calendar
    fees: pd.DataFrame
    txns: pd.DataFrame
    validation: dict
    warnings: list


def read_table(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / f"{name}.csv"
    if not path.is_file():
        raise InputError(f"Missing input file: {path}")
    df = pd.read_csv(path, dtype=READ_DTYPES.get(name))
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in df.columns]
    if missing:
        raise InputError(f"{name}.csv is missing columns: {missing}")
    for col in DATE_COLUMNS[name]:
        try:
            df[col] = pd.to_datetime(df[col], format="%Y-%m-%d", errors="raise")
        except (ValueError, TypeError) as exc:
            raise InputError(f"{name}.{col} has a value that is not YYYY-MM-DD: {exc}") from exc
    return df


def enrich_fact(name: str, fact: pd.DataFrame, dim_client: pd.DataFrame,
                dim_date: pd.DataFrame, validation: dict, warnings: list) -> pd.DataFrame:
    """Left-join tier and calendar attributes with explicit many-to-one checks.

    Rows whose client_id or date is not in the dimension are KEPT (never
    dropped). They behave like Power BI's blank dimension member: included
    when no filter is applied on that dimension, excluded by any filter on it.
    """
    date_col = FACT_DATE_COLUMN[name]
    n_rows = len(fact)

    out = fact.merge(dim_client[["client_id", "client_tier", "is_active"]],
                     on="client_id", how="left", validate="many_to_one",
                     indicator="_client_match")
    calendar = dim_date[["date", "year", "month"]].rename(
        columns={"date": date_col, "year": "cal_year", "month": "cal_month"})
    out = out.merge(calendar, on=date_col, how="left", validate="many_to_one")
    if len(out) != n_rows:
        raise InputError(f"{name}: row count changed during joins ({n_rows} -> {len(out)})")

    unmapped = out["_client_match"].eq("left_only")
    out["in_calendar"] = out["cal_year"].notna()
    out = out.drop(columns="_client_match")

    info = {
        "rows": n_rows,
        "null_client_id_rows": int(fact["client_id"].isna().sum()),
        "client_id_not_in_dim_client_rows": int(unmapped.sum()),
        "client_id_not_in_dim_client_distinct": int(out.loc[unmapped, "client_id"].nunique()),
        "mapped_rows_with_blank_tier": int((~unmapped & out["client_tier"].isna()).sum()),
        "null_date_rows": int(out[date_col].isna().sum()),
        "date_not_in_dim_date_rows": int((out[date_col].notna() & ~out["in_calendar"]).sum()),
        "min_date": out[date_col].min(),
        "max_date": out[date_col].max(),
    }
    validation[name] = info
    if info["client_id_not_in_dim_client_rows"]:
        warnings.append(f"{name}: {info['client_id_not_in_dim_client_rows']} rows have client_id "
                        "missing from dim_client (kept; excluded from tier slices only).")
    if info["date_not_in_dim_date_rows"] or info["null_date_rows"]:
        warnings.append(f"{name}: {info['date_not_in_dim_date_rows']} rows have dates outside "
                        f"dim_date and {info['null_date_rows']} have null dates (kept; they can "
                        "only appear in the unfiltered Grand Total).")
    return out


def load_model(data_dir: Path) -> Model:
    frames = {name: read_table(data_dir, name) for name in REQUIRED_COLUMNS}
    validation: dict[str, Any] = {}
    warnings: list[str] = []

    # dim_date: key must be unique and non-null (one side of every date relationship)
    dim_date = frames["dim_date"]
    if dim_date["date"].isna().any():
        raise InputError("dim_date.date has null values")
    if dim_date["date"].duplicated().any():
        raise InputError("dim_date.date is not unique; many-to-one date joins are invalid")
    cal_dates = dim_date["date"].sort_values().reset_index(drop=True)
    first, last = cal_dates.iloc[0], cal_dates.iloc[-1]
    validation["dim_date"] = {
        "rows": len(dim_date),
        "unique_dates": int(cal_dates.nunique()),
        "first_date": first,
        "last_date": last,
        "continuous": len(cal_dates) == (last - first).days + 1,
        "years": sorted(int(y) for y in dim_date["year"].unique()),
    }
    if not validation["dim_date"]["continuous"]:
        warnings.append("dim_date is not continuous; period shifts intersect with existing dates only.")

    # dim_client: key must be unique and non-null
    dim_client = frames["dim_client"]
    if dim_client["client_id"].isna().any():
        raise InputError("dim_client.client_id has null values")
    if dim_client["client_id"].duplicated().any():
        raise InputError("dim_client.client_id is not unique; many-to-one client joins are invalid")
    tier_counts = dim_client["client_tier"].value_counts(dropna=False)
    validation["dim_client"] = {
        "rows": len(dim_client),
        "tier_counts": {("<blank>" if pd.isna(k) else str(k)): int(v) for k, v in tier_counts.items()},
        "is_active_counts": {str(k): int(v) for k, v in
                             dim_client["is_active"].value_counts(dropna=False).items()},
    }
    for tier in REQUIRED_TIERS:
        if tier not in tier_counts.index:
            warnings.append(f"Required tier {tier!r} not present in dim_client.client_tier.")

    snap = enrich_fact("fact_portfolio_snapshot", frames["fact_portfolio_snapshot"],
                       dim_client, dim_date, validation, warnings)
    fees = enrich_fact("fact_fees", frames["fact_fees"], dim_client, dim_date, validation, warnings)
    txns = enrich_fact("fact_transactions", frames["fact_transactions"],
                       dim_client, dim_date, validation, warnings)

    # Snapshot-specific checks (grain, blanks, flag values, snapshot day)
    grain_dupes = int(snap.duplicated(["client_id", "snapshot_date"], keep=False).sum())
    suspect_values = snap["is_return_suspect"].value_counts(dropna=False)
    validation["fact_portfolio_snapshot"].update({
        "rows_in_duplicate_client_date_groups": grain_dupes,
        "blank_aum": int(snap["aum"].isna().sum()),
        "blank_active_alpha_ytd": int(snap["active_alpha_ytd"].isna().sum()),
        "blank_is_return_suspect": int(snap["is_return_suspect"].isna().sum()),
        "is_return_suspect_counts": {("<blank>" if pd.isna(k) else str(k)): int(v)
                                     for k, v in suspect_values.items()},
        "distinct_snapshot_dates": int(snap["snapshot_date"].nunique()),
        "snapshot_dates_not_on_day_1": int((snap["snapshot_date"].dt.day != 1).sum()),
    })
    if grain_dupes:
        warnings.append(f"fact_portfolio_snapshot: {grain_dupes} rows share a client_id/snapshot_date.")

    # Transaction labels used by Net Flows
    type_counts = txns["txn_type"].value_counts(dropna=False)
    flow_rows = txns["txn_type"].isin([DEPOSIT_TYPE, WITHDRAWAL_TYPE])
    validation["fact_transactions"].update({
        "txn_type_counts": {str(k): int(v) for k, v in type_counts.items()},
        "negative_amount_deposit_or_withdrawal_rows": int((flow_rows & (txns["amount"] < 0)).sum()),
    })
    for label in (DEPOSIT_TYPE, WITHDRAWAL_TYPE):
        if label not in type_counts.index:
            warnings.append(f"txn_type {label!r} not found; Net Flows will treat it as BLANK.")
    if validation["fact_transactions"]["negative_amount_deposit_or_withdrawal_rows"]:
        warnings.append("Some Deposit/Withdrawal amounts are negative, but amounts are documented as positive.")

    return Model(dim_date=dim_date, cal_dates=cal_dates, cal_set=frozenset(cal_dates),
                 dim_client=dim_client, snap=snap, fees=fees, txns=txns,
                 validation=validation, warnings=warnings)


# ----------------------------------------------------------------------------
# Filter contexts
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Context:
    label: str
    dates: Optional[frozenset]   # None = no filter on dim_date (Grand Total)
    tier: Optional[str]          # None = no filter on dim_client[client_tier]
    period: Optional[tuple]      # (first, last) date of the dim_date selection, for shifts


def complete_month_period(selected: pd.Series, label: str) -> tuple:
    """Return (first, last) and require a continuous run of complete months."""
    if selected.empty:
        raise InputError(f"{label}: the dim_date selection is empty")
    selected = selected.sort_values()
    first, last = selected.iloc[0], selected.iloc[-1]
    if len(selected) != (last - first).days + 1:
        raise InputError(f"{label}: the dim_date selection is not continuous")
    if first.day != 1 or (last + pd.Timedelta(days=1)).day != 1:
        raise InputError(f"{label}: the dim_date selection is not made of complete months")
    return first, last


def build_context(model: Model, label: str, year: Optional[int], month: Optional[int],
                  tier: Optional[str]) -> Context:
    if year is None:
        return Context(label, None, tier, complete_month_period(model.cal_dates, label))
    mask = model.dim_date["year"].eq(year)
    if month is not None:
        mask &= model.dim_date["month"].eq(month)
    selected = model.dim_date.loc[mask, "date"]
    return Context(label, frozenset(selected), tier, complete_month_period(selected, label))


def shifted_context(model: Model, ctx: Context, months: int) -> Context:
    """SAMEPERIODLASTYEAR (months=-12) / DATEADD(..., -1, MONTH) (months=-1).

    The whole selected period is shifted; complete months stay complete
    (Dec 1-31 -> Nov 1-30), then the result is intersected with dim_date.
    """
    first, last = ctx.period
    new_first = first + pd.DateOffset(months=months)
    new_last = last + pd.DateOffset(months=months) + pd.offsets.MonthEnd(0)
    cal = model.cal_dates
    selected = cal[(cal >= new_first) & (cal <= new_last)]
    return dataclasses.replace(ctx, label=f"{ctx.label} shifted {months:+d} months",
                               dates=frozenset(selected), period=None)


def ctx_rows(df: pd.DataFrame, date_col: str, ctx: Context) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    if ctx.dates is not None:
        mask &= df[date_col].isin(list(ctx.dates))
    if ctx.tier is not None:
        mask &= df["client_tier"].eq(ctx.tier)
    return df.loc[mask]


# ----------------------------------------------------------------------------
# Measure logic
# ----------------------------------------------------------------------------
def ending_point(model: Model, ctx: Context) -> tuple:
    """LASTNONBLANK(dim_date[date], SUM(aum)) -> (last_date, Ending AUM, rows at that date)."""
    rows = ctx_rows(model.snap, "snapshot_date", ctx)
    rows = rows.loc[rows["in_calendar"]]              # LASTNONBLANK iterates dim_date[date]
    nonblank = rows.loc[rows["aum"].notna()]
    if nonblank.empty:
        return None, None, rows.iloc[0:0]
    last_date = nonblank["snapshot_date"].max()
    at_last = rows.loc[rows["snapshot_date"].eq(last_date)]
    return last_date, dax_sum(at_last["aum"]), at_last


def alpha_from_rows(rows: pd.DataFrame, cal_set: frozenset) -> dict:
    """AUM-Weighted Alpha plus diagnostics, for snapshot rows already in context.

    1. latest = MAX(snapshot_date) over ALL rows in context, suspects included.
    2. Keep rows at that date (KEEPFILTERS(dim_date[date] = latest)).
    3. Eligible = is_return_suspect <> 1 and non-blank alpha and aum.
       (A blank flag counts as not suspect, as BLANK <> 1 is TRUE in DAX.)
    4. alpha = DIVIDE(SUM(alpha * aum), SUM(aum)) over eligible rows only.
    No fallback to an earlier date.
    """
    dates = rows["snapshot_date"].dropna()
    latest = dates.max() if not dates.empty else None
    if latest is None or latest not in cal_set:
        at_latest = rows.iloc[0:0]
    else:
        at_latest = rows.loc[rows["snapshot_date"].eq(latest)]

    suspect = at_latest["is_return_suspect"].eq(1)
    has_values = at_latest["active_alpha_ytd"].notna() & at_latest["aum"].notna()
    eligible = at_latest.loc[~suspect & has_values]
    with_suspects = at_latest.loc[has_values]

    numerator = dax_sum(eligible["active_alpha_ytd"] * eligible["aum"])
    denominator = dax_sum(eligible["aum"])
    incl_numerator = dax_sum(with_suspects["active_alpha_ytd"] * with_suspects["aum"])
    incl_denominator = dax_sum(with_suspects["aum"])
    return {
        "latest_snapshot": latest,
        "rows_at_latest": int(len(at_latest)),
        "eligible_rows": int(len(eligible)),
        "excluded_suspect_rows": int(suspect.sum()),
        "excluded_blank_value_rows": int((~suspect & ~has_values).sum()),
        "excluded_suspect_aum": dax_sum(at_latest.loc[suspect, "aum"]),
        "weighted_numerator": numerator,
        "eligible_aum_denominator": denominator,
        "aum_weighted_alpha": dax_divide(numerator, denominator),
        "weighted_alpha_including_suspects": dax_divide(incl_numerator, incl_denominator),
        "eligible_simple_mean_alpha": (None if eligible.empty
                                       else float(eligible["active_alpha_ytd"].mean())),
    }


def alpha_diagnostics(model: Model, ctx: Context) -> dict:
    return alpha_from_rows(ctx_rows(model.snap, "snapshot_date", ctx), model.cal_set)


def top10_client_share(at_last: pd.DataFrame, ending_aum: Optional[float]) -> Optional[float]:
    """One common last date for the slice, chosen BEFORE ranking clients."""
    if at_last.empty:
        return None
    per_client = (at_last.dropna(subset=["aum"])
                  .groupby("client_id", dropna=False, as_index=False)["aum"].sum()
                  .sort_values(["aum", "client_id"], ascending=[False, True], kind="mergesort")
                  .head(10))
    return dax_divide(dax_sum(per_client["aum"]), ending_aum)


def compute_measures(model: Model, ctx: Context) -> dict[str, Any]:
    fees = ctx_rows(model.fees, "fee_date", ctx)
    txns = ctx_rows(model.txns, "txn_date", ctx)
    snap = ctx_rows(model.snap, "snapshot_date", ctx)

    total_fees = dax_sum(fees["amount"])
    deposits = dax_sum(txns.loc[txns["txn_type"].eq(DEPOSIT_TYPE), "amount"])
    withdrawals = dax_sum(txns.loc[txns["txn_type"].eq(WITHDRAWAL_TYPE), "amount"])
    net_flows = dax_subtract(deposits, withdrawals)
    naive_aum = dax_sum(snap["aum"])

    _, ending_aum, at_last = ending_point(model, ctx)
    ending_clients = None if at_last.empty else int(at_last["client_id"].nunique(dropna=False))
    _, ending_aum_ly, _ = ending_point(model, shifted_context(model, ctx, -12))
    _, ending_aum_pm, _ = ending_point(model, shifted_context(model, ctx, -1))

    distinct_dates = int(snap["snapshot_date"].nunique())
    annualized_fees_bps = None if total_fees is None else total_fees * 12 * 10000
    alpha = alpha_from_rows(snap, model.cal_set)["aum_weighted_alpha"]

    values = {
        "Total Fees": total_fees,
        "Net Flows": net_flows,
        "AUM (naive SUM)": naive_aum,
        "Ending AUM": ending_aum,
        "Ending Clients": ending_clients,
        "Avg AUM per Client": dax_divide(ending_aum, ending_clients),
        "Ending AUM LY": ending_aum_ly,
        "AUM YoY %": dax_divide(dax_subtract(ending_aum, ending_aum_ly), ending_aum_ly),
        "Ending AUM PM": ending_aum_pm,
        "AUM MoM %": dax_divide(dax_subtract(ending_aum, ending_aum_pm), ending_aum_pm),
        "Avg Monthly AUM": dax_divide(naive_aum, distinct_dates or None),
        "Fee Yield (bps)": dax_divide(annualized_fees_bps, naive_aum),
        "Organic Growth Rate": dax_divide(net_flows, ending_aum_ly),
        "AUM-Weighted Alpha": alpha,
        "Alpha Signal": alpha_signal(alpha),
        "Top 10 Client Share": top10_client_share(at_last, ending_aum),
    }
    assert list(values) == list(MEASURES), "measure list out of sync"
    return values


# ----------------------------------------------------------------------------
# Part C / Part D evidence
# ----------------------------------------------------------------------------
def evidence_ending_vs_client_last(model: Model, gt: Context) -> dict:
    """(a) Grand Total Ending AUM vs sum of each client's own last balance."""
    global_latest, ending_aum, _ = ending_point(model, gt)
    valid = model.snap.loc[model.snap["in_calendar"] & model.snap["aum"].notna()]
    per_client_last = (valid.sort_values(["client_id", "snapshot_date"], kind="mergesort")
                       .groupby("client_id", dropna=False).tail(1))
    sum_client_last = dax_sum(per_client_last["aum"])
    predating = per_client_last.loc[per_client_last["snapshot_date"] < global_latest]
    at_global = per_client_last.loc[per_client_last["snapshot_date"].eq(global_latest)]
    no_snapshot = set(model.dim_client["client_id"]) - set(model.snap["client_id"].dropna())
    return {
        "scope": "All clients (no is_active filter); Grand Total context.",
        "global_latest_snapshot": global_latest,
        "grand_total_ending_aum": ending_aum,
        "sum_of_each_clients_last_available_aum": sum_client_last,
        "difference_dollars_client_last_minus_ending_aum": dax_subtract(sum_client_last, ending_aum),
        "clients_with_snapshots": int(len(per_client_last)),
        "clients_last_snapshot_at_global_latest": int(len(at_global)),
        "clients_last_snapshot_before_global_latest": int(len(predating)),
        "aum_of_clients_whose_last_snapshot_predates_global_latest": dax_sum(predating["aum"]),
        "predating_clients_by_last_snapshot_year": {
            str(int(k)): int(v) for k, v in
            predating["snapshot_date"].dt.year.value_counts().sort_index().items()},
        "predating_clients_by_dim_client_is_active": {
            str(k): int(v) for k, v in predating["is_active"].value_counts(dropna=False).items()},
        "check_sum_at_global_latest_equals_ending_aum_abs_diff": (
            None if ending_aum is None else abs((dax_sum(at_global["aum"]) or 0.0) - ending_aum)),
        "dim_client_clients_with_no_snapshot_rows": len(no_snapshot),
    }


def evidence_fee_yield_2024(model: Model, ctx2024: Context) -> dict:
    """(b) Fee Yield vs a CANDIDATE fee-basis formula for 2024. Quantified only; no cause asserted."""
    fees = ctx_rows(model.fees, "fee_date", ctx2024).copy()
    snap = ctx_rows(model.snap, "snapshot_date", ctx2024).copy()
    total_fees = dax_sum(fees["amount"])
    snapshot_aum = dax_sum(snap["aum"])
    aum_basis = dax_sum(fees["aum_basis"])
    annualized = None if total_fees is None else total_fees * 12 * 10000

    fees["ym"] = fees["fee_date"].dt.to_period("M")
    snap["ym"] = snap["snapshot_date"].dt.to_period("M")

    # Aggregate each side to client-month BEFORE joining, so AUM is never multiplied.
    fee_cm = (fees.groupby(["client_id", "ym"], dropna=False)
              .agg(fee_rows=("fee_id", "size"), fee_amount=("amount", "sum"),
                   aum_basis_sum=("aum_basis", "sum"), aum_basis_max=("aum_basis", "max"),
                   aum_basis_distinct=("aum_basis", "nunique"))
              .reset_index())
    snap_cm = (snap.groupby(["client_id", "ym"], dropna=False)
               .agg(snapshot_rows=("snapshot_id", "size"), snapshot_aum=("aum", "sum"))
               .reset_index())
    cm = snap_cm.merge(fee_cm, on=["client_id", "ym"], how="outer",
                       validate="one_to_one", indicator=True)
    both = cm.loc[cm["_merge"].eq("both")].copy()
    snap_only = cm.loc[cm["_merge"].eq("left_only")]
    fee_only = cm.loc[cm["_merge"].eq("right_only")]

    # Prior-month snapshot AUM (from the full table) for an alignment comparison
    all_cm = (model.snap.assign(ym=model.snap["snapshot_date"].dt.to_period("M"))
              .groupby(["client_id", "ym"], dropna=False)["aum"].sum().reset_index())
    prior = all_cm.assign(ym=all_cm["ym"] + 1).rename(columns={"aum": "prior_month_snapshot_aum"})
    both = both.merge(prior, on=["client_id", "ym"], how="left", validate="one_to_one")

    basis_vs_same = (both["aum_basis_max"] - both["snapshot_aum"]).abs()
    basis_vs_prior = (both["aum_basis_max"] - both["prior_month_snapshot_aum"]).abs()

    by_type = (fees.groupby("fee_type", dropna=False)
               .agg(rows=("fee_id", "size"), amount=("amount", "sum"),
                    aum_basis=("aum_basis", "sum"))
               .reset_index())
    fee_month = fees.groupby("ym").agg(fee_rows=("fee_id", "size"), fees=("amount", "sum"),
                                       aum_basis=("aum_basis", "sum"),
                                       fee_clients=("client_id", "nunique"))
    snap_month = snap.groupby("ym").agg(snapshot_aum=("aum", "sum"),
                                        snapshot_clients=("client_id", "nunique"))
    monthly = fee_month.join(snap_month, how="outer").reset_index()

    return {
        "scope": "Year=2024 (dim_date year), all tiers.",
        "total_fees": total_fees,
        "denominator_sum_snapshot_aum": snapshot_aum,
        "denominator_sum_fee_aum_basis": aum_basis,
        "fee_yield_bps_sum_fees_x12x10000_over_sum_snapshot_aum": dax_divide(annualized, snapshot_aum),
        "CANDIDATE_ICE9_effective_fee_rate_bps_sum_fees_x12x10000_over_sum_aum_basis": (
            dax_divide(annualized, aum_basis)),
        "candidate_label_note": ("Candidate only: the ICE9 Effective Fee Rate definition has not been "
                                 "confirmed. This is NOT presented as the course measure."),
        "fee_months": sorted(str(p) for p in fees["ym"].dropna().unique()),
        "snapshot_months": sorted(str(p) for p in snap["ym"].dropna().unique()),
        "fee_distinct_clients": int(fees["client_id"].nunique()),
        "snapshot_distinct_clients": int(snap["client_id"].nunique()),
        "client_months_with_both": int(len(both)),
        "client_months_snapshot_but_no_fee_rows": int(len(snap_only)),
        "client_months_fee_rows_but_no_snapshot": int(len(fee_only)),
        "snapshot_aum_in_client_months_without_fees": dax_sum(snap_only["snapshot_aum"]),
        "fee_amount_in_client_months_without_snapshot": dax_sum(fee_only["fee_amount"]),
        "fee_rows_per_client_month_distribution": {
            str(int(k)): int(v) for k, v in fee_cm["fee_rows"].value_counts().sort_index().items()},
        "client_months_with_more_than_one_distinct_aum_basis": int((fee_cm["aum_basis_distinct"] > 1).sum()),
        "sum_aum_basis_all_rows": aum_basis,
        "sum_aum_basis_one_per_client_month_max": dax_sum(fee_cm["aum_basis_max"]),
        "aligned_client_months_aum_basis_max_within_0.01_of_same_month_snapshot_aum": int((basis_vs_same <= 0.01).sum()),
        "aligned_client_months_aum_basis_max_within_0.01_of_prior_month_snapshot_aum": int((basis_vs_prior <= 0.01).sum()),
        "aligned_client_months_mean_abs_diff_basis_vs_same_month_snapshot": (
            None if basis_vs_same.dropna().empty else float(basis_vs_same.mean())),
        "fee_date_day_of_month_top10": {
            str(int(k)): int(v) for k, v in fees["fee_date"].dt.day.value_counts().head(10).items()},
        "fee_types": by_type.to_dict("records"),
        "monthly_coverage": monthly.to_dict("records"),
        "note": "Differences are quantified here; no cause is asserted by this script.",
    }


def all_suspect_client_year(model: Model) -> dict:
    """Observed client-year whose latest snapshot rows are all suspect, if any."""
    s = model.snap.loc[model.snap["cal_year"].notna()]
    latest = s.groupby(["client_id", "cal_year"])["snapshot_date"].transform("max")
    at_latest = s.loc[s["snapshot_date"].eq(latest)]
    groups = (at_latest.groupby(["client_id", "cal_year"])
              .agg(rows=("snapshot_id", "size"),
                   suspect_rows=("is_return_suspect", lambda x: int(x.eq(1).sum())))
              .reset_index())
    candidates = groups.loc[groups["rows"].gt(0) & groups["suspect_rows"].eq(groups["rows"])]
    candidates = candidates.sort_values(["cal_year", "client_id"], ascending=[False, True])
    if candidates.empty:
        return {"exercised": False, "candidate_count": 0,
                "note": "No client-year in the data has all latest-snapshot rows suspect; "
                        "this edge case was not exercised."}

    pick = candidates.iloc[0]
    client_id, year = pick["client_id"], int(pick["cal_year"])
    rows = s.loc[s["client_id"].eq(client_id) & s["cal_year"].eq(year)]
    diag = alpha_from_rows(rows, model.cal_set)

    # What a WRONG fallback to the latest earlier eligible date would have shown (contrast only)
    eligible = rows.loc[~rows["is_return_suspect"].eq(1)
                        & rows["active_alpha_ytd"].notna() & rows["aum"].notna()]
    fallback = None
    if not eligible.empty:
        d = eligible["snapshot_date"].max()
        e = eligible.loc[eligible["snapshot_date"].eq(d)]
        fallback = {"date": d,
                    "alpha": dax_divide(dax_sum(e["active_alpha_ytd"] * e["aum"]), dax_sum(e["aum"]))}
    return {
        "exercised": True,
        "candidate_count": int(len(candidates)),
        "context": {"dim_client.client_id": client_id, "dim_date.year": year},
        "diagnostics": diag,
        "expected": "aum_weighted_alpha is BLANK and latest_snapshot is the year's latest date.",
        "fallback_value_that_must_NOT_be_returned": fallback,
    }


def build_evidence(model: Model, contexts: dict[str, Context],
                   results: dict[tuple[str, str], Any], data_dir: Path) -> dict:
    gt, y2024 = contexts["Grand Total"], contexts["Year=2024"]

    alpha_gt = alpha_diagnostics(model, gt)
    alpha_2024 = alpha_diagnostics(model, y2024)

    tier_growth = {}
    for tier in REQUIRED_TIERS:
        label = f"Year=2024|Tier={tier}"
        ending, ly = results[("Ending AUM", label)], results[("Ending AUM LY", label)]
        net = results[("Net Flows", label)]
        change = dax_subtract(ending, ly)
        tier_growth[label] = {
            "net_flows": net,
            "ending_aum_ly": ly,
            "ending_aum": ending,
            "organic_growth_rate": results[("Organic Growth Rate", label)],
            "aum_yoy_pct": results[("AUM YoY %", label)],
            "aum_change_dollars": change,
            "aum_change_minus_net_flows": dax_subtract(change, net),
        }

    part_d_contexts = ["Grand Total", "Year=2022"] + [f"Year=2024|Tier={t}" for t in REQUIRED_TIERS]
    no_data = Context("Year=1900", frozenset(model.dim_date.loc[model.dim_date["year"].eq(1900), "date"]),
                      None, None)

    try:
        data_dir_label = str(data_dir.resolve().relative_to(REPO_ROOT))
    except ValueError:
        data_dir_label = str(data_dir)

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_data_dir": data_dir_label,
        "notes": [
            "All values are independent pandas calculations from CSVs; none are Power BI results.",
            "BLANK is written as null. Ratios are raw decimals (not multiplied by 100).",
        ],
        "data_validation": model.validation,
        "data_warnings": model.warnings,
        "part_c": {
            "a_ending_aum_vs_each_client_last_balance": evidence_ending_vs_client_last(model, gt),
            "b_fee_yield_2024": evidence_fee_yield_2024(model, y2024),
            "c_alpha_exclusion": {
                "grand_total_latest_snapshot": alpha_gt,
                "year_2024": alpha_2024,
                "same_latest_snapshot": alpha_gt["latest_snapshot"] == alpha_2024["latest_snapshot"],
            },
            "d_tier_growth_2024": {
                "tiers": tier_growth,
                "note": ("aum_change_minus_net_flows is the part of the AUM change that net "
                         "contributions do not explain. It is NOT attributed here to investment "
                         "returns; it can also reflect fees, other transactions, client entry/exit "
                         "and data effects."),
            },
        },
        "part_d_alpha_diagnostics": {
            "contexts": {label: alpha_diagnostics(model, contexts[label]) for label in part_d_contexts},
            "no_data_context_year_1900": {
                "dim_date_rows_in_1900": int(len(no_data.dates)),
                "diagnostics": alpha_diagnostics(model, no_data),
                "expected": "All values BLANK (null), eligible_rows = 0.",
            },
            "all_latest_rows_suspect_client_year": all_suspect_client_year(model),
        },
    }


def to_jsonable(obj: Any) -> Any:
    """Convert pandas/numpy values to JSON-safe values (NaN/NaT -> null)."""
    if obj is None or obj is pd.NaT or obj is pd.NA:
        return None
    if isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    if isinstance(obj, pd.Period):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (int, float)):
        return to_jsonable(obj.item())            # numpy scalar -> python scalar
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, int):
        return obj
    return str(obj)


# ----------------------------------------------------------------------------
# Output and reconciliation
# ----------------------------------------------------------------------------
def format_value(kind: str, value: Any) -> str:
    if value is None:
        return ""
    if kind == "text":
        return str(value)
    if kind == "count":
        return str(int(value))
    return repr(float(value))


def parse_export_value(kind: str, text: str) -> Any:
    """Blank text -> BLANK. Text measures keep their string. Numbers must be plain decimals."""
    if text == "":
        return None
    if kind == "text":
        return text
    if not NUMBER_PATTERN.match(text):
        raise ValueError(f"invalid numeric value {text!r} (export raw numbers, no %, $ or commas)")
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite numeric value {text!r}")
    if kind == "count" and not value.is_integer():
        raise ValueError(f"count value {text!r} is not a whole number")
    return value


def read_powerbi_export(path: Path) -> tuple[dict, dict, list[str]]:
    """Return (parsed values, raw text, errors). Never modifies the file."""
    try:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False,
                          encoding="utf-8-sig")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        return {}, {}, [f"Could not read {path.name}: {exc}"]

    raw.columns = [c.strip() for c in raw.columns]
    if sorted(raw.columns) != ["measure", "slice", "value"]:
        return {}, {}, [f"{path.name} must have exactly the columns measure,slice,value; "
                         f"found {list(raw.columns)}"]
    for col in raw.columns:
        raw[col] = raw[col].str.strip()

    errors: list[str] = []
    dupes = raw.loc[raw.duplicated(["measure", "slice"], keep=False)]
    for (m, s), group in dupes.groupby(["measure", "slice"]):
        errors.append(f"Duplicate rows for ({m!r}, {s!r}) at file lines "
                      f"{[int(i) + 2 for i in group.index]}")

    required = {(m, s) for m in MEASURES for s in SLICE_LABELS}
    present = set(zip(raw["measure"], raw["slice"]))
    for key in sorted(required - present):
        errors.append(f"Missing row: {key}")
    for key in sorted(present - required):
        errors.append(f"Unexpected measure/slice (check exact spelling): {key}")

    parsed, texts = {}, {}
    for idx, row in raw.iterrows():
        key = (row["measure"], row["slice"])
        if key not in required:
            continue
        try:
            parsed[key] = parse_export_value(MEASURES[row["measure"]], row["value"])
            texts[key] = row["value"]
        except ValueError as exc:
            errors.append(f"Line {int(idx) + 2} {key}: {exc}")
    return parsed, texts, errors


def compare(kind: str, pbi: Any, pandas_value: Any) -> tuple[Optional[float], bool]:
    if pbi is None and pandas_value is None:
        return None, True
    if pbi is None or pandas_value is None:
        return None, False                         # blank vs value (including 0) fails
    if kind == "text":
        return None, pbi == pandas_value
    diff = abs(float(pbi) - float(pandas_value))
    return diff, diff <= ABS_TOLERANCE[kind]


def remove_stale(path: Path) -> None:
    if path.exists():
        path.unlink()
        print(f"Removed stale {path.name} from a previous run so it cannot be mistaken for current evidence.")


def reconcile(reports_dir: Path, results: dict[tuple[str, str], Any]) -> int:
    pbi_path = reports_dir / POWERBI_VALUES_FILE
    recon_path = reports_dir / RECONCILIATION_FILE

    if not pbi_path.is_file():
        remove_stale(recon_path)
        print(f"\nPower BI export missing; reconciliation not completed. (Expected {pbi_path})")
        return EXIT_EXPORT_MISSING

    parsed, texts, errors = read_powerbi_export(pbi_path)
    if errors:
        remove_stale(recon_path)
        print(f"\nINVALID Power BI export ({len(errors)} problem(s)); reconciliation not completed:")
        for err in errors:
            print(f"  - {err}")
        return EXIT_INVALID

    rows = []
    for measure, kind in MEASURES.items():
        for slice_label in SLICE_LABELS:
            key = (measure, slice_label)
            diff, ok = compare(kind, parsed[key], results[key])
            rows.append({
                "measure": measure,
                "slice": slice_label,
                "powerbi_value": texts[key],
                "pandas_value": format_value(kind, results[key]),
                "abs_diff": "" if diff is None else repr(diff),
                "match": ok,
            })
    recon = pd.DataFrame(rows)
    recon.to_csv(recon_path, index=False)

    passed = int(recon["match"].sum())
    failed = len(recon) - passed
    print(f"\nReconciliation written: {recon_path}")
    print(f"Passed: {passed}   Failed: {failed}   Total: {len(recon)}")
    if failed:
        print("\nMismatched rows:")
        print(recon.loc[~recon["match"]].to_string(index=False))
        return EXIT_MISMATCH
    return EXIT_OK


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    data_dir, reports_dir = args.data_dir.resolve(), args.reports_dir.resolve()
    print(f"Data dir:    {data_dir}")
    print(f"Reports dir: {reports_dir}")

    try:
        model = load_model(data_dir)
        contexts = {label: build_context(model, label, year, month, tier)
                    for label, year, month, tier in SLICES}
    except InputError as exc:
        print(f"INPUT VALIDATION FAILED: {exc}")
        return EXIT_INVALID

    for warning in model.warnings:
        print(f"WARNING: {warning}")

    results: dict[tuple[str, str], Any] = {}
    for label in SLICE_LABELS:
        for measure, value in compute_measures(model, contexts[label]).items():
            results[(measure, label)] = value

    reports_dir.mkdir(parents=True, exist_ok=True)
    pandas_values = pd.DataFrame(
        [{"measure": m, "slice": s, "value": format_value(MEASURES[m], results[(m, s)])}
         for m in MEASURES for s in SLICE_LABELS])
    pandas_path = reports_dir / PANDAS_VALUES_FILE
    pandas_values.to_csv(pandas_path, index=False)
    blanks = int(pandas_values["value"].eq("").sum())
    print(f"Wrote {len(pandas_values)} independent pandas values ({blanks} BLANK): {pandas_path}")

    evidence = to_jsonable(build_evidence(model, contexts, results, data_dir))
    evidence_path = reports_dir / EVIDENCE_FILE
    with evidence_path.open("w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, allow_nan=False)
    print(f"Wrote Part C / Part D evidence: {evidence_path}")

    return reconcile(reports_dir, results)


if __name__ == "__main__":
    sys.exit(main())
