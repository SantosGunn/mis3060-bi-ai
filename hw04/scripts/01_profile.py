"""
HW4 Part A: Audit / profile the raw Wildcat Capital extract.

Reads the eight raw CSVs as text (dtype=str, keep_default_na=False), never
modifies them, and writes:
    reports/profile_raw.csv     one row per table/column (generic profiler)
    reports/dq_summary_raw.csv  one row per check (ERROR / WARN / INFO / PASS)
    reports/near_dup_clients_raw.csv  per-client evidence for near-duplicate dim_client rows

Layout of this file
    1. Paths and file list
    2. Generic, table-agnostic helpers (parsers, shapes, profiler)
    3. Table-specific schema and business rules (the only hard-coded part)
    4. Check groups: column level, single table, referential, cross table
    5. Run, save, print summary

Severity
    ERROR  wrong, or will break a join or calculation
    WARN   probably wrong, investigate
    INFO   worth knowing (often legitimate structure)
    PASS   check ran and found nothing (kept so the audit shows what was verified)

Bounds
    "ranges"     hard bounds that follow from the field's definition (a count or amount
                 cannot be negative, a fraction lies in [0, 1], a month is 1-12). ERROR.
    "plausible"  business assumptions (max advisor experience, max expense ratio,
                 adult clients). Outside the band is unusual, not impossible. WARN.
    No Wildcat data dictionary was supplied, so no bound below is a *documented* constraint;
    ERROR is reserved for bounds that hold by definition.

Denominators
    pct_blank         blank cells / all rows
    parse_fail_pct    nonblank values that fail the expected type / nonblank values
    check pct         affected rows / rows the check applies to (the 'denominator' column)
"""

from __future__ import annotations

import re
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
HW_DIR = SCRIPT_DIR.parent                      # hw04/
RAW_DIR = HW_DIR / "data" / "raw"
REPORT_DIR = HW_DIR / "reports"

TABLES = [
    "dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
    "fact_fees", "fact_portfolio_snapshot", "fact_transactions",
]

MAX_EXAMPLES = 5
TOP_N = 5

# Tolerances (stated assumptions)
TOL_CURRENCY = 0.01   # stored amounts are rounded to cents, so a recompute can differ by up to $0.005
TOL_RATE = 1e-4       # returns stored to 6 dp; '%' strings to 2 dp of a percent (= 4 dp as a decimal)


def load_tables() -> dict[str, pd.DataFrame]:
    missing = [t for t in TABLES if not (RAW_DIR / f"{t}.csv").exists()]
    if missing:
        sys.exit(f"Missing raw files in {RAW_DIR}: {missing}")
    return {
        t: pd.read_csv(RAW_DIR / f"{t}.csv", dtype=str, keep_default_na=False)
        for t in TABLES
    }


# ---------------------------------------------------------------------------
# 2. Generic helpers (work on any column of any table)
# ---------------------------------------------------------------------------
NULL_TOKENS = {"none", "null", "nan", "n/a", "na", "-", "?", "missing", "nil"}

RE_INT = re.compile(r"^[+-]?\d+$")
RE_FLOAT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_INT_AS_FLOAT = re.compile(r"^[+-]?\d+\.0+$")
BOOL_TOKENS = {"True", "False"}


def is_blank(s: pd.Series) -> pd.Series:
    """Empty or whitespace-only. A literal word like 'None' is NOT blank."""
    return s.str.strip() == ""


def parses_as(s: pd.Series, kind: str) -> pd.Series:
    """True where the raw text is a valid value of `kind`. Blanks return False."""
    if kind == "int":
        return s.str.match(RE_INT)
    if kind == "float":
        return s.str.match(RE_FLOAT)
    if kind == "date":
        ok = s.str.match(RE_DATE)
        parsed = pd.to_datetime(s.where(ok), format="%Y-%m-%d", errors="coerce")
        return ok & parsed.notna()
    if kind == "bool":
        return s.isin(BOOL_TOKENS)
    if kind == "str":
        return ~is_blank(s)
    raise ValueError(kind)


def to_num(s: pd.Series) -> pd.Series:
    """Numeric conversion of values that pass the float pattern only; everything else NaN."""
    return pd.to_numeric(s.where(s.str.match(RE_FLOAT)), errors="coerce")


def to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.where(s.str.match(RE_DATE)), format="%Y-%m-%d", errors="coerce")


def value_shape(s: pd.Series) -> pd.Series:
    """Collapse each value to a pattern: letters -> A, digit runs -> 9. '45.0' -> '9.9', 'PA' -> 'A'."""
    shp = s.str.replace(r"[A-Za-z]+", "A", regex=True).str.replace(r"\d+", "9", regex=True)
    return shp.where(~is_blank(s), "<blank>")


def infer_type(s: pd.Series) -> str:
    """Fallback when a column has no schema entry: the type most nonblank values parse as
    (ties go to the narrower type, so all-integer columns stay int), provided at least half
    parse. A majority rule, not a near-unanimous one, so the minority that fails is reported
    as parse failures instead of the whole column falling back to str."""
    nb = s[~is_blank(s)]
    if nb.empty:
        return "str"
    share = {kind: parses_as(nb, kind).mean() for kind in ("bool", "int", "float", "date")}
    if nb.str.strip().str.match(r"^0\d").any():  # leading zeros = a code (e.g. ZIP); numeric would drop them
        share["int"] = share["float"] = 0.0
    best = max(share, key=share.get)            # max keeps the first (narrowest) kind on ties
    return best if share[best] >= 0.5 else "str"


def fmt_counts(vc: pd.Series, n: int = TOP_N) -> str:
    return "; ".join(f"{k!r}:{v}" for k, v in vc.head(n).items())


def profile_column(table: str, col: str, s: pd.Series, expected: str | None) -> dict:
    """Generic profile of one text column. No table knowledge in here."""
    n = len(s)
    stripped = s.str.strip()
    blank = stripped == ""
    nonblank = s[~blank]
    n_nb = len(nonblank)
    expected = expected or infer_type(s)

    ok = parses_as(nonblank, expected) if n_nb else pd.Series(dtype=bool)
    fails = nonblank[~ok] if n_nb else nonblank

    shape_s = value_shape(s)                     # computed once, reused below
    shapes = shape_s.value_counts()
    # Mixed formats: for typed columns, ignore sign so '-9.9' and '9.9' count as one format.
    if expected in ("int", "float", "date", "bool") and n_nb:
        fmt = shape_s[~blank].str.lstrip("+-").value_counts()
        mixed = len(fmt) > 1
        mixed_detail = fmt_counts(fmt) if mixed else ""
    else:
        norm = nonblank.str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
        case_variants = nonblank.nunique() - norm.nunique()
        mixed = case_variants > 0
        mixed_detail = f"{case_variants} values differ only by case/whitespace" if mixed else ""

    num = to_num(nonblank) if expected in ("int", "float") else None
    dates = to_date(nonblank) if expected == "date" else None

    return {
        "table": table,
        "column": col,
        "expected_type": expected,
        "n_rows": n,
        "n_blank": int(blank.sum()),
        "pct_blank": round(100 * blank.sum() / n, 3) if n else 0,
        "n_literal_null_tokens": int(stripped[~blank].str.lower().isin(NULL_TOKENS).sum()),
        "n_nonblank": n_nb,
        "n_distinct_nonblank": int(nonblank.nunique()),
        "pct_distinct_nonblank": round(100 * nonblank.nunique() / n_nb, 3) if n_nb else 0,
        "top_values": fmt_counts(s.value_counts()),
        "n_shapes": int(len(shapes)),
        "top_shapes": fmt_counts(shapes),
        "parse_fail_count": int(len(fails)),
        "parse_fail_pct_of_nonblank": round(100 * len(fails) / n_nb, 3) if n_nb else 0,
        "parse_fail_examples": "; ".join(map(repr, fails.drop_duplicates().head(MAX_EXAMPLES))),
        "ws_leading_trailing": int((s != stripped).sum()),
        "ws_internal_multi": int(s.str.contains(r"\s{2,}", regex=True).sum()),
        "mixed_formats": bool(mixed),
        "mixed_format_detail": mixed_detail,
        "min_len": int(nonblank.str.len().min()) if n_nb else None,
        "max_len": int(nonblank.str.len().max()) if n_nb else None,
        "numeric_min": (num.min() if num is not None and num.notna().any() else
                        (dates.min().date().isoformat() if dates is not None and dates.notna().any() else None)),
        "numeric_max": (num.max() if num is not None and num.notna().any() else
                        (dates.max().date().isoformat() if dates is not None and dates.notna().any() else None)),
    }


