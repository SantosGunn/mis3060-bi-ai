"""
=============================================================================
Script:     hw02_eda.py
Purpose:    Exploratory data analysis (EDA) of Wildcat Capital transactions
Dataset:    data/raw/fact_transactions.csv (Wildcat Capital transaction fact table)
Author:     Santos Gunningham
Generated:  2026-09-23

Run from the repository's main folder:
    python hw02/hw02_eda.py

Outputs:
    hw02/hw02_profile.txt                 plain-text copy of results (items 2-13)
    hw02/charts/hist_amount.png           histogram of amount with mean/median
    hw02/charts/box_amount_by_type.png    horizontal box plot of amount by type
    hw02/charts/scatter_shares_amount.png shares vs amount, colored by type

Notes:
    - The raw CSV is only read, never written.
    - Every number is calculated from the CSV; nothing is hard-coded.
    - Unusual values (e.g. negative shares) are kept in the analysis.
=============================================================================
"""

from itertools import combinations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # save charts to files without needing a display
import matplotlib.pyplot as plt
import matplotlib.ticker
import pandas as pd

# -----------------------------------------------------------------------------
# Paths and settings
# -----------------------------------------------------------------------------
DATA_PATH = Path("data/raw/fact_transactions.csv")
OUT_DIR = Path("hw02")
CHART_DIR = OUT_DIR / "charts"
PROFILE_PATH = OUT_DIR / "hw02_profile.txt"

EXPECTED_SHAPE = (298_772, 9)
NUMERIC_COLS = ["shares", "price", "amount"]

# Chart colors (colorblind-checked categorical palette, fixed order)
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

pd.set_option("display.width", 120)
pd.set_option("display.max_columns", 50)
pd.set_option("display.float_format", lambda v: f"{v:,.2f}")

# -----------------------------------------------------------------------------
# Output helper: everything reported goes to the terminal AND the profile file
# -----------------------------------------------------------------------------
report_lines = []


def report(text=""):
    """Print a line to the terminal and keep it for the profile file."""
    text = str(text)
    print(text)
    report_lines.append(text)


def section(number, title):
    """Print a clearly labeled section header."""
    report()
    report("=" * 78)
    report(f"[{number}] {title}")
    report("=" * 78)


def find_col(df, candidates, keyword):
    """Return the first matching column name for an ID field.

    Tries exact names first, then any column containing the keyword.
    Returns None if nothing matches.
    """
    for name in candidates:
        if name in df.columns:
            return name
    for name in df.columns:
        if keyword in name.lower():
            return name
    return None


# -----------------------------------------------------------------------------
# 1. Load the data (read-only; the original CSV is never modified)
# -----------------------------------------------------------------------------
if not DATA_PATH.exists():
    raise FileNotFoundError(
        f"Could not find {DATA_PATH}. Run this script from the repository's "
        "main folder: python hw02/hw02_eda.py"
    )

raw = pd.read_csv(DATA_PATH)
df = raw.copy()  # working copy for analysis; `raw` stays exactly as loaded

report("WILDCAT CAPITAL - TRANSACTION DATA PROFILE (HW02)")
report(f"Source file: {DATA_PATH}")
report(f"Author: Santos Gunningham")
report(f"Run timestamp: {pd.Timestamp.now():%Y-%m-%d %H:%M:%S}")

# -----------------------------------------------------------------------------
# 2. Shape
# -----------------------------------------------------------------------------
section(2, "DATASET SHAPE")
report(f"Rows:    {raw.shape[0]:,}")
report(f"Columns: {raw.shape[1]:,}")

# -----------------------------------------------------------------------------
# 3. Column names and data types as loaded (before any conversion)
# -----------------------------------------------------------------------------
section(3, "COLUMN NAMES AND DATA TYPES (AS LOADED)")
dtypes = raw.dtypes.astype(str).rename("dtype").to_frame()
dtypes.index.name = "column"
report(dtypes.to_string())

# -----------------------------------------------------------------------------
# 4. Missing values per column
# -----------------------------------------------------------------------------
section(4, "MISSING VALUES PER COLUMN")
missing = pd.DataFrame({
    "missing_count": raw.isna().sum(),
    "missing_pct": (raw.isna().mean() * 100).round(2),
})
missing.index.name = "column"
report(missing.to_string())
report(f"Total missing cells: {int(raw.isna().sum().sum()):,}")

# Make sure shares/price/amount are numeric for the analysis below.
# (Only the working copy changes; the dtypes above were reported as loaded.)
for col in NUMERIC_COLS:
    if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
        before_na = df[col].isna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        added_na = df[col].isna().sum() - before_na
        report(f"Note: '{col}' was converted to numeric for analysis; "
               f"{added_na:,} non-numeric value(s) became missing.")

# -----------------------------------------------------------------------------
# 5. Descriptive statistics for every numeric column
# -----------------------------------------------------------------------------
section(5, "DESCRIPTIVE STATISTICS (NUMERIC COLUMNS)")
numeric = df.select_dtypes(include="number")
if numeric.empty:
    report("No numeric columns found.")
