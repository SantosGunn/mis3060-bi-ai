# HW05: Wildcat Capital Star Schema and Power BI

MIS3060 Business Intelligence with AI, Villanova University.

This folder models the eight cleaned Wildcat Capital tables as a star schema, proves the keys and grains in Python, and builds the model in Power BI Desktop.

**Workflow:** `validate_star.py` was drafted in Claude Desktop, downloaded, and run in VS Code. Claude Code then reviewed it before commit (see "Claude Code review findings" below).

## Folder structure

```
hw05/
├── README.md                 # this file
├── star_design.md            # Parts A, B, C, E and F
├── validate_star.py          # pandas checks for keys, foreign keys, dates and grain
├── validation_results.md     # written by validate_star.py when it runs
├── data/                     # the eight cleaned CSVs, unchanged
│   ├── dim_advisor.csv
│   ├── dim_benchmark.csv
│   ├── dim_client.csv
│   ├── dim_date.csv
│   ├── dim_security.csv
│   ├── fact_fees.csv
│   ├── fact_portfolio_snapshot.csv
│   └── fact_transactions.csv
└── powerbi/
    ├── hw05.pbix             # Power BI model (Part D)
    ├── model_view.png        # Model view screenshot
    └── row_counts.png        # Power BI row counts for all eight tables
```

The repository `.gitignore` excludes `*.csv`, so the files in `data/` must be added with `git add -f hw05/data/*.csv` (the same way the HW04 clean CSVs were committed).

## How to run the validation

Requirements: Python 3 with pandas (`pip install pandas`).

From the repository root (`mis3060-bi-ai`) in the VS Code terminal:

```bash
python hw05/validate_star.py
```

The script finds `hw05/data/` relative to its own location, so it also works when run from another folder. It never modifies the CSVs. It prints each check and writes `hw05/validation_results.md`, then exits with code 0 if every check passes or 1 if any check fails.

What it checks:

| Area | Checks |
|---|---|
| Row counts | Rows and columns of all eight tables against the counts in the assignment |
| Primary keys | No nulls and no duplicates in each table's PK |
| Foreign keys | Every fact → dimension key, plus `dim_client[advisor_id]` → `dim_advisor` and `dim_security[benchmark_id]` → `dim_benchmark` |
| `security_id` blanks | Blanks on Deposit / Withdrawal / Advisory Fee are reported as legitimate; blanks on Buy / Sell / Dividend, and filled values on cash rows, are failures; orphan values are checked separately |
| Dates | `fee_date`, `snapshot_date` and `txn_date` all parse and exist in `dim_date[date]`; `dim_date[date]` is unique and contiguous (one row per day); info rows for snapshots on month-end dates and `client_since` outside the calendar |
| Grain | `fact_fees` unique on (client_id, fee_date); `fact_portfolio_snapshot` unique on (client_id, snapshot_date); `fact_transactions` unique on txn_id; monthly facts dated the 1st; snapshot year/month match the date |
| Advisor paths (info) | How many fact rows have an `advisor_id` different from the client's advisor in `dim_client`; how many transactions are flagged `is_post_departure_txn` |
| Measures | Fee `amount` = `aum_basis` × `bps_charged` / 10,000 / 12; `aum_basis` = the snapshot `aum` for the same client and month; `active_alpha_ytd` = `return_ytd` − `benchmark_return_ytd`; no negative amounts; Buy/Sell/Dividend `amount` = `shares` × `price`; `shares` and `price` blank on cash rows; info rows for `is_return_suspect` returns and the Advisory Fee vs `fact_fees` totals |

See `validation_results.md` for the results of the most recent run.

## Power BI model

`powerbi/hw05.pbix` loads the eight tables with 12 relationships. The author confirmed in Manage relationships that all 12 are active, many-to-one and single-direction:

- All three facts → `dim_client` and `dim_advisor`
- `fee_date`, `snapshot_date`, `txn_date` → `dim_date[date]`
- `fact_transactions[security_id]` → `dim_security`
- `fact_portfolio_snapshot[benchmark_id]` → `dim_benchmark`
- `dim_security[benchmark_id]` → `dim_benchmark`

`dim_client[advisor_id]` → `dim_advisor` is intentionally omitted to avoid an ambiguous filter path; see `star_design.md`, Part E(b).

### Checks observed in Power BI Desktop

These were run by hand in Power BI Desktop. Each number was also cross-checked against the CSVs with pandas, and all match. Details are in `star_design.md`, Part D.

- **Row counts:** transactions 298,572; fees 122,197; snapshots 129,547; advisors 25; benchmarks 8; clients 2,500; dates 1,827; securities 500. All eight match the CSVs (screenshot: `powerbi/row_counts.png`).
- **Advisor filter:** a page filter on `dim_advisor[first_name]` = Craig reduced transactions to 10,980, fees to 4,707 and snapshots to 4,948. These match the CSV row counts for `advisor_id` 24. The filter was cleared afterwards.
- **Blank ticker:** a ticker / transaction amount table shows the expected blank ticker group, totalling 3,573,887,227.67. That equals the total amount of the 101,528 cash and fee rows with no `security_id`.

### Settings confirmed by the author in Power BI Desktop

Claude Code cannot open the `.pbix`, so it did not check these independently.

