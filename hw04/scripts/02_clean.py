"""
HW4 Part C: Clean the Wildcat Capital extract.

Implements decision_log.md exactly, in its order of operations:

    Step 1  dim_client         quarantine 25 probable-duplicate client IDs      (Issue 5)
    Step 2  fact_transactions  quarantine orphan-client transactions            (Issue 4)
    Step 3  dim_client         standardize full state names                     (Issue 6)
    Step 4  fact_transactions  standardize '45.0' security IDs                  (Issue 2)
    Step 5  fact_transactions  correct verified negative Buy shares + flag      (Issue 3)
    Step 6  fact_portfolio_snapshot  convert '%' return_ytd to decimals         (Issue 1)
    Step 7  several            add the remaining flag columns                   (Issues 7, 8, 9, 10)
    Step 8  all                verify, then write clean files, quarantine files,
                               audit logs and README_clean.md

Inputs   hw04/data/raw/*.csv           (read as text, never modified)
Outputs  hw04/data/clean/*.csv         (same 8 file names, same columns + 6 documented flags)
         hw04/data/clean/README_clean.md
         hw04/data/audit/cleaning_log.csv
         hw04/data/audit/value_changes.csv
         hw04/data/audit/quarantine_*.csv

Rules followed
  * Raw DataFrames are kept untouched; all edits happen on separate working copies.
  * Problem rows are found with data-based conditions. The EXPECTED counts below are
    only assertions on top of that detection, never the way rows are selected.
  * A failed precondition raises CleaningError and stops the script before anything
    is written. A failed post-condition raises AssertionError (via verify()).
  * Unchanged cells stay byte-identical text: ZIP zeros, blanks, 'None', '9.9e-05', ...
  * Every output file is rebuilt from raw and overwritten on each run, so reruns are
    deterministic and never append duplicate audit rows.
"""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths and table metadata
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
HW_DIR = SCRIPT_DIR.parent
RAW_DIR = HW_DIR / "data" / "raw"
CLEAN_DIR = HW_DIR / "data" / "clean"
AUDIT_DIR = HW_DIR / "data" / "audit"

PK = {
    "dim_advisor": "advisor_id",
    "dim_benchmark": "benchmark_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
    "fact_transactions": "txn_id",
}
TABLES = list(PK)

# The six documented flag columns, appended after the original columns in this order.
FLAG_COLUMNS = {
    "dim_client": ["risk_profile_missing_flag"],
    "fact_transactions": ["shares_sign_corrected_flag", "after_last_snapshot_flag"],
    "fact_portfolio_snapshot": ["return_outlier_flag", "aum_at_floor_flag"],
    "fact_fees": ["aum_basis_at_floor_flag"],
}

QUARANTINE_FILES = {
    "dim_client": "quarantine_dim_client_probable_duplicates.csv",
    "fact_transactions": "quarantine_fact_transactions_orphan_client.csv",
}

# Business constants from the decision log
CASH_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}        # no security/shares/price
STATE_NAME_TO_CODE = {                                         # Issue 6: explicit 7-entry map
    "Pennsylvania": "PA", "Florida": "FL", "New York": "NY", "New Jersey": "NJ",
    "California": "CA", "Illinois": "IL", "Texas": "TX",
}
US_STATE_CODES = set("""AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE
NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY""".split())
RETURN_BAND = (-0.6, 1.0)          # Issue 8: assumed plausibility band (assumption, not a rule)
AUM_FLOOR = Decimal("1000")        # Issue 9: the repeated exact minimum
TOL_MONEY = Decimal("0.01")        # amounts are stored to the cent
TOL_RATE = 1e-4                    # returns to 6 dp; '%' text to 2 dp of a percent

RE_FLOAT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
RE_INT_AS_FLOAT = re.compile(r"^\d+\.0+$")

# Expected results from decision_log.md. Used ONLY as assertions after data-based detection.
EXPECTED = {
    "raw_rows": {"dim_advisor": 25, "dim_benchmark": 8, "dim_client": 2525, "dim_date": 1827,
                 "dim_security": 500, "fact_fees": 122197, "fact_portfolio_snapshot": 129547,
                 "fact_transactions": 298772},
    "quarantined": {"dim_client": 25, "fact_transactions": 200},
    "dup_pairs": 25,
    "dup_copy_zip_lead0": 4, "dup_copy_blank_risk": 1, "dup_copy_full_state": 1,
    "orphan_rows": 200, "orphan_distinct_keys": 200,
    "orphan_by_type": {"Buy": 58, "Dividend": 38, "Sell": 35, "Deposit": 25,
                       "Advisory Fee": 24, "Withdrawal": 20},
    "orphan_cash_rows": 69, "orphan_nonblank_security": 131, "orphan_negative_buy": 1,
    "orphan_amount_total": Decimal("10888495.37"),
    "state_changes": 77,
    "security_changes": 197044,
    "share_sign_changes": 835,
    "pct_conversions": 300,
    "flag_risk_missing": 75,
    "flag_return_outlier": 2440, "outlier_return_only_band": 2157, "outlier_alpha_band": 2217,
    "outlier_both": 1934,
    "flag_aum_floor": 420, "flag_fee_aum_floor": 386,
    "flag_after_last_snapshot": 2410,
    "zip_lead0_clean": 228,
    "structural_blanks_clean": 101528,
    "dividends_clean": 53826,
    "weekend_buy_sell_clean": (40630, 143218), "weekend_cash_clean": (44316, 155354),
    "certifications_none": 6,
    "security_blank_sector": 219, "security_blank_expense": 281,
}


# ---------------------------------------------------------------------------
# Stop rules
# ---------------------------------------------------------------------------
class CleaningError(RuntimeError):
    """A repair or quarantine precondition failed. Nothing is written."""


def require(condition: bool, issue: str, check: str, found) -> None:
    """Precondition: stop with a clear message naming the issue, the check and what was found."""
    if not condition:
        raise CleaningError(f"[{issue}] precondition failed: {check}. Found: {found}")


def verify(condition: bool, issue: str, check: str, found) -> None:
    """Post-condition (works even under python -O, unlike a bare assert)."""
    if not condition:
        raise AssertionError(f"[{issue}] post-check failed: {check}. Found: {found}")


def show(label: str, before, after=None) -> None:
    if after is None:
        print(f"    {label}: {before}")
    else:
        print(f"    {label}: before={before} -> after={after}")


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
class Audit:
    def __init__(self) -> None:
        self.log: list[dict] = []
        self.changes: list[pd.DataFrame] = []
        self.flags: list[dict] = []

    def add_log(self, table: str, issue: str, action: str, rows: int, note: str = "") -> None:
        self.log.append({"table": table, "issue": issue, "action": action,
                         "rows_affected": int(rows), "note": note})

    def record_changes(self, table: str, keys: pd.Series, column: str,
                       old: pd.Series, new: pd.Series) -> None:
        self.changes.append(pd.DataFrame({
            "table": table, "key_column": PK[table], "key": keys.to_numpy(),
            "column": column, "old_value": old.to_numpy(), "new_value": new.to_numpy(),
        }))

    def change_frame(self) -> pd.DataFrame:
        cols = ["table", "key_column", "key", "column", "old_value", "new_value"]
        if not self.changes:
            return pd.DataFrame(columns=cols)
        return pd.concat(self.changes, ignore_index=True)[cols]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def blank(s: pd.Series) -> pd.Series:
    return s.str.strip() == ""


