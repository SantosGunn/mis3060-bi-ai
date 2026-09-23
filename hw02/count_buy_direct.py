"""
Script:   hw02/count_buy_direct.py
Purpose:  Count rows in the Wildcat Capital transaction table where
          txn_type is exactly 'Buy' (case-sensitive, no trimming).
Author:   Santos Gunningham

Run from the repository's main folder:
    python hw02/count_buy_direct.py

The CSV is only read, never written. The count is calculated from the file.
"""

from pathlib import Path

import pandas as pd

DATA_PATH = Path("data/raw/fact_transactions.csv")
TARGET = "Buy"

if not DATA_PATH.exists():
    raise FileNotFoundError(
        f"Could not find {DATA_PATH}. Run this script from the repository's "
        "main folder: python hw02/count_buy_direct.py"
    )

# Read only the column we need, as text, so values are compared exactly as stored
txn_type = pd.read_csv(DATA_PATH, usecols=["txn_type"], dtype=str)["txn_type"]

buy_count = int((txn_type == TARGET).sum())  # exact match; missing values never match

print(f"Source file: {DATA_PATH}")
print(f"Total rows: {len(txn_type):,}")
print(f"Rows where txn_type == '{TARGET}' exactly: {buy_count:,}")

# Diagnostic only: values that look like 'Buy' but are not an exact match
# (e.g. 'buy', 'Buy ', 'BUY'). These are NOT included in the count above.
near = txn_type[(txn_type != TARGET)
                & txn_type.str.strip().str.lower().eq(TARGET.lower())]
if near.empty:
    print("Near-matches (case/whitespace variants): 0")
else:
    print(f"Near-matches (case/whitespace variants), not counted: {len(near):,}")
    print(near.map(repr).value_counts().to_string())