else:
    stats = numeric.describe().T  # count, mean, std, min, 25%, 50%, 75%, max
    stats = stats.rename(columns={"50%": "median"})
    report(stats.to_string())

# -----------------------------------------------------------------------------
# 6. Transaction type counts and percentages
# -----------------------------------------------------------------------------
section(6, "TRANSACTIONS BY TXN_TYPE (MOST TO LEAST FREQUENT)")
type_counts = df["txn_type"].value_counts(dropna=False)
type_table = pd.DataFrame({
    "count": type_counts,
    "pct": (type_counts / len(df) * 100).round(2),
})
type_table.index.name = "txn_type"
report(type_table.to_string())
report(f"Total: {int(type_table['count'].sum()):,}")

# -----------------------------------------------------------------------------
# 7. Unique clients, advisors, and securities (missing values excluded)
# -----------------------------------------------------------------------------
section(7, "UNIQUE CLIENTS, ADVISORS, AND SECURITIES (EXCLUDING MISSING)")
id_cols = {
    "Clients": find_col(df, ["client_id", "client_key", "client"], "client"),
    "Advisors": find_col(df, ["advisor_id", "advisor_key", "advisor"], "advisor"),
    "Securities": find_col(df, ["security_id", "security_key", "ticker",
                                "security", "symbol"], "secur"),
}
for label, col in id_cols.items():
    if col is None:
        report(f"{label:<11} column not found")
    else:
        report(f"{label:<11} {df[col].nunique(dropna=True):>10,}   (column: {col})")

# -----------------------------------------------------------------------------
# 8. Earliest and latest txn_date (temporary conversion only)
# -----------------------------------------------------------------------------
section(8, "DATE RANGE OF TXN_DATE")
txn_dates = pd.to_datetime(df["txn_date"], errors="coerce")  # temporary Series
unparsed = txn_dates.isna().sum() - df["txn_date"].isna().sum()
report(f"Earliest txn_date: {txn_dates.min():%Y-%m-%d}")
report(f"Latest txn_date:   {txn_dates.max():%Y-%m-%d}")
if unparsed > 0:
    report(f"Note: {unparsed:,} non-missing date value(s) could not be parsed.")

# -----------------------------------------------------------------------------
# 9. Duplicate txn_id values
# -----------------------------------------------------------------------------
section(9, "DUPLICATE TXN_ID CHECK")
dup_extra = int(df["txn_id"].duplicated(keep="first").sum())
dup_ids = int(df.loc[df["txn_id"].duplicated(keep=False), "txn_id"].nunique())
report(f"Duplicate entries beyond first occurrence: {dup_extra:,}")
report(f"Distinct txn_id values that repeat:        {dup_ids:,}")

# -----------------------------------------------------------------------------
# 10. Mean, median, and skewness of amount
# -----------------------------------------------------------------------------
section(10, "AMOUNT: MEAN, MEDIAN, SKEWNESS")
amount_mean = df["amount"].mean()
amount_median = df["amount"].median()
amount_skew = df["amount"].skew()
report(f"Mean:     {amount_mean:,.2f}")
report(f"Median:   {amount_median:,.2f}")
report(f"Skewness: {amount_skew:,.4f}")

# -----------------------------------------------------------------------------
# 11. Amount by transaction type (sorted by mean amount, high to low)
# -----------------------------------------------------------------------------
section(11, "AMOUNT BY TXN_TYPE (SORTED BY MEAN AMOUNT, HIGH TO LOW)")
by_type = (
    df.groupby("txn_type", dropna=False)["amount"]
    .agg(txn_count="size", mean_amount="mean", median_amount="median")
    .round({"mean_amount": 2, "median_amount": 2})
    .sort_values("mean_amount", ascending=False)
)
report(by_type.to_string(formatters={
    "txn_count": "{:,}".format,
    "mean_amount": "{:,.2f}".format,
    "median_amount": "{:,.2f}".format,
}))

# -----------------------------------------------------------------------------
# 12. Correlation matrix and ranked variable pairs
# -----------------------------------------------------------------------------
section(12, "CORRELATION MATRIX: SHARES, PRICE, AMOUNT (PEARSON)")
corr = df[NUMERIC_COLS].corr().round(2)
report(corr.to_string(float_format="{:.2f}".format))
report()
report("Pairs ranked by absolute correlation (strongest first):")
pairs = [
    (a, b, corr.loc[a, b])
    for a, b in combinations(NUMERIC_COLS, 2)  # distinct pairs, no self-pairs
]
pairs.sort(key=lambda p: abs(p[2]), reverse=True)
for rank, (a, b, r) in enumerate(pairs, start=1):
    report(f"  {rank}. {a} & {b}: r = {r:.2f}  (|r| = {abs(r):.2f})")