def as_float(s: pd.Series) -> pd.Series:
    """Float view of text that matches the numeric pattern; anything else is NaN."""
    return pd.to_numeric(s.where(s.str.match(RE_FLOAT)), errors="coerce")


def numeric(s: pd.Series, issue: str, label: str) -> pd.Series:
    """Float view of a column that MUST be fully numeric. Stops if any value is blank or does not
    parse, because NaN compares False and would let a range or reconciliation test pass silently."""
    v = as_float(s)
    require(v.notna().all(), issue, f"{label}: every value must be numeric",
            f"{int(v.isna().sum())} invalid, e.g. {s[v.isna()].head(3).tolist()}")
    return v


def n_outside_tol(gap: pd.Series, tol) -> int:
    """Rows that do NOT reconcile. Written as not(gap <= tol) so a NaN gap counts as a failure."""
    return int((~(gap <= tol)).sum())


def dec(x: str) -> Decimal:
    return Decimal(x.strip())


def load_raw() -> dict[str, pd.DataFrame]:
    missing = [t for t in TABLES if not (RAW_DIR / f"{t}.csv").exists()]
    if missing:
        raise CleaningError(f"Missing raw files in {RAW_DIR}: {missing}")
    return {t: pd.read_csv(RAW_DIR / f"{t}.csv", dtype=str, keep_default_na=False) for t in TABLES}


# ---------------------------------------------------------------------------
# Step 0: baseline
# ---------------------------------------------------------------------------
def step0_baseline(raw: dict[str, pd.DataFrame]) -> None:
    print("\nStep 0  Load raw files as text")
    for t, df in raw.items():
        verify(len(df) == EXPECTED["raw_rows"][t], "Step 0", f"{t} raw row count", len(df))
        require(df[PK[t]].is_unique and not blank(df[PK[t]]).any(),
                "Step 0", f"{t}.{PK[t]} must be a unique, nonblank primary key",
                f"{int(df[PK[t]].duplicated().sum())} duplicates")
        show(t, f"{len(df):,} rows x {df.shape[1]} cols")


# ---------------------------------------------------------------------------
# Step 1: probable duplicate clients (Issue 5)
# ---------------------------------------------------------------------------
def step1_duplicate_clients(raw, work, audit) -> pd.DataFrame:
    """Quarantine the fact-less copy of each probable-duplicate client pair.

    Detection (data-based): group clients on EVERY column except client_id and last_name.
    first_name is part of the grouping key, so it must be equal. Any group with more than
    one row is a candidate pair. For each pair we then require:
      (b) exactly one ID has fact rows across fees, snapshots and transactions,
      (c) last_name is nonblank, differs, and the shorter is a strict, case-sensitive
          prefix of the longer.
    The ID that owns the account history is kept, whichever spelling it has.
    Runs on raw text, before Step 3 changes any state name.
    """
    issue = "Issue 5"
    print("\nStep 1  Quarantine probable duplicate clients (Issue 5)")
    c = work["dim_client"]
    match_cols = [col for col in c.columns if col not in ("client_id", "last_name")]

    fact_ids = (set(raw["fact_fees"]["client_id"]) | set(raw["fact_portfolio_snapshot"]["client_id"])
                | set(raw["fact_transactions"]["client_id"]))

    grp = c[c.duplicated(match_cols, keep=False)]
    sizes = grp.groupby(match_cols, sort=False).size()
    require((sizes == 2).all(), issue, "every candidate group must be a pair",
            f"group sizes {sizes.value_counts().to_dict()}")

    pairs = []
    for _, g in grp.groupby(match_cols, sort=False):
        a, b = g.iloc[0], g.iloc[1]
        has = {a.client_id: a.client_id in fact_ids, b.client_id: b.client_id in fact_ids}
        require(sum(has.values()) == 1, issue, "exactly one ID per pair carries facts",
                f"pair {a.client_id}/{b.client_id}: {has}")
        keep, drop = (a, b) if has[a.client_id] else (b, a)
        ln_keep, ln_drop = keep.last_name, drop.last_name
        short, long_ = sorted([ln_keep, ln_drop], key=len)
        require(ln_keep.strip() != "" and ln_drop.strip() != "" and ln_keep != ln_drop
                and long_.startswith(short) and len(long_) > len(short),
                issue, "last_name must differ only as a strict prefix",
                f"pair {keep.client_id} '{ln_keep}' / {drop.client_id} '{ln_drop}'")
        pairs.append({"quarantine_id": drop.client_id, "retained_id": keep.client_id,
                      "kept_last_name": ln_keep, "copy_last_name": ln_drop})
    pairs = pd.DataFrame(pairs)
    verify(len(pairs) == EXPECTED["dup_pairs"], issue, "number of probable-duplicate pairs", len(pairs))

    # Overlap counts the decision log asks us to recompute
    q_rows = c[c["client_id"].isin(pairs["quarantine_id"])]
    verify(int(q_rows["zip_code"].str.startswith("0").sum()) == EXPECTED["dup_copy_zip_lead0"],
           issue, "quarantined copies with leading-zero ZIP", int(q_rows["zip_code"].str.startswith("0").sum()))
    verify(int(blank(q_rows["risk_profile"]).sum()) == EXPECTED["dup_copy_blank_risk"],
           issue, "quarantined copies with blank risk_profile", int(blank(q_rows["risk_profile"]).sum()))
    full_state = q_rows["state"].isin(STATE_NAME_TO_CODE)
    verify(int(full_state.sum()) == EXPECTED["dup_copy_full_state"],
           issue, "quarantined copies with full state name", int(full_state.sum()))

    before = len(c)
    work["dim_client"] = c[~c["client_id"].isin(pairs["quarantine_id"])].copy()
    after = len(work["dim_client"])
    show("dim_client rows", before, after)
    show("pairs found", len(pairs))
    show("examples", "; ".join(f"keep {r.retained_id} '{r.kept_last_name}', quarantine "
                               f"{r.quarantine_id} '{r.copy_last_name}'" for r in pairs.head(3).itertuples()))

    verify(after == before - len(pairs), issue, "rows removed = pairs", (before, after))
    for t in ("fact_fees", "fact_portfolio_snapshot", "fact_transactions"):
        n = int(work[t]["client_id"].isin(pairs["quarantine_id"]).sum())
        verify(n == 0, issue, f"no {t} row points at a quarantined client", n)
    still = work["dim_client"].duplicated(match_cols, keep=False).sum()
    verify(still == 0, issue, "near-duplicate check on remaining clients", int(still))

    audit.add_log("dim_client", issue, "quarantine", len(pairs),
                  "probable duplicates: all columns except client_id/last_name equal, last_name a strict "
                  "prefix variant, exactly one ID carries facts; fact-bearing ID kept with its spelling")
    return pairs


