# HW04 – Wildcat Capital data-quality audit

Assignment: [HW04_Data_Cleaning.md](HW04_Data_Cleaning.md). Part A is done; Parts B–E are not started.

## Structure

```
hw04/
  data/raw/                  the eight source CSVs (read only, never modified)
  scripts/01_profile.py      Part A audit / profiler
  scripts/verify_setup.py    stale copy of the pre-review profiler (see "Noted, not changed")
  reports/profile_raw.csv    per-column profile
  reports/dq_summary_raw.csv one row per check
  reports/near_dup_clients_raw.csv  per-client near-duplicate evidence
```

## How to run

From `hw04/`:

```
.\.venv\Scripts\python.exe scripts\01_profile.py
```

## Part A: audit (`scripts/01_profile.py`)

Reads all eight CSVs as text (`dtype=str, keep_default_na=False`). Row and column counts match the assignment table. Writes:

| File | Contents |
|---|---|
| `reports/profile_raw.csv` | Per-column profile (75 columns, 8 tables): blanks, literal null tokens, distinct count, top values, value shapes, parse failures vs expected type, whitespace, mixed formats, length and numeric/date min/max |
| `reports/dq_summary_raw.csv` | One row per check: 7 ERROR, 9 WARN, 40 INFO, 231 PASS |
| `reports/near_dup_clients_raw.csv` | Per-client evidence for the 50 near-duplicate `dim_client` rows |

Check groups: (1) column level: type, allowed values, hard ranges, plausibility bands, key uniqueness, conditional blanks; (2) single table: exact duplicates, duplicates ignoring the PK, near-duplicates, row contradictions; (3) referential integrity: all 13 relationships (10 ID-based, 3 to `dim_date`); (4) cross-table business rules.

Severity follows the assignment: ERROR, WARN, INFO. PASS rows are also kept, so the summary shows which checks ran and found nothing.

### Main findings (raw extract)

- `fact_transactions.security_id`: all 197,175 nonblank values are stored as floats (`'45.0'`). They match `dim_security` only after normalization.
- `fact_transactions`: 836 Buys have negative `shares`. All 836 reconcile to `amount` if the sign is ignored.
- `fact_transactions.client_id`: 200 rows reference 200 client ids that are missing from `dim_client`.
- `fact_portfolio_snapshot.return_ytd`: 300 values carry a `%` suffix. All 300 reconcile with alpha only after dividing by 100.
- `dim_client`: 76 blank `risk_profile` values and 78 full state names (e.g. `Pennsylvania`).
- `dim_client`: 25 near-duplicate pairs whose `last_name` differs by a prefix: 23 copies are truncated (`Jacobso`), 2 are extended (`Pacen`, `Leen`). In every pair, the copy is an id in 2501–2525 with no facts, and the original id carries all the facts.
- Buy/Sell on weekends (40,649 rows). Snapshot months with no fee row (7,350). Advisory Fee transactions never reconcile to `fact_fees` (median ratio 3.11). 2,410 transactions after an inactive client's last snapshot.

### Assumptions (inferred, not documented)

No Wildcat data dictionary was supplied. These rules come from the data or from general domain knowledge, and the profiler applies them as stated:

- **Allowed-value lists are inferred.** The lists for `region`, `risk_profile`, `client_tier`, `primary_account_type` / `account_type`, `fee_type`, `txn_type`, `asset_class` and `day_of_week` were built from the values observed in the extract, plus standard US state codes. They are treated as ERROR (WARN for `state`), but they are not documented domains. A legitimate value that simply did not appear would be missed, and an unlisted legitimate value would be flagged.
- **Sign conventions are inferred.** The rule "`shares` and `amount` are positive; `txn_type` carries the direction" comes from the data: Sell rows carry positive shares and every `amount` is positive. The ERROR on the 836 negative-share Buys depends on this assumption. Fee and AUM positivity follow the same reasoning.
- **Plausibility bands are assumptions (WARN):** advisor experience ≤ 50 years; AUM target $1M–$10B; expense ratio and fee ≤ 300 bps; client age 18–110; `client_since` ≥ 1950; YTD return and alpha in [−0.6, 1.0].
- **Client-tier AUM bands** (<$500k Retail, $500k–5M HNW, ≥$5M UHNW) are assumptions.
- **Dividend holdings comparison is exploratory.** Net shares held are rebuilt only from in-extract Buys and Sells. Opening positions, transfers, reinvestment lots and corporate actions such as splits are not in the extract. Only 172 of 23,751 dividends have `shares` within 1% of the rebuilt position, but that result can neither confirm nor rule out what dividend `shares` means. The only firm result is that `amount = shares × price` holds on all 53,864 dividends.

