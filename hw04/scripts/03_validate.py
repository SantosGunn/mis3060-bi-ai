"""
HW4 Part D: Referential integrity and validation, raw vs clean.

Reads all eight tables from data/raw and data/clean (dtype=str, keep_default_na=False),
evaluates both stages with the SAME definitions in one run, and writes:

    reports/data_quality_scorecard.csv        one row per table per stage (16 rows)
    reports/validation_ri_results.csv         13 relationships x 2 stages = 26 rows
    reports/validation_parent_keys.csv        parent-key uniqueness, per relationship and stage
    reports/validation_rule_results.csv       every single-table rule, per stage
    reports/validation_reconciliations.csv    cross-table reconciliations, per stage
    reports/validation_iqr_thresholds.csv     IQR fences (reference = clean stage) + flag counts
    reports/validation_iqr_flags.csv          row-level 0/1 IQR flags for both stages
    reports/validation_definitions.md         formulas, assumptions, limitations

It never modifies data/raw or data/clean, never calls 02_clean.py, and never touches the
Part A reports (profile_raw.csv, dq_summary_raw.csv, near_dup_clients_raw.csv).

Reviewed definitions (SCHEMA, RELATIONSHIPS, parsers) are imported from 01_profile.py
without running its main routine. Every figure is computed from the data; nothing is
hard-coded or forced to 100%.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
HW_DIR = SCRIPT_DIR.parent
RAW_DIR = HW_DIR / "data" / "raw"
CLEAN_DIR = HW_DIR / "data" / "clean"
REPORT_DIR = HW_DIR / "reports"

PART_A_REPORTS = {"profile_raw.csv", "dq_summary_raw.csv", "near_dup_clients_raw.csv"}
OUTPUTS = {
    "scorecard": "data_quality_scorecard.csv",
    "ri": "validation_ri_results.csv",
    "parent": "validation_parent_keys.csv",
    "rules": "validation_rule_results.csv",
    "recon": "validation_reconciliations.csv",
    "iqr_thresholds": "validation_iqr_thresholds.csv",
    "iqr_flags": "validation_iqr_flags.csv",
    "definitions": "validation_definitions.md",
}
assert not (set(OUTPUTS.values()) & PART_A_REPORTS), "would overwrite a Part A report"


# ---------------------------------------------------------------------------
# Reuse reviewed definitions from 01_profile.py (import only; its main() is not run)
# ---------------------------------------------------------------------------
def _import_profile():
    path = SCRIPT_DIR / "01_profile.py"
    spec = importlib.util.spec_from_file_location("hw04_profile_defs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # defines functions/constants only; main() is guarded
    return mod


P = _import_profile()
SCHEMA = P.SCHEMA
RELATIONSHIPS = P.RELATIONSHIPS           # 10 ID-based + 3 date relationships
TABLES = list(P.TABLES)
is_blank, parses_as, RE_FLOAT = P.is_blank, P.parses_as, P.RE_FLOAT
STAGES = ("raw", "clean")

# Business constants (same values as the reviewed scripts and decision log)
CASH_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}
TRADED_TYPES = {"Buy", "Sell", "Dividend"}
TOL_MONEY = Decimal("0.01")
TOL_MONEY_F = 0.01 + 1e-9                 # float tolerance with a tiny guard for binary rounding
TOL_RATE = P.TOL_RATE                     # 1e-4

# Rule classes. Only "hard" and "inferred" count toward % rule pass; "plausibility" is reported apart.
HARD, INFERRED, PLAUSIBILITY = "hard", "inferred_convention", "plausibility"

# Range rules from SCHEMA["ranges"] are natural bounds (hard) EXCEPT these sign rules, which are
# conventions inferred from the data (decision log Issue 3): direction is carried by txn_type.
INFERRED_SIGN_RULES = {("fact_transactions", "shares"), ("fact_transactions", "amount"),
                       ("fact_fees", "amount")}
# Allowed-value lists: these are definitional or external standards (hard); every other list in
# SCHEMA was inferred from the values observed in the extract (inferred convention).
HARD_CODE_LISTS = {("dim_date", "is_month_end"), ("dim_date", "is_quarter_end"), ("dim_date", "is_year_end"),
                   ("dim_date", "is_trading_day"), ("dim_date", "day_of_week"), ("dim_client", "state")}

PK = {t: SCHEMA[t]["pk"][0] for t in TABLES}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_stage(folder: Path, stage: str) -> dict[str, pd.DataFrame]:
    missing = [t for t in TABLES if not (folder / f"{t}.csv").exists()]
    if missing:
        hint = " Run scripts/02_clean.py first." if stage == "clean" else ""
        sys.exit(f"Missing {stage} files in {folder}: {missing}.{hint}")
    return {t: pd.read_csv(folder / f"{t}.csv", dtype=str, keep_default_na=False) for t in TABLES}


# ---------------------------------------------------------------------------
# 1. Reusable referential-integrity function (keep for Assignment 5)
# ---------------------------------------------------------------------------
def check_referential_integrity(fact_df: pd.DataFrame, fact_key: str,
                                dim_df: pd.DataFrame, dim_key: str) -> dict:
    """Check that every nonblank fact_df[fact_key] exists in dim_df[dim_key].

    Matching is EXACT TEXT (no stripping, no numeric conversion), so '45.0' does not match '45'.
    Missing values (NaN/None, e.g. from a typed load) are treated as blank keys, never as orphans.
    Keys are compared with Series.isin, so no join is performed and rows cannot multiply.

    Returns a dict. Rates are percentages (0-100) or None when the denominator is 0 (report as N/A):
      child_rows             rows in fact_df
      child_blank_keys       rows whose key is empty or whitespace-only
      null_key_rate_pct      child_blank_keys / child_rows
      eligible_keys          child_rows - child_blank_keys (the match-rate denominator)
      matched_keys           eligible rows whose key text is in the parent key set
      match_rate_pct         matched_keys / eligible_keys
      orphan_rows            eligible_keys - matched_keys
      distinct_orphan_keys   number of different unmatched key values
      orphan_key_examples    up to 8 unmatched key values (sorted)
      parent_rows, parent_blank_keys   blank parent keys are excluded from the match set
    """
    for df, col, name in ((fact_df, fact_key, "fact_df"), (dim_df, dim_key, "dim_df")):
        if col not in df.columns:
            raise KeyError(f"{name} has no column {col!r}")

    # Missing values (NaN/None from a typed load) become '' so they count as blank keys,
    # not as the text 'nan' (which would be misreported as an orphan).
    child = fact_df[fact_key].astype(object).where(fact_df[fact_key].notna(), "").astype(str)
    parent = dim_df[dim_key].astype(object).where(dim_df[dim_key].notna(), "").astype(str)
    child_blank = is_blank(child) if len(child) else pd.Series(dtype=bool)
    parent_blank = is_blank(parent) if len(parent) else pd.Series(dtype=bool)
    parent_keys = set(parent[~parent_blank]) if len(parent) else set()

    eligible = child[~child_blank] if len(child) else child
    matched_mask = eligible.isin(parent_keys)
    orphans = eligible[~matched_mask]

    n_rows, n_blank, n_elig = len(child), int(child_blank.sum()) if len(child) else 0, len(eligible)
    n_match = int(matched_mask.sum())
    return {
        "child_rows": n_rows,
        "child_blank_keys": n_blank,
        "null_key_rate_pct": round(100 * n_blank / n_rows, 3) if n_rows else None,
        "eligible_keys": n_elig,
        "matched_keys": n_match,
        "match_rate_pct": round(100 * n_match / n_elig, 3) if n_elig else None,
        "orphan_rows": n_elig - n_match,
        "distinct_orphan_keys": int(orphans.nunique()),
        "orphan_key_examples": "; ".join(sorted(orphans.unique().tolist())[:8]),
        "parent_rows": len(parent),
        "parent_blank_keys": int(parent_blank.sum()) if len(parent) else 0,
    }


def check_parent_key_uniqueness(dim_df: pd.DataFrame, dim_key: str) -> dict:
    """Separate check: a parent key that repeats would make a many-to-one join multiply rows."""
    k = dim_df[dim_key].astype(str)
    nb = k[~is_blank(k)] if len(k) else k
    dup_rows = int(nb.duplicated(keep=False).sum())
    return {"parent_rows": len(k), "parent_blank_keys": len(k) - len(nb),
            "duplicate_key_rows": dup_rows, "distinct_duplicate_keys": int(nb[nb.duplicated()].nunique()),
            "unique": dup_rows == 0 and len(k) == len(nb)}


def ri_results(stages: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, prow = [], []
    for stage in STAGES:
        t = stages[stage]
        for child, ckey, parent, pkey in RELATIONSHIPS:
            r = check_referential_integrity(t[child], ckey, t[parent], pkey)
            rows.append({"stage": stage, "relationship": f"{child}.{ckey} -> {parent}.{pkey}",
                         "child_table": child, "child_key": ckey, "parent_table": parent, "parent_key": pkey, **r})
            u = check_parent_key_uniqueness(t[parent], pkey)
            prow.append({"stage": stage, "relationship": f"{child}.{ckey} -> {parent}.{pkey}",
                         "parent_table": parent, "parent_key": pkey, **u})
    return pd.DataFrame(rows), pd.DataFrame(prow)


# ---------------------------------------------------------------------------
# Value helpers: invalid and nonfinite numbers are never silently compared
# ---------------------------------------------------------------------------
def num(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(values, assessable). assessable = nonblank, matches the numeric pattern, and is finite.
    'inf', 'nan', '9.28%' and '1e400' are all NOT assessable; their value is NaN."""
    ok = s.str.match(RE_FLOAT)
    v = pd.to_numeric(s.where(ok), errors="coerce")
    finite = pd.Series(np.isfinite(v.to_numpy(dtype=float, na_value=np.nan)), index=s.index)
    return v.where(finite), ok & finite