# ---------------------------------------------------------------------------
# Step 2: orphan transactions (Issue 4)
# ---------------------------------------------------------------------------
def step2_orphan_transactions(work, audit) -> pd.DataFrame:
    """Quarantine transactions whose client_id is not in the (already reduced) dim_client.
    No placeholder clients, no guessed IDs."""
    issue = "Issue 4"
    print("\nStep 2  Quarantine orphan-client transactions (Issue 4)")
    tx = work["fact_transactions"]
    client_ids = set(work["dim_client"]["client_id"])
    orphan = ~tx["client_id"].isin(client_ids)
    o = tx[orphan]

    require(len(o) == EXPECTED["orphan_rows"], issue, "orphan rows against reduced dim_client", len(o))
    require(o["client_id"].nunique() == EXPECTED["orphan_distinct_keys"], issue,
            "distinct orphan client IDs", o["client_id"].nunique())

    by_type = o["txn_type"].value_counts().to_dict()
    verify(by_type == EXPECTED["orphan_by_type"], issue, "orphans by txn_type", by_type)
    n_cash = int(o["txn_type"].isin(CASH_TYPES).sum())
    n_sec = int((~blank(o["security_id"])).sum())
    n_neg = int(((o["txn_type"] == "Buy") & (as_float(o["shares"]) < 0)).sum())
    verify(n_cash == EXPECTED["orphan_cash_rows"], issue, "orphan cash-type rows", n_cash)
    verify(n_sec == EXPECTED["orphan_nonblank_security"], issue, "orphan rows with security_id", n_sec)
    verify(n_neg == EXPECTED["orphan_negative_buy"], issue, "orphan negative-share Buys", n_neg)
    total = sum((dec(v) for v in o["amount"]), Decimal("0"))
    verify(total == EXPECTED["orphan_amount_total"], issue, "quarantined amount total (exact decimal)", total)

    before = len(tx)
    work["fact_transactions"] = tx[~orphan].copy()
    after = len(work["fact_transactions"])
    show("fact_transactions rows", before, after)
    show("orphans by type", by_type)
    show("quarantined amount total", f"{total:,.2f}")

    verify(work["fact_transactions"]["client_id"].isin(client_ids).all(), issue,
           "client match rate = 100% on clean transactions", "unmatched remain")
    audit.add_log("fact_transactions", issue, "quarantine", len(o),
                  f"client_id not in dim_client; {o['client_id'].nunique()} distinct keys; "
                  f"{n_cash} cash-type, {n_sec} with security_id, {n_neg} negative-share Buy; "
                  f"amount total {total:.2f}")
    return o[["txn_id"]].copy()


# ---------------------------------------------------------------------------
# Step 3: state names (Issue 6)
# ---------------------------------------------------------------------------
def step3_states(work, audit) -> None:
    issue = "Issue 6"
    print("\nStep 3  Standardize full state names (Issue 6)")
    c = work["dim_client"]
    not_code = ~c["state"].isin(US_STATE_CODES)
    unmapped = sorted(set(c.loc[not_code, "state"]) - set(STATE_NAME_TO_CODE))
    require(not unmapped, issue, "every non-code state must be in the 7-entry mapping", unmapped)
    require(int(not_code.sum()) == EXPECTED["state_changes"], issue, "rows to standardize", int(not_code.sum()))

    old = c.loc[not_code, "state"]
    new = old.map(STATE_NAME_TO_CODE)
    c.loc[not_code, "state"] = new
    audit.record_changes("dim_client", c.loc[not_code, "client_id"], "state", old, new)

    after_bad = int((~c["state"].isin(US_STATE_CODES)).sum())
    show("non-code states", int(not_code.sum()), after_bad)
    show("by value", old.value_counts().to_dict())
    verify(after_bad == 0, issue, "allowed-values check returns 0", after_bad)
    audit.add_log("dim_client", issue, "standardize", int(not_code.sum()),
                  "full state name -> 2-letter code (format only; state correctness not verified)")


# ---------------------------------------------------------------------------
# Step 4: security IDs (Issue 2)
# ---------------------------------------------------------------------------
def step4_security_ids(work, audit) -> None:
    issue = "Issue 2"
    print("\nStep 4  Standardize '45.0' security IDs (Issue 2)")
    tx = work["fact_transactions"]
    nb = ~blank(tx["security_id"])
    bad_shape = nb & ~tx["security_id"].str.match(RE_INT_AS_FLOAT)
    require(not bad_shape.any(), issue, "every nonblank security_id must match ^\\d+\\.0+$",
            tx.loc[bad_shape, "security_id"].head(5).tolist())
    require(int(nb.sum()) == EXPECTED["security_changes"], issue, "nonblank security IDs to standardize",
            int(nb.sum()))
    blanks_before = int((~nb).sum())

    old = tx.loc[nb, "security_id"]
    new = old.str.replace(r"\.0+$", "", regex=True)
    tx.loc[nb, "security_id"] = new
    audit.record_changes("fact_transactions", tx.loc[nb, "txn_id"], "security_id", old, new)

    sec_ids = set(work["dim_security"]["security_id"])
    nb_after = ~blank(tx["security_id"])
    match = tx.loc[nb_after, "security_id"].isin(sec_ids).mean()
    show("raw-text match to dim_security", "0.0%" if len(old) else "n/a", f"{100 * match:.3f}%")
    show("blanks", blanks_before, int((~nb_after).sum()))
    verify(match == 1.0, issue, "100% text match to dim_security", match)
    verify(int((~nb_after).sum()) == EXPECTED["structural_blanks_clean"], issue, "blank security_id kept",
           int((~nb_after).sum()))
    audit.add_log("fact_transactions", issue, "standardize", int(nb.sum()),
                  "dropped '.0' from integer security IDs; blanks left blank")


# ---------------------------------------------------------------------------
# Step 5: negative Buy shares (Issue 3)
# ---------------------------------------------------------------------------
def buy_reconciles(shares: str, price: str, amount: str, use_abs: bool) -> bool:
    s = dec(shares)
    s = abs(s) if use_abs else s
    return abs(s * dec(price) - dec(amount)) <= TOL_MONEY


