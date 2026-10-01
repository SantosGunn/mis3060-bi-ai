"""
=============================================================================
Script:     hw03_timeline.py
Purpose:    Build a corporate events timeline by matching each executive
            event (8-K Item 5.02) to the nearest quarterly earnings filing
            (8-K Item 2.02) for the same company.
Author:     Santos Gunningham
Generated:  2026-09-30

Run from anywhere (paths are resolved relative to this script):
    python hw03/hw03_timeline.py

Inputs (read only, never modified):
    hw03/earnings_history.csv
    hw03/executive_events.csv

Output:
    hw03/corporate_events_timeline.csv

How it works:
    1. Both CSVs are read with every column kept as a string, so CIKs keep
       their leading zeros (e.g. "0000320193").
    2. Earnings filings are grouped by ticker. Matching uses FILING dates
       only (executive filing_date vs. earnings filing_date). The
       executive effective_date is carried through but never used to match.
    3. For each executive-event row, the earnings filing with the smallest
       absolute day difference for the same ticker is chosen.
         days_to_nearest_earnings = executive_filing_date - earnings_filing_date
       Negative = the executive filing came before earnings.
       Positive = the executive filing came after earnings.
    4. TIE RULE: if two earnings filings are equally close (same absolute
       difference, one before and one after), the EARLIER earnings filing
       date is chosen.
    5. event_timing:
         "same week"        |difference| <= 7 days (including 0)
         "before earnings"  difference < -7
         "after earnings"   difference > 7
    6. NO MATCH: if a ticker has no usable earnings filings, or a date
       cannot be parsed, the event is still kept. The earnings fields,
       days_to_nearest_earnings, and event_timing are set to NOT_FOUND and
       a warning is printed.
    7. One output row is written per executive-event row, so separate role
       appointments for the same person stay as separate rows.
    8. An empty executive-events CSV (zero bytes or header only) does not
       crash the script: a header-only output file is written and the
       totals print as zero.
=============================================================================
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to this script's folder)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
EARNINGS_CSV = SCRIPT_DIR / "earnings_history.csv"
EXECUTIVES_CSV = SCRIPT_DIR / "executive_events.csv"
OUTPUT_CSV = SCRIPT_DIR / "corporate_events_timeline.csv"

NOT_FOUND = "NOT_FOUND"
SAME_WEEK_DAYS = 7
DATE_FORMAT = "%Y-%m-%d"

# Expected source columns (used for the output header even if a file is empty)
EXEC_COLUMNS = ["company", "ticker", "cik", "filing_date", "event_type",
                "person_name", "title", "effective_date"]
EARN_COLUMNS = ["company", "ticker", "cik", "filing_date", "period",
                "revenue_reported", "eps_diluted", "net_income"]

# Output columns. Executive columns come first; filing_date is renamed to
# executive_filing_date. Earnings columns get an "earnings_" prefix so the
# two filing dates (and the two company/CIK values) can't be confused.
OUTPUT_COLUMNS = [
    "company",
    "ticker",
    "cik",
    "executive_filing_date",
    "event_type",
    "person_name",
    "title",
    "effective_date",
    "earnings_company",
    "earnings_cik",
    "earnings_filing_date",
    "earnings_period",
    "earnings_revenue_reported",
    "earnings_eps_diluted",
    "earnings_net_income",
    "days_to_nearest_earnings",
    "event_timing",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def warn(message):
    print(f"WARNING: {message}")


def read_csv_as_strings(path, expected_columns):
    """Read a CSV into a list of dicts with every value kept as a string.

    Returns [] for a zero-byte or header-only file. Exits with a clear
    message if the file is missing or required columns are absent.
    """
    if not path.exists():
        sys.exit(f"ERROR: input file not found: {path}")

    # utf-8-sig quietly drops a byte-order mark if Excel added one
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:          # zero-byte file
            return []
        fieldnames = [name.strip() for name in reader.fieldnames]
        missing = [c for c in expected_columns if c not in fieldnames]
        if missing:
            sys.exit(f"ERROR: {path.name} is missing columns: {missing}")
        rows = []
        for raw in reader:
            row = {}
            for key, value in raw.items():
                if key is None:                # extra unnamed cells, ignore
                    continue
                row[key.strip()] = (value or "").strip()
            # skip completely blank lines
            if any(row.get(c, "") for c in expected_columns):
                rows.append(row)
        return rows


def parse_date(text):
    """Return a date for 'YYYY-MM-DD' text, or None if it can't be parsed."""
    try:
        return datetime.strptime(text.strip(), DATE_FORMAT).date()
    except (ValueError, AttributeError):
        return None


def classify_timing(days):
    if abs(days) <= SAME_WEEK_DAYS:
        return "same week"
    if days < -SAME_WEEK_DAYS:
        return "before earnings"
    return "after earnings"


