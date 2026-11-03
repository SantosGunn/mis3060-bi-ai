# HW05 Star Schema Design: Wildcat Capital

This document covers Parts A, B, C, E and F. Every key, grain and date claim below, and the arithmetic behind the measure classifications in Part C, is checked by `validate_star.py`; the results of the latest run are in `validation_results.md`.

---

## Part A: Keys

| Table | Type | Primary key | Foreign keys (column → table[column]) |
|---|---|---|---|
| dim_advisor | Dimension | `advisor_id` | — |
| dim_benchmark | Dimension | `benchmark_id` | — |
| dim_client | Dimension | `client_id` | `advisor_id` → dim_advisor[advisor_id] |
| dim_date | Dimension | `date_id` | — |
| dim_security | Dimension | `security_id` | `benchmark_id` → dim_benchmark[benchmark_id] |
| fact_fees | Fact | `fee_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`fee_date` → dim_date[date] |
| fact_portfolio_snapshot | Fact | `snapshot_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`benchmark_id` → dim_benchmark[benchmark_id]<br>`snapshot_date` → dim_date[date] |
| fact_transactions | Fact | `txn_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`security_id` → dim_security[security_id] *(may be blank)*<br>`txn_date` → dim_date[date] |

**Notes**

- **Fact dates match `dim_date[date]`, not `dim_date[date_id]`.** The facts store calendar dates (`2020-01-01`); `date_id` is an integer (1 to 1,827) that no fact table carries.
- **`fact_transactions[security_id]` can legitimately be blank.** Deposits, withdrawals and advisory fee debits move cash and involve no security. The script confirms that every blank is on one of those three types and that every Buy, Sell and Dividend has a security_id that exists in `dim_security`.
- **`dim_client[client_since]` is not a foreign key.** It is a descriptive date, and many values are earlier than 2020, outside the `dim_date` range (2020-01-01 to 2024-12-31), so it cannot join to the calendar.
- `account_type` on `fact_portfolio_snapshot` and `fee_type` / `txn_type` on the other facts are degenerate attributes (descriptive text stored on the fact), not keys.

---

## Part B: Grain

- **fact_fees:** One row represents one fee charged to one client for one calendar month, dated the first of that month.
- **fact_portfolio_snapshot:** One row represents one client's portfolio as of the first day of one month.
- **fact_transactions:** One row represents one individual transaction (a trade, dividend, deposit, withdrawal or advisory fee debit) in one client's account on one day.

`validate_star.py` checks these grains: `fact_fees` is unique on (`client_id`, `fee_date`), `fact_portfolio_snapshot` is unique on (`client_id`, `snapshot_date`), both monthly facts are always dated the 1st of the month, and `fact_transactions` is unique on `txn_id` (it has no other natural key; several trades can share client, security and date).

---

## Part C: Measures

### Fact measures

| Table | Column | Classification | What that means for summing / averaging |
|---|---|---|---|
| fact_fees | `amount` | Additive | Fee dollars can be summed across clients, advisors, fee types and months; the total is fee revenue for that slice. |
| fact_fees | `aum_basis` | Semi-additive | The asset balance a fee was charged on can be summed across clients within one month, but adding it across months counts the same assets again; use the latest month or an average over time. It equals `fact_portfolio_snapshot[aum]` for the same client and month on every row. |
| fact_fees | `bps_charged` | Non-additive | An annual rate in basis points cannot be summed. Each `amount` is one month of that rate (`aum_basis` × `bps_charged` / 10,000 / 12), so the effective annual rate for a slice is SUM(amount) × 12 / SUM(aum_basis) × 10,000 bps, not a simple average. |
| fact_portfolio_snapshot | `aum` | Semi-additive | AUM is a balance: sum it across clients for a single snapshot date, but never across months; over time take the last (or average) month. |
| fact_portfolio_snapshot | `return_ytd` | Non-additive | Percent returns cannot be summed across clients or months; across clients use an AUM-weighted average, and across months take the value at the period end because it is already year to date (within one year only). The 3,875 rows flagged `is_return_suspect` include returns from −99% to +9,467%, so exclude them, or check them, before averaging. |
| fact_portfolio_snapshot | `benchmark_return_ytd` | Non-additive | The benchmark's year-to-date return is a percentage; summing it is meaningless, and averaging it across clients repeats the same benchmark value many times. |
| fact_portfolio_snapshot | `active_alpha_ytd` | Non-additive | The difference between two percentages is still a percentage; recompute it from weighted returns rather than summing or simply averaging. |
| fact_portfolio_snapshot | `cash_pct` | Non-additive | A share of the portfolio held in cash cannot be summed; across clients use an AUM-weighted average (cash dollars / total AUM). |
| fact_transactions | `amount` | Additive (within a `txn_type`) | Dollar amounts sum across clients, securities and days, but all are stored as positive numbers, so only sum one type at a time (or apply a sign) – adding Buys to Sells or Deposits to Withdrawals produces a meaningless total. The Advisory Fee rows ($263.7M in total) do not reconcile to `fact_fees[amount]` ($204.7M), so the two are not interchangeable and must never be added together. |
| fact_transactions | `shares` | Additive (within one security and one `txn_type`) | Share counts sum across clients and days for a single security and type. Dividend rows also carry a share count (the holding the dividend was paid on), so adding Buy, Sell and Dividend shares together, or shares of different securities, does not represent anything; blank on cash rows. |
| fact_transactions | `price` | Non-additive | A per-share value cannot be summed; an average must be weighted by shares (SUM(amount) / SUM(shares)) within one `txn_type`. On Dividend rows it is the payout per share, not a trade price, so do not average it with Buy/Sell prices; blank on cash rows. |

### Numeric columns in fact tables that are not measures

- Keys: `fee_id`, `snapshot_id`, `txn_id`, `client_id`, `advisor_id`, `benchmark_id`, `security_id`
- Date parts: `fact_portfolio_snapshot[year]`, `fact_portfolio_snapshot[month]` (repeat information from `snapshot_date` and `dim_date`)
- Flags: `fact_portfolio_snapshot[is_return_suspect]`, `fact_transactions[is_post_departure_txn]` (0/1 filters; counting them is fine, but they are not business amounts)
- `fact_portfolio_snapshot[account_type]` looks numeric for 529 accounts but is a text category

### Numeric attributes in dimension tables that should never be summed

- **dim_advisor:** `years_experience`, `aum_target_mm` (a target per advisor; adding targets is not a firm-wide figure unless deliberately defined that way)
- **dim_client:** `age`, `zip_code` (a code, stored as text to keep leading zeros), `initial_aum` (each client's starting balance, taken on different `client_since` dates; a sum is not the firm's AUM at any point in time, so use `fact_portfolio_snapshot[aum]` instead)
- **dim_security:** `expense_ratio_bps` (a rate; average it, do not sum it)
- **dim_date:** `date_id`, `year`, `quarter`, `month`, `week_of_year`, and the 0/1 flags `is_month_end`, `is_quarter_end`, `is_year_end`, `is_trading_day`
- **All dimensions:** every `*_id` key

In Power BI, these columns should have **Summarize by = Don't summarize** so they are not silently summed in visuals.

---

## Part D: Power BI model (summary)

The saved model is `powerbi/hw05.pbix`, the Model view screenshot is `powerbi/model_view.png`, and the row-count screenshot is `powerbi/row_counts.png`.

### Checks observed in Power BI Desktop

These were run by hand in Power BI Desktop and recorded from what was on screen. Claude Code cross-checked each number against the CSVs with pandas, and every figure matches.

**Row counts reconcile.** A table visual of row counts (see `powerbi/row_counts.png`) shows:

| Table | Rows in Power BI | Rows in CSV |
|---|---:|---:|
| fact_transactions | 298,572 | 298,572 |
| fact_fees | 122,197 | 122,197 |
| fact_portfolio_snapshot | 129,547 | 129,547 |
| dim_advisor | 25 | 25 |
| dim_benchmark | 8 | 8 |
| dim_client | 2,500 | 2,500 |
| dim_date | 1,827 | 1,827 |
| dim_security | 500 | 500 |

**Advisor filter propagates to all three facts.** A page filter on `dim_advisor[first_name]` = Craig produced the counts below. Craig Ramirez (`advisor_id` 24) is the only advisor named Craig. The filter was cleared afterwards.

| Fact | Rows with filter | Rows for `advisor_id` 24 in CSV |
|---|---:|---:|
| fact_transactions | 10,980 | 10,980 |
| fact_fees | 4,707 | 4,707 |
| fact_portfolio_snapshot | 4,948 | 4,948 |

This shows the three `fact_*[advisor_id]` → `dim_advisor` relationships filter correctly. It does not show whether `dim_client[advisor_id]` → `dim_advisor` exists, because each fact's advisor matches the client's advisor on every row. The counts would be the same either way.

**Blank `security_id` rows group under a blank ticker.** A table of `dim_security[ticker]` against Sum of `fact_transactions[amount]` shows the expected blank ticker row, totalling 3,573,887,227.67. That equals the total `amount` of the 101,528 Deposit, Withdrawal and Advisory Fee rows with no `security_id` (see E(a)). It confirms that `fact_transactions[security_id]` → `dim_security` joins on the filled rows and keeps the blank rows.

### Settings confirmed by the author in Power BI Desktop

The author checked these settings in Power BI Desktop and reported them. Claude Code cannot open the `.pbix`, so it did not check them independently.

- **Relationships:** All 12 relationships in the table below were checked in Manage relationships. Each is active, many-to-one (*:1) and single-direction (dimension filters fact). No `dim_client[advisor_id]` → `dim_advisor` relationship exists.
- **Date table:** `dim_date` is marked as the date table, using `dim_date[date]`.
- **Data types:** `dim_client[zip_code]` is Text (keeps leading zeros). `fact_fees[fee_date]`, `fact_portfolio_snapshot[snapshot_date]` and `fact_transactions[txn_date]` are Date.
- **Summarize by:** These are set to Don't summarize, matching the non-measure lists in Part C:
  - every `_id` column
  - every numeric `dim_date` column
  - `dim_client[age]` and `dim_client[initial_aum]`
  - `dim_advisor[years_experience]` and `dim_advisor[aum_target_mm]`
  - `dim_security[expense_ratio_bps]`
  - `fact_transactions[is_post_departure_txn]`
  - `fact_portfolio_snapshot[is_return_suspect]`

### Not confirmed

These have not been checked by a recorded test or a reported setting:
- Filter tests through `dim_client`, `dim_date` or `dim_benchmark`. Only the advisor and security paths were tested with data.
- Data types of columns other than the four listed above.
The 12 relationships:

| From (many side) | To (one side) |
|---|---|
| fact_fees[client_id] | dim_client[client_id] |
| fact_fees[advisor_id] | dim_advisor[advisor_id] |
| fact_fees[fee_date] | dim_date[date] |
| fact_portfolio_snapshot[client_id] | dim_client[client_id] |
| fact_portfolio_snapshot[advisor_id] | dim_advisor[advisor_id] |
| fact_portfolio_snapshot[snapshot_date] | dim_date[date] |
| fact_portfolio_snapshot[benchmark_id] | dim_benchmark[benchmark_id] |
| fact_transactions[client_id] | dim_client[client_id] |
| fact_transactions[advisor_id] | dim_advisor[advisor_id] |
| fact_transactions[txn_date] | dim_date[date] |
| fact_transactions[security_id] | dim_security[security_id] |
| dim_security[benchmark_id] | dim_benchmark[benchmark_id] |

Not created: `dim_client[advisor_id]` → `dim_advisor[advisor_id]` (see E(b)).

`dim_date` is marked as the date table on `dim_date[date]` (author-confirmed). The three fact date columns are typed **Date** (author-confirmed). They must match the type of `dim_date[date]` for the joins to work.

---

## Part E: Relationships and design questions

**Conformed dimensions.** `dim_client`, `dim_advisor` and `dim_date` are conformed: all three fact tables join to them on the same keys with the same meaning, so a single slicer on client tier, advisor region or year filters fees, snapshots and transactions consistently and they can share one visual. `dim_benchmark` is shared by two facts but with **different meanings** (see (d)), so it is only partly conformed. `dim_security` belongs to `fact_transactions` only.

**(a) Why do some transactions have no `security_id`, and is that a defect?**
Deposits, withdrawals and advisory fee debits are cash movements in or out of the account; no security is bought, sold or paid out, so there is nothing to point to and `shares` and `price` are blank on the same rows. That is correct, not a defect. `validate_star.py` proves it: every blank `security_id` is on a Deposit, Withdrawal or Advisory Fee row, no Buy/Sell/Dividend is missing a security, and every non-blank value exists in `dim_security`. In Power BI these rows fall under the "(Blank)" member of `dim_security`, so a visual sliced by security attributes shows cash flows as Blank. That is expected; filter by `txn_type` if needed.

**(b) `advisor_id` is in `dim_client` and in all three facts. Which relationship(s) are active, and why?**
I kept each fact's `advisor_id` → `dim_advisor` active and left out `dim_client[advisor_id]` → `dim_advisor`. If both existed, `dim_advisor` could reach every fact two ways (directly, and through `dim_client`), which Power BI treats as an ambiguous path and would force one of them to be inactive. The fact columns are the better path because they can attribute each row to an advisor individually, while `dim_client[advisor_id]` holds one advisor per client, so if a client were reassigned, filtering through `dim_client` would move all of that client's history to the new advisor. The script shows that in this dataset the fact advisor matches the client's advisor on every row, so the choice changes no numbers today; it protects the model if the source starts recording reassignments. The fact column is not yet a full history: 2,410 transactions are flagged `is_post_departure_txn` and are still attributed to the same `advisor_id`, so advisor-level transaction totals should filter or call out those rows. `dim_client[advisor_id]` stays in the table as a plain column, so a client's assigned advisor can still be shown.

**(c) `dim_date` has `date_id`, but the facts store calendar dates. Which column did you join on, and why?**
I joined `fee_date`, `snapshot_date` and `txn_date` to `dim_date[date]`. None of the fact tables carries `date_id`, so a join on it would match nothing; the assignment says not to add new columns, so I did not create a key lookup. `dim_date[date]` is unique and covers every fact date (the script checks both), which also lets `dim_date` be marked as the date table on that column for time intelligence in HW6.

**(d) Star or snowflake: does anything connect one dimension to another? Did you keep it?**
Two dimension-to-dimension keys exist: `dim_client[advisor_id]` → `dim_advisor` and `dim_security[benchmark_id]` → `dim_benchmark`. I removed the first, for the reason in (b). I kept the second, `dim_security` → `dim_benchmark`, so the model is a star with one small snowflake branch. It lets transactions be analysed by the benchmark each security tracks. That is not the same as the security's own asset class: `dim_benchmark[asset_class]` differs from `dim_security[asset_class]` for 279 of 500 securities (for example, Equity securities benchmarked to MSCI EAFE are "International", to the Russell 2000 "Small Cap", and Alternatives benchmarked to the 60/40 Blend are "Multi-Asset"), so use `dim_security[asset_class]` for "what was traded". It does not create an ambiguous path, because `fact_transactions` has no direct `benchmark_id`. The caution is that `dim_benchmark` means different things to different facts: for snapshots it is the **client portfolio's** benchmark; for transactions it is the **security's** benchmark. A benchmark slicer filters both facts at once with those two meanings, so visuals that mix them need to be labelled carefully.

---

## Part F: Reflection: three business questions

**1. Fees: "How much fee revenue did each advisor region earn per quarter in 2024, split by fee type?"**
Answerable in a single visual with no DAX: put `dim_advisor[region]` and `dim_date[quarter]` on the axis, `fact_fees[fee_type]` as legend, and Sum of `fact_fees[amount]`, filtered to 2024. Fee amount is fully additive and all three dimensions filter `fact_fees` directly. The answer must come from `fact_fees`, not from the Advisory Fee rows in `fact_transactions`, which total a different amount.

**2. Snapshots: "What was total AUM by client tier at the end of each year, and how did it change?"**
Not in a single visual without DAX. `aum` is semi-additive, so the default Sum with a year on the axis adds twelve monthly balances together and overstates AUM by roughly 12×. A measure such as "AUM at the last snapshot in the period" is needed (HW6). The schema also makes the period end awkward: snapshots are dated the **first** of each month, so `dim_date[is_month_end]` and `is_year_end` never select a snapshot. To fix this, I would date each snapshot at the month end it describes (or add an "is latest snapshot in period" flag on the fact), so a plain filter could select the right balance. The same issue applies to `return_ytd`: averaging it across clients is unweighted, so an AUM-weighted return also needs a measure, and the `is_return_suspect` rows should be filtered out first.

**3. Transactions: "What were net new assets (deposits minus withdrawals) by advisor each month?"**
Not in a single visual without DAX. Every `amount` is stored as a positive number and direction is only in `txn_type`, so Sum of `amount` adds withdrawals to deposits. I would need a measure that subtracts Withdrawal from Deposit, or two visuals side by side. To fix this, I would store a signed amount (outflows negative) or add a small `dim_txn_type` with a sign column (+1 / −1), so net flow becomes a plain Sum. A related question, "Buy volume by security asset class", *does* work in one visual today (filter `txn_type` = Buy, axis `dim_security[asset_class]`, Sum of `amount`), but cash flows show up under a Blank security.