def step5_negative_buys(work, audit) -> None:
    """Inferred sign convention (not documented by Wildcat): share counts are positive and
    direction comes from txn_type. Flip the sign only on Buys where |shares| x price
    reconciles to the stored amount within $0.01."""
    issue = "Issue 3"
    print("\nStep 5  Correct verified negative Buy shares (Issue 3)")
    tx = work["fact_transactions"]
    traded = ~tx["txn_type"].isin(CASH_TYPES)
    numeric(tx.loc[traded, "shares"], issue, "shares on Buy/Sell/Dividend rows")
    numeric(tx.loc[traded, "price"], issue, "price on Buy/Sell/Dividend rows")
    numeric(tx["amount"], issue, "amount on all rows")
    sh = as_float(tx["shares"])
    neg = sh < 0
    require(set(tx.loc[neg, "txn_type"]) <= {"Buy"}, issue, "negative shares only on Buy rows",
            tx.loc[neg, "txn_type"].value_counts().to_dict())
    cand = neg & (tx["txn_type"] == "Buy")
    require(int(cand.sum()) == EXPECTED["share_sign_changes"], issue, "negative-share Buys in clean rows",
            int(cand.sum()))
    ok = [buy_reconciles(s, p, a, use_abs=True)
          for s, p, a in zip(tx.loc[cand, "shares"], tx.loc[cand, "price"], tx.loc[cand, "amount"])]
    require(all(ok), issue, "every negative Buy must satisfy |shares| x price = amount (+/- $0.01)",
            f"{ok.count(False)} fail")

    price_before, amount_before = tx["price"].copy(), tx["amount"].copy()
    old = tx.loc[cand, "shares"]
    new = old.str.replace(r"^-", "", regex=True)         # text edit: only the sign changes
    tx.loc[cand, "shares"] = new
    audit.record_changes("fact_transactions", tx.loc[cand, "txn_id"], "shares", old, new)
    tx["shares_sign_corrected_flag"] = np.where(cand, "1", "0")

    sh_after = as_float(tx.loc[traded, "shares"])
    verify(sh_after.notna().all(), issue, "shares still numeric on all traded rows", int(sh_after.isna().sum()))
    n_neg_after = int((sh_after < 0).sum())
    buys = tx["txn_type"] == "Buy"
    fails = sum(not buy_reconciles(s, p, a, use_abs=False)
                for s, p, a in zip(tx.loc[buys, "shares"], tx.loc[buys, "price"], tx.loc[buys, "amount"]))
    show("negative shares", int(neg.sum()), n_neg_after)
    show("Buy amount-rule failures", int(cand.sum()), fails)
    verify((as_float(new) == -as_float(old)).all(), issue, "new value = -old value", "mismatch")
    verify(n_neg_after == 0, issue, "no negative shares remain", n_neg_after)
    verify(fails == 0, issue, "amount = shares x price on all clean Buys", fails)
    verify(tx["price"].equals(price_before) and tx["amount"].equals(amount_before), issue,
           "price and amount unchanged", "changed")
    verify(int((tx["shares_sign_corrected_flag"] == "1").sum()) == int(cand.sum()), issue,
           "flag sum = rows changed", int((tx["shares_sign_corrected_flag"] == "1").sum()))
    audit.add_log("fact_transactions", issue, "standardize", int(cand.sum()),
                  "flipped sign of negative Buy shares that reconcile to amount (inferred convention)")


# ---------------------------------------------------------------------------
# Step 6: percentage returns (Issue 1)
# ---------------------------------------------------------------------------
def alpha_gap(ret: pd.Series, bench: pd.Series, alpha: pd.Series) -> pd.Series:
    return (ret - bench - alpha).abs()


def step6_percent_returns(work, audit) -> None:
    issue = "Issue 1"
    print("\nStep 6  Convert '%' return_ytd to decimals (Issue 1)")
    p = work["fact_portfolio_snapshot"]
    pct = p["return_ytd"].str.strip().str.endswith("%")
    num_text = p.loc[pct, "return_ytd"].str.strip().str[:-1]
    require(num_text.str.match(RE_FLOAT).all(), issue, "'%' values must be numeric before the sign",
            num_text[~num_text.str.match(RE_FLOAT)].head(5).tolist())
    require(int(pct.sum()) == EXPECTED["pct_conversions"], issue, "'%' values found", int(pct.sum()))

    bench = numeric(p["benchmark_return_ytd"], issue, "benchmark_return_ytd")
    alpha = numeric(p["active_alpha_ytd"], issue, "active_alpha_ytd")
    numeric(p.loc[~pct, "return_ytd"], issue, "return_ytd (non-'%' rows)")
    gap_div = alpha_gap(as_float(num_text) / 100, bench[pct], alpha[pct])
    gap_raw = alpha_gap(as_float(num_text), bench[pct], alpha[pct])
    require(n_outside_tol(gap_div, TOL_RATE) == 0, issue, "every '%' row reconciles to alpha when divided by 100",
            f"{n_outside_tol(gap_div, TOL_RATE)} fail")
    show("'%' rows reconciling without /100 (evidence)", int((gap_raw <= TOL_RATE).sum()))

    old = p.loc[pct, "return_ytd"]
    # Decimal division keeps the exact digits: '9.28%' -> '0.0928', '-3.18%' -> '-0.0318'
    new = num_text.map(lambda x: format(Decimal(x) / Decimal(100), "f"))
    p.loc[pct, "return_ytd"] = new
    audit.record_changes("fact_portfolio_snapshot", p.loc[pct, "snapshot_id"], "return_ytd", old, new)

    ret = as_float(p["return_ytd"])
    fails_type = int(ret.isna().sum())
    gap = alpha_gap(ret, bench, alpha)
    show("type-validity failures", int(pct.sum()), fails_type)
    show("examples", "; ".join(f"{a} -> {b}" for a, b in zip(old.head(3), new.head(3))))
    verify(fails_type == 0, issue, "0 type-validity failures in return_ytd", fails_type)
    verify(n_outside_tol(gap, TOL_RATE) == 0, issue, "alpha reconciliation on all rows (NaN counts as failure)",
           n_outside_tol(gap, TOL_RATE))
    verify(int((ret < -1).sum()) == 0, issue, "return_ytd >= -1", int((ret < -1).sum()))
    audit.add_log("fact_portfolio_snapshot", issue, "convert", int(pct.sum()),
                  "'x%' -> x/100 as decimal text; verified against benchmark_return_ytd and active_alpha_ytd")