def build_earnings_index(earnings_rows):
    """Group earnings filings by ticker as (filing_date, row) pairs."""
    index = {}
    for row in earnings_rows:
        ticker = row["ticker"].upper()
        filed = parse_date(row["filing_date"])
        if filed is None:
            warn(f"skipping earnings row for {ticker or '?'} with unreadable "
                 f"filing_date '{row['filing_date']}'")
            continue
        index.setdefault(ticker, []).append((filed, row))
    return index


def find_nearest(exec_date, candidates):
    """Pick the nearest earnings filing. Ties go to the EARLIER filing date."""
    return min(candidates,
               key=lambda pair: (abs((exec_date - pair[0]).days), pair[0]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    earnings_rows = read_csv_as_strings(EARNINGS_CSV, EARN_COLUMNS)
    exec_rows = read_csv_as_strings(EXECUTIVES_CSV, EXEC_COLUMNS)

    print(f"Loaded {len(earnings_rows)} earnings filings from {EARNINGS_CSV.name}")
    print(f"Loaded {len(exec_rows)} executive events from {EXECUTIVES_CSV.name}")
    if not exec_rows:
        warn(f"{EXECUTIVES_CSV.name} has no event rows; "
             "writing a header-only timeline.")

    earnings_by_ticker = build_earnings_index(earnings_rows)

    output_rows = []
    for ev in exec_rows:
        ticker = ev["ticker"].upper()
        out = {
            "company": ev["company"],
            "ticker": ev["ticker"],
            "cik": ev["cik"],
            "executive_filing_date": ev["filing_date"],
            "event_type": ev["event_type"],
            "person_name": ev["person_name"],
            "title": ev["title"],
            "effective_date": ev["effective_date"],
        }
        # default every match field to NOT_FOUND, then fill in if matched
        for col in OUTPUT_COLUMNS[8:]:
            out[col] = NOT_FOUND

        exec_date = parse_date(ev["filing_date"])
        candidates = earnings_by_ticker.get(ticker, [])

        if exec_date is None:
            warn(f"{ticker} | {ev['person_name']}: unreadable executive "
                 f"filing_date '{ev['filing_date']}', no match made")
        elif not candidates:
            warn(f"{ticker} | {ev['person_name']}: no earnings filings found "
                 f"for ticker {ticker}, no match made")
        else:
            earn_date, earn = find_nearest(exec_date, candidates)
            days = (exec_date - earn_date).days
            if earn["cik"] != ev["cik"]:
                warn(f"{ticker}: CIK differs between files "
                     f"(executive {ev['cik']} vs earnings {earn['cik']})")
            out.update({
                "earnings_company": earn["company"],
                "earnings_cik": earn["cik"],
                "earnings_filing_date": earn["filing_date"],
                "earnings_period": earn["period"],
                "earnings_revenue_reported": earn["revenue_reported"],
                "earnings_eps_diluted": earn["eps_diluted"],
                "earnings_net_income": earn["net_income"],
                "days_to_nearest_earnings": str(days),
                "event_timing": classify_timing(days),
            })
        output_rows.append(out)

    # -- Save --------------------------------------------------------------
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    # -- Print by company ----------------------------------------------------
    # Company order: as they first appear in the earnings file, then any
    # companies that only appear in the executive file.
    company_order = []
    for row in earnings_rows + exec_rows:
        t = row["ticker"].upper()
        if t and t not in company_order:
            company_order.append(t)

    print()
    print("=" * 78)
    print("CORPORATE EVENTS TIMELINE")
    print("days = executive filing date - earnings filing date "
          "(negative = before earnings)")
    print("Tie rule: if two earnings filings are equally close, "
          "the earlier one is used.")
    print("=" * 78)

    for ticker in company_order:
        events = [r for r in output_rows if r["ticker"].upper() == ticker]
        name = next((r["company"] for r in earnings_rows + exec_rows
                     if r["ticker"].upper() == ticker), ticker)
        print(f"\n{name} ({ticker}) - {len(events)} event(s)")
        print("-" * 78)
        if not events:
            print("  No executive events.")
            continue
        for r in events:
            print(f"  Exec filed {r['executive_filing_date']} | "
                  f"{r['event_type']:<11} | {r['person_name']} - {r['title']}")
            print(f"      Nearest earnings filed: {r['earnings_filing_date']} | "
                  f"Days: {r['days_to_nearest_earnings']} | "
                  f"Timing: {r['event_timing']}")

    # -- Totals --------------------------------------------------------------
    totals = {"before earnings": 0, "after earnings": 0,
              "same week": 0, NOT_FOUND: 0}
    for r in output_rows:
        totals[r["event_timing"]] += 1

    print()
    print("=" * 78)
    print(f"TOTALS across {len(company_order)} companies "
          f"({len(output_rows)} executive events)")
    print(f"  Before earnings: {totals['before earnings']}")
    print(f"  After earnings:  {totals['after earnings']}")
    print(f"  Same week:       {totals['same week']}")
    if totals[NOT_FOUND]:
        print(f"  No match (NOT_FOUND): {totals[NOT_FOUND]}")
    print("=" * 78)
    print(f"\nSaved {len(output_rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