def type_valid(s: pd.Series, kind: str) -> pd.Series:
    """Type validity for one column. The reviewed parser (01_profile.parses_as) decides the FORMAT:
    strict integer text for 'int' ('45.0' fails), numeric text for 'float', ISO dates, True/False.
    Numeric kinds must ALSO convert to a finite number, so '1e400' or a 400-digit integer is not valid."""
    ok = parses_as(s, kind)
    if kind in ("int", "float"):
        ok &= num(s)[1]
    return ok


def date_val(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    ok = parses_as(s, "date")
    return pd.to_datetime(s.where(ok), format="%Y-%m-%d", errors="coerce"), ok


def structural_na(table: str, df: pd.DataFrame) -> dict[str, pd.Series]:
    """Cells that are NOT APPLICABLE by design (decision log Issue 15), per column."""
    out = {}
    for col, cond, values in SCHEMA[table].get("conditional_blank", []):
        out[col] = df[cond].isin(values)
    return out


# ---------------------------------------------------------------------------
# 2. Single-table rules (hard, inferred conventions, plausibility)
# ---------------------------------------------------------------------------
class RuleBook:
    """Collects one row per rule with explicit counts:
        not_applicable  rows the rule does not apply to (e.g. structural blanks, other txn types)
        unassessable    applicable rows that cannot be judged (blank, invalid or nonfinite input)
        eligible        applicable and assessable; passed + failed = eligible
    A NaN never reaches a comparison: pass is computed only inside `eligible`."""

    def __init__(self, stage: str):
        self.stage, self.rows = stage, []

    def add(self, table, rule_id, columns, rule_class, kind, description,
            applicable: pd.Series, assessable: pd.Series, passes: pd.Series, df: pd.DataFrame,
            example_cols=None):
        applicable = applicable.fillna(False).astype(bool)
        assessable = assessable.fillna(False).astype(bool)
        eligible = applicable & assessable
        ok = eligible & passes.fillna(False).astype(bool)
        fail = eligible & ~ok
        n_e = int(eligible.sum())
        cols = [PK[table]] + [c for c in (example_cols or columns) if c in df.columns and c != PK[table]]
        ex = df.loc[fail, cols].head(3)
        self.rows.append({
            "stage": self.stage, "table": table, "rule_id": rule_id, "columns": "+".join(columns),
            "rule_class": rule_class, "kind": kind, "description": description,
            "rows": len(df), "not_applicable": int((~applicable).sum()),
            "unassessable": int((applicable & ~assessable).sum()),
            "eligible": n_e, "passed": int(ok.sum()), "failed": int(fail.sum()),
            "pass_pct": round(100 * int(ok.sum()) / n_e, 3) if n_e else None,
            "fail_examples": " | ".join(", ".join(f"{c}={r[c]}" for c in cols) for _, r in ex.iterrows()),
        })


def all_true(df):
    return pd.Series(True, index=df.index)


def rules_for_stage(stage: str, t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rb = RuleBook(stage)
    for table in TABLES:
        df, spec = t[table], SCHEMA[table]
        na = structural_na(table, df)
        applies = lambda col: ~na.get(col, pd.Series(False, index=df.index))  # noqa: E731

        # Allowed code lists (blank = unassessable; structural blank = not applicable)
        for col, allowed in spec.get("allowed", {}).items():
            cls = HARD if (table, col) in HARD_CODE_LISTS else INFERRED
            rb.add(table, f"{table}.{col}.allowed", [col], cls, "code_list",
                   f"value in {'standard' if cls == HARD else 'observed/inferred'} list of {len(allowed)} codes",
                   applies(col), ~is_blank(df[col]), df[col].isin(allowed), df)

        # Natural bounds and sign rules
        for col, (lo, hi, why) in spec.get("ranges", {}).items():
            v, ok = num(df[col])
            cls = INFERRED if (table, col) in INFERRED_SIGN_RULES else HARD
            kind = "sign" if (table, col) in INFERRED_SIGN_RULES or (lo in (0, 0.01, 0.0001) and hi is None) else "bound"
            passes = pd.Series(True, index=df.index)
            if lo is not None:
                passes &= v >= lo
            if hi is not None:
                passes &= v <= hi
            rb.add(table, f"{table}.{col}.range", [col], cls, kind, f"[{lo}, {hi}]: {why}",
                   applies(col), ok, passes, df)

        # Date bounds
        for col, (lo, hi, _) in spec.get("date_ranges", {}).items():
            d, ok = date_val(df[col])
            passes = pd.Series(True, index=df.index)
            if lo:
                passes &= d >= pd.Timestamp(lo)
            if hi:
                passes &= d <= pd.Timestamp(hi)
            rb.add(table, f"{table}.{col}.date_range", [col], HARD, "bound",
                   f"date within [{lo}, {hi}] (extract coverage)", applies(col), ok, passes, df)

        # Patterns
        for col, (pattern, _) in spec.get("patterns", {}).items():
            rb.add(table, f"{table}.{col}.pattern", [col], HARD, "pattern", f"matches {pattern}",
                   applies(col), ~is_blank(df[col]), df[col].str.match(pattern), df)

        # Structural (conditional) blanks: blank exactly when the condition says not applicable
        for col, cond, values in spec.get("conditional_blank", []):
            rb.add(table, f"{table}.{col}.conditional_blank", [col, cond], INFERRED, "structural",
                   f"{col} blank if and only if {cond} in {sorted(values)}",
                   all_true(df), ~is_blank(df[cond]), is_blank(df[col]) == df[cond].isin(values), df)

        # Plausibility bands (warnings only; never part of % rule pass)
        for col, (lo, hi, why) in spec.get("plausible", {}).items():
            v, ok = num(df[col])
            passes = pd.Series(True, index=df.index)
            if lo is not None:
                passes &= v >= lo
            if hi is not None:
                passes &= v <= hi
            rb.add(table, f"{table}.{col}.plausible", [col], PLAUSIBILITY, "band",
                   f"[{lo}, {hi}] assumption: {why}", applies(col), ok, passes, df)
        for col, (lo, hi) in spec.get("plausible_dates", {}).items():
            d, ok = date_val(df[col])
            passes = pd.Series(True, index=df.index)
            if lo:
                passes &= d >= pd.Timestamp(lo)
            if hi:
                passes &= d <= pd.Timestamp(hi)
            rb.add(table, f"{table}.{col}.plausible_date", [col], PLAUSIBILITY, "band",
                   f"date within [{lo}, {hi}] assumption", applies(col), ok, passes, df)

    table_specific_rules(rb, t)
    return pd.DataFrame(rb.rows)


def table_specific_rules(rb: RuleBook, t: dict[str, pd.DataFrame]) -> None:
    # dim_date: derived calendar attributes must agree with the date (definitional, hard)
    d = t["dim_date"]
    dt, ok = date_val(d["date"])
    derived = {
        "year": dt.dt.year, "quarter": dt.dt.quarter, "month": dt.dt.month,
        "week_of_year": dt.dt.isocalendar().week, "is_month_end": dt.dt.is_month_end,
        "is_quarter_end": dt.dt.is_quarter_end, "is_year_end": dt.dt.is_year_end,
    }
    for col, exp in derived.items():
        exp_txt = exp.astype("Int64").astype(str)        # numbers and booleans as '2020', '1', '0'
        rb.add("dim_date", f"dim_date.{col}.derived", [col, "date"], HARD, "derived",
               f"{col} agrees with date" + (" (ISO week)" if col == "week_of_year" else ""),
               all_true(d), ok, d[col] == exp_txt, d)
    for col, exp in {"month_name": dt.dt.month_name(), "day_of_week": dt.dt.day_name()}.items():
        rb.add("dim_date", f"dim_date.{col}.derived", [col, "date"], HARD, "derived", f"{col} agrees with date",
               all_true(d), ok, d[col] == exp, d)
    weekend = dt.dt.day_of_week >= 5
    # An invalid date cannot be classed as weekday or weekend, so it is applicable but unassessable,
    # not silently "not applicable".
    rb.add("dim_date", "dim_date.is_trading_day.weekend", ["is_trading_day", "date"], HARD, "derived",
           "weekend days are non-trading days", weekend | ~ok, ok, d["is_trading_day"] == "0", d)

    # fact_portfolio_snapshot: year/month agree with snapshot_date (hard); alpha identity (within-table)
    p = t["fact_portfolio_snapshot"]
    sd, ok = date_val(p["snapshot_date"])
    rb.add("fact_portfolio_snapshot", "snapshot.year_month.derived", ["year", "month", "snapshot_date"], HARD,
           "derived", "year and month agree with snapshot_date", all_true(p), ok,
           (p["year"] == sd.dt.year.astype("Int64").astype(str)) & (p["month"] == sd.dt.month.astype("Int64").astype(str)), p)
    rb.add("fact_portfolio_snapshot", "snapshot.date_first_of_month", ["snapshot_date"], INFERRED, "structural",
           "monthly snapshot dated on the 1st", all_true(p), ok, sd.dt.day == 1, p)
    r, r_ok = num(p["return_ytd"])
    b, b_ok = num(p["benchmark_return_ytd"])
    a, a_ok = num(p["active_alpha_ytd"])
    rb.add("fact_portfolio_snapshot", "snapshot.alpha_identity", ["return_ytd", "benchmark_return_ytd",
                                                                   "active_alpha_ytd"],
           INFERRED, "within_table_reconciliation",
           f"active_alpha_ytd = return_ytd - benchmark_return_ytd within {TOL_RATE} (raw '%' text is not "
           "reinterpreted, so it is unassessable)", all_true(p), r_ok & b_ok & a_ok, (r - b - a).abs() <= TOL_RATE, p)

    # fact_fees: monthly fee formula (within-table) and date convention
    f = t["fact_fees"]
    ab, ab_ok = num(f["aum_basis"])
    bp, bp_ok = num(f["bps_charged"])
    am, am_ok = num(f["amount"])
    rb.add("fact_fees", "fees.amount_formula", ["aum_basis", "bps_charged", "amount"], INFERRED,
           "within_table_reconciliation", "amount = aum_basis x bps_charged / 10000 / 12 within $0.01",
           all_true(f), ab_ok & bp_ok & am_ok, (am - ab * bp / 10_000 / 12).abs() <= TOL_MONEY_F, f)
    fd, fd_ok = date_val(f["fee_date"])
    rb.add("fact_fees", "fees.date_first_of_month", ["fee_date"], INFERRED, "structural",
           "monthly fee dated on the 1st", all_true(f), fd_ok, fd.dt.day == 1, f)

    # fact_transactions: amount = shares x price for traded types (within-table, inferred sign convention)
    x = t["fact_transactions"]
    sh, sh_ok = num(x["shares"])
    pr, pr_ok = num(x["price"])
    amt, amt_ok = num(x["amount"])
    for ty in sorted(TRADED_TYPES):
        rb.add("fact_transactions", f"txn.{ty.lower()}_amount", ["shares", "price", "amount"], INFERRED,
               "within_table_reconciliation", f"{ty}: amount = shares x price within $0.01",
               x["txn_type"] == ty, sh_ok & pr_ok & amt_ok, (amt - sh * pr).abs() <= TOL_MONEY_F, x,
               ["txn_type", "shares", "price", "amount"])

    # Primary key uniqueness is a scorecard metric (not repeated here). Business keys are rules:
    for table in TABLES:
        for bk in SCHEMA[table].get("business_keys", []):
            df = t[table]
            nb = ~df[bk].apply(is_blank).any(axis=1)
            rb.add(table, f"{table}.{'+'.join(bk)}.business_key_unique", bk, HARD, "uniqueness",
                   f"{'+'.join(bk)} is unique", all_true(df), nb, ~df.duplicated(bk, keep=False), df)


# ---------------------------------------------------------------------------
# 3. Cross-table reconciliations (join cardinality checked first)
# ---------------------------------------------------------------------------
def recon_row(stage, rid, description, **kw) -> dict:
    base = {"stage": stage, "recon_id": rid, "scope": "cross_table", "description": description,
            "left_rows": None, "right_rows": None, "left_dup_keys": None, "right_dup_keys": None,
            "cardinality": "", "matched_pairs": None, "unmatched_left": None, "unmatched_right": None,
            "excluded_left": None, "excluded_right": None, "unassessable": None,
            "passed": None, "failed": None, "pass_pct": None, "status": "", "note": ""}
    base.update(kw)
    if base["passed"] is not None and base["failed"] is not None and (base["passed"] + base["failed"]):
        # pass_pct is over ASSESSED pairs only (passed + failed); unassessable pairs are reported apart
        base["pass_pct"] = round(100 * base["passed"] / (base["passed"] + base["failed"]), 3)
    return base


def dec_gap(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(assessable, agrees). Exact decimal comparison within $0.01. A pair is assessable only when both
    values are valid finite numbers; blank or invalid values are unassessable, never agreement."""
    assess = num(a)[1] & num(b)[1]
    agree = [bool(ok) and abs(Decimal(x) - Decimal(y)) <= TOL_MONEY for ok, x, y in zip(assess, a, b)]
    return assess, pd.Series(agree, index=a.index, dtype=bool)


def valid_keys(df: pd.DataFrame, cols: list[str], kinds: list[str]) -> pd.Series:
    """Rows whose join keys are all nonblank and valid. Blank keys must never match each other."""
    ok = pd.Series(True, index=df.index)
    for col, kind in zip(cols, kinds):
        ok &= ~is_blank(df[col]) & type_valid(df[col], kind)
    return ok


def compare_text(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(assessable, agrees) for an attribute comparison. Blank on either side = unassessable, so two
    blanks never count as agreement."""
    assess = ~is_blank(a) & ~is_blank(b)
    return assess, assess & (a == b)


def reconciliations(stage: str, t: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    c, fe, ps, tx = t["dim_client"], t["fact_fees"], t["fact_portfolio_snapshot"], t["fact_transactions"]

    # R1: fee AUM basis vs snapshot AUM for the same client-month (expected one-to-one).
    # Rows with a blank or invalid client_id/date are excluded BEFORE the join (blank keys never match).
    lk, rk = ["client_id", "fee_date"], ["client_id", "snapshot_date"]
    fe_ok, ps_ok = valid_keys(fe, lk, ["int", "date"]), valid_keys(ps, rk, ["int", "date"])
    fe_k, ps_k = fe[fe_ok], ps[ps_ok]
    ldup, rdup = int(fe_k.duplicated(lk, keep=False).sum()), int(ps_k.duplicated(rk, keep=False).sum())
    desc = "fact_fees.aum_basis = fact_portfolio_snapshot.aum (client + month)"
    if ldup or rdup:
        rows.append(recon_row(stage, "R1", desc, left_rows=len(fe), right_rows=len(ps), left_dup_keys=ldup,
                              right_dup_keys=rdup, excluded_left=int((~fe_ok).sum()),
                              excluded_right=int((~ps_ok).sum()), cardinality="not one-to-one",
                              status="not evaluated", note="duplicate join keys would multiply rows"))
    else:
        j = fe_k[lk + ["aum_basis"]].merge(ps_k[rk + ["aum"]], left_on=lk, right_on=rk, how="outer",
                                           indicator=True, validate="one_to_one")
        both = j[j["_merge"] == "both"]
        assess, ok = dec_gap(both["aum_basis"], both["aum"])
        rows.append(recon_row(stage, "R1", desc, left_rows=len(fe), right_rows=len(ps), left_dup_keys=0,
                              right_dup_keys=0, excluded_left=int((~fe_ok).sum()), excluded_right=int((~ps_ok).sum()),
                              cardinality="one-to-one", matched_pairs=len(both),
                              unmatched_left=int((j["_merge"] == "left_only").sum()),
                              unmatched_right=int((j["_merge"] == "right_only").sum()),
                              unassessable=int((~assess).sum()), passed=int(ok.sum()),
                              failed=int((assess & ~ok).sum()), status="evaluated",
                              note="tolerance $0.01 (exact decimal); excluded = blank/invalid join keys; "
                                   "unassessable = blank or invalid amount on either side. unmatched_right = "
                                   "snapshot months with no fee row (decision log Issue 12), reported, not a failure"))

    # R2/R3 look up dim_client by client_id. Blank or invalid client_ids are excluded on both sides
    # before the join, so blank keys never match each other.
    c_ok = valid_keys(c, ["client_id"], ["int"])
    c_k = c[c_ok]
    cdup = int(c_k.duplicated("client_id", keep=False).sum())

    def attribute_check(rid, desc, df, left_col, right_col):
        d_ok = valid_keys(df, ["client_id"], ["int"])
        base = dict(left_rows=len(df), right_rows=len(c), excluded_left=int((~d_ok).sum()),
                    excluded_right=int((~c_ok).sum()))
        if cdup:
            return recon_row(stage, rid, desc, right_dup_keys=cdup, cardinality="not many-to-one",
                             status="not evaluated", note="duplicate client_id in dim_client", **base)
        right = c_k[["client_id", right_col]].rename(columns={right_col: "_dim_value"})
        m = df.loc[d_ok, ["client_id", left_col]].merge(right, on="client_id", how="left", indicator=True,
                                                         validate="many_to_one")
        assert len(m) == int(d_ok.sum()), "join multiplied rows"
        hit = m["_merge"] == "both"
        assess, ok = compare_text(m.loc[hit, left_col], m.loc[hit, "_dim_value"])
        return recon_row(stage, rid, desc, right_dup_keys=0, cardinality="many-to-one",
                         matched_pairs=int(hit.sum()), unmatched_left=int((~hit).sum()),
                         unassessable=int((~assess).sum()), passed=int(ok.sum()), failed=int((assess & ~ok).sum()),
                         status="evaluated",
                         note="excluded = blank/invalid client_id; unmatched_left = client not in dim_client "
                              "(see RI results); unassessable = value blank on either side (two blanks are "
                              "not agreement)", **base)

    # R2: advisor on each fact row = client's advisor (many-to-one into dim_client)
    for rid, name, df in (("R2a", "fact_fees", fe), ("R2b", "fact_portfolio_snapshot", ps),
                          ("R2c", "fact_transactions", tx)):
        rows.append(attribute_check(rid, f"{name}.advisor_id = dim_client.advisor_id (via client_id)", df,
                                    "advisor_id", "advisor_id"))
    # R3: snapshot account_type = client's primary_account_type (many-to-one)
    rows.append(attribute_check("R3", "fact_portfolio_snapshot.account_type = dim_client.primary_account_type",
                                ps, "account_type", "primary_account_type"))

    # R4: Advisory Fee transactions vs billed fees, by client-month. KNOWN UNRESOLVED (Issue 13):
    # reported for transparency only; the two measures are never combined or forced to agree.
    #  - rows with a blank/invalid client_id or date are excluded before grouping (counted)
    #  - a client-month containing ANY invalid amount is unassessable as a whole; its partial total is
    #    never compared
    #  - sums use exact decimals (a float comparison can misjudge a difference of exactly $0.01)
    def month_totals(df, date_col):
        key_ok = valid_keys(df, ["client_id", date_col], ["int", "date"])
        g = df[key_ok].assign(ym=df.loc[key_ok, date_col].str[:7], amt_ok=num(df.loc[key_ok, "amount"])[1])
        grp = g.groupby(["client_id", "ym"])
        complete = grp["amt_ok"].all()
        total = grp["amount"].agg(lambda s: sum((Decimal(v) for v in s), Decimal("0"))
                                  if num(s)[1].all() else None)
        return pd.DataFrame({"complete": complete, "total": total}), int((~key_ok).sum())

    af = tx[tx["txn_type"] == "Advisory Fee"]
    a_g, a_excl = month_totals(af, "txn_date")
    f_g, f_excl = month_totals(fe, "fee_date")
    k = a_g.add_suffix("_txn").join(f_g.add_suffix("_fee"), how="outer")
    both = k["complete_txn"].notna() & k["complete_fee"].notna()
    pair_ok = both & (k["complete_txn"] == True) & (k["complete_fee"] == True)  # noqa: E712
    cmp = k[pair_ok]
    agree = pd.Series([abs(x - y) <= TOL_MONEY for x, y in zip(cmp["total_txn"], cmp["total_fee"])],
                      index=cmp.index, dtype=bool)
    rows.append(recon_row(stage, "R4", "Advisory Fee transaction debits vs fact_fees billed amount (client-month)",
                          left_rows=len(af), right_rows=len(fe), cardinality="aggregated to client-month first",
                          excluded_left=a_excl, excluded_right=f_excl, matched_pairs=int(both.sum()),
                          unmatched_left=int((k["complete_txn"].notna() & k["complete_fee"].isna()).sum()),
                          unmatched_right=int((k["complete_txn"].isna() & k["complete_fee"].notna()).sum()),
                          unassessable=int((both & ~pair_ok).sum()),
                          passed=int(agree.sum()), failed=int((~agree).sum()),
                          status="known unresolved discrepancy (decision log Issue 13); not counted in any score",
                          note=(f"excluded = rows with blank/invalid client_id or date; unassessable = client-months "
                                f"where either side contains an invalid amount (txn groups "
                                f"{int((a_g['complete'] == False).sum())}, fee groups "  # noqa: E712
                                f"{int((f_g['complete'] == False).sum())}). "  # noqa: E712
                                f"Assessed client-months: txn debits total {sum(cmp['total_txn'], Decimal(0)):,.2f}, "
                                f"billed fees total {sum(cmp['total_fee'], Decimal(0)):,.2f}. Exact decimal, +/- $0.01. "
                                "Totals shown side by side only; do not add or combine the two measures. fact_fees is "
                                "the internally reconciled billed-fee measure, not verified recognized revenue")))
    return rows


# ---------------------------------------------------------------------------
# 4. IQR outliers (reference thresholds from the CLEAN stage, applied to both stages)
# ---------------------------------------------------------------------------
IQR_TARGETS = [
    # (table, value column, grouping column or None for one pooled population, why)
    ("dim_client", "initial_aum", None,
     "pooled across all clients, chosen to describe the overall client distribution of opening balances"),
    ("fact_transactions", "amount", "txn_type",
     "a dividend, a deposit and a trade are different events with different typical sizes"),
]


def group_key(df: pd.DataFrame, grp: str | None) -> pd.Series:
    return df[grp] if grp else pd.Series("(all)", index=df.index)


def iqr_thresholds(clean: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for table, col, grp, why in IQR_TARGETS:
        df = clean[table]
        v, ok = num(df[col])
        for g, s in v[ok].groupby(group_key(df, grp)[ok]):
            q1, q3 = s.quantile(0.25), s.quantile(0.75)     # pandas default: linear interpolation
            iqr = q3 - q1
            rows.append({"table": table, "column": col, "group_column": grp or "(none)", "group": g,
                         "reference_stage": "clean", "reference_n": len(s), "q1": q1, "q3": q3, "iqr": iqr,
                         "lower_fence": q1 - 1.5 * iqr, "upper_fence": q3 + 1.5 * iqr, "why_grouped": why})
    return pd.DataFrame(rows)


def iqr_flags(stages: dict, thr: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    flag_frames, counts = [], []
    for stage in STAGES:
        for table, col, grp, _ in IQR_TARGETS:
            df = stages[stage][table]
            th = thr[(thr["table"] == table) & (thr["column"] == col)].set_index("group")
            v, ok = num(df[col])
            gk = group_key(df, grp)
            lo, hi = gk.map(th["lower_fence"]), gk.map(th["upper_fence"])
            assessable = ok & lo.notna() & hi.notna()
            flag = assessable & ((v < lo) | (v > hi))
            flag_frames.append(pd.DataFrame({
                "stage": stage, "table": table, "key_column": PK[table], "key": df[PK[table]].to_numpy(),
                "column": col, "group": gk.to_numpy(), "value": df[col].to_numpy(),
                "assessable": assessable.astype(int).to_numpy(), "iqr_outlier_flag": flag.astype(int).to_numpy()}))
            for g in th.index:
                in_g = gk == g
                counts.append({"stage": stage, "table": table, "column": col, "group": g,
                               "rows_in_group": int(in_g.sum()), "assessable": int((in_g & assessable).sum()),
                               "flagged_low": int((in_g & assessable & (v < lo)).sum()),
                               "flagged_high": int((in_g & assessable & (v > hi)).sum())})
            other = ~gk.isin(th.index)
            if other.any():
                counts.append({"stage": stage, "table": table, "column": col, "group": "(no reference group)",
                               "rows_in_group": int(other.sum()), "assessable": 0, "flagged_low": 0,
                               "flagged_high": 0})
    return pd.concat(flag_frames, ignore_index=True), pd.DataFrame(counts)


# ---------------------------------------------------------------------------
# 5. Scorecard
# ---------------------------------------------------------------------------
def pct(n, d):
    return round(100 * n / d, 3) if d else None


def scorecard(stages, rules: pd.DataFrame, ri: pd.DataFrame) -> pd.DataFrame:
    rows = []
    raw_cols = {t: list(stages["raw"][t].columns) for t in TABLES}
    for stage in STAGES:
        for table in TABLES:
            df = stages[stage][table][raw_cols[table]]          # original columns only (no cleaning flags)
            types = SCHEMA[table]["types"]
            na = structural_na(table, df)

            # Completeness: applicable cells that are nonblank / applicable cells
            appl = comp = 0
            valid = typed = 0
            for col in df.columns:
                a = ~na.get(col, pd.Series(False, index=df.index))
                nb = a & ~is_blank(df[col])
                appl += int(a.sum())
                comp += int(nb.sum())
                # Type validity: applicable nonblank cells that match the expected format AND, for
                # numeric columns, convert to a finite number (strict integer text for int columns)
                typed += int(nb.sum())
                valid += int((nb & type_valid(df[col], types.get(col, "str"))).sum())

            # Key uniqueness: rows whose primary key is nonblank and occurs exactly once / rows
            k = df[PK[table]]
            uniq = int((~is_blank(k) & ~k.duplicated(keep=False)).sum())

            # Rule pass: hard + inferred-convention evaluations only
            r = rules[(rules["stage"] == stage) & (rules["table"] == table) & rules["rule_class"].isin([HARD, INFERRED])]
            r_pass, r_elig, r_unas = int(r["passed"].sum()), int(r["eligible"].sum()), int(r["unassessable"].sum())
            pl = rules[(rules["stage"] == stage) & (rules["table"] == table) & (rules["rule_class"] == PLAUSIBILITY)]

            # Referential match across this table's outgoing relationships
            out = ri[(ri["stage"] == stage) & (ri["child_table"] == table)]
            m, e = int(out["matched_keys"].sum()), int(out["eligible_keys"].sum())

            rows.append({
                "table": table, "stage": stage, "row_count": len(df),
                "pct_completeness": pct(comp, appl), "completeness_num": comp, "completeness_den": appl,
                "pct_key_uniqueness": pct(uniq, len(df)), "key_uniqueness_num": uniq, "key_uniqueness_den": len(df),
                "pct_type_validity": pct(valid, typed), "type_validity_num": valid, "type_validity_den": typed,
                "pct_rule_pass": pct(r_pass, r_elig), "rule_pass_num": r_pass, "rule_pass_den": r_elig,
                "rule_evaluations_unassessable": r_unas, "rules_counted": len(r),
                "pct_referential_match": pct(m, e) if len(out) else None,
                "referential_num": m if len(out) else None, "referential_den": e if len(out) else None,
                "outgoing_relationships": len(out),
                "plausibility_warnings": int(pl["failed"].sum()),
            })
    out = pd.DataFrame(rows)
    for col in ("referential_num", "referential_den"):   # whole numbers; N/A where no relationship
        out[col] = out[col].astype("Int64")
    return out


# ---------------------------------------------------------------------------
# 6. Definitions document
# ---------------------------------------------------------------------------
def definitions_md(thr: pd.DataFrame, rules: pd.DataFrame) -> str:
    cls_counts = rules[rules["stage"] == "clean"].groupby("rule_class").size().to_dict()
    thr_lines = [f"| {r.table}.{r.column} | {r.group} | {r.reference_n:,} | {r.q1:,.2f} | {r.q3:,.2f} | "
                 f"{r.lower_fence:,.2f} | {r.upper_fence:,.2f} |" for r in thr.itertuples()]
    return "\n".join([
        "# Validation definitions (Part D)",
        "",
        "Generated by `scripts/03_validate.py`. Both stages (raw, clean) are evaluated in one run with the "
        "same original columns and the same rule definitions. Cleaning flag columns are excluded from every "
        "metric. All figures are computed from the data.",
        "",
        "## Referential integrity: `check_referential_integrity(fact_df, fact_key, dim_df, dim_key)`",
        "",
        "- Exact text matching: `45.0` does not match `45`. Keys are compared with `isin`, so rows never multiply.",
        "- Blank (empty or whitespace-only) child keys are excluded from the match rate and reported as "
        "`null_key_rate_pct = blank child keys / child rows`.",
        "- `match_rate_pct = matched nonblank child keys / nonblank child keys`. Blank parent keys never match.",
        "- `orphan_rows = nonblank child keys - matched`; `distinct_orphan_keys` counts different orphan values.",
        "- Any rate whose denominator is 0 (empty table, all-blank keys) is N/A, not 0% or 100%.",
        "- Parent-key uniqueness is checked separately (`validation_parent_keys.csv`).",
        "- 13 relationships: 10 ID-based and 3 to `dim_date.date`; 26 evaluations (2 stages).",
        "",
        "## Scorecard metrics (`data_quality_scorecard.csv`, one row per table per stage)",
        "",
        "| Metric | Numerator | Denominator |",
        "|---|---|---|",
        "| % completeness | applicable cells that are nonblank | applicable cells (original columns); "
        "structurally not-applicable cells are excluded (sector for non-equity, expense_ratio_bps for non-ETFs, "
        "security_id/shares/price on Deposit, Withdrawal, Advisory Fee rows). Blank risk_profile counts as "
        "incomplete. The text `None` in certifications is a valid value, so it counts as complete. |",
        "| % key uniqueness | rows whose primary key is nonblank and appears exactly once | rows |",
        "| % type validity | applicable nonblank cells that match the expected format (strict integer text for "
        "integer columns, so `45.0` fails) and, for numeric columns, convert to a finite number (`1e400` fails) "
        "| applicable nonblank cells (missingness is reported by completeness, not here) |",
        "| % rule pass | passing evaluations of hard + inferred-convention rules | eligible evaluations "
        "(applicable and assessable) |",
        "| % referential match | matched nonblank keys summed over the table's outgoing relationships | "
        "nonblank keys summed over those relationships; N/A for tables with no outgoing relationship |",
        "",
        "**Key uniqueness disclosure.** The metric uses primary keys only. Probable duplicates with distinct "
        "IDs (the 25 client pairs in the raw data) do not lower it; they are covered by the decision log.",
        "",
        "## Rules (`validation_rule_results.csv`)",
        "",
        f"Rule counts per stage: {cls_counts}.",
        "",
        "- **hard**: natural bounds (age >= 0, cash_pct in [0, 1], return_ytd >= -1, price > 0, ...), calendar "
        "definitions, standard code lists (US state codes, weekday names, 0/1 flags), date coverage, patterns, "
        "business-key uniqueness.",
        "- **inferred_convention**: rules worked out from the data, not documented by Wildcat: code lists built "
        "from observed values (risk_profile, client_tier, account types, fee_type, txn_type, asset_class, "
        "region), sign rules (shares > 0, transaction amount > 0, fee amount > 0; direction comes from "
        "txn_type), conditional blanks, monthly rows on the 1st, and within-table reconciliations "
        "(amount = shares x price, fee formula, alpha identity).",
        "- **plausibility**: assumed bands (return/alpha in [-0.6, 1.0], age 18-110, ...). Reported as "
        "warnings; never part of % rule pass.",
        "- Each rule reports `not_applicable` (rule does not apply), `unassessable` (applies but the input is "
        "blank, invalid or nonfinite), and `eligible = passed + failed`. Unassessable evaluations are never "
        "counted as passes. Example: raw `9.28%` cannot be compared with -1, so it is unassessable.",
        "- Invalid numbers (`inf`, `nan`, text) are rejected before any comparison; NaN never passes.",
        "",
        "## Cross-table reconciliations (`validation_reconciliations.csv`)",
        "",
        "Rows with blank or invalid join keys are excluded before any join and counted in `excluded_left` / "
        "`excluded_right`, so blank keys never match each other. Join cardinality is then checked; duplicate "
        "join keys stop that reconciliation (status `not evaluated`). Unmatched rows are reported separately "
        "from failures. A compared value that is blank or invalid on either side makes the pair "
        "`unassessable` (two blanks are never agreement). `pass_pct = passed / (passed + failed)`.",
        "",
        "- R1: fee `aum_basis` = snapshot `aum` for the same client and month (one-to-one, exact decimal, +/- $0.01).",
        "- R2a-c: advisor on each fee, snapshot and transaction = the client's advisor in dim_client (many-to-one).",
        "- R3: snapshot `account_type` = client `primary_account_type` (many-to-one).",
        "- R4: Advisory Fee transactions vs billed fees by client-month. A client-month containing any invalid "
        "amount is unassessable as a whole (partial totals are never compared). **Known unresolved discrepancy** "
        "(decision log Issue 13), reported for transparency and excluded from every score. Totals are shown "
        "side by side and never combined.",
        "",
        "Within-table checks (shares x price, fee formula, alpha identity) are in the rule results, not here.",
        "",
        "## IQR outliers (`validation_iqr_thresholds.csv`, `validation_iqr_flags.csv`)",
        "",
        "- Fences: Q1 - 1.5 x IQR and Q3 + 1.5 x IQR, with Q1/Q3 from pandas `quantile` (linear interpolation).",
        "- Reference population: the **clean** stage, valid finite values only, computed per group. The same "
        "fences are applied to raw and clean so the comparison is like for like.",
        "- `initial_aum` uses one pooled population of all clients. Pooled thresholds were chosen to describe "
        "the overall client distribution of opening balances, so the flags show which accounts are unusually "
        "large relative to the whole client base (in practice the largest accounts): unusual, not wrong. "
        "Within-tier fences would answer a different question (unusual for its tier) and were not used.",
        "- Transaction `amount` is grouped by `txn_type`, because dividends, deposits, fees and trades are "
        "different events with different typical sizes.",
        "- A lower fence below 0 means no low-side flags are possible for that group.",
        "- **Flagged means unusual, not necessarily wrong.** Large accounts and large trades are real. Flags "
        "are written to the reports only; clean tables are not modified. These flags are separate from the "
        "fixed-band `return_outlier_flag` added in cleaning.",
        "",
        "| Column | Group | Reference n | Q1 | Q3 | Lower fence | Upper fence |",
        "|---|---|---:|---:|---:|---:|---:|",
        *thr_lines,
        "",
        "## Limitations",
        "",
        "- Raw values are judged as stored. `%` returns and `45.0` IDs are not reinterpreted at the raw stage, "
        "so they lower type validity, rule assessability and referential match there.",
        "- Remaining issues stay visible in the clean stage: blank risk profiles lower completeness, snapshot "
        "months without fees appear in R1 `unmatched_right`, and R4 stays unreconciled.",
        "- Plausibility bands and grouping choices are assumptions; changing them changes warning counts, "
        "not hard-rule pass rates.",
        "- Allowed-value lists marked inferred were built from observed values; a new legitimate code would "
        "fail them.",
        "",
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(REPORT_DIR / name, index=False, encoding="utf-8", lineterminator="\n", na_rep="N/A")


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stages = {"raw": load_stage(RAW_DIR, "raw"), "clean": load_stage(CLEAN_DIR, "clean")}
    for t in TABLES:                                          # clean = original columns + documented flags
        extra = [c for c in stages["clean"][t].columns if c not in stages["raw"][t].columns]
        missing = [c for c in stages["raw"][t].columns if c not in stages["clean"][t].columns]
        if missing or any(not c.endswith("_flag") for c in extra):
            sys.exit(f"{t}: clean columns do not match raw columns plus flags (missing={missing}, extra={extra})")

    ri, parent = ri_results(stages)
    rules = pd.concat([rules_for_stage(s, stages[s]) for s in STAGES], ignore_index=True)
    recon = pd.DataFrame([r for s in STAGES for r in reconciliations(s, stages[s])])
    thr = iqr_thresholds(stages["clean"])
    flags, flag_counts = iqr_flags(stages, thr)
    thr_out = flag_counts.merge(thr, on=["table", "column", "group"], how="left")
    sc = scorecard(stages, rules, ri)

    write_csv(sc, OUTPUTS["scorecard"])
    write_csv(ri, OUTPUTS["ri"])
    write_csv(parent, OUTPUTS["parent"])
    write_csv(rules, OUTPUTS["rules"])
    write_csv(recon, OUTPUTS["recon"])
    write_csv(thr_out, OUTPUTS["iqr_thresholds"])
    write_csv(flags, OUTPUTS["iqr_flags"])
    (REPORT_DIR / OUTPUTS["definitions"]).write_text(definitions_md(thr, rules), encoding="utf-8")

    # Concise console summary
    pd.set_option("display.width", 200)
    show = sc[["table", "stage", "row_count", "pct_completeness", "pct_key_uniqueness", "pct_type_validity",
               "pct_rule_pass", "pct_referential_match"]].copy()
    print("\nData quality scorecard (N/A = no denominator)")
    print(show.sort_values(["table", "stage"], key=lambda s: s.map({"raw": 0, "clean": 1}) if s.name == "stage" else s)
          .to_string(index=False, na_rep="N/A"))
    print("\nReferential integrity: match rate % (raw -> clean), orphan rows")
    by = {(r.stage, r.relationship): r for r in ri.itertuples()}
    fmt = lambda x: "N/A" if x is None or pd.isna(x) else f"{x:g}"  # noqa: E731
    for rel in [f"{c}.{k} -> {p}.{q}" for c, k, p, q in RELATIONSHIPS]:
        a, b = by[("raw", rel)], by[("clean", rel)]
        print(f"  {rel:<68} {fmt(a.match_rate_pct) + '%':>8} -> {fmt(b.match_rate_pct) + '%':<8} "
              f"orphans {a.orphan_rows:,} -> {b.orphan_rows:,}")
    print(f"  parent keys unique in every relationship and stage: {bool(parent['unique'].all())}")
    print("\nCross-table reconciliations")
    for r in recon.itertuples():
        f = lambda x: "-" if x is None or pd.isna(x) else f"{int(x):,}"  # noqa: E731
        print(f"  {r.stage:<5} {r.recon_id:<4} passed {f(r.passed):>7} / assessed {f(r.passed + r.failed):<7} "
              f"unassessable {f(r.unassessable):<3} unmatched L/R {f(r.unmatched_left)}/{f(r.unmatched_right):<7} "
              f"excluded L/R {f(r.excluded_left)}/{f(r.excluded_right)}  {r.status[:40]}")
    hard_fail = rules[(rules["stage"] == "clean") & rules["rule_class"].isin([HARD, INFERRED]) & (rules["failed"] > 0)]
    print(f"\nClean-stage hard/inferred rules with failures: {len(hard_fail)}")
    if len(hard_fail):
        print(hard_fail[["table", "rule_id", "failed", "eligible"]].to_string(index=False))
    print("\nIQR flags (reference = clean):")
    print(flag_counts.groupby(["stage", "table", "column"])[["flagged_low", "flagged_high"]].sum().to_string())
    print(f"\nSaved {len(OUTPUTS)} reports to {REPORT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