# ---------------------------------------------------------------------------
# Step 7: remaining flags (Issues 7, 8, 9, 10)
# ---------------------------------------------------------------------------
def step7_flags(work, audit) -> None:
    print("\nStep 7  Add flag columns (Issues 7, 8, 9, 10)")

    # Issue 7: blank risk profile stays blank; flag it. Benchmark is not proof of risk tolerance.
    c = work["dim_client"]
    m = blank(c["risk_profile"])
    c["risk_profile_missing_flag"] = np.where(m, "1", "0")
    show("risk_profile_missing_flag", int(m.sum()))
    verify(int(m.sum()) == EXPECTED["flag_risk_missing"], "Issue 7", "flag sum", int(m.sum()))
    audit.add_log("dim_client", "Issue 7", "flag", int(m.sum()),
                  "added risk_profile_missing_flag; blanks not filled")

    # Issue 8: assumed plausibility band on converted return_ytd and on active_alpha_ytd
    p = work["fact_portfolio_snapshot"]
    lo, hi = RETURN_BAND
    r = numeric(p["return_ytd"], "Issue 8", "return_ytd (after Issue 1)")
    a = numeric(p["active_alpha_ytd"], "Issue 8", "active_alpha_ytd")
    r_out, a_out = (r < lo) | (r > hi), (a < lo) | (a > hi)
    m = r_out | a_out
    p["return_outlier_flag"] = np.where(m, "1", "0")
    show("return_outlier_flag", f"{int(m.sum())} (return {int(r_out.sum())}, alpha {int(a_out.sum())}, "
                                f"both {int((r_out & a_out).sum())})")
    verify(int(r_out.sum()) == EXPECTED["outlier_return_only_band"], "Issue 8", "return outside band",
           int(r_out.sum()))
    verify(int(a_out.sum()) == EXPECTED["outlier_alpha_band"], "Issue 8", "alpha outside band", int(a_out.sum()))
    verify(int((r_out & a_out).sum()) == EXPECTED["outlier_both"], "Issue 8", "both outside band",
           int((r_out & a_out).sum()))
    verify(int(m.sum()) == EXPECTED["flag_return_outlier"], "Issue 8", "flag sum", int(m.sum()))
    audit.add_log("fact_portfolio_snapshot", "Issue 8", "flag", int(m.sum()),
                  f"added return_outlier_flag: return_ytd or active_alpha_ytd outside assumed band {RETURN_BAND}; "
                  "values unchanged, flag means investigate")

    # Issue 9: AUM exactly 1,000.00 (possible system floor; hypothesis only)
    numeric(p["aum"], "Issue 9", "snapshot aum")
    numeric(work["fact_fees"]["aum_basis"], "Issue 9", "fee aum_basis")
    m = p["aum"].map(lambda v: dec(v) == AUM_FLOOR)
    p["aum_at_floor_flag"] = np.where(m, "1", "0")
    show("aum_at_floor_flag", int(m.sum()))
    verify(int(m.sum()) == EXPECTED["flag_aum_floor"], "Issue 9", "snapshot flag sum", int(m.sum()))
    audit.add_log("fact_portfolio_snapshot", "Issue 9", "flag", int(m.sum()),
                  "added aum_at_floor_flag (aum = 1,000.00); values unchanged")

    f = work["fact_fees"]
    m = f["aum_basis"].map(lambda v: dec(v) == AUM_FLOOR)
    f["aum_basis_at_floor_flag"] = np.where(m, "1", "0")
    show("aum_basis_at_floor_flag", int(m.sum()))
    verify(int(m.sum()) == EXPECTED["flag_fee_aum_floor"], "Issue 9", "fee flag sum", int(m.sum()))
    audit.add_log("fact_fees", "Issue 9", "flag", int(m.sum()),
                  "added aum_basis_at_floor_flag (aum_basis = 1,000.00); values unchanged")

    # Issue 10: inactive client, transaction month after the client's last snapshot month
    tx = work["fact_transactions"]
    last_month = p.groupby("client_id")["snapshot_date"].max().str[:7]
    inactive = set(c.loc[c["is_active"] == "False", "client_id"])
    lm = tx["client_id"].map(last_month)
    m = tx["client_id"].isin(inactive) & lm.notna() & (tx["txn_date"].str[:7] > lm.fillna(""))
    tx["after_last_snapshot_flag"] = np.where(m, "1", "0")
    no_snap = len(inactive - set(last_month.index))
    show("after_last_snapshot_flag", int(m.sum()))
    show("inactive clients with no snapshot (cannot be evaluated)", no_snap)
    verify(int(m.sum()) == EXPECTED["flag_after_last_snapshot"], "Issue 10", "flag sum", int(m.sum()))
    audit.add_log("fact_transactions", "Issue 10", "flag", int(m.sum()),
                  "added after_last_snapshot_flag (inactive client, txn month > last snapshot month); "
                  "values unchanged")
    audit.add_log("fact_transactions", "Issue 3", "flag",
                  int((tx["shares_sign_corrected_flag"] == "1").sum()),
                  "shares_sign_corrected_flag added in Step 5; = 1 only on rows whose sign was changed")


# ---------------------------------------------------------------------------
# Step 8a: build quarantine frames from UNTOUCHED raw rows
# ---------------------------------------------------------------------------
def build_quarantine(raw, dup_pairs, orphan_keys) -> dict[str, pd.DataFrame]:
    q_client = raw["dim_client"][raw["dim_client"]["client_id"].isin(dup_pairs["quarantine_id"])].copy()
    q_client["qa_reason"] = ("probable duplicate: equal on every column except client_id/last_name; "
                             "last_name strict-prefix variant; no fact rows")
    q_client["qa_step"] = "Step 1 (Issue 5)"
    q_client["qa_retained_client_id"] = q_client["client_id"].map(
        dup_pairs.set_index("quarantine_id")["retained_id"])

    q_tx = raw["fact_transactions"][raw["fact_transactions"]["txn_id"].isin(orphan_keys["txn_id"])].copy()
    q_tx["qa_reason"] = "orphan: client_id not found in dim_client"
    q_tx["qa_step"] = "Step 2 (Issue 4)"
    return {"dim_client": q_client, "fact_transactions": q_tx}


