"""
Script:   hw02/count_buy_subtraction.py
Purpose:  Derive the Buy count by subtraction: total rows minus rows whose
          txn_type is exactly Sell, Deposit, Withdrawal, Dividend, or
          Advisory Fee. No direct filtering on 'Buy'.
Author:   Santos Gunningham

Run from the repository's main folder:
    python hw02/count_buy_subtraction.py

The CSV is only read, never written. All counts are calculated from the file.
"""

from pathlib import Path

import pandas as pd

DATA_PATH = Path("data/raw/fact_transactions.csv")
SUBTRACT_TYPES = ["Sell", "Deposit", "Withdrawal", "Dividend", "Advisory Fee"]

if not DATA_PATH.exists():
    raise FileNotFoundError(
        f"Could not find {DATA_PATH}. Run this script from the repository's "
        "main folder: python hw02/count_buy_subtraction.py"
    )

# Read only the column we need, as text, so values are compared exactly as stored
txn_type = pd.read_csv(DATA_PATH, usecols=["txn_type"], dtype=str)["txn_type"]

total_rows = len(txn_type)
is_subtracted = txn_type.isin(SUBTRACT_TYPES)  # exact matches; missing never matches
subtract_count = int(is_subtracted.sum())
buy_by_subtraction = total_rows - subtract_count

print(f"Source file: {DATA_PATH}")
print(f"Total rows:                        {total_rows:,}")
print()
print("Rows being subtracted (exact txn_type match):")
for t in SUBTRACT_TYPES:
    print(f"  {t:<14} {int((txn_type == t).sum()):>10,}")
print(f"  {'Subtotal':<14} {subtract_count:>10,}")
print()
print(f"Buy count (total - subtracted):    {buy_by_subtraction:,}")

# Validity check: show what the remaining rows actually contain. The result
# equals the true Buy count only if 'Buy' is the only value left here
# (no blanks, typos, or other transaction types).
remaining = txn_type[~is_subtracted].map(repr).value_counts(dropna=False)
print()
print("Values in the remaining rows (should be only 'Buy'):")
print(remaining.to_string())
