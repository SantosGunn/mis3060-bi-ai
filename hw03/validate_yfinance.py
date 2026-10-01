"""
=============================================================================
Script:     validate_yfinance.py
Purpose:    Cross-check our 8-K extraction for Walmart (WMT) against Yahoo
            Finance's quarterly income statement, retrieved with yfinance.
Author:     Santos Gunningham
Generated:  2026-09-30

Run from anywhere (paths are resolved relative to this script):
    python hw03/validate_yfinance.py

Inputs (read only, never modified):
    Yahoo Finance quarterly income statement for WMT (via yfinance)
    hw03/earnings_history.csv  (WMT row for the quarter ended July 31, 2026)

How it works:
    1. Downloads WMT's quarterly income statement and prints every
       quarter-end date Yahoo returns.
    2. Selects the quarter ending 2026-07-31 ONLY. If that column is not
       present, it says so and does not fall back to another quarter.
    3. Reads two Yahoo rows by their exact labels:
         "Total Revenue"  and  "Net Income"
       Yahoo's "Net Income" is net income attributable to the company
       (after noncontrolling interest), which matches the 8-K's
       "net income attributable to Walmart". If a label is missing, the
       script reports it and lists similar labels for reference, but it
       does not substitute a different row.
    4. Prints each value in dollars and in millions of dollars.
    5. Reads the WMT "second quarter fiscal 2027" row (FY27 Q2 = quarter
       ended July 31, 2026) from earnings_history.csv and confirms it
       still matches the expected extraction: revenue 187,937 and net
       income 6,366 (millions of USD).
    6. Compares Yahoo with the 8-K extraction and prints the difference in
       millions and as a percent. Because the 8-K figures are rounded to
       the nearest million, a gap under $0.5 million is treated as a
       rounding-level match. Neither source is changed.
=============================================================================
"""

import csv
import math
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
EARNINGS_CSV = SCRIPT_DIR / "earnings_history.csv"

TICKER = "WMT"
TARGET_QUARTER_END = date(2026, 7, 31)
CSV_PERIOD = "second quarter fiscal 2027"      # Walmart FY27 Q2

# Expected values from our 8-K extraction (millions of USD)
EXPECTED_8K = {
    "revenue": 187937,
    "net_income": 6366,   # net income attributable to Walmart
}

# Metric -> (Yahoo row label, earnings_history.csv column, description)
METRICS = {
    "revenue": ("Total Revenue", "revenue_reported", "Revenue"),
    "net_income": ("Net Income", "net_income",
                   "Net income attributable to Walmart"),
}

ROUNDING_TOLERANCE_M = 0.5   # 8-K values are rounded to the nearest million
NOT_FOUND = "NOT_FOUND"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt_dollars(value):
    return f"${value:,.0f}"


def fmt_millions(value_m):
    return f"${value_m:,.1f} million"


def is_missing(value):
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def get_quarterly_income_statement():
    """Return Yahoo's quarterly income statement as a DataFrame, or None."""
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance is not installed. Run: pip install yfinance")
        return None

    try:
        ticker = yf.Ticker(TICKER)
        # Newer yfinance uses quarterly_income_stmt; older uses
        # quarterly_financials. Both return rows = line items,
        # columns = quarter-end dates.
        stmt = getattr(ticker, "quarterly_income_stmt", None)
        if stmt is None or stmt.empty:
            stmt = ticker.quarterly_financials
    except Exception as exc:  # network errors, Yahoo format changes, etc.
        print(f"ERROR: could not retrieve data from Yahoo Finance: {exc}")
        return None

    if stmt is None or stmt.empty:
        print("ERROR: Yahoo Finance returned an empty quarterly income statement.")
        return None
    return stmt


def find_target_column(stmt):
    """Return the column for TARGET_QUARTER_END, or None. No substitution."""
    for col in stmt.columns:
        try:
            if col.date() == TARGET_QUARTER_END:
                return col
        except AttributeError:
            if str(col)[:10] == TARGET_QUARTER_END.isoformat():
                return col
    return None


def read_csv_row():
    """Return the WMT row for CSV_PERIOD from earnings_history.csv, or None."""
    if not EARNINGS_CSV.exists():
        print(f"ERROR: {EARNINGS_CSV} not found.")
        return None
    with open(EARNINGS_CSV, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f)
                if r.get("ticker", "").strip().upper() == TICKER
                and r.get("period", "").strip().lower() == CSV_PERIOD]
    if not rows:
        print(f"ERROR: no {TICKER} row with period '{CSV_PERIOD}' "
              f"in {EARNINGS_CSV.name}.")
        return None
    if len(rows) > 1:
        print(f"WARNING: {len(rows)} matching {TICKER} rows found; "
              "using the first one.")
    return rows[0]