# ---------------------------------------------------------------------------
# Step 8b: whole-dataset verification (before anything is written)
# ---------------------------------------------------------------------------
def verify_everything(raw, work, quarantine, changes: pd.DataFrame) -> None:
    print("\nStep 8  Verify raw = clean + quarantined, cell-level changes, retained structure")
    for t in TABLES:
        r, c = raw[t], work[t]
        q = quarantine.get(t, r.iloc[0:0])
        pk = PK[t]
        # Columns: original columns in original order, then only the documented flags
        verify(list(c.columns) == list(r.columns) + FLAG_COLUMNS.get(t, []), t, "clean column order",
               list(c.columns))
        verify(list(q.columns[:r.shape[1]]) == list(r.columns), t, "quarantine keeps raw columns", list(q.columns))
        # Row counts and key sets
        verify(len(r) == len(c) + len(q), t, "raw rows = clean + quarantined", (len(r), len(c), len(q)))
        verify(len(q) == EXPECTED["quarantined"].get(t, 0), t, "quarantined rows", len(q))
        ck, qk, rk = set(c[pk]), set(q[pk]), set(r[pk])
        verify(ck.isdisjoint(qk) and (ck | qk) == rk and c[pk].is_unique, t,
               "clean and quarantine keys disjoint and together equal raw keys", (len(ck), len(qk), len(rk)))
        # Quarantined rows are byte-identical raw text
        if len(q):
            rq = r.set_index(pk).loc[q[pk], [col for col in r.columns if col != pk]]
            qq = q.set_index(pk)[rq.columns]
            verify(rq.equals(qq), t, "quarantine cells equal raw text", "differs")
        # Flags are 0/1 text only
        for fcol in FLAG_COLUMNS.get(t, []):
            verify(set(c[fcol]) <= {"0", "1"}, t, f"{fcol} is 0/1", set(c[fcol]))

        # Cell-level diff of original columns vs raw, matched by primary key
        rr = r.set_index(pk).loc[c[pk]]
        cc = c.set_index(pk)[rr.columns]
        diffs = []
        for col in rr.columns:
            m = rr[col].to_numpy() != cc[col].to_numpy()
            if m.any():
                diffs.append(pd.DataFrame({"key": rr.index[m], "column": col,
                                           "old_value": rr[col].to_numpy()[m], "new_value": cc[col].to_numpy()[m]}))
        actual = (pd.concat(diffs, ignore_index=True) if diffs
                  else pd.DataFrame(columns=["key", "column", "old_value", "new_value"]))
        logged = changes.loc[changes["table"] == t, ["key", "column", "old_value", "new_value"]]
        a_set = set(map(tuple, actual.astype(str).to_numpy()))
        l_set = set(map(tuple, logged.astype(str).to_numpy()))
        verify(len(l_set) == len(logged), t, "no duplicate value_change records", len(logged) - len(l_set))
        verify(a_set == l_set, t, "every changed cell is logged and every log row matches the data",
               f"unlogged={len(a_set - l_set)}, not-applied={len(l_set - a_set)}")
        show(t, f"raw {len(r):,} = clean {len(c):,} + quarantined {len(q):,}; changed cells {len(a_set):,}")

    expected_changes = {("dim_client", "state"): EXPECTED["state_changes"],
                        ("fact_transactions", "security_id"): EXPECTED["security_changes"],
                        ("fact_transactions", "shares"): EXPECTED["share_sign_changes"],
                        ("fact_portfolio_snapshot", "return_ytd"): EXPECTED["pct_conversions"]}
    got = changes.groupby(["table", "column"]).size().to_dict()
    verify(got == expected_changes, "value_changes", "changes per table/column", got)

    # Retained structure the decision log promises to preserve (Issues 14 to 17, 11, 19)
    c, tx, s = work["dim_client"], work["fact_transactions"], work["dim_security"]
    zl = int(c["zip_code"].str.startswith("0").sum())
    verify(zl == EXPECTED["zip_lead0_clean"] and (c["zip_code"].str.len() == 5).all(),
           "Issue 16", "leading-zero ZIPs kept (5 chars)", zl)
    verify(zl + EXPECTED["dup_copy_zip_lead0"] == int(raw["dim_client"]["zip_code"].str.startswith("0").sum()),
           "Issue 16", "232 raw = 228 clean + 4 quarantined", zl)
    cash = tx["txn_type"].isin(CASH_TYPES)
    for col in ("security_id", "shares", "price"):
        b = blank(tx[col])
        verify(int(b.sum()) == EXPECTED["structural_blanks_clean"], "Issue 15", f"{col} blanks", int(b.sum()))
        verify((b == cash).all(), "Issue 15", f"{col} blank exactly on cash-type rows", int((b != cash).sum()))
    verify(int(blank(s["sector"]).sum()) == EXPECTED["security_blank_sector"]
           and int(blank(s["expense_ratio_bps"]).sum()) == EXPECTED["security_blank_expense"],
           "Issue 15", "dim_security blanks unchanged", "changed")
    nn = int((work["dim_advisor"]["certifications"] == "None").sum())
    verify(nn == EXPECTED["certifications_none"], "Issue 17", "'None' certifications kept", nn)

    div = tx[tx["txn_type"] == "Dividend"]
    verify(len(div) == EXPECTED["dividends_clean"], "Issue 14", "retained Dividend rows", len(div))
    rd = raw["fact_transactions"].set_index("txn_id").loc[div["txn_id"]]
    dd = div.set_index("txn_id")
    for col in raw["fact_transactions"].columns.drop("txn_id"):
        if col == "security_id":
            ok = (dd[col] == rd[col].str.replace(r"\.0+$", "", regex=True)).all()
        else:
            ok = (dd[col] == rd[col]).all()
        verify(ok, "Issue 14", f"Dividend {col} equals raw (security_id: only '.0' removed)", col)

    cal = work["dim_date"].set_index("date")["is_trading_day"]
    off = tx["txn_date"].map(cal) == "0"
    bs = tx["txn_type"].isin({"Buy", "Sell"})
    got_bs, got_cash = (int((off & bs).sum()), int(bs.sum())), (int((off & ~bs).sum()), int((~bs).sum()))
    verify(got_bs == EXPECTED["weekend_buy_sell_clean"], "Issue 11", "Buy/Sell on non-trading days", got_bs)
    verify(got_cash == EXPECTED["weekend_cash_clean"], "Issue 11", "cash events on non-trading days", got_cash)

    since = c.set_index("client_id")["client_since"]
    for t, dcol in (("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date")):
        n = int((work[t][dcol].str[:7] < work[t]["client_id"].map(since).str[:7]).sum())
        verify(n == 0, "Issue 19", f"{t} rows in a month before client_since", n)
    n = int((tx["txn_date"] < tx["client_id"].map(since)).sum())
    verify(n == 0, "Issue 19", "transactions before client_since", n)
    verify(len(work["fact_fees"]) == EXPECTED["raw_rows"]["fact_fees"], "Issue 12", "fact_fees row count",
           len(work["fact_fees"]))
    print("    retained-structure checks: all passed")


