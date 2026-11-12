# HW06 — Measure library and design answers

## Model and filter conventions

All 16 measures belong to `_Measures`. The model uses the posted Wildcat star model. `dim_date` was marked as the date table using `dim_date[date]` after checking its setting. Dimension filters propagate through active, single-direction relationships to the facts. Snapshot grain is one client per snapshot date: pandas found no duplicate client/date pairs. The 60 monthly snapshots are dated on the first of each month; the latest is 2024-12-01. “Ending” means the latest available snapshot, not a fabricated December 31 observation.

Balances are summed across clients at a shared date. Ratios, averages, rankings and text classifications are recalculated in each total context. Annual and grand-total ratios are not sums of displayed row percentages. Time shifts move the selected date period before evaluating Ending AUM; the grand-total LY selection ends in 2023 and PM in November 2024. Missing LY produces BLANK for 2020 growth rates.

## Part A — DAX and business meaning

### Total Fees

```dax
Total Fees =
SUM ( fact_fees[amount] )
```

**Pattern:** SUM: additive fees across rows and periods.

**Manager meaning:** Total fees charged in the selected period and client population.

**Format:** Currency, 2 decimals.

### Net Flows

```dax
Net Flows =
CALCULATE ( SUM ( fact_transactions[amount] ), fact_transactions[txn_type] = "Deposit" )
    - CALCULATE ( SUM ( fact_transactions[amount] ), fact_transactions[txn_type] = "Withdrawal" )
```

**Pattern:** SUM: additive deposits minus withdrawals; transaction type supplies direction.

**Manager meaning:** Net client contributions, excluding buys, sells, dividends and fee transactions from this flow definition.

**Format:** Currency, 2 decimals.

### AUM (naive SUM)

```dax
AUM (naive SUM) =
SUM ( fact_portfolio_snapshot[aum] )
```

**Pattern:** SUM deliberately misapplied to a balance across time.

**Manager meaning:** Demonstrates repeated counting of monthly balances; it is retained for validation and excluded from the report visuals.

**Format:** Currency, 2 decimals.

### Ending AUM

```dax
Ending AUM =
CALCULATE (
    SUM ( fact_portfolio_snapshot[aum] ),
    LASTNONBLANK (
        dim_date[date],
        CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) )
    )
)
```

**Pattern:** Last balance: additive across clients at a common snapshot, not across time.

**Manager meaning:** AUM at the last available snapshot within the selected filters.

**Format:** Currency, 2 decimals.

### Ending Clients

```dax
Ending Clients =
CALCULATE (
    DISTINCTCOUNT ( fact_portfolio_snapshot[client_id] ),
    LASTNONBLANK (
        dim_date[date],
        CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) )
    )
)
```

**Pattern:** Last balance/date plus distinct count: do not sum client counts across time or overlapping groups.

**Manager meaning:** Number of clients represented at the same last snapshot used for Ending AUM.

**Format:** Whole number.

### Avg AUM per Client

```dax
Avg AUM per Client =
DIVIDE ( [Ending AUM], [Ending Clients] )
```

**Pattern:** Recompute ratio from ending balance and ending distinct count.

**Manager meaning:** Average portfolio size among clients present at the selected ending snapshot.

**Format:** Currency, 2 decimals.

### Ending AUM LY

```dax
Ending AUM LY =
CALCULATE ( [Ending AUM], SAMEPERIODLASTYEAR ( dim_date[date] ) )
```

**Pattern:** Last balance within the selected date set shifted one year earlier.

**Manager meaning:** Prior-year comparison balance for the current selection.

**Format:** Currency, 2 decimals.

### AUM YoY %

```dax
AUM YoY % =
DIVIDE ( [Ending AUM] - [Ending AUM LY], [Ending AUM LY] )
```

**Pattern:** Recompute growth ratio; non-additive.

**Manager meaning:** Percentage change from the prior-year ending balance.

**Format:** Percentage, 2 decimals.

### Ending AUM PM

```dax
Ending AUM PM =
CALCULATE ( [Ending AUM], DATEADD ( dim_date[date], -1, MONTH ) )
```

**Pattern:** Last balance within the selected date set shifted one month earlier.

**Manager meaning:** Prior-month comparison balance for the current selection.

**Format:** Currency, 2 decimals.

### AUM MoM %

```dax
AUM MoM % =
DIVIDE ( [Ending AUM] - [Ending AUM PM], [Ending AUM PM] )
```

**Pattern:** Recompute growth ratio; non-additive.

**Manager meaning:** Percentage change from the prior-month ending balance.

**Format:** Percentage, 2 decimals.

### Avg Monthly AUM