def to_float(text):
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 74)
    print(f"YAHOO FINANCE VALIDATION - {TICKER} quarter ended "
          f"{TARGET_QUARTER_END:%B %d, %Y}")
    print("=" * 74)

    # -- Step 1: our 8-K extraction from earnings_history.csv ---------------
    print(f"\n[1] 8-K extraction from {EARNINGS_CSV.name}")
    csv_row = read_csv_row()
    extracted_m = {}
    if csv_row:
        print(f"    Row: {csv_row['ticker']} | CIK {csv_row['cik']} | "
              f"filed {csv_row['filing_date']} | {csv_row['period']}")
        for key, (_, csv_col, desc) in METRICS.items():
            raw = csv_row.get(csv_col, "")
            value = to_float(raw)
            expected = EXPECTED_8K[key]
            if value is None:
                print(f"    {desc}: {raw or 'blank'} (not a number) - "
                      f"expected {expected:,}")
                continue
            extracted_m[key] = value
            status = ("confirmed" if value == expected
                      else f"DOES NOT MATCH expected {expected:,}")
            print(f"    {desc}: {value:,.0f} million ({csv_col}) - {status}")
    else:
        print("    Could not confirm the extracted values from the CSV.")

    # Compare Yahoo against the CSV value if we have it, else the
    # expected constant, so the comparison still runs.
    comparison_m = {k: extracted_m.get(k, v) for k, v in EXPECTED_8K.items()}

    # -- Step 2: Yahoo quarterly income statement ---------------------------
    print(f"\n[2] Yahoo Finance quarterly income statement ({TICKER})")
    stmt = get_quarterly_income_statement()
    if stmt is None:
        print("\nValidation could not be completed.")
        sys.exit(1)

    print("    Available quarter-end dates:")
    for col in stmt.columns:
        label = col.date().isoformat() if hasattr(col, "date") else str(col)
        print(f"      - {label}")

    target_col = find_target_column(stmt)
    if target_col is None:
        print(f"\n    UNAVAILABLE: Yahoo has no quarter ending "
              f"{TARGET_QUARTER_END.isoformat()}.")
        print("    No other quarter was substituted. Validation stopped.")
        sys.exit(1)
    print(f"\n    Selected quarter: {TARGET_QUARTER_END.isoformat()}")

    # -- Step 3: pull metrics and compare ----------------------------------
    print("\n[3] Yahoo values vs. 8-K extraction")
    available_labels = [str(i) for i in stmt.index]
    results = {}

    for key, (yahoo_label, _, desc) in METRICS.items():
        print(f"\n    {desc}")
        if yahoo_label not in stmt.index:
            print(f"      UNAVAILABLE: Yahoo row '{yahoo_label}' not found.")
            similar = [l for l in available_labels
                       if yahoo_label.split()[-1].lower() in l.lower()]
            if similar:
                print(f"      Similar Yahoo rows (not used): {similar}")
            results[key] = "unavailable"
            continue

        value = stmt.loc[yahoo_label, target_col]
        if is_missing(value):
            print(f"      UNAVAILABLE: Yahoo row '{yahoo_label}' is blank "
                  f"for {TARGET_QUARTER_END.isoformat()}.")
            results[key] = "unavailable"
            continue

        yahoo_dollars = float(value)
        yahoo_m = yahoo_dollars / 1_000_000
        ours_m = comparison_m[key]
        diff_m = yahoo_m - ours_m
        pct = (diff_m / ours_m * 100) if ours_m else float("nan")

        print(f"      Yahoo row label:   '{yahoo_label}'")
        print(f"      Yahoo (dollars):   {fmt_dollars(yahoo_dollars)}")
        print(f"      Yahoo (millions):  {fmt_millions(yahoo_m)}")
        print(f"      8-K extraction:    {fmt_millions(ours_m)} "
              f"({fmt_dollars(ours_m * 1_000_000)})")
        print(f"      Difference:        {diff_m:+,.1f} million "
              f"({pct:+.3f}%)  [Yahoo minus 8-K]")

        if abs(diff_m) < ROUNDING_TOLERANCE_M:
            print("      Result:            MATCH (within 8-K rounding)")
            results[key] = "match"
        else:
            print("      Result:            DIFFERENT - review both sources "
                  "(neither was changed)")
            results[key] = "different"

    # -- Summary -----------------------------------------------------------
    print("\n" + "=" * 74)
    print("SUMMARY")
    for key, (_, _, desc) in METRICS.items():
        print(f"  {desc}: {results.get(key, 'unavailable').upper()}")
    print("Source files were read only; nothing was modified.")
    print("=" * 74)


if __name__ == "__main__":
    main()