# ---------------------------------------------------------------------------
# Step 8c: write outputs (only after every check has passed)
# ---------------------------------------------------------------------------
def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write as text with '\n' line endings (same bytes on Windows and Mac), then re-read to prove
    the file holds exactly the intended text."""
    df = df.astype(str).reset_index(drop=True)
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    back = pd.read_csv(path, dtype=str, keep_default_na=False)
    verify(back.equals(df), "write", f"{path.name} re-reads identically", "differs")


WRITING = {"started": False}


def write_outputs(work, quarantine, audit: Audit, changes: pd.DataFrame) -> None:
    WRITING["started"] = True
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        write_csv(work[t], CLEAN_DIR / f"{t}.csv")
    for t, fname in QUARANTINE_FILES.items():
        write_csv(quarantine[t], AUDIT_DIR / fname)
    write_csv(pd.DataFrame(audit.log), AUDIT_DIR / "cleaning_log.csv")
    write_csv(changes, AUDIT_DIR / "value_changes.csv")
    stale = sorted(p.name for p in AUDIT_DIR.glob("quarantine_*.csv") if p.name not in QUARANTINE_FILES.values())
    if stale:
        print(f"    NOTE: other quarantine files exist from earlier runs and were not written now: {stale}")
    (CLEAN_DIR / "README_clean.md").write_text(readme_text(work, quarantine, changes), encoding="utf-8")


# ---------------------------------------------------------------------------
# README_clean.md
# ---------------------------------------------------------------------------
BI_TYPES = {
    "dim_advisor": {"advisor_id": "Whole number (key)", "first_name": "Text", "last_name": "Text",
                    "region": "Text", "years_experience": "Whole number", "aum_target_mm": "Whole number",
                    "certifications": "Text (keep the word `None`; do not treat it as null)"},
    "dim_benchmark": {"benchmark_id": "Whole number (key)", "name": "Text", "asset_class": "Text",
                      "ticker_proxy": "Text"},
    "dim_client": {"client_id": "Whole number (key)", "first_name": "Text", "last_name": "Text",
                   "age": "Whole number", "city": "Text", "state": "Text (2-letter code)",
                   "zip_code": "**Text** (leading zeros)", "risk_profile": "Text (blank allowed)",
                   "client_tier": "Text", "primary_account_type": "Text (`529` is a category, not a number)",
                   "initial_aum": "Fixed decimal (currency)", "client_since": "Date (YYYY-MM-DD)",
                   "advisor_id": "Whole number (FK)", "is_active": "True/False",
                   "risk_profile_missing_flag": "Whole number 0/1"},
    "dim_date": {"date_id": "Whole number (key)", "date": "Date (YYYY-MM-DD; join key for facts)",
                 "year": "Whole number", "quarter": "Whole number", "month": "Whole number",
                 "month_name": "Text (sort by month)", "week_of_year": "Whole number (ISO week)",
                 "day_of_week": "Text", "is_month_end": "Whole number 0/1", "is_quarter_end": "Whole number 0/1",
                 "is_year_end": "Whole number 0/1", "is_trading_day": "Whole number 0/1"},
    "dim_security": {"security_id": "Whole number (key)", "ticker": "Text", "name": "Text",
                     "asset_class": "Text", "sector": "Text (blank for non-equity)",
                     "benchmark_id": "Whole number (FK)", "is_etf": "True/False",
                     "expense_ratio_bps": "Decimal (blank for non-ETFs; do not fill with 0)"},
    "fact_fees": {"fee_id": "Whole number (key)", "client_id": "Whole number (FK)",
                  "advisor_id": "Whole number (FK)", "fee_date": "Date (FK to dim_date.date)",
                  "fee_type": "Text", "aum_basis": "Fixed decimal (currency)", "bps_charged": "Decimal",
                  "amount": "Fixed decimal (currency)", "aum_basis_at_floor_flag": "Whole number 0/1"},
    "fact_portfolio_snapshot": {"snapshot_id": "Whole number (key)", "client_id": "Whole number (FK)",
                                "advisor_id": "Whole number (FK)", "benchmark_id": "Whole number (FK)",
                                "snapshot_date": "Date (FK to dim_date.date)", "year": "Whole number",
                                "month": "Whole number", "aum": "Fixed decimal (currency)",
                                "return_ytd": "Decimal (fraction: 0.0928 = 9.28%; some values in e-notation)",
                                "benchmark_return_ytd": "Decimal (fraction)",
                                "active_alpha_ytd": "Decimal (fraction; some values in e-notation)",
                                "cash_pct": "Decimal (fraction)", "account_type": "Text",
                                "return_outlier_flag": "Whole number 0/1", "aum_at_floor_flag": "Whole number 0/1"},
    "fact_transactions": {"txn_id": "Whole number (key)", "client_id": "Whole number (FK)",
                          "advisor_id": "Whole number (FK)",
                          "security_id": "Whole number (FK; blank on cash-type rows)",
                          "txn_date": "Date (FK to dim_date.date)", "txn_type": "Text",
                          "shares": "Decimal (blank on cash-type rows)", "price": "Decimal (blank on cash-type rows)",
                          "amount": "Fixed decimal (currency, always positive)",
                          "shares_sign_corrected_flag": "Whole number 0/1",
                          "after_last_snapshot_flag": "Whole number 0/1"},
}

RELATIONSHIPS = [
    ("dim_client.advisor_id", "dim_advisor.advisor_id"),
    ("dim_security.benchmark_id", "dim_benchmark.benchmark_id"),
    ("fact_fees.client_id", "dim_client.client_id"),
    ("fact_fees.advisor_id", "dim_advisor.advisor_id"),
    ("fact_portfolio_snapshot.client_id", "dim_client.client_id"),
    ("fact_portfolio_snapshot.advisor_id", "dim_advisor.advisor_id"),
    ("fact_portfolio_snapshot.benchmark_id", "dim_benchmark.benchmark_id"),
    ("fact_transactions.client_id", "dim_client.client_id"),
    ("fact_transactions.advisor_id", "dim_advisor.advisor_id"),
    ("fact_transactions.security_id", "dim_security.security_id"),
    ("fact_fees.fee_date", "dim_date.date"),
    ("fact_portfolio_snapshot.snapshot_date", "dim_date.date"),
    ("fact_transactions.txn_date", "dim_date.date"),
]


def readme_text(work, quarantine, changes) -> str:
    n = {t: len(df) for t, df in work.items()}
    flag = lambda t, f: int((work[t][f] == "1").sum())  # noqa: E731
    by_col = changes.groupby(["table", "column"]).size().to_dict()

    lines = [
        "# Clean Wildcat Capital data (`data/clean/`)",
        "",
        "Produced by `scripts/02_clean.py` from `data/raw/` following `decision_log.md`. "
        "Raw files are never modified. Every changed cell is in `data/audit/value_changes.csv`; every step is in "
        "`data/audit/cleaning_log.csv`; removed rows are in `data/audit/quarantine_*.csv` with their raw values.",
        "",
        "## Row counts",
        "",
        "| Table | Clean rows | Quarantined |",
        "|---|---:|---:|",
    ]
    lines += [f"| {t} | {n[t]:,} | {len(quarantine.get(t, [])):,} |" for t in TABLES]
    lines += [
        "",
        "## How to load these files",
        "",
        "- Read every file **as text first**. In pandas: `pd.read_csv(path, dtype=str, keep_default_na=False)`. "
        "Default parsing turns `None` into null, drops ZIP leading zeros and reads `529` as a number.",
        "- Then set the column types below. Blanks are meaningful (see limitations); load them as null, never as 0.",
        "",
        "## Relationships (13, all many-to-one, fact/child → dimension/parent)",
        "",
        "| # | From (many) | To (one) | Note |",
        "|---|---|---|---|",
    ]
    notes = {
        "fact_transactions.security_id": "blank on Deposit / Withdrawal / Advisory Fee rows (no security)",
        "fact_fees.fee_date": "monthly, always the 1st",
        "fact_portfolio_snapshot.snapshot_date": "monthly, always the 1st",
    }
    lines += [f"| {i} | `{a}` | `{b}` | {notes.get(a, '')} |" for i, (a, b) in enumerate(RELATIONSHIPS, 1)]
    lines += ["", "Every key now matches its parent as text (no `45.0`-style IDs remain).", "",
              "## Column types for a BI tool", ""]
    for t in TABLES:
        lines += [f"**{t}**", "", "| Column | Type |", "|---|---|"]
        lines += [f"| {col} | {BI_TYPES[t][col]} |" for col in work[t].columns]
        lines += [""]
    lines += [
        "## Added flag columns (0/1; 1 = condition true)",
        "",
        "| Table.column | Meaning | Rows = 1 |",
        "|---|---|---:|",
        f"| dim_client.risk_profile_missing_flag | risk_profile is blank (not filled) | "
        f"{flag('dim_client', 'risk_profile_missing_flag'):,} |",
        f"| fact_transactions.shares_sign_corrected_flag | the shares sign on this Buy was changed from negative "
        f"to positive in cleaning | {flag('fact_transactions', 'shares_sign_corrected_flag'):,} |",
        f"| fact_transactions.after_last_snapshot_flag | inactive client; transaction month is after the client's "
        f"last snapshot month | {flag('fact_transactions', 'after_last_snapshot_flag'):,} |",
        f"| fact_portfolio_snapshot.return_outlier_flag | return_ytd or active_alpha_ytd outside the assumed band "
        f"[{RETURN_BAND[0]}, {RETURN_BAND[1]}]; investigate, do not auto-exclude | "
        f"{flag('fact_portfolio_snapshot', 'return_outlier_flag'):,} |",
        f"| fact_portfolio_snapshot.aum_at_floor_flag | aum is exactly 1,000.00 | "
        f"{flag('fact_portfolio_snapshot', 'aum_at_floor_flag'):,} |",
        f"| fact_fees.aum_basis_at_floor_flag | aum_basis is exactly 1,000.00 | "
        f"{flag('fact_fees', 'aum_basis_at_floor_flag'):,} |",
        "",
        "## Changes made",
        "",
        f"- dim_client.state: {by_col.get(('dim_client', 'state'), 0):,} full names → 2-letter codes "
        "(format only; the state itself was not verified).",
        f"- fact_transactions.security_id: {by_col.get(('fact_transactions', 'security_id'), 0):,} values "
        "`45.0` → `45`.",
        f"- fact_transactions.shares: {by_col.get(('fact_transactions', 'shares'), 0):,} negative Buy share "
        "counts made positive, only where |shares| × price = amount within $0.01.",
        f"- fact_portfolio_snapshot.return_ytd: {by_col.get(('fact_portfolio_snapshot', 'return_ytd'), 0):,} "
        "`x%` values → x/100, verified against benchmark_return_ytd and active_alpha_ytd.",
        f"- dim_client: {len(quarantine['dim_client'])} probable-duplicate clients quarantined.",
        f"- fact_transactions: {len(quarantine['fact_transactions'])} orphan-client transactions quarantined.",
        "",
        "## Known limitations (kept on purpose; see decision_log.md)",
        "",
        "1. **Probable duplicate clients (Issue 5).** 25 client IDs with no facts were quarantined because they "
        "matched a fact-bearing client on every column except client_id and last_name (first_name equal), "
        "and last_name differed only as a strict prefix. "
        "They are strongly supported duplicates, not confirmed identities. The kept last_name is the spelling "
        "attached to the account history, not a verified legal name.",
        "2. **Orphan transactions removed (Issue 4).** 200 transactions point at client IDs not in dim_client. "
        "If those clients exist elsewhere, client activity is understated; the rows can be restored from the "
        "quarantine file.",
        "3. **Share sign convention is inferred (Issue 3).** Shares are treated as always positive with direction "
        "from txn_type. This is inferred from the data, not documented. If a negative Buy was really a reversal, "
        "the corrected row overstates holdings; use shares_sign_corrected_flag to find them.",
        "4. **State standardization is format only (Issue 6).** No check that the state is correct.",
        "5. **Missing risk profiles (Issue 7).** Left blank and flagged. These clients use benchmark 3, the same "
        "as Balanced clients, but that does not prove their risk tolerance.",
        "6. **Extreme returns and alpha (Issue 8).** Values outside the assumed band are flagged, not changed. "
        "The band is an assumption. Flagged rows should be investigated; whether to include them is a decision "
        "for each analysis.",
        "7. **AUM at exactly 1,000.00 (Issue 9).** May be a system floor; not confirmed. Not assumed to cause the "
        "extreme returns.",
        "8. **Activity after an inactive client's last snapshot (Issue 10).** Flagged, not removed. No "
        "account-closing date exists to judge it.",
        "9. **Transactions on non-trading days (Issue 11).** About 28% of trades fall on weekends, the same share "
        "as weekend days in the calendar. Dates were not moved. Day-of-week and price-on-date analysis is "
        "unreliable. Join to dim_date.is_trading_day to identify them.",
        "10. **Snapshot months without a fee row (Issue 12).** No fee rows were created. If billing data is "
        "missing, billed fees are understated.",
        "11. **Advisory Fee transactions do not match fact_fees (Issue 13).** None of the overlapping client-months "
        "match. Keep both; **do not add or combine them in one measure** until Wildcat explains the relationship. "
        "fact_fees is the internally reconciled billed-fee measure; it is not verified recognized revenue.",
        "12. **Dividend shares (Issue 14).** The meaning of shares on Dividend rows is unresolved. A holdings "
        "comparison was exploratory only (no opening positions, transfers, reinvestment lots or corporate "
        "actions). Report dividend totals with this caveat.",
        "13. **Conditional blanks (Issue 15).** sector is blank exactly for Fixed Income, Alternative and Cash "
        "Equivalent securities; expense_ratio_bps is blank exactly for non-ETFs; security_id, shares and price "
        "are blank exactly on Deposit, Withdrawal and Advisory Fee rows. Treated as not applicable; never fill "
        "with 0.",
        "14. **ZIP codes (Issue 16) and `None` certifications (Issue 17)** must be loaded as text.",
        "15. **Scientific notation (Issue 18).** Some small returns/alpha are written like `9.9e-05`; they are "
        "valid decimals and were left as written.",
        "16. **Monthly rows dated before client_since in the same month (Issue 19)** are expected: monthly rows "
        "are stamped on the 1st.",
        "17. **Market holidays (Issue 20).** dim_date marks every weekday as a trading day, so weekday market "
        "holidays count as trading days.",
        "18. **Same security name on different tickers (Issue 21).** Three pairs; may be separate securities, "
        "not proven. Not merged.",
        "19. **Unused dimension members (Issue 22).** Some benchmarks and most dates are not used by every fact "
        "table; this is expected.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    raw = load_raw()
    step0_baseline(raw)
    work = {t: df.copy() for t, df in raw.items()}      # raw stays untouched from here on
    audit = Audit()

    dup_pairs = step1_duplicate_clients(raw, work, audit)
    orphan_keys = step2_orphan_transactions(work, audit)
    step3_states(work, audit)
    step4_security_ids(work, audit)
    step5_negative_buys(work, audit)
    step6_percent_returns(work, audit)
    step7_flags(work, audit)

    # Documented "leave as is" decisions, so the log shows they were considered and checked
    for t, issue, note in [
        ("fact_transactions", "Issue 11", "txn_date left unchanged on non-trading days"),
        ("fact_portfolio_snapshot", "Issue 12", "no fee rows created for snapshot months without fees"),
        ("fact_transactions", "Issue 13", "Advisory Fee transactions and fact_fees left separate; do not combine"),
        ("fact_transactions", "Issue 14", "Dividend shares/price/amount left unchanged"),
        ("several", "Issue 15", "conditional blanks preserved"),
        ("dim_client", "Issue 16", "ZIP codes kept as text with leading zeros"),
        ("dim_advisor", "Issue 17", "literal 'None' certifications kept"),
        ("fact_portfolio_snapshot", "Issue 18", "scientific-notation values left as written"),
    ]:
        audit.add_log(t, issue, "leave as is", 0, note)

    quarantine = build_quarantine(raw, dup_pairs, orphan_keys)
    changes = audit.change_frame()
    verify_everything(raw, work, quarantine, changes)

    # Raw frames must still equal what is on disk (proves nothing edited them in memory)
    for t in TABLES:
        on_disk = pd.read_csv(RAW_DIR / f"{t}.csv", dtype=str, keep_default_na=False)
        verify(raw[t].equals(on_disk), t, "raw DataFrame untouched", "modified")

    write_outputs(work, quarantine, audit, changes)
    print(f"\nWrote 8 clean files + README_clean.md to {CLEAN_DIR}")
    print(f"Wrote cleaning_log.csv ({len(audit.log)} rows), value_changes.csv ({len(changes):,} rows) and "
          f"{len(QUARANTINE_FILES)} quarantine files to {AUDIT_DIR}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (CleaningError, AssertionError) as exc:
        msg = ("Output writing had started, so files in data/clean and data/audit may be partial; "
               "fix the problem and rerun." if WRITING["started"] else "No output files were written in this run.")
        print(f"\nSTOPPED: {exc}\n{msg}", file=sys.stderr)
        sys.exit(1)