# -----------------------------------------------------------------------------
# 13. Shares by transaction type (missing shares stay missing)
# -----------------------------------------------------------------------------
section(13, "SHARES BY TXN_TYPE: MIN, MAX, NEGATIVE COUNT")
shares_by_type = df.groupby("txn_type", dropna=False)["shares"].agg(
    min_shares="min",
    max_shares="max",
    negative_shares=lambda s: int((s < 0).sum()),  # NaN is not counted as < 0
    missing_shares=lambda s: int(s.isna().sum()),
)
report(shares_by_type.to_string())
report("(min/max ignore missing shares; missing values are not replaced with 0)")

# -----------------------------------------------------------------------------
# 14. Shape check against the expected size
# -----------------------------------------------------------------------------
if raw.shape != EXPECTED_SHAPE:
    print()
    print(f"WARNING: dataset shape is {raw.shape[0]:,} rows x {raw.shape[1]} "
          f"columns; expected {EXPECTED_SHAPE[0]:,} rows x "
          f"{EXPECTED_SHAPE[1]} columns.")
else:
    print()
    print(f"Shape check passed: {EXPECTED_SHAPE[0]:,} rows x "
          f"{EXPECTED_SHAPE[1]} columns.")

# -----------------------------------------------------------------------------
# 15. Charts
# -----------------------------------------------------------------------------
CHART_DIR.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "figure.dpi": 110,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": "#e6e5e1",
    "grid.linewidth": 0.8,
    "axes.axisbelow": True,
    "axes.titleweight": "bold",
})
amount = df["amount"].dropna()
types = by_type.index.tolist()  # same order everywhere: by mean amount
type_colors = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)}

# 15a. Histogram of amount with mean and median lines
fig, ax = plt.subplots(figsize=(10, 6))
ax.hist(amount, bins=100, color="#86b6ef", edgecolor="#fcfcfb", linewidth=0.3)
ax.axvline(amount_mean, color="#eb6834", linewidth=2,
           label=f"Mean = {amount_mean:,.2f}")
ax.axvline(amount_median, color="#1c5cab", linewidth=2, linestyle="--",
           label=f"Median = {amount_median:,.2f}")
ax.set_title("Distribution of Transaction Amount")
ax.set_xlabel("Amount ($)")
ax.set_ylabel("Number of transactions")
ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
ax.legend(frameon=False)
fig.tight_layout()
fig.savefig(CHART_DIR / "hist_amount.png")
plt.close(fig)

# 15b. Horizontal box plot of amount by transaction type
fig, ax = plt.subplots(figsize=(10, 1.2 + 0.8 * len(types)))
box_data = [df.loc[df["txn_type"] == t, "amount"].dropna() for t in types]
bp = ax.boxplot(box_data, vert=False, patch_artist=True, widths=0.55,
                flierprops=dict(marker=".", markersize=3, alpha=0.3,
                                markeredgecolor="#52514e"),
                medianprops=dict(color="#0b0b0b", linewidth=2))
for patch, t in zip(bp["boxes"], types):
    patch.set_facecolor(type_colors[t])
    patch.set_alpha(0.75)
ax.set_yticks(range(1, len(types) + 1), [str(t) for t in types])
ax.invert_yaxis()  # highest mean amount at the top
ax.set_title("Transaction Amount by Transaction Type")
ax.set_xlabel("Amount ($)")
ax.set_ylabel("Transaction type")
ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
fig.tight_layout()
fig.savefig(CHART_DIR / "box_amount_by_type.png")
plt.close(fig)

# 15c. Scatter of shares vs amount, colored by transaction type
fig, ax = plt.subplots(figsize=(10, 6.5))
for t in types:
    sub = df[(df["txn_type"] == t)][["shares", "amount"]].dropna()
    ax.scatter(sub["shares"], sub["amount"], s=6, alpha=0.35,
               color=type_colors[t], label=f"{t} (n={len(sub):,})",
               edgecolors="none", rasterized=True)
ax.axvline(0, color="#52514e", linewidth=0.8)
ax.axhline(0, color="#52514e", linewidth=0.8)
ax.set_title("Shares vs. Amount by Transaction Type")
ax.set_xlabel("Shares")
ax.set_ylabel("Amount ($)")
ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
ax.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
leg = ax.legend(title="Transaction type", frameon=False, markerscale=3,
                loc="best")
for handle in getattr(leg, "legend_handles", getattr(leg, "legendHandles", [])):
    handle.set_alpha(1)  # solid legend markers even though points are faint
fig.tight_layout()
fig.savefig(CHART_DIR / "scatter_shares_amount.png")
plt.close(fig)

print()
print(f"Charts saved to {CHART_DIR}/:")
for name in ["hist_amount.png", "box_amount_by_type.png",
             "scatter_shares_amount.png"]:
    print(f"  - {name}")

# -----------------------------------------------------------------------------
# 16. Save the plain-text profile (items 2-13)
# -----------------------------------------------------------------------------
PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
PROFILE_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
print(f"Profile saved to {PROFILE_PATH}")