```dax
Avg Monthly AUM =
DIVIDE ( SUM ( fact_portfolio_snapshot[aum] ), DISTINCTCOUNT ( fact_portfolio_snapshot[snapshot_date] ) )
```

**Pattern:** Recompute sum of monthly balances divided by distinct snapshot dates.

**Manager meaning:** Average total AUM over the observed months in the selection.

**Format:** Currency, 2 decimals.

### Fee Yield (bps)

```dax
Fee Yield (bps) =
DIVIDE ( [Total Fees] * 12 * 10000, SUM ( fact_portfolio_snapshot[aum] ) )
```

**Pattern:** Recompute ratio from fees and monthly AUM exposure; non-additive.

**Manager meaning:** Annualized fees per dollar of snapshot AUM, expressed in basis points.

**Format:** Decimal number, 2 decimals; bps, not percentage.

### Organic Growth Rate

```dax
Organic Growth Rate =
DIVIDE ( [Net Flows], [Ending AUM LY] )
```

**Pattern:** Recompute ratio; non-additive.

**Manager meaning:** Net contributions in the selected period as a share of prior-year ending AUM.

**Format:** Percentage, 2 decimals.

### AUM-Weighted Alpha

```dax
AUM-Weighted Alpha =
VAR LastSnapshotDate =
    -- Latest snapshot in the current filter context, taken from ALL rows
    -- (suspect rows included) so the date is fixed before any exclusion
    MAX ( fact_portfolio_snapshot[snapshot_date] )
VAR RowsAtLastSnapshot =
    CALCULATETABLE (
        fact_portfolio_snapshot,
        KEEPFILTERS ( dim_date[date] = LastSnapshotDate )
    )
VAR EligibleRows =
    FILTER (
        RowsAtLastSnapshot,
        fact_portfolio_snapshot[is_return_suspect] <> 1
            && NOT ISBLANK ( fact_portfolio_snapshot[active_alpha_ytd] )
            && NOT ISBLANK ( fact_portfolio_snapshot[aum] )
    )
VAR WeightedNumerator =
    SUMX (
        EligibleRows,
        fact_portfolio_snapshot[active_alpha_ytd] * fact_portfolio_snapshot[aum]
    )
VAR EligibleAUM =
    SUMX ( EligibleRows, fact_portfolio_snapshot[aum] )
RETURN
    DIVIDE ( WeightedNumerator, EligibleAUM )
```

**Pattern:** Recompute and weight at the last snapshot; exclude suspect rows from both numerator and denominator.

**Manager meaning:** AUM-weighted year-to-date active performance against benchmarks for eligible portfolios at the selected last snapshot.

**Format:** Percentage, 2 decimals.

### Alpha Signal

```dax
Alpha Signal =
VAR Alpha = [AUM-Weighted Alpha]
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( Alpha ), BLANK (),
        Alpha >= 0.02, "Outperforming",
        Alpha <= -0.02, "Lagging",
        "In line"
    )
```

**Pattern:** Recompute classification of the weighted ratio; non-additive text.

**Manager meaning:** Labels active performance using inclusive +2% and −2% thresholds, with no label when alpha is blank.

**Format:** Text.

### Top 10 Client Share

```dax
Top 10 Client Share =
VAR LastSnapshot =
    LASTNONBLANK (
        dim_date[date],
        CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ) )
    )
VAR ClientBalances =
    ADDCOLUMNS (
        VALUES ( dim_client[client_id] ),
        "@AUM", CALCULATE ( SUM ( fact_portfolio_snapshot[aum] ), LastSnapshot )
    )
VAR TopClients =
    TOPN ( 10, ClientBalances, [@AUM], DESC, dim_client[client_id], ASC )
RETURN
    DIVIDE ( SUMX ( TopClients, [@AUM] ), [Ending AUM] )
```

**Pattern:** Recompute rank and ratio at one shared ending date; non-additive.

**Manager meaning:** Concentration of ending AUM in the ten largest clients within the current selection.

**Format:** Percentage, 2 decimals.

## Part C — Design answers

### (a) One ending date versus each client's own ending date

With no filters, Ending AUM is **$12,729,572,078.86** at 2024-12-01. Independently evaluating each client's last available balance and then summing, equivalent to `SUMX ( VALUES ( dim_client[client_id] ), [Ending AUM] )`, produces **$13,149,297,713.80**. The difference is **$419,725,634.94**.

The client-by-client calculation carries forward 175 clients whose last snapshots predate the global latest snapshot: 13 last appear in 2022 and 162 in 2023. All 175 are marked inactive in dim_client. Their stale balances exactly account for the difference. The common-date Ending AUM answers “How much do we manage today?” as of the latest available data. Summing each client's own last balance combines different dates and includes departed clients' historical portfolios.

### (b) Fee Yield versus ICE9 Effective Fee Rate