- **Relationships:** All 12 relationships were checked in Manage relationships. Each is active, many-to-one and single-direction. There is no `dim_client` → `dim_advisor` relationship.
- **Date table:** `dim_date` is marked as the date table, using `dim_date[date]`.
- **Data types:** `zip_code` is Text. `fee_date`, `snapshot_date` and `txn_date` are Date.
- **Summarize by:** These are set to Don't summarize:
  - all `_id` columns
  - the numeric `dim_date` columns
  - `dim_client[age]` and `initial_aum`
  - `dim_advisor[years_experience]` and `aum_target_mm`
  - `dim_security[expense_ratio_bps]`
  - `fact_transactions[is_post_departure_txn]`
  - `fact_portfolio_snapshot[is_return_suspect]`

**Not confirmed:**
- Filter tests through `dim_client`, `dim_date` or `dim_benchmark`.
- Data types of other columns.

**File size:** `powerbi/hw05.pbix` is 21,934,802 bytes (about 20.9 MB), under GitHub's 100 MB limit, so it is included in this repository.

## Claude Code review findings

Claude Code reviewed `validate_star.py`, `star_design.md`, this README and `validation_results.md`. It first checked the documents against the parts they answer (A to F) and against the data itself. It then rechecked them against the HW05 assignment text once that was provided.

**Scope limit:** Claude Code cannot open Power BI Desktop. It did not run any check inside `powerbi/hw05.pbix`. The Power BI results and settings above were observed and reported by the author. Claude Code checked the file size, looked at the two screenshots, and cross-checked the reported numbers against the CSVs.

### What held up

- All key, foreign key, grain and date checks were already correct. The first run (38 PASS, 0 FAIL, 7 INFO) was reproduced before anything was changed.
- Each PK, FK, and grain claim in Parts A and B matches the data. The `security_id` blank logic correctly separates legitimate cash-row blanks from defects.
- The additivity classifications in Part C are right in substance, and the E(a) to E(d) relationship choices are sound.
- In Part F, Q1 works in a single visual, and the explanations of why Q2 and Q3 need DAX are correct. The claim that snapshots never fall on an `is_month_end` date is now confirmed by the script (0 rows).

### Issues found and changed

1. **The script did not test the measure arithmetic.** Part C relied on relationships it never checked. I added a `Measures` section to `validate_star.py` that confirms:
   - fee `amount` = `aum_basis` × `bps_charged` / 10,000 / 12
   - `aum_basis` equals the snapshot `aum` for the same client and month
   - `active_alpha_ytd` = `return_ytd` − `benchmark_return_ytd`
   - all amounts are non-negative
   - Buy/Sell/Dividend `amount` = `shares` × `price`
   - cash rows have blank `shares` and `price`

   I also added two checks elsewhere: `dim_date[date]` is contiguous (needed for Mark as date table), and INFO rows for snapshots on month-end dates, post-departure transactions, suspect returns, and the Advisory Fee totals.
2. **`bps_charged` (Part C):** "annualised" was vague. The fee is a monthly charge on an annual rate, so the effective rate is now written as SUM(amount) × 12 / SUM(aum_basis) × 10,000 bps.
3. **`shares` and `price` (Part C):** Dividend rows also carry `shares` and `price`, so "additive within one security" was not enough. It is now "within one security and one `txn_type`". `price` on Dividend rows is noted as a payout per share, not a trade price.
4. **Advisory Fee vs `fact_fees` (Part C, F Q1):** The Advisory Fee rows in `fact_transactions` total $263.7M and `fact_fees` totals $204.7M. A note now says the two must not be added together or swapped for each other.
5. **`return_ytd` (Part C, F Q2):** 3,875 rows are flagged `is_return_suspect`, with returns up to +9,467%. A note now says to exclude these before averaging. The "take the period-end value" advice is now limited to within one year.
6. **E(b) overstated the fact `advisor_id`.** It said the column records the advisor responsible "at that time", but the data does not show this. The fact advisor equals the client's advisor on every row, and 2,410 `is_post_departure_txn` transactions are still attributed to the same advisor. The rationale is now worded as a design safeguard, with a caution about post-departure rows.
7. **E(d) treated a benchmark as an asset class.** For 279 of 500 securities, `dim_benchmark[asset_class]` differs from `dim_security[asset_class]`. For example, Equity securities benchmarked to MSCI EAFE show as "International". The wording now says so and points "what was traded" analysis to `dim_security[asset_class]`.
8. **Files in the wrong folder:** This README and Part D pointed to `powerbi/hw05.pbix` and `powerbi/model_view.png`, but both files were saved directly in `hw05/` and the `powerbi/` folder was empty. Both files were moved, unchanged (SHA-256 hashes match before and after), into `hw05/powerbi/`, so the documented paths are now correct.
9. **Missing note on `data/`:** The repository `.gitignore` excludes `*.csv`, so `hw05/data/` would have been silently left out of the commit. A note on force-adding these files was added above.
10. **Minor script fix:** The `date_id` INFO row now reports the actual min and max instead of assuming 1 to row count.

After these changes the validation was rerun: **45 PASS, 0 FAIL, 11 INFO** (exit code 0).

### Model view screenshot

- **Earlier screenshots:** The first `model_view.png` showed the Σ (summarize) icon on ID columns, `dim_client[age]`, `dim_date` columns, and six other numeric attributes that Part C says not to sum. The author set all of them to **Don't summarize** and replaced the screenshot.
- **Final screenshot:** In the final `powerbi/model_view.png`, Σ appears only on the Part C measures, such as `amount`, `aum`, `price` and `shares`.
- **Relationship lines:** These could not be traced one by one at the screenshot's resolution. The relationship settings rest on the author's Manage relationships check.