# ---------------------------------------------------------------------------
# 3. Table-specific schema and business rules
#    Everything in this section describes Wildcat Capital; nothing above does.
# ---------------------------------------------------------------------------
EXTRACT_START, EXTRACT_END = "2020-01-01", "2024-12-31"

US_STATE_CODES = set("""AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE
NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY""".split())

SCHEMA = {
    "dim_advisor": {
        "pk": ["advisor_id"],
        "types": {"advisor_id": "int", "first_name": "str", "last_name": "str", "region": "str",
                  "years_experience": "int", "aum_target_mm": "int", "certifications": "str"},
        "allowed": {"region": {"Northeast", "Mid-Atlantic", "Southeast", "Midwest", "West", "Southwest"}},
        "ranges": {"years_experience": (0, None, "experience cannot be negative"),
                   "aum_target_mm": (0.01, None, "a target must be positive")},
        "plausible": {"years_experience": (None, 50, "careers rarely exceed 50 years"),
                      "aum_target_mm": (1, 10_000, "assumed $1M-$10B book size")},
    },
    "dim_benchmark": {
        "pk": ["benchmark_id"],
        "types": {"benchmark_id": "int", "name": "str", "asset_class": "str", "ticker_proxy": "str"},
        "business_keys": [["ticker_proxy"], ["name"]],
    },
    "dim_client": {
        "pk": ["client_id"],
        "types": {"client_id": "int", "first_name": "str", "last_name": "str", "age": "int", "city": "str",
                  "state": "str", "zip_code": "str", "risk_profile": "str", "client_tier": "str",
                  "primary_account_type": "str", "initial_aum": "float", "client_since": "date",
                  "advisor_id": "int", "is_active": "bool"},
        "allowed": {
            "risk_profile": {"Conservative", "Moderately Conservative", "Balanced",
                             "Moderately Aggressive", "Aggressive"},
            "client_tier": {"Retail", "HNW", "UHNW"},
            "primary_account_type": {"Taxable", "IRA", "Roth IRA", "Trust", "529"},
            "state": US_STATE_CODES,
        },
        "ranges": {"age": (0, None, "age cannot be negative"),
                   "initial_aum": (0.01, None, "an opening balance must be positive")},
        "plausible": {"age": (18, 110, "assumes adult account holders; custodial/529 owners could be minors")},
        "date_ranges": {"client_since": (None, EXTRACT_END, "ERROR")},
        "plausible_dates": {"client_since": ("1950-01-01", None)},
        "patterns": {"zip_code": (r"^\d{5}(-\d{4})?$", "ERROR")},
        # Rows that agree on every one of these attributes are probably the same person
        "near_dup": {"match": ["age", "city", "state", "zip_code", "initial_aum", "client_since", "advisor_id"],
                     "compare": ["first_name", "last_name"]},
    },
    "dim_date": {
        "pk": ["date_id"],
        "types": {"date_id": "int", "date": "date", "year": "int", "quarter": "int", "month": "int",
                  "month_name": "str", "week_of_year": "int", "day_of_week": "str", "is_month_end": "int",
                  "is_quarter_end": "int", "is_year_end": "int", "is_trading_day": "int"},
        "business_keys": [["date"]],
        "allowed": {
            "is_month_end": {"0", "1"}, "is_quarter_end": {"0", "1"},
            "is_year_end": {"0", "1"}, "is_trading_day": {"0", "1"},
            "day_of_week": {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"},
        },
        "ranges": {"quarter": (1, 4, "calendar definition"), "month": (1, 12, "calendar definition"),
                   "week_of_year": (1, 53, "ISO calendar definition")},
    },
    "dim_security": {
        "pk": ["security_id"],
        "types": {"security_id": "int", "ticker": "str", "name": "str", "asset_class": "str", "sector": "str",
                  "benchmark_id": "int", "is_etf": "bool", "expense_ratio_bps": "float"},
        "business_keys": [["ticker"]],
        "allowed": {"asset_class": {"Equity", "Fixed Income", "Alternative", "Cash Equivalent"}},
        "ranges": {"expense_ratio_bps": (0, None, "a fee rate cannot be negative")},
        "plausible": {"expense_ratio_bps": (None, 300, "assumed ceiling; few funds charge over 3%")},
        # (column, condition column, values of condition where the column is EXPECTED to be blank)
        "conditional_blank": [("sector", "asset_class", {"Fixed Income", "Alternative", "Cash Equivalent"}),
                              ("expense_ratio_bps", "is_etf", {"False"})],
        "near_dup": {"match": ["name"], "compare": ["ticker"]},
    },
    "fact_fees": {
        "pk": ["fee_id"],
        "types": {"fee_id": "int", "client_id": "int", "advisor_id": "int", "fee_date": "date",
                  "fee_type": "str", "aum_basis": "float", "bps_charged": "float", "amount": "float"},
        "business_keys": [["client_id", "fee_date"]],
        "allowed": {"fee_type": {"Management", "Advisory", "Custodial", "Performance"}},
        "ranges": {"aum_basis": (0.01, None, "a fee basis must be positive"),
                   "bps_charged": (0, None, "a fee rate cannot be negative"),
                   "amount": (0.01, None, "a billed fee must be positive")},
        "plausible": {"bps_charged": (None, 300, "assumed ceiling; advisory fees above 3% are unusual")},
        "date_ranges": {"fee_date": (EXTRACT_START, EXTRACT_END, "ERROR")},
    },
    "fact_portfolio_snapshot": {
        "pk": ["snapshot_id"],
        "types": {"snapshot_id": "int", "client_id": "int", "advisor_id": "int", "benchmark_id": "int",
                  "snapshot_date": "date", "year": "int", "month": "int", "aum": "float",
                  "return_ytd": "float", "benchmark_return_ytd": "float", "active_alpha_ytd": "float",
                  "cash_pct": "float", "account_type": "str"},
        "business_keys": [["client_id", "snapshot_date"]],
        "allowed": {"account_type": {"Taxable", "IRA", "Roth IRA", "Trust", "529"}},
        "ranges": {"aum": (0.01, None, "a balance must be positive"), "cash_pct": (0, 1, "a fraction"),
                   "month": (1, 12, "calendar definition"),
                   "return_ytd": (-1, None, "a long-only portfolio cannot lose more than 100%"),
                   "benchmark_return_ytd": (-1, None, "an index cannot lose more than 100%")},
        "plausible": {"return_ytd": (-0.6, 1.0, "assumed band for a YTD return"),
                      "active_alpha_ytd": (-0.6, 1.0, "assumed band for YTD alpha")},
        "date_ranges": {"snapshot_date": (EXTRACT_START, EXTRACT_END, "ERROR")},
    },
    "fact_transactions": {
        "pk": ["txn_id"],
        "types": {"txn_id": "int", "client_id": "int", "advisor_id": "int", "security_id": "int",
                  "txn_date": "date", "txn_type": "str", "shares": "float", "price": "float", "amount": "float"},
        "allowed": {"txn_type": {"Buy", "Sell", "Dividend", "Deposit", "Withdrawal", "Advisory Fee"}},
        "ranges": {"shares": (0.0001, None, "direction is carried by txn_type, so share counts are positive"),
                   "price": (0.01, None, "a traded price must be positive"),
                   "amount": (0.01, None, "direction is carried by txn_type, so amounts are positive")},
        "date_ranges": {"txn_date": (EXTRACT_START, EXTRACT_END, "ERROR")},
        "conditional_blank": [("security_id", "txn_type", {"Deposit", "Withdrawal", "Advisory Fee"}),
                              ("shares", "txn_type", {"Deposit", "Withdrawal", "Advisory Fee"}),
                              ("price", "txn_type", {"Deposit", "Withdrawal", "Advisory Fee"})],
    },
}

# Ten ID-based relationships + three date relationships (child table, child col, parent table, parent col)
RELATIONSHIPS = [
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
    ("fact_fees", "fee_date", "dim_date", "date"),
    ("fact_portfolio_snapshot", "snapshot_date", "dim_date", "date"),
    ("fact_transactions", "txn_date", "dim_date", "date"),
]


# ---------------------------------------------------------------------------
# Finding recorder
# ---------------------------------------------------------------------------
FINDINGS: list[dict] = []


def add(severity, group, table, target, check, affected, denominator, note="", examples=""):
    """Record one check result. Zero affected rows is downgraded to PASS unless severity is INFO."""
    affected = int(affected)
    if affected == 0 and (severity in ("ERROR", "WARN") or (severity == "INFO" and not note)):
        severity = "PASS"
    FINDINGS.append({
        "severity": severity,
        "check_group": group,
        "table": table,
        "column_or_relationship": target,
        "check": check,
        "affected_rows": affected,
        "denominator": int(denominator),
        "pct_affected": round(100 * affected / denominator, 3) if denominator else 0.0,
        "examples": examples,
        "note": note,
    })


def examples_from(df: pd.DataFrame, cols: list[str], n: int = MAX_EXAMPLES) -> str:
    rows = df[cols].head(n)
    return " | ".join(", ".join(f"{c}={r[c]}" for c in cols) for _, r in rows.iterrows())


def out_of_bounds(v: pd.Series, lo, hi) -> pd.Series:
    """True where v is below lo or above hi; a None bound is open."""
    bad = pd.Series(False, index=v.index)
    if lo is not None:
        bad |= v < lo
    if hi is not None:
        bad |= v > hi
    return bad


def pk_of(table: str) -> list[str]:
    return SCHEMA.get(table, {}).get("pk", [])


def ex_cols(table: str, *cols: str) -> list[str]:
    out = list(pk_of(table))
    for c in cols:
        if c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# 4a. Column-level checks (driven by SCHEMA, generic code)
# ---------------------------------------------------------------------------
def column_checks(name: str, df: pd.DataFrame) -> None:
    spec = SCHEMA.get(name, {})
    n = len(df)
    G = "1_column"

    # Type validity: nonblank values that fail the expected type
    for col, kind in spec.get("types", {}).items():
        if col not in df.columns:
            add("ERROR", G, name, col, "expected column missing", n, n)
            continue
        s = df[col]
        nb = ~is_blank(s)
        bad = nb & ~parses_as(s, kind)
        if bad.any():
            int_as_float = bad & s.str.match(RE_INT_AS_FLOAT)
            pct_text = bad & s.str.strip().str.endswith("%")
            note = f"expected {kind}; denominator = nonblank values"
            if int_as_float.any():
                note += f"; {int(int_as_float.sum())} are integers written as floats (e.g. '45.0')"
            if pct_text.any():
                note += f"; {int(pct_text.sum())} carry a '%' suffix"
            add("ERROR", G, name, col, f"type validity ({kind})", bad.sum(), nb.sum(), note,
                examples_from(df[bad], ex_cols(name, col)))
        else:
            add("PASS", G, name, col, f"type validity ({kind})", 0, nb.sum())

        # Numeric written in scientific notation: parses, but a format inconsistency
        if kind == "float":
            sci = s.str.contains(r"[eE]", regex=True) & parses_as(s, "float")
            if sci.any():
                add("INFO", G, name, col, "scientific-notation text", sci.sum(), nb.sum(),
                    "valid numbers, but a second text format; harmless once converted to float",
                    examples_from(df[sci], ex_cols(name, col)))

        # Whitespace
        ws = s != s.str.strip()
        if ws.any():
            add("WARN", G, name, col, "leading/trailing whitespace", ws.sum(), n, "",
                examples_from(df[ws], ex_cols(name, col)))

        # Literal null words (e.g. 'None') are values, not blanks
        tok = s.str.strip().str.lower().isin(NULL_TOKENS)
        if tok.any():
            add("INFO", G, name, col, "literal null-like token", tok.sum(), n,
                f"tokens: {fmt_counts(s[tok].value_counts())}. Decide whether the word means 'missing' "
                "or is a real category (e.g. no certification)")

    # Completeness: blanks per typed column (reported, judged in decision log)
    cond_cols = {c for c, _, _ in spec.get("conditional_blank", [])}
    for col in spec.get("types", {}):
        if col in df.columns and col not in cond_cols:
            b = is_blank(df[col])
            if b.any():
                add("WARN", G, name, col, "blank values", b.sum(), n,
                    "blank with no structural reason found; investigate",
                    examples_from(df[b], ex_cols(name, col)))

    # Primary key uniqueness and nulls
    pk = spec.get("pk", [])
    if pk:
        key = df[pk].astype(str).agg("|".join, axis=1)
        dup = key.duplicated(keep=False)
        add("ERROR", G, name, "+".join(pk), "primary key unique", dup.sum(), n, "",
            examples_from(df[dup], pk))
        nullk = df[pk].apply(is_blank).any(axis=1)
        add("ERROR", G, name, "+".join(pk), "primary key not blank", nullk.sum(), n)

    # Business (natural) key uniqueness
    for bk in spec.get("business_keys", []):
        sub = df[~df[bk].apply(is_blank).any(axis=1)]
        dup = sub.duplicated(bk, keep=False)
        add("ERROR", G, name, "+".join(bk), "business key unique", dup.sum(), len(sub), "",
            examples_from(sub[dup], ex_cols(name, *bk)))

    # Allowed values (nonblank only)
    for col, allowed in spec.get("allowed", {}).items():
        s = df[col]
        nb = ~is_blank(s)
        bad = nb & ~s.isin(allowed)
        add("ERROR" if col != "state" else "WARN", G, name, col, "allowed values", bad.sum(), nb.sum(),
            (f"unexpected values: {fmt_counts(s[bad].value_counts(), 10)}"
             + ("; these look like full state names, i.e. mixed formats" if col == "state" else ""))
            if bad.any() else "",
            examples_from(df[bad], ex_cols(name, col)))

    # Hard bounds on numeric columns (hold by definition -> ERROR)
    for col, (lo, hi, basis) in spec.get("ranges", {}).items():
        v = to_num(df[col])
        valid = v.notna()
        bad = valid & out_of_bounds(v, lo, hi)
        add("ERROR", G, name, col, f"hard range [{lo}, {hi}]", bad.sum(), valid.sum(),
            f"hard bound: {basis}; denominator = values that parsed as numbers",
            examples_from(df[bad], ex_cols(name, col)))

    # Plausibility bands (business assumptions -> WARN)
    for col, (lo, hi, basis) in spec.get("plausible", {}).items():
        pct = df[col].str.endswith("%")
        v = to_num(df[col].str.rstrip("%")) / np.where(pct, 100, 1)
        valid = v.notna()
        bad = valid & out_of_bounds(v, lo, hi)
        add("WARN", G, name, col, f"plausibility [{lo}, {hi}]", bad.sum(), valid.sum(),
            f"assumption: {basis}; outside it is unusual, not impossible"
            + ("; '%' values scaled /100 for this test" if pct.any() else ""),
            examples_from(df[bad], ex_cols(name, col)))

    for col, (lo, hi, sev) in spec.get("date_ranges", {}).items():
        d = to_date(df[col])
        valid = d.notna()
        bad = valid & out_of_bounds(d, lo and pd.Timestamp(lo), hi and pd.Timestamp(hi))
        add(sev, G, name, col, f"date range [{lo}, {hi}]", bad.sum(), valid.sum(),
            f"hard bound: the extract covers {EXTRACT_START} to {EXTRACT_END}" if lo else
            f"hard bound: cannot be later than the extract end {EXTRACT_END}",
            examples_from(df[bad], ex_cols(name, col)))

    for col, (lo, hi) in spec.get("plausible_dates", {}).items():
        d = to_date(df[col])
        valid = d.notna()
        bad = valid & out_of_bounds(d, lo and pd.Timestamp(lo), hi and pd.Timestamp(hi))
        add("WARN", G, name, col, f"plausibility date [{lo}, {hi}]", bad.sum(), valid.sum(),
            "assumption: earlier dates are unusual, not impossible", examples_from(df[bad], ex_cols(name, col)))

    for col, (pattern, sev) in spec.get("patterns", {}).items():
        s = df[col]
        nb = ~is_blank(s)
        bad = nb & ~s.str.match(pattern)
        add(sev, G, name, col, f"pattern {pattern}", bad.sum(), nb.sum(), "",
            examples_from(df[bad], ex_cols(name, col)))
        lead0 = s.str.startswith("0")
        if lead0.any():
            add("INFO", G, name, col, "leading zeros present", lead0.sum(), n,
                "must stay text; numeric parsing would drop the zero and break the code")

    # Conditional blanks: blank is EXPECTED for some categories (legitimate structure)
    for col, cond, blank_when in spec.get("conditional_blank", []):
        b = is_blank(df[col])
        expected_blank = df[cond].isin(blank_when)
        add("INFO", G, name, col, f"blank by design when {cond} in {sorted(blank_when)}",
            (b & expected_blank).sum(), n, "legitimate structure: not applicable, not missing")
        miss = b & ~expected_blank
        add("ERROR", G, name, col, f"blank where {cond} requires a value", miss.sum(), (~expected_blank).sum(),
            "", examples_from(df[miss], ex_cols(name, cond, col)))
        extra = ~b & expected_blank
        add("WARN", G, name, col, f"value present where {cond} implies not applicable", extra.sum(),
            expected_blank.sum(), "", examples_from(df[extra], ex_cols(name, cond, col)))


# ---------------------------------------------------------------------------
# 4b. Single-table checks: duplicates, near-duplicates, row contradictions
# ---------------------------------------------------------------------------
def duplicate_checks(name: str, df: pd.DataFrame) -> None:
    G = "2_single_table"
    n = len(df)
    exact = df.duplicated(keep=False)
    add("ERROR", G, name, "(all columns)", "exact duplicate rows", exact.sum(), n)
    pk = pk_of(name)
    if pk:
        rest = [c for c in df.columns if c not in pk]
        d = df.duplicated(rest, keep=False)
        add("ERROR", G, name, "(all except PK)", "duplicate rows ignoring primary key", d.sum(), n, "",
            examples_from(df[d], pk))

    nd = SCHEMA.get(name, {}).get("near_dup")
    if nd:
        near_duplicates(name, df, nd["match"], nd["compare"])


def classify_difference(a: str, b: str) -> str:
    """How two values of ONE column differ. A truncation needs an actual difference and a
    nonblank shorter side, so identical values are never called truncated."""
    if a == b:
        return "identical"
    if a.strip().lower() == b.strip().lower():
        return "case/whitespace"
    short, long_ = sorted((a.strip(), b.strip()), key=len)
    if short and len(short) < len(long_) and long_.lower().startswith(short.lower()):
        return "truncated/extended"
    return "other"


def near_duplicate_groups(df: pd.DataFrame, match: list[str]) -> pd.DataFrame:
    """Rows sharing every `match` value with at least one other row, tagged with a group number."""
    grp = df[df.duplicated(match, keep=False)].copy()
    grp["_g"] = grp.groupby(match, sort=False).ngroup()
    return grp


def near_duplicates(name: str, df: pd.DataFrame, match: list[str], compare: list[str]) -> None:
    """Rows equal on every `match` column. Each `compare` column is classified on its own
    (identical / case-whitespace / truncated-extended / other); a pair's label lists only
    the columns that actually differ, e.g. 'last_name:truncated/extended'."""
    G = "2_single_table"
    pk = pk_of(name)
    grp = near_duplicate_groups(df, match)
    if grp.empty:
        add("PASS", G, name, "+".join(match), f"near-duplicates (same {'+'.join(match)})", 0, len(df))
        return
    pairs = []
    kinds: dict[str, int] = {}
    for _, g in grp.groupby("_g"):
        rows = [r for _, r in g.iterrows()]
        for a, b in combinations(rows, 2):
            diffs = {c: classify_difference(str(a[c]), str(b[c])) for c in compare}
            label = ", ".join(f"{c}:{k}" for c, k in diffs.items() if k != "identical") or "all identical"
            kinds[label] = kinds.get(label, 0) + 1
            if len(pairs) < MAX_EXAMPLES:
                va = " ".join(str(a[c]) for c in compare)
                vb = " ".join(str(b[c]) for c in compare)
                pairs.append(f"{','.join(str(a[c]) for c in pk)} '{va}' ~ {','.join(str(b[c]) for c in pk)} '{vb}'")
    # WARN when every differing column differs only by truncation or case: that pattern looks like a copy
    copy_like = sum(v for k, v in kinds.items()
                    if k == "all identical" or all(p.split(":")[1] in ("truncated/extended", "case/whitespace")
                                                   for p in k.split(", ")))
    add("WARN" if copy_like else "INFO", G, name, "+".join(match), f"near-duplicates (same {'+'.join(match)})",
        len(grp), len(df),
        f"{grp['_g'].nunique()} groups, {sum(kinds.values())} pairs; per-column differences: "
        + "; ".join(f"{k}={v}" for k, v in sorted(kinds.items())),
        " | ".join(pairs))


def row_rules(t: dict[str, pd.DataFrame]) -> None:
    """Contradictions between columns of the same row. Table-specific by nature."""
    G = "2_single_table"

    # dim_date: every derived attribute must agree with the date itself
    d = t["dim_date"]
    dt = to_date(d["date"])
    derived = {
        "year": dt.dt.year.astype("Int64").astype(str),
        "quarter": dt.dt.quarter.astype("Int64").astype(str),
        "month": dt.dt.month.astype("Int64").astype(str),
        "month_name": dt.dt.month_name(),
        "day_of_week": dt.dt.day_name(),
        "week_of_year": dt.dt.isocalendar().week.astype("Int64").astype(str),
        "is_month_end": dt.dt.is_month_end.astype(int).astype(str),
        "is_quarter_end": dt.dt.is_quarter_end.astype(int).astype(str),
        "is_year_end": dt.dt.is_year_end.astype(int).astype(str),
    }
    for col, exp in derived.items():
        bad = dt.notna() & (d[col] != exp)
        add("ERROR", G, "dim_date", col, f"{col} agrees with date", bad.sum(), dt.notna().sum(),
            "week_of_year tested as ISO week" if col == "week_of_year" else "",
            examples_from(d[bad], ["date_id", "date", col]))
    weekend = dt.dt.day_of_week >= 5
    bad = (weekend & (d["is_trading_day"] == "1")) | (~weekend & (d["is_trading_day"] == "0"))
    add("WARN", G, "dim_date", "is_trading_day", "trading day = weekday", bad.sum(), len(d),
        "differences would be market holidays", examples_from(d[bad], ["date", "day_of_week", "is_trading_day"]))
    n_off, n_wkend = int((d["is_trading_day"] == "0").sum()), int(weekend.sum())
    add("INFO", G, "dim_date", "is_trading_day", "exchange holidays modeled?", 0, len(d),
        f"{n_off} non-trading days vs {n_wkend} weekend days"
        + ("; equal, so market holidays are treated as trading days" if n_off == n_wkend else ""))
    gaps = dt.sort_values().diff().dropna() != pd.Timedelta(days=1)
    add("ERROR", G, "dim_date", "date", "calendar has no gaps", gaps.sum(), len(d) - 1)
    add("INFO", G, "dim_date", "date", "calendar coverage", 0, len(d),
        f"{dt.min().date()} to {dt.max().date()}")

    # dim_security: ETF flag vs expense ratio vs asset class
    s = t["dim_security"]
    eq_etf = (s["asset_class"] == "Equity") & (s["is_etf"] == "True")
    add("WARN", G, "dim_security", "asset_class+is_etf", "equity rows flagged as ETF", eq_etf.sum(), len(s))
    add("INFO", G, "dim_security", "name", "same issuer name on different tickers",
        s.duplicated("name", keep=False).sum(), len(s), "different tickers, so not necessarily duplicates")

    # dim_client: tier vs initial AUM. Bands are an ASSUMPTION inferred from typical wealth tiers.
    c = t["dim_client"]
    aum = to_num(c["initial_aum"])
    band = pd.cut(aum, [0, 500_000, 5_000_000, np.inf], right=False, labels=["Retail", "HNW", "UHNW"])
    bad = aum.notna() & (band.astype(str) != c["client_tier"])
    add("WARN", G, "dim_client", "client_tier+initial_aum",
        "tier consistent with initial AUM (<500k Retail, 500k-5M HNW, >=5M UHNW)", bad.sum(), aum.notna().sum(),
        "bands are an assumption; adjust if Wildcat publishes its own",
        examples_from(c[bad], ["client_id", "client_tier", "initial_aum"]))

    # fact_fees: amount = aum_basis * bps / 10,000 / 12 (monthly fee)
    f = t["fact_fees"]
    calc = to_num(f["aum_basis"]) * to_num(f["bps_charged"]) / 10_000 / 12
    amt = to_num(f["amount"])
    ok = calc.notna() & amt.notna()
    bad = ok & ((amt - calc).abs() > TOL_CURRENCY)
    add("ERROR", G, "fact_fees", "amount", "amount = aum_basis x bps / 10000 / 12", bad.sum(), ok.sum(),
        f"tolerance +/- ${TOL_CURRENCY}; max abs diff {((amt - calc).abs()[ok].max()):.4f}",
        examples_from(f[bad], ["fee_id", "aum_basis", "bps_charged", "amount"]))
    not_first = ~f["fee_date"].str.endswith("-01")
    add("WARN", G, "fact_fees", "fee_date", "monthly fee dated on the 1st", not_first.sum(), len(f))

    # fact_portfolio_snapshot
    p = t["fact_portfolio_snapshot"]
    pd_ = to_date(p["snapshot_date"])
    bad = pd_.notna() & ((pd_.dt.year.astype("Int64").astype(str) != p["year"]) |
                         (pd_.dt.month.astype("Int64").astype(str) != p["month"]))
    add("ERROR", G, "fact_portfolio_snapshot", "year+month", "year/month agree with snapshot_date",
        bad.sum(), pd_.notna().sum(), "", examples_from(p[bad], ["snapshot_id", "snapshot_date", "year", "month"]))
    not_first = ~p["snapshot_date"].str.endswith("-01")
    add("WARN", G, "fact_portfolio_snapshot", "snapshot_date", "monthly snapshot dated on the 1st",
        not_first.sum(), len(p))

    # Alpha reconciliation: active_alpha = return - benchmark_return.
    # Test '%' rows both ways to VERIFY whether the '%' text means 'divide by 100'.
    pct = p["return_ytd"].str.strip().str.endswith("%")
    r_plain = to_num(p["return_ytd"])
    r_pct = to_num(p["return_ytd"].str.strip().str.rstrip("%")) / 100
    bench = to_num(p["benchmark_return_ytd"])
    alpha = to_num(p["active_alpha_ytd"])
    plain_ok = ~pct & r_plain.notna() & bench.notna() & alpha.notna()
    bad = plain_ok & ((r_plain - bench - alpha).abs() > TOL_RATE)
    add("ERROR", G, "fact_portfolio_snapshot", "active_alpha_ytd",
        "alpha = return_ytd - benchmark_return_ytd (decimal rows)", bad.sum(), plain_ok.sum(),
        f"tolerance {TOL_RATE}", examples_from(p[bad], ["snapshot_id", "return_ytd", "benchmark_return_ytd",
                                                        "active_alpha_ytd"]))
    if pct.any():
        pk_ok = pct & r_pct.notna() & bench.notna() & alpha.notna()
        recon_div100 = pk_ok & ((r_pct - bench - alpha).abs() <= TOL_RATE)
        recon_raw = pk_ok & ((r_pct * 100 - bench - alpha).abs() <= TOL_RATE)
        add("INFO", G, "fact_portfolio_snapshot", "return_ytd",
            "'%' rows: alpha reconciles if value / 100", recon_div100.sum(), pk_ok.sum(),
            f"reconciles without /100: {int(recon_raw.sum())}. Evidence for how to convert the '%' text",
            examples_from(p[pct], ["snapshot_id", "return_ytd", "benchmark_return_ytd", "active_alpha_ytd"]))
    aum_p = to_num(p["aum"])
    floor = aum_p.notna() & (aum_p == aum_p.min())
    add("INFO", G, "fact_portfolio_snapshot", "aum", f"rows sitting exactly at minimum AUM ({aum_p.min():,.2f})",
        floor.sum(), aum_p.notna().sum(), "a repeated exact minimum can mean a system floor, not a real balance",
        examples_from(p[floor], ["snapshot_id", "client_id", "snapshot_date", "aum"]))

    # fact_transactions: sign rules and amount = shares x price
    x = t["fact_transactions"]
    sh, pr, am = to_num(x["shares"]), to_num(x["price"]), to_num(x["amount"])
    for ty in sorted(x["txn_type"].unique()):
        m = (x["txn_type"] == ty) & sh.notna() & pr.notna() & am.notna()
        if not m.any():
            continue
        bad = m & ((am - sh * pr).abs() > TOL_CURRENCY)
        abs_ok = m & ((am - (sh * pr).abs()).abs() <= TOL_CURRENCY)
        add("ERROR", G, "fact_transactions", "amount", f"{ty}: amount = shares x price", bad.sum(), m.sum(),
            f"tolerance +/- ${TOL_CURRENCY}; of the failures, {int((bad & abs_ok).sum())} reconcile "
            "if the sign of shares is ignored",
            examples_from(x[bad], ["txn_id", "txn_type", "shares", "price", "amount"]))
    neg = sh < 0
    add("ERROR", G, "fact_transactions", "shares", "negative shares", neg.sum(), sh.notna().sum(),
        f"by txn_type: {fmt_counts(x.loc[neg, 'txn_type'].value_counts())}",
        examples_from(x[neg], ["txn_id", "txn_type", "shares", "amount"]))
    # Dividend shares x price = amount says the three fields agree; it does not say WHICH shares.
    # EXPLORATORY: compare dividend shares to net shares held (prior in-extract Buys - Sells). The
    # extract has no opening holdings, transfers, reinvestment lots or corporate actions, so 'held'
    # is a partial reconstruction and the comparison cannot confirm or rule out either reading.
    sid = normalize_key(x["security_id"])
    trade = x["txn_type"].map({"Buy": 1, "Sell": -1}).fillna(0) * sh.abs().fillna(0)
    order = pd.DataFrame({"c": x["client_id"], "s": sid, "d": x["txn_date"], "id": to_num(x["txn_id"])})
    order = order[~is_blank(x["security_id"])].sort_values(["c", "s", "d", "id"])
    held = (trade[order.index].groupby([order["c"], order["s"]]).cumsum() - trade[order.index]).reindex(x.index)
    div = (x["txn_type"] == "Dividend") & sh.notna() & pr.notna() & am.notna()
    arith = div & ((am - sh * pr).abs() <= TOL_CURRENCY)
    has_pos = div & (held > 0)
    eq_pos = has_pos & ((sh.abs() / held - 1).abs() <= 0.01)
    ratio = (sh.abs() / held)[has_pos]
    add("INFO", G, "fact_transactions", "shares", "Dividend shares compared with net shares held (exploratory)",
        int(eq_pos.sum()), int(has_pos.sum()),
        f"amount = shares x price on {int(arith.sum())} of {int(div.sum())} dividends, so the fields are internally "
        "consistent, but that does not show the dividend equals the whole position: shares may be newly "
        f"reinvested shares at the reinvestment price. Exploratory: of {int(has_pos.sum())} dividends with a positive "
        f"net position from earlier in-extract Buys/Sells, {int(eq_pos.sum())} have shares within 1% of it (median "
        f"shares/held {ratio.median():.2f}); {int((div & ~has_pos).sum())} have no earlier Buy in the extract. "
        "Holdings are only partly reconstructable (no opening positions, transfers, reinvestment lots or corporate "
        "actions), so this neither confirms nor rules out either reading. Meaning of Dividend shares is unresolved; "
        "do not recompute amounts",
        examples_from(x[has_pos & ~eq_pos].assign(held_before=held.round(4)),
                      ["txn_id", "client_id", "security_id", "txn_date", "shares", "held_before"]))

    # Non-trading-day lookup: report duplicate dates instead of silently dropping them, then validate m:1
    cal = unique_lookup(t["dim_date"][["date", "is_trading_day"]], ["date"], "dim_date", G,
                        conflict_cols=["is_trading_day"])
    nontrade = x.merge(cal, left_on="txn_date", right_on="date", how="left", validate="many_to_one")
    assert len(nontrade) == len(x), "calendar merge changed the transaction row count"
    for types, sev in [({"Buy", "Sell"}, "WARN"), ({"Dividend", "Deposit", "Withdrawal", "Advisory Fee"}, "INFO")]:
        m = nontrade["txn_type"].isin(types)
        bad = m & (nontrade["is_trading_day"] == "0")
        add(sev, G, "fact_transactions", "txn_date", f"{'/'.join(sorted(types))} on non-trading day",
            bad.sum(), m.sum(), "markets are closed on weekends" if sev == "WARN" else
            "cash events can post on weekends; context only",
            examples_from(nontrade[bad], ["txn_id", "txn_type", "txn_date"]))


# ---------------------------------------------------------------------------
# 4c. Referential integrity (generic; no many-to-many risk because it uses isin, not merge)
# ---------------------------------------------------------------------------
def normalize_key(s: pd.Series) -> pd.Series:
    """Key normalization used only to DIAGNOSE format mismatches: strip spaces, '45.0' -> '45'."""
    s = s.str.strip()
    return s.where(~s.str.match(RE_INT_AS_FLOAT), s.str.replace(r"\.0+$", "", regex=True))


def check_ri(t: dict[str, pd.DataFrame], child: str, ccol: str, parent: str, pcol: str) -> dict:
    G = "3_referential"
    rel = f"{child}.{ccol} -> {parent}.{pcol}"
    c, p = t[child], t[parent]
    n = len(c)

    pkeys = p[pcol]
    pdup = pkeys.duplicated(keep=False)
    if pdup.any():
        add("ERROR", G, child, rel, "parent key unique (join would multiply rows)", pdup.sum(), len(p),
            "", examples_from(p[pdup], [pcol]))
    parent_set = set(pkeys[~is_blank(pkeys)])
    parent_norm = set(normalize_key(pkeys[~is_blank(pkeys)]))

    blank = is_blank(c[ccol])
    nb = c[~blank]
    raw_match = nb[ccol].isin(parent_set)
    norm_match = normalize_key(nb[ccol]).isin(parent_norm)
    orphans = nb[~norm_match]

    if blank.any():
        add("INFO", G, child, rel, "blank foreign key", blank.sum(), n,
            "blank FKs are excluded from the match-rate denominator; judge whether blank is allowed "
            "(see conditional-blank checks)")
    fmt_only = (~raw_match & norm_match)
    add("ERROR", G, child, rel, "key text does not match parent text (format mismatch)", fmt_only.sum(), len(nb),
        "matches only after normalization (strip / drop '.0'); a text or typed join will drop these",
        examples_from(nb[fmt_only], ex_cols(child, ccol)))
    add("ERROR", G, child, rel, "orphan foreign key (no parent even after normalization)", len(orphans), len(nb),
        f"{orphans[ccol].nunique()} distinct orphan keys; e.g. {sorted(orphans[ccol].unique().tolist())[:8]}"
        if len(orphans) else "",
        examples_from(orphans, ex_cols(child, ccol)))
    unused = set(normalize_key(pkeys)) - set(normalize_key(nb[ccol]))
    add("INFO", G, parent, rel, "parent keys never referenced by this child", len(unused), len(p),
        f"e.g. {sorted(unused, key=lambda v: (len(v), v))[:8]}" if unused else "")
    return {
        "relationship": rel,
        "raw_match_rate": round(100 * raw_match.mean(), 3) if len(nb) else None,
        "normalized_match_rate": round(100 * norm_match.mean(), 3) if len(nb) else None,
        "null_key_rate": round(100 * blank.mean(), 3),
        "orphan_rows": len(orphans),
    }


# ---------------------------------------------------------------------------
# 4d. Cross-table business rules
# ---------------------------------------------------------------------------
def unique_lookup(df: pd.DataFrame, key: list[str], label: str, group: str = "4_cross_table",
                  conflict_cols: list[str] | None = None) -> pd.DataFrame:
    """Return df de-duplicated on key so a later merge can use validate='many_to_one'.
    Always records the key-uniqueness result (PASS when unique). When duplicates exist, also
    reports how many duplicate keys disagree on `conflict_cols`, because 'first row kept' then
    changes the answer of the check that uses the lookup."""
    k = "+".join(key)
    dup = df.duplicated(key, keep=False)
    add("WARN", group, label, k, "lookup key unique (duplicates: first row kept for this check)",
        dup.sum(), len(df), f"{df.loc[dup, key].drop_duplicates().shape[0]} duplicated keys" if dup.any() else "",
        examples_from(df[dup], list(dict.fromkeys(key + (conflict_cols or [])))))
    if dup.any() and conflict_cols:
        n_conf = df[dup].groupby(key)[conflict_cols].nunique().gt(1).any(axis=1)
        add("ERROR", group, label, k, f"duplicate lookup keys disagree on {'+'.join(conflict_cols)}",
            int(n_conf.sum()), int(n_conf.size), "first-row choice affects results for these keys")
    return df.drop_duplicates(key, keep="first")


def near_dup_client_evidence(c: pd.DataFrame, fe: pd.DataFrame, ps: pd.DataFrame,
                             tx: pd.DataFrame) -> pd.DataFrame:
    """One row per near-duplicate dim_client id: its group, names, the attributes the near-dup
    match did NOT use, and how many fee / snapshot / transaction rows reference it."""
    nd = SCHEMA["dim_client"]["near_dup"]
    grp = near_duplicate_groups(c, nd["match"])
    if grp.empty:
        return pd.DataFrame()
    unmatched = [col for col in c.columns if col not in nd["match"] + nd["compare"] + pk_of("dim_client")]
    ev = grp[["_g", "client_id", *nd["compare"], *unmatched]].rename(columns={"_g": "near_dup_group"})
    ev["near_dup_group"] += 1
    ev["other_attrs_differ"] = ev.groupby("near_dup_group")[unmatched].transform("nunique").gt(1).apply(
        lambda r: "+".join(r.index[r]), axis=1)
    for label, df, dcol in [("fees", fe, "fee_date"), ("snapshots", ps, "snapshot_date"),
                            ("transactions", tx, "txn_date")]:
        refs = df[df["client_id"].isin(ev["client_id"])]
        ev[f"n_{label}"] = ev["client_id"].map(refs["client_id"].value_counts()).fillna(0).astype(int)
        span = refs.groupby("client_id")[dcol].agg(["min", "max"])
        ev[f"{label}_first"] = ev["client_id"].map(span["min"]).fillna("")
        ev[f"{label}_last"] = ev["client_id"].map(span["max"]).fillna("")
    ev["n_fact_rows"] = ev[["n_fees", "n_snapshots", "n_transactions"]].sum(axis=1)
    return ev.sort_values(["near_dup_group", "client_id"], key=lambda s: s.astype(int)).reset_index(drop=True)


def cross_table(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Cross-table rules. Returns the near-duplicate client evidence table for main() to save."""
    G = "4_cross_table"
    cl = unique_lookup(t["dim_client"][["client_id", "advisor_id", "client_since", "primary_account_type",
                                         "risk_profile", "is_active"]], ["client_id"], "dim_client")
    fe, ps, tx = t["fact_fees"], t["fact_portfolio_snapshot"], t["fact_transactions"]

    # Advisor on each fact row matches the client's advisor in dim_client
    for name, df in [("fact_fees", fe), ("fact_portfolio_snapshot", ps), ("fact_transactions", tx)]:
        m = df.merge(cl, on="client_id", how="inner", suffixes=("", "_dim"), validate="many_to_one")
        assert len(m) <= len(df), "merge multiplied rows"
        bad = m["advisor_id"] != m["advisor_id_dim"]
        add("ERROR", G, name, f"{name}.advisor_id vs dim_client.advisor_id", "fact advisor = client's advisor",
            bad.sum(), len(m), "denominator = fact rows whose client exists",
            examples_from(m[bad], ex_cols(name, "client_id", "advisor_id", "advisor_id_dim")))

    # Activity dated before the client relationship started
    for name, df, dcol, monthly in [("fact_fees", fe, "fee_date", True),
                                    ("fact_portfolio_snapshot", ps, "snapshot_date", True),
                                    ("fact_transactions", tx, "txn_date", False)]:
        m = df.merge(cl[["client_id", "client_since"]], on="client_id", how="inner", validate="many_to_one")
        before = m[dcol] < m["client_since"]
        same_month = before & (m[dcol].str[:7] == m["client_since"].str[:7])
        add("INFO", G, name, f"{name}.{dcol} vs dim_client.client_since",
            "dated before client_since but in the same month", same_month.sum(), len(m),
            "monthly rows are stamped on the 1st, so a mid-month start legitimately precedes its first row"
            if monthly else "")
        add("WARN", G, name, f"{name}.{dcol} vs dim_client.client_since",
            "dated in a month before client_since", (before & ~same_month).sum(), len(m), "",
            examples_from(m[before & ~same_month], ex_cols(name, "client_id", dcol, "client_since")))

    # Snapshot account_type matches the client's primary account type
    m = ps.merge(cl, on="client_id", how="inner", validate="many_to_one")
    bad = m["account_type"] != m["primary_account_type"]
    add("WARN", G, "fact_portfolio_snapshot", "account_type vs dim_client.primary_account_type",
        "snapshot account type = client primary account type", bad.sum(), len(m))

    # Benchmark assignment vs risk profile: each risk profile should map to one benchmark
    mapping = m.groupby("risk_profile")["benchmark_id"].agg(lambda s: s.value_counts().to_dict())
    multi = {k: v for k, v in mapping.items() if len(v) > 1}
    add("INFO", G, "fact_portfolio_snapshot", "benchmark_id vs dim_client.risk_profile",
        "benchmark used per risk profile (blank = '')", 0, len(m),
        "; ".join(f"{k!r}->{v}" for k, v in mapping.items())
        + (f". Profiles using >1 benchmark: {list(multi)}" if multi else ". Each profile maps to one benchmark")
        + ". Blank-profile clients' benchmark is evidence about their likely profile, not proof")
    dominant = {k: max(v, key=v.get) for k, v in mapping.items() if k != ""}
    exp = m["risk_profile"].map(dominant)
    bad = exp.notna() & (m["benchmark_id"] != exp)
    add("WARN", G, "fact_portfolio_snapshot", "benchmark_id vs dim_client.risk_profile",
        "benchmark differs from the profile's usual benchmark", bad.sum(), exp.notna().sum())

    # Fees vs snapshots: same client-month should carry the same AUM (one-to-one after uniqueness check)
    f1 = unique_lookup(fe[["fee_id", "client_id", "fee_date", "aum_basis"]], ["client_id", "fee_date"], "fact_fees")
    s1 = unique_lookup(ps[["client_id", "snapshot_date", "aum"]], ["client_id", "snapshot_date"],
                       "fact_portfolio_snapshot")
    j = f1.merge(s1, left_on=["client_id", "fee_date"], right_on=["client_id", "snapshot_date"],
                 how="outer", indicator=True, validate="one_to_one")
    both = j["_merge"] == "both"
    diff = (to_num(j["aum_basis"]) - to_num(j["aum"])).abs()
    bad = both & (diff > TOL_CURRENCY)
    add("ERROR", G, "fact_fees", "fact_fees.aum_basis vs fact_portfolio_snapshot.aum",
        "fee AUM basis = snapshot AUM for same client-month", bad.sum(), both.sum(), f"tolerance ${TOL_CURRENCY}",
        examples_from(j[bad], ["fee_id", "client_id", "fee_date", "aum_basis", "aum"]))
    add("ERROR", G, "fact_fees", "fact_fees -> fact_portfolio_snapshot", "fee month has a snapshot",
        (j["_merge"] == "left_only").sum(), len(f1))
    sn = j[j["_merge"] == "right_only"]
    add("WARN", G, "fact_portfolio_snapshot", "fact_portfolio_snapshot -> fact_fees", "snapshot month has a fee row",
        len(sn), len(s1), f"{sn['client_id'].nunique()} clients affected; could be fee waivers or missing billing. "
        "Do not create fee rows to fill this", examples_from(sn, ["client_id", "snapshot_date", "aum"]))

    # Advisory Fee transactions vs fact_fees for the same client-month
    af = tx[tx["txn_type"] == "Advisory Fee"]
    af = af.assign(ym=af["txn_date"].str[:7], amt=to_num(af["amount"]))
    af_m = af.groupby(["client_id", "ym"])["amt"].sum().rename("txn_fee")
    ff = fe.assign(ym=fe["fee_date"].str[:7], amt=to_num(fe["amount"]))
    ff = ff.groupby(["client_id", "ym"])["amt"].sum().rename("fee_table")
    k = pd.concat([af_m, ff], axis=1, join="inner")
    match = (k["txn_fee"] - k["fee_table"]).abs() <= TOL_CURRENCY
    add("WARN", G, "fact_transactions", "Advisory Fee txns vs fact_fees (client-month totals)",
        "fee debits reconcile to billed fees", int((~match).sum()), len(k),
        f"{len(af_m)} client-months with fee debits, {len(k)} also in fact_fees; median ratio txn/fee "
        f"{(k['txn_fee'] / k['fee_table']).median():.2f}. If nothing reconciles, the two tables likely measure "
        "different things; do not force them to agree")

    # Gaps inside each client's monthly snapshot history
    sd = ps.assign(_d=to_date(ps["snapshot_date"])).dropna(subset=["_d"])
    g = sd.groupby("client_id")["_d"].agg(["min", "max", "count"])
    expected = (g["max"].dt.year - g["min"].dt.year) * 12 + (g["max"].dt.month - g["min"].dt.month) + 1
    gap = expected - g["count"]
    add("WARN", G, "fact_portfolio_snapshot", "client_id+snapshot_date", "missing months inside a client's history",
        int(gap[gap > 0].sum()), int(expected.sum()), f"{int((gap > 0).sum())} clients with gaps; "
        "denominator = months between each client's first and last snapshot")

    # Active flag vs whether snapshots run to the end of the extract
    last = g["max"].dt.strftime("%Y-%m-%d").rename("last_snap").reset_index()
    final = sd["_d"].max().strftime("%Y-%m-%d")
    m = cl.merge(last, on="client_id", how="inner", validate="one_to_one")
    a1 = (m["is_active"] == "False") & (m["last_snap"] == final)
    a2 = (m["is_active"] == "True") & (m["last_snap"] < final)
    add("WARN", G, "dim_client", "is_active vs last snapshot", f"inactive client still has a {final} snapshot",
        a1.sum(), (m["is_active"] == "False").sum())
    add("WARN", G, "dim_client", "is_active vs last snapshot", f"active client with no {final} snapshot",
        a2.sum(), (m["is_active"] == "True").sum(), "", examples_from(m[a2], ["client_id", "last_snap"]))
    txl = tx.merge(last, on="client_id", how="inner", validate="many_to_one")
    txl = txl.merge(cl[["client_id", "is_active"]], on="client_id", validate="many_to_one")
    late = (txl["is_active"] == "False") & (txl["txn_date"].str[:7] > txl["last_snap"].str[:7])
    add("WARN", G, "fact_transactions", "txn_date vs last snapshot (inactive clients)",
        "transaction after an inactive client's last snapshot month", late.sum(),
        (txl["is_active"] == "False").sum(), "",
        examples_from(txl[late], ["txn_id", "client_id", "txn_date", "last_snap"]))

    # Clients with no facts at all, and whether near-duplicate client rows carry facts
    used = set(fe["client_id"]) | set(ps["client_id"]) | set(tx["client_id"])
    c = t["dim_client"]
    unused = ~c["client_id"].isin(used)
    add("INFO", G, "dim_client", "dim_client vs all facts", "client has no fees, snapshots or transactions",
        unused.sum(), len(c), "", examples_from(c[unused], ["client_id", "first_name", "last_name"]))
    near_dup_evidence = near_dup_client_evidence(c, fe, ps, tx)
    if len(near_dup_evidence):
        ev = near_dup_evidence
        per_group = ev.groupby("near_dup_group")["n_fact_rows"].apply(lambda s: int((s > 0).sum()))
        add("INFO", G, "dim_client", "near-duplicate clients vs facts",
            "near-duplicate client ids that carry facts", int((ev["n_fact_rows"] > 0).sum()), len(ev),
            f"{len(per_group)} groups: {int((per_group == 1).sum())} with exactly one id carrying facts, "
            f"{int((per_group == 0).sum())} with none, {int((per_group > 1).sum())} with several. "
            f"{int(ev['other_attrs_differ'].ne('').sum())} ids sit in a group whose non-matched attributes differ. "
            "Per-client evidence in reports/near_dup_clients_raw.csv; evidence only, no quarantine decision here",
            examples_from(ev, ["near_dup_group", "client_id", "last_name", "n_fees", "n_snapshots",
                               "n_transactions"], 2 * MAX_EXAMPLES))

    # Security attributes vs transactions: only securities can have shares/price
    sec = unique_lookup(t["dim_security"][["security_id", "asset_class"]], ["security_id"], "dim_security")
    xs = tx[~is_blank(tx["security_id"])].assign(_sid=lambda d: normalize_key(d["security_id"]))
    m = xs.merge(sec, left_on="_sid", right_on="security_id", how="left", suffixes=("", "_dim"),
                 validate="many_to_one")
    divs = m[m["txn_type"] == "Dividend"]
    add("INFO", G, "fact_transactions", "Dividend vs dim_security.asset_class", "dividends by asset class",
        0, len(divs), fmt_counts(divs["asset_class"].value_counts(), 10))
    return near_dup_evidence


# ---------------------------------------------------------------------------
# 5. Run
# ---------------------------------------------------------------------------
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    t = load_tables()

    # Generic profile of every column of every table
    rows = []
    for name, df in t.items():
        types = SCHEMA.get(name, {}).get("types", {})
        for col in df.columns:
            rows.append(profile_column(name, col, df[col], types.get(col)))
        add("INFO", "0_table", name, "(table)", "row and column count", len(df), len(df),
            f"{len(df):,} rows x {df.shape[1]} columns")
    profile = pd.DataFrame(rows)

    for name, df in t.items():
        column_checks(name, df)
        duplicate_checks(name, df)
    row_rules(t)
    ri = [check_ri(t, *r) for r in RELATIONSHIPS]
    near_dup_evidence = cross_table(t)

    summary = pd.DataFrame(FINDINGS)
    order = {"ERROR": 0, "WARN": 1, "INFO": 2, "PASS": 3}
    summary = summary.sort_values(["severity", "check_group", "table"],
                                  key=lambda s: s.map(order) if s.name == "severity" else s).reset_index(drop=True)
    summary.insert(0, "finding_id", [f"F{i + 1:03d}" for i in range(len(summary))])

    profile.to_csv(REPORT_DIR / "profile_raw.csv", index=False)
    summary.to_csv(REPORT_DIR / "dq_summary_raw.csv", index=False)
    near_dup_evidence.to_csv(REPORT_DIR / "near_dup_clients_raw.csv", index=False)

    # Console summary
    pd.set_option("display.width", 200)
    pd.set_option("display.max_colwidth", 70)
    print(f"\nRead {len(t)} tables from {RAW_DIR}")
    print(pd.DataFrame({n: [len(df), df.shape[1]] for n, df in t.items()}, index=["rows", "cols"]).T)
    print("\nFindings by table and severity")
    print(pd.crosstab(summary["table"], summary["severity"]).reindex(columns=list(order), fill_value=0))
    print("\nReferential integrity (match rates over nonblank keys)")
    print(pd.DataFrame(ri).to_string(index=False))
    issues = summary[summary["severity"].isin(["ERROR", "WARN"])]
    print(f"\nERROR / WARN findings ({len(issues)})")
    print(issues[["finding_id", "severity", "table", "column_or_relationship", "check", "affected_rows",
                  "pct_affected"]].to_string(index=False))
    print(f"\nSaved {REPORT_DIR / 'profile_raw.csv'} ({len(profile)} rows)")
    print(f"Saved {REPORT_DIR / 'dq_summary_raw.csv'} ({len(summary)} rows)")
    print(f"Saved {REPORT_DIR / 'near_dup_clients_raw.csv'} ({len(near_dup_evidence)} rows)")


if __name__ == "__main__":
    main()