ICE9_DAX_Foundations.docx, Part B Task 4, confirms the course formula:

```dax
Effective Fee Rate (bps) =
DIVIDE ( [Total Fees] * 12 * 10000, SUM ( fact_fees[aum_basis] ) )
```

For 2024, both measures use $48,714,005.93 of fees and the same annualization/conversion factor. Their denominators differ:

| Calculation | Denominator | Result |
|---|---:|---:|
| HW06 Fee Yield, sum of snapshot AUM | $135,459,843,783.73 | 43.1543441090 bps |
| ICE9 Effective Fee Rate, sum of fee aum_basis | $128,385,303,527.10 | 45.5323199074 bps |

Pandas joined by client and month. Of 27,900 snapshot client-months, 26,216 have a fee row and **1,684 have no fee row**. Those uncovered client-months contain **$7,074,540,256.63** of summed monthly AUM, exactly the denominator difference. Each matched client-month has one fee row, and its aum_basis equals the same-month snapshot AUM; no fee client-month lacks a snapshot. Both tables cover all 12 months and 2,325 distinct clients, so aggregate client counts alone conceal the gap.

Thus Fee Yield divides the observed fees by a wider AUM exposure base and is lower. The limitation is incomplete fee-row coverage of snapshot client-months: these tables do not distinguish genuinely non-billed months from missing fee records. The gap cannot by itself prove a discount, billing error or economic cause. Effective Fee Rate describes the represented billed exposure; Fee Yield describes observed fee revenue relative to all snapshot exposure.

The script's original JSON key still says CANDIDATE_ICE9 because the course formula was unavailable when it ran. The document was obtained afterward and confirms that exact formula; the calculations do not need changing.

### (c) Last-snapshot alpha and suspect returns

active_alpha_ytd is cumulative year-to-date performance. Adding monthly YTD observations repeatedly counts overlapping performance periods, and an average across months answers a different question. The measure fixes the latest snapshot within the current filters, then excludes suspect rows from both its weighted numerator and its AUM denominator. It also excludes blank alpha or AUM values and uses DIVIDE for a blank/zero denominator.

For the grand total and Year=2024, the last date is 2024-12-01. Of 2,325 snapshot rows, 2,177 are eligible and 148 are suspect. Excluding those suspect rows removes $15,543,506.10 of AUM.

| Last-snapshot calculation | Raw ratio | Percentage |
|---|---:|---:|
| AUM-weighted alpha, eligible rows | 0.01447994680056427 | 1.447995% |
| Simple mean, same eligible rows | 0.008788000918695454 | 0.878800% |
| AUM-weighted alpha, suspects included | 0.01667843242874973 | 1.667843% |

The eligible weighted numerator is 184,098,457.35441887 and denominator is $12,714,028,572.76. A simple mean gives every client equal weight; the measure weights by portfolio size. Including suspect returns raises the result here and exposes it to flagged performance data. Exclusion improves the reliability of the reported statistic but does not establish the true performance of the excluded portfolios.

### (d) Organic growth by tier in 2024

| Tier | Net flows | Organic Growth Rate | AUM YoY % | AUM increase |
|---|---:|---:|---:|---:|
| HNW | $25,227,406.26 | 1.1843% | 19.6402% | $418,367,003.91 |
| Retail | $44,184,047.61 | 9.8670% | 19.1286% | $85,656,849.22 |
| UHNW | $8,101,601.39 | 0.1004% | 19.5931% | $1,580,576,488.73 |

Retail supplies the largest net contributions in dollars and relative to its prior-year balance. HNW is second on both measures. UHNW contributes little new money relative to its large balance but has the largest dollar AUM increase. All three tiers' AUM grows about 19%, so net contributions alone do not explain their balance growth.

Organic Growth Rate measures deposits minus withdrawals relative to prior-year AUM. It is not investment return, gross acquisition, retention, or profitability, and it does not distinguish new clients from additional deposits by existing clients. The residual AUM increase after net flows cannot automatically be called investment returns: fees, other transactions, client entry/exit, timing and data effects may also contribute. Tier percentages must be recomputed at the total, not added.

## Report page

The Measures page contains the four required cards and the year table. The client-tier table has a visual-level dim_date[year] filter of 2024, leaving the year table and cards unaffected. The naive SUM is retained in the model and reconciliation but not displayed in report visuals. Cards show approximately $12.73bn Ending AUM, 2,325 Ending Clients, $5.48M Avg AUM per Client and 6.16% Top 10 Client Share.

## Evidence

See `../reports/design_evidence.json` for independent diagnostics, `../reports/powerbi_values.csv` for actual DAX outputs, and `../reports/measure_reconciliation.csv` for their comparison. The successful local run reported 160 passed and 0 failed.