## Claude Code review notes

### Round 1 – profiler logic

| # | Flagged | Change |
|---|---|---|
| 1 | `near_duplicates()` used `any()` for prefix matching across name columns, so an identical first name made any last-name difference count as "truncated/extended". | Each compare column is now classified separately (identical / case-whitespace / truncated-extended / other). A truncation needs a real difference and a nonblank shorter value. Labels name the column, e.g. `last_name:truncated/extended=25`. All pairs within each group are compared. The count is unchanged (25 last-name pairs: 23 truncated, 2 extended), but it now rests on the right test. |
| 2 | Business assumptions were hard ERROR bounds: advisor experience, AUM target, expense ratio, fee bps, age 18–110, `client_since` ≥ 1950. | `ranges` (ERROR) holds only bounds that are true by definition, each with a stated basis. The assumptions moved to `plausible` / `plausible_dates` (WARN). |
| 3 | The finding "Dividend amount equals full position value" (WARN) read `shares × price = amount` as proof that the dividend equals the whole position. | Replaced with an INFO that states only internal consistency, plus an exploratory holdings comparison (see Assumptions). |
| 4 | The non-trading-day merge called `drop_duplicates("date")` on `dim_date` with no report. | It now goes through `unique_lookup()`, which always records key uniqueness with examples and reports duplicates that conflict on `is_trading_day`. The merge uses `validate="many_to_one"` and asserts the row count is unchanged. |
| 5 | The near-duplicate client check reported only aggregate fact-row counts. | It now writes `reports/near_dup_clients_raw.csv`: one row per candidate id with its group, names, unmatched attributes, and per-fact-table counts and date spans. This is evidence only; no quarantine decision is made. |
| – | `Series.dt.dayofweek` deprecation warning. | Switched to `dt.day_of_week`. |

### Round 2 – Part A requirements check against HW04_Data_Cleaning.md

| Flagged | Change |
|---|---|
| "Must work on **any** table": for a column with no schema entry, `infer_type` assigned a type only when ≥95% of values parsed. Otherwise it fell back to `str`, which hides parse failures and mixed formats. A test table with `$2.00` among numbers and `01/02/2024` / `2024-13-01` among dates showed 0 parse failures. | `infer_type` now picks the type most nonblank values parse as, provided at least half do; ties go to the narrower type. Values with leading zeros stay text. On the test table, the bad values are now reported as parse failures and mixed formats. The eight Wildcat tables are unaffected because every column has a schema type: `profile_raw.csv` is byte-identical after the rerun. |
| The dividend holdings finding could read as conclusive. | The finding is renamed "(exploratory)", and its note lists the missing data: opening positions, transfers, reinvestment lots, corporate actions. |
| The repo-root `.gitignore` ignores `*.csv`, and its exception `!hw*/*.csv` does not reach `hw04/reports/`, so the required `profile_raw.csv` and `dq_summary_raw.csv` would never have been committed. | Added `!reports/*.csv` to `hw04/.gitignore`; the root file is unchanged. `data/raw/` stays ignored. |
| README lacked the "structure" section the submission checklist asks for, and did not mark the inferred rules as assumptions. | Added the Structure section and the Assumptions section. |

Checked and met, no change: per-column profile metrics; the four check groups; ERROR/WARN/INFO tagging; all 13 relationships; text-only reads; both required report files.

### Noted, not changed

- `scripts/verify_setup.py` is a byte-identical copy of the **pre-review** `01_profile.py` (SHA-256 `08BA22E8…`). It is not identical to the current profiler, so it was not deleted. It is untracked, so git cannot restore it if deleted.
- For `str` columns, `mixed_formats` detects only case/whitespace variants. Abbreviation-vs-full-name mixes (e.g. `PA` vs `Pennsylvania`) show up in `top_shapes` and in the `state` allowed-values WARN, not in the `mixed_formats` flag.
- The business rules in `row_rules()` and `cross_table()` are table-specific by nature; the profiler and column, duplicate and referential checks are generic.
