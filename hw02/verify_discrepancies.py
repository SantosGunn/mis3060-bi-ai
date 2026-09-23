"""
verify_discrepancies.py - checks for the two HW02 benchmark differences.
Run from the repo's main folder:  python hw02/verify_discrepancies.py
Read-only: the CSV is never modified.
"""
from decimal import Decimal

import matplotlib
import numpy as np
import pandas as pd

CSV = "data/raw/fact_transactions.csv"

print(f"pandas {pd.__version__} | numpy {np.__version__} | matplotlib {matplotlib.__version__}")

# ---------------------------------------------------------------------------
# 1. txn_date dtype: is "str" a pandas 3 labeling change, and is it still text?
# ---------------------------------------------------------------------------
print("\n[1] txn_date dtype")
df = pd.read_csv(CSV)
col = df["txn_date"]
print("dtype as loaded:         ", repr(col.dtype))
print("is text (string dtype)?  ", pd.api.types.is_string_dtype(col))
print("is datetime?             ", pd.api.types.is_datetime64_any_dtype(col))
print("python type of 1st value:", type(col.iloc[0]).__name__, repr(col.iloc[0]))
print("future.infer_string:     ", pd.get_option("future.infer_string"))

# Same file loaded with the legacy (pandas 2.x style) object dtype for text
legacy = pd.read_csv(CSV, usecols=["txn_date"], dtype={"txn_date": object})
print("dtype with dtype=object: ", legacy["txn_date"].dtype)
print("values identical?        ", col.astype(object).equals(legacy["txn_date"]))

# ---------------------------------------------------------------------------
# 2. Median amount: the two middle values and their unrounded average
# ---------------------------------------------------------------------------
print("\n[2] median amount")
amt = df["amount"].dropna().sort_values(ignore_index=True)
n = len(amt)
print("non-missing amounts:", n, "(even)" if n % 2 == 0 else "(odd)")
if n % 2 == 0:
    lo, hi = float(amt.iloc[n // 2 - 1]), float(amt.iloc[n // 2])
    print(f"middle values (positions {n // 2} and {n // 2 + 1}, 1-based): {lo!r}, {hi!r}")
    exact_avg = (Decimal(repr(lo)) + Decimal(repr(hi))) / 2
    print("exact decimal average:   ", exact_avg)

med = amt.median()
print("pandas median (repr):    ", repr(float(med)))
print("stored binary value:     ", Decimal(float(med)))
print("f-string  :.2f          ->", f"{med:.2f}", "  (correct rounding of the stored binary)")
print("round(float(med), 2)    ->", round(float(med), 2))
print("np.round(med, 2)        ->", np.round(med, 2), "  (x*100, round half to even)")
print("Series.round(2)         ->", pd.Series([med]).round(2).iloc[0])
